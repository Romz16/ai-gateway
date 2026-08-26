import asyncio
import json
import time
from uuid import uuid4

from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.telemetry import Telemetry


class RequestBoundary:
    """Bound bodies before JSON parsing and emit only sanitized request telemetry."""

    def __init__(self, app: ASGIApp, telemetry: Telemetry, max_body_bytes: int) -> None:
        self.app, self.telemetry, self.max_body_bytes = app, telemetry, max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        carrier = {
            k.decode(): v.decode("ascii", errors="ignore")
            for k, v in scope["headers"]
            if k == b"traceparent"
        }
        context = TraceContextTextMapPropagator().extract(carrier)
        with self.telemetry.tracer.start_as_current_span(
            "gateway.request",
            context=context,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            trace_id = format(span.get_span_context().trace_id, "032x")
            scope.setdefault("state", {}).update(
                request_id=request_id, trace_id=trace_id, started_at=time.monotonic()
            )
            status, started = 500, time.monotonic()
            self.telemetry.inflight.inc()

            async def wrapped_send(message: Message) -> None:
                nonlocal status
                if message["type"] == "http.response.start":
                    status = message["status"]
                    message["headers"] = list(message.get("headers", [])) + [
                        (b"x-request-id", request_id.encode()),
                        (b"x-trace-id", trace_id.encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (b"cache-control", b"no-store"),
                    ]
                await send(message)

            async def reject(code: str, message: str, status_code: int) -> None:
                body = json.dumps(
                    {
                        "error": {
                            "code": code,
                            "message": message,
                            "request_id": request_id,
                            "trace_id": trace_id,
                        }
                    }
                ).encode()
                await wrapped_send(
                    {
                        "type": "http.response.start",
                        "status": status_code,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await wrapped_send({"type": "http.response.body", "body": body})

            try:
                body = bytearray()
                async with asyncio.timeout(5):
                    while True:
                        chunk = await receive()
                        if chunk["type"] == "http.disconnect":
                            return
                        body.extend(chunk.get("body", b""))
                        if len(body) > self.max_body_bytes:
                            await reject("INVALID_REQUEST", "The request body is too large.", 413)
                            return
                        if not chunk.get("more_body", False):
                            break
                consumed = False

                async def buffered_receive() -> Message:
                    nonlocal consumed
                    if not consumed:
                        consumed = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                await self.app(scope, buffered_receive, wrapped_send)
            except TimeoutError:
                await reject("INVALID_REQUEST", "The request body deadline was reached.", 408)
            except Exception:
                # Do not let ASGI servers log exception text containing private data.
                self.telemetry.event("internal_error", request_id=request_id, trace_id=trace_id)
                await reject("INTERNAL_ERROR", "The request could not be completed.", 500)
            finally:
                known = {
                    "/health",
                    "/ready",
                    "/metrics",
                    "/v1/generate",
                    "/v1/generate/structured",
                    "/v1/usage",
                    "/v1/providers/status",
                    "/docs",
                    "/openapi.json",
                }
                route = scope["path"] if scope["path"] in known else "other"
                self.telemetry.requests.labels(route=route, status=str(status)).inc()
                self.telemetry.duration.labels(route=route).observe(time.monotonic() - started)
                self.telemetry.inflight.dec()
                span.set_attribute("http.response.status_code", status)
                span.set_attribute("gateway.request_id", request_id)
                self.telemetry.event(
                    "request_completed",
                    request_id=request_id,
                    trace_id=trace_id,
                    status=status,
                    route=route,
                )
