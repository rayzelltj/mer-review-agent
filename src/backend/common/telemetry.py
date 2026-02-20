from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode


def current_trace_id() -> str | None:
    span = trace.get_current_span()
    if span is None:
        return None
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return f"{ctx.trace_id:032x}"


def current_span_id() -> str | None:
    span = trace.get_current_span()
    if span is None:
        return None
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return f"{ctx.span_id:016x}"


def current_traceparent() -> str | None:
    trace_id = current_trace_id()
    span_id = current_span_id()
    if not trace_id or not span_id:
        return None
    return f"00-{trace_id}-{span_id}-01"


@contextmanager
def traced_phase(
    name: str,
    *,
    logger: logging.Logger | None = None,
    attributes: dict[str, Any] | None = None,
) -> Iterator[None]:
    tracer = trace.get_tracer("macae")
    start = time.perf_counter()
    with tracer.start_as_current_span(name) as span:
        for key, value in (attributes or {}).items():
            if value is not None:
                span.set_attribute(key, value)
        try:
            yield
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("phase.duration_ms", duration_ms)
            if logger:
                logger.info(
                    "phase=%s duration_ms=%.2f trace_id=%s",
                    name,
                    duration_ms,
                    current_trace_id(),
                )
