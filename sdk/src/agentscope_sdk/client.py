"""AgentScope tracing client.

    from agentscope_sdk import AgentScope

    scope = AgentScope()  # reads AGENTSCOPE_API_KEY and AGENTSCOPE_HOST

    with scope.trace("support-run", input=question) as t:
        with scope.span("search", kind="tool", input=query) as s:
            s.update(output=hits)
        t.update(output=answer)

    @scope.observe(kind="tool")
    def search(query): ...

Nesting follows the call stack via contextvars (works across asyncio tasks; a new
thread starts with no current trace). Events are sent in batches by a background
thread. The SDK never raises into your code: network or server errors are retried,
then dropped and logged.
"""

import atexit
import functools
import inspect
import json
import logging
import os
import queue
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

logger = logging.getLogger("agentscope_sdk")

SpanKind = Literal["span", "llm", "tool"]
MAX_FIELD_CHARS = 50_000  # per input/output/metadata, after JSON encoding
_UPDATABLE = {"input", "output", "metadata", "model", "input_tokens", "output_tokens", "name"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _jsonable(value: Any) -> Any:
    """JSON-safe copy of a value: unknown objects become repr(), huge values are cut."""
    try:
        text = json.dumps(value, default=repr)
    except Exception:  # e.g. circular references
        text = json.dumps(repr(value))
    if len(text) > MAX_FIELD_CHARS:
        return {"truncated": True, "preview": text[:MAX_FIELD_CHARS]}
    return json.loads(text)


class Observation:
    """A trace or span in progress. Use update() to attach output, tokens, etc."""

    def __init__(self, **fields: Any):
        self.data: dict[str, Any] = {"id": str(uuid.uuid4()), "start_time": _now(), **fields}

    @property
    def id(self) -> str:
        return self.data["id"]

    def update(self, **fields: Any) -> None:
        for key, value in fields.items():
            if key in _UPDATABLE:
                self.data[key] = value
            else:
                logger.warning("agentscope: ignoring unknown field %r", key)

    def _finish(self, error: BaseException | None) -> dict[str, Any]:
        out = {**self.data, "end_time": _now()}
        if error is not None:
            out["status"], out["error"] = "error", f"{type(error).__name__}: {error}"[:10_000]
        for key in ("input", "output", "metadata"):
            if out.get(key) is not None:
                out[key] = _jsonable(out[key])
        return out


_trace: ContextVar[Observation | None] = ContextVar("agentscope_trace", default=None)
_span: ContextVar[Observation | None] = ContextVar("agentscope_span", default=None)


class AgentScope:
    def __init__(
        self,
        api_key: str | None = None,
        host: str | None = None,
        *,
        flush_interval: float = 1.0,
        max_batch: int = 100,
        max_queue: int = 10_000,
        max_retries: int = 3,
        timeout: float = 5.0,
        http_client: httpx.Client | None = None,
    ):
        self.api_key = api_key or os.environ.get("AGENTSCOPE_API_KEY", "")
        self.host = (host or os.environ.get("AGENTSCOPE_HOST", "http://localhost:8000")).rstrip("/")
        self.enabled = bool(self.api_key)
        if not self.enabled:
            logger.warning("agentscope: no API key (AGENTSCOPE_API_KEY); tracing is disabled")
        self.flush_interval = flush_interval
        self.max_batch = min(max_batch, 500)  # server batch limit
        self.max_retries = max_retries
        self._http = http_client or httpx.Client(timeout=timeout)
        self._queue: queue.Queue[tuple[str, dict]] = queue.Queue(max_queue)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        atexit.register(self.shutdown)

    # ---------- Public API ----------

    @contextmanager
    def trace(
        self, name: str, *, input: Any = None, metadata: dict | None = None
    ) -> Iterator[Observation]:
        """Start a trace (one agent run). Spans opened inside it become its children."""
        t = Observation(name=name, input=input, metadata=metadata)
        trace_token, span_token = _trace.set(t), _span.set(None)
        error: BaseException | None = None
        try:
            yield t
        except BaseException as exc:
            error = exc
            raise
        finally:
            _trace.reset(trace_token)
            _span.reset(span_token)
            self._emit("trace", t, error)

    @contextmanager
    def span(
        self,
        name: str,
        *,
        kind: SpanKind = "span",
        input: Any = None,
        metadata: dict | None = None,
        model: str | None = None,
    ) -> Iterator[Observation]:
        """Start a span inside the current trace (or a new trace, if none is active)."""
        if _trace.get() is None:
            with self.trace(name, input=input, metadata=metadata):
                with self.span(name, kind=kind, input=input, metadata=metadata, model=model) as s:
                    yield s
            return

        parent = _span.get()
        s = Observation(
            name=name,
            kind=kind,
            input=input,
            metadata=metadata,
            model=model,
            trace_id=_trace.get().id,
            parent_id=parent.id if parent else None,
        )
        token = _span.set(s)
        error: BaseException | None = None
        try:
            yield s
        except BaseException as exc:
            error = exc
            raise
        finally:
            _span.reset(token)
            self._emit("span", s, error)

    def observe(
        self,
        name: str | None = None,
        *,
        kind: SpanKind = "span",
        capture_input: bool = True,
        capture_output: bool = True,
    ) -> Callable:
        """Decorator: run the function inside a span (sync or async)."""

        def decorate(fn: Callable) -> Callable:
            span_name = name or fn.__qualname__

            def inputs(args, kwargs):
                if not capture_input:
                    return None
                try:
                    bound = inspect.signature(fn).bind(*args, **kwargs)
                    return {k: v for k, v in bound.arguments.items() if k not in ("self", "cls")}
                except Exception:
                    return {"args": args, "kwargs": kwargs}

            if inspect.iscoroutinefunction(fn):

                @functools.wraps(fn)
                async def async_wrapper(*args, **kwargs):
                    with self.span(span_name, kind=kind, input=inputs(args, kwargs)) as s:
                        result = await fn(*args, **kwargs)
                        if capture_output:
                            s.update(output=result)
                        return result

                return async_wrapper

            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                with self.span(span_name, kind=kind, input=inputs(args, kwargs)) as s:
                    result = fn(*args, **kwargs)
                    if capture_output:
                        s.update(output=result)
                    return result

            return wrapper

        return decorate

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until queued events are sent (or dropped). False if `timeout` ran out."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if time.monotonic() >= deadline:
                logger.warning(
                    "agentscope: %d events still unsent after %.1fs (is %s reachable?)",
                    self._queue.unfinished_tasks,
                    timeout,
                    self.host,
                )
                return False
            time.sleep(0.02)
        return True

    def shutdown(self, timeout: float = 2.0) -> None:
        """Flush, then stop the sender. Registered with atexit."""
        self.flush(timeout)
        self._stop.set()

    # ---------- Internals (must never raise into user code) ----------

    def _emit(self, kind: str, obs: Observation, error: BaseException | None) -> None:
        if not self.enabled:
            return
        try:
            item = obs._finish(error)
            self._ensure_thread()
            self._queue.put_nowait((kind, item))
        except queue.Full:
            logger.warning("agentscope: queue full, dropping a %s", kind)
        except Exception:
            logger.exception("agentscope: failed to record a %s", kind)

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="agentscope-sender", daemon=True
                )
                self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                first = self._queue.get(timeout=self.flush_interval)
            except queue.Empty:
                continue
            batch = [first]
            while len(batch) < self.max_batch:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            try:
                self._send(batch)
            except Exception:
                logger.exception("agentscope: unexpected error while sending")
            finally:
                for _ in batch:
                    self._queue.task_done()

    def _send(self, batch: list[tuple[str, dict]]) -> None:
        payload = {
            "traces": [d for k, d in batch if k == "trace"],
            "spans": [d for k, d in batch if k == "span"],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._http.post(f"{self.host}/v1/ingest", json=payload, headers=headers)
                if resp.status_code < 300:
                    return
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    # Bad key or invalid data: retrying won't help.
                    logger.error(
                        "agentscope: server rejected %d events (HTTP %d): %s",
                        len(batch),
                        resp.status_code,
                        resp.text[:300],
                    )
                    return
            except httpx.HTTPError as exc:
                logger.debug("agentscope: send attempt %d failed: %s", attempt + 1, exc)
            if attempt < self.max_retries and not self._stop.wait(0.5 * 2**attempt):
                continue
            break
        logger.warning("agentscope: could not reach %s; dropped %d events", self.host, len(batch))
