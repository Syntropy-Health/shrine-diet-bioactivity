"""Optional Braintrust logging for integration tests.

Soft-imports ``braintrust``. Becomes a no-op when:
  - ``BRAINTRUST_API_KEY`` is unset
  - ``braintrust`` SDK not installed
  - any initialization or span error occurs

Project: ``diet-os-eval`` (https://www.braintrust.dev/app)

Usage:
    from _braintrust_logger import bt_span

    with bt_span("test_full_benchmark_render_unaffected") as span:
        scenarios = load_run_scenarios(results_dir)
        span.log(output={"scenario_count": len(scenarios)})

This module is duplicated in ``mcp/tests/e2e/`` because the two test trees
live in independent packages with different ``sys.path`` configurations.
Keep both copies in sync.
"""
from __future__ import annotations

import contextlib
import logging
import os
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_BT_LOGGER: Any = None
_INIT_ATTEMPTED: bool = False
_BRAINTRUST_PROJECT = "diet-os-eval"


def _maybe_init() -> Any:
    """Initialize the Braintrust logger once per process. Idempotent.

    Returns the active braintrust logger or ``None`` when logging is
    disabled (env var missing, SDK missing, or init failure).
    """
    global _BT_LOGGER, _INIT_ATTEMPTED
    if _INIT_ATTEMPTED:
        return _BT_LOGGER
    _INIT_ATTEMPTED = True

    api_key = os.environ.get("BRAINTRUST_API_KEY")
    if not api_key:
        logger.debug("BRAINTRUST_API_KEY not set; integration-test logging disabled")
        return None

    try:
        import braintrust  # type: ignore[import-not-found]
    except ImportError:
        logger.debug("braintrust SDK not installed; integration-test logging disabled")
        return None

    try:
        _BT_LOGGER = braintrust.init_logger(
            project=_BRAINTRUST_PROJECT,
            api_key=api_key,
        )
        logger.info("Braintrust logger initialized for project %r", _BRAINTRUST_PROJECT)
        return _BT_LOGGER
    except Exception as exc:  # noqa: BLE001 — never let init break tests
        logger.warning("Failed to initialize Braintrust logger: %s", exc)
        return None


class _NoOpSpan:
    """No-op stub yielded when Braintrust is disabled.

    Mirrors the (very small) subset of the braintrust span API that
    integration tests use: ``log(**kwargs)`` and ``end()``.
    """

    def log(self, **kwargs: Any) -> None:  # noqa: D401 — trivial no-op
        _ = kwargs  # explicit reference; satisfies Pyright "not accessed" hint
        return None

    def end(self) -> None:  # noqa: D401 — trivial no-op
        return None


@contextlib.contextmanager
def bt_span(name: str, **inputs: Any) -> Iterator[Any]:
    """Yield a Braintrust span (or no-op stub) for a test invocation.

    The ``inputs`` kwargs are recorded as the span's input payload.
    The yielded object exposes ``.log(**kwargs)`` and ``.end()``;
    when Braintrust is disabled, these become no-ops.

    Never raises — wrapping is intentionally fail-soft so a Braintrust
    outage cannot break a test run.
    """
    bt = _maybe_init()
    if bt is None:
        yield _NoOpSpan()
        return

    span: Any
    try:
        span = bt.start_span(name=name, type="test", input=inputs)
    except Exception as exc:  # noqa: BLE001 — fail-soft on span start
        logger.warning("bt_span %r start failed: %s", name, exc)
        yield _NoOpSpan()
        return

    try:
        yield span
    finally:
        try:
            span.end()
        except Exception as exc:  # noqa: BLE001 — fail-soft on span end
            logger.debug("bt_span %r end failed: %s", name, exc)
