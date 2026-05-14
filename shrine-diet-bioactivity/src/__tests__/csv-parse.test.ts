/**
 * Tests for the CTD CSV row parser.
 *
 * The existing `load-ctd.ts` used `line.split(',')` which corrupts rows
 * containing quoted disease names with embedded commas (CTD has many of
 * these — "Lymphoma, Mantle-Cell", "Alzheimer Disease, Late Onset", etc.).
 *
 * These tests pin down the RFC-4180-ish parser used by the CTD loader.
 */
import { describe, it, expect } from 'vitest';
import { parseCsvLine } from '../../scripts/_csv-parse.js';

describe('parseCsvLine', () => {
  it('splits a simple unquoted row', () => {
    expect(parseCsvLine('a,b,c')).toEqual(['a', 'b', 'c']);
  });

  it('preserves embedded commas inside double-quoted fields', () => {
    // Real CTD row pattern: ChemicalName,ChemicalID,CasRN,DiseaseName,...
    const line =
      'Curcumin,C001,,"Lymphoma, Mantle-Cell",MESH:D020522,therapeutic';
    expect(parseCsvLine(line)).toEqual([
      'Curcumin',
      'C001',
      '',
      'Lymphoma, Mantle-Cell',
      'MESH:D020522',
      'therapeutic',
    ]);
  });

  it('handles multiple quoted fields in one row', () => {
    const line =
      '"Tetracycline, mixture","C123","","Alzheimer Disease, Late Onset, 1",MESH:D000544';
    expect(parseCsvLine(line)).toEqual([
      'Tetracycline, mixture',
      'C123',
      '',
      'Alzheimer Disease, Late Onset, 1',
      'MESH:D000544',
    ]);
  });

  it('preserves empty trailing fields', () => {
    expect(parseCsvLine('a,,c,')).toEqual(['a', '', 'c', '']);
  });

  it('escapes double-quotes inside quoted fields ("" → ")', () => {
    // RFC 4180: "" inside a quoted field represents a literal double quote.
    const line = '"compound ""x"" form","C42","","Disease A"';
    expect(parseCsvLine(line)).toEqual([
      'compound "x" form',
      'C42',
      '',
      'Disease A',
    ]);
  });

  it('treats lone double-quotes inside an unquoted field as literal', () => {
    // Defensive: malformed rows shouldn't crash; preserve content.
    expect(parseCsvLine('a,b"weird,c')).toEqual(['a', 'b"weird', 'c']);
  });

  it('handles a real-world CTD row with all 10 fields populated', () => {
    const line =
      '10074-G5,C534883,,"Adenocarcinoma of Lung, Non-Squamous",MESH:D000077193,,MYC,4.31,,26656844|27602772';
    const fields = parseCsvLine(line);
    expect(fields).toHaveLength(10);
    expect(fields[3]).toBe('Adenocarcinoma of Lung, Non-Squamous');
    expect(fields[4]).toBe('MESH:D000077193');
    expect(fields[7]).toBe('4.31');
  });

  it('returns an empty array for an empty line', () => {
    expect(parseCsvLine('')).toEqual([]);
  });

  it('preserves a single field with no commas', () => {
    expect(parseCsvLine('Curcumin')).toEqual(['Curcumin']);
  });

  it('does NOT strip trailing \\r — load-ctd handles CRLF before calling', () => {
    // The defense-in-depth \r strip lives in load-ctd's streamGzipCsv
    // (rawLine.endsWith('\r') ? slice(0,-1) : rawLine). The parser
    // itself stays line-ending agnostic. This test pins that contract:
    // if a caller passes a CR-terminated line through, it shows up in
    // the last field — that's the caller's responsibility to handle.
    expect(parseCsvLine('a,b,c\r')).toEqual(['a', 'b', 'c\r']);
  });
});
