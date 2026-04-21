import { describe, it, expect, vi, beforeEach } from 'vitest';
import { LightRagClient, LightRagProxyError } from '../lightrag_proxy.js';

/**
 * Typed fetch-stub factory. Returns a triple: (fetchSpy, lastRequest, setResponse).
 */
function makeFetch() {
  let lastRequest: { url: string; init?: RequestInit } | null = null;
  let nextResponse: Response = new Response(JSON.stringify({}), { status: 200 });
  const spy = vi.fn(async (url: string | URL, init?: RequestInit) => {
    lastRequest = { url: typeof url === 'string' ? url : url.toString(), init };
    return nextResponse;
  });
  const setResponse = (body: unknown, status = 200) => {
    nextResponse = new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  return {
    fetch: spy as unknown as typeof fetch,
    getLastRequest: () => lastRequest,
    setResponse,
  };
}

describe('LightRagClient.query', () => {
  let stub: ReturnType<typeof makeFetch>;
  let client: LightRagClient;

  beforeEach(() => {
    stub = makeFetch();
    client = new LightRagClient({
      baseUrl: 'http://localhost:9621',
      fetchImpl: stub.fetch,
    });
  });

  it('POSTs /query with body including scope_filter', async () => {
    stub.setResponse({ response: 'ok', scope_filter: ['shared'] });
    await client.query({
      query: 'anti-inflammatory herbs',
      mode: 'hybrid',
      top_k: 40,
      scope_filter: ['shared'],
    });
    const req = stub.getLastRequest();
    expect(req?.url).toBe('http://localhost:9621/query');
    expect(req?.init?.method).toBe('POST');
    const body = JSON.parse(req!.init!.body as string);
    expect(body).toEqual({
      query: 'anti-inflammatory herbs',
      mode: 'hybrid',
      top_k: 40,
      scope_filter: ['shared'],
    });
  });

  it('returns typed QueryResponse on 200', async () => {
    stub.setResponse({
      response: 'curcumin is anti-inflammatory',
      scope_filter: ['shared', 'tenant:clinic-a'],
    });
    const result = await client.query({
      query: 'x',
      mode: 'hybrid',
      scope_filter: ['shared', 'tenant:clinic-a'],
    });
    expect(result.response).toBe('curcumin is anti-inflammatory');
    expect(result.scope_filter).toEqual(['shared', 'tenant:clinic-a']);
  });

  it('throws LightRagProxyError on 4xx', async () => {
    stub.setResponse({ detail: 'invalid scope' }, 400);
    await expect(
      client.query({ query: 'x', mode: 'hybrid', scope_filter: ['bogus'] }),
    ).rejects.toBeInstanceOf(LightRagProxyError);
  });

  it('throws LightRagProxyError on 5xx with upstream status', async () => {
    stub.setResponse({ detail: 'boom' }, 503);
    try {
      await client.query({
        query: 'x',
        mode: 'hybrid',
        scope_filter: ['shared'],
      });
      expect.fail('expected rejection');
    } catch (e) {
      expect(e).toBeInstanceOf(LightRagProxyError);
      expect((e as LightRagProxyError).status).toBe(503);
    }
  });
});

describe('LightRagClient.getSubgraph', () => {
  it('GETs /graphs with label, max_depth, max_nodes, scope_filter', async () => {
    const stub = makeFetch();
    stub.setResponse({ nodes: [], edges: [] });
    const client = new LightRagClient({
      baseUrl: 'http://localhost:9621',
      fetchImpl: stub.fetch,
    });
    await client.getSubgraph({
      label: 'Ashwagandha',
      max_depth: 1,
      max_nodes: 50,
      scope_filter: ['shared', 'tenant:clinic-a'],
    });
    const req = stub.getLastRequest()!;
    const url = new URL(req.url);
    expect(url.pathname).toBe('/graphs');
    expect(url.searchParams.get('label')).toBe('Ashwagandha');
    expect(url.searchParams.get('max_depth')).toBe('1');
    expect(url.searchParams.get('max_nodes')).toBe('50');
    expect(url.searchParams.get('scope_filter')).toBe(
      'shared,tenant:clinic-a',
    );
    expect(req.init?.method).toBe('GET');
  });

  it('defaults max_depth=1 and max_nodes=100 when unspecified', async () => {
    const stub = makeFetch();
    stub.setResponse({ nodes: [], edges: [] });
    const client = new LightRagClient({
      baseUrl: 'http://localhost:9621',
      fetchImpl: stub.fetch,
    });
    await client.getSubgraph({
      label: 'Turmeric',
      scope_filter: ['shared'],
    });
    const url = new URL(stub.getLastRequest()!.url);
    expect(url.searchParams.get('max_depth')).toBe('1');
    expect(url.searchParams.get('max_nodes')).toBe('100');
  });
});

describe('LightRagClient.listPopularLabels', () => {
  it('GETs /graph/label/popular with limit + scope_filter', async () => {
    const stub = makeFetch();
    stub.setResponse(['Herb', 'Compound', 'Food']);
    const client = new LightRagClient({
      baseUrl: 'http://localhost:9621',
      fetchImpl: stub.fetch,
    });
    const labels = await client.listPopularLabels({
      limit: 50,
      scope_filter: ['shared'],
    });
    expect(labels).toEqual(['Herb', 'Compound', 'Food']);
    const url = new URL(stub.getLastRequest()!.url);
    expect(url.pathname).toBe('/graph/label/popular');
    expect(url.searchParams.get('limit')).toBe('50');
    expect(url.searchParams.get('scope_filter')).toBe('shared');
  });
});

describe('LightRagClient.ingestCustomKG', () => {
  it('POSTs /documents/custom_kg with scope_filter + payload', async () => {
    const stub = makeFetch();
    stub.setResponse({
      ingested: { entities: 1, relationships: 0 },
      scope: 'tenant:clinic-a',
    });
    const client = new LightRagClient({
      baseUrl: 'http://localhost:9621',
      fetchImpl: stub.fetch,
    });
    const result = await client.ingestCustomKG({
      scope_filter: ['shared', 'tenant:clinic-a'],
      custom_kg: {
        entities: [
          {
            entity_name: 'LocalHerb',
            entity_type: 'Herb',
            description: 'x',
          },
        ],
        relationships: [],
      },
      source_label: 'clinic-a-intake',
    });
    expect(result.ingested.entities).toBe(1);
    expect(result.scope).toBe('tenant:clinic-a');
    const req = stub.getLastRequest()!;
    expect(req.url).toBe('http://localhost:9621/documents/custom_kg');
    expect(req.init?.method).toBe('POST');
    const body = JSON.parse(req.init!.body as string);
    expect(body.scope_filter).toEqual(['shared', 'tenant:clinic-a']);
    expect(body.custom_kg.entities[0].entity_name).toBe('LocalHerb');
  });

  it('propagates 400 on shared-write attempt', async () => {
    const stub = makeFetch();
    stub.setResponse({ detail: 'tenant required' }, 400);
    const client = new LightRagClient({
      baseUrl: 'http://localhost:9621',
      fetchImpl: stub.fetch,
    });
    await expect(
      client.ingestCustomKG({
        scope_filter: ['shared'],
        custom_kg: { entities: [], relationships: [] },
      }),
    ).rejects.toBeInstanceOf(LightRagProxyError);
  });
});

describe('LightRagClient baseUrl normalization', () => {
  it('accepts baseUrl with trailing slash', async () => {
    const stub = makeFetch();
    stub.setResponse({ response: 'x', scope_filter: ['shared'] });
    const client = new LightRagClient({
      baseUrl: 'http://localhost:9621/',
      fetchImpl: stub.fetch,
    });
    await client.query({
      query: 'x',
      mode: 'hybrid',
      scope_filter: ['shared'],
    });
    expect(stub.getLastRequest()!.url).toBe('http://localhost:9621/query');
  });
});
