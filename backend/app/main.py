"""FastAPI application factory.

The request-body-size guard is a pure-ASGI middleware placed ahead of any body parser so
an over-large upload is rejected before FastAPI reads the body (Requirement 32.16). The
listener binds to ``settings.bind_host`` (Requirement 32.7), which defaults to loopback.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI

from app.config import Settings, get_settings

Scope = dict
Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]


class RequestBodySizeLimitMiddleware:
    """Pure-ASGI middleware rejecting bodies over ``max_request_body_size``.

    Placed ahead of any body parser. It enforces the limit both from the declared
    ``Content-Length`` header (fast path) and by counting streamed bytes (chunked path),
    responding 413 before the body reaches a parser.
    """

    def __init__(self, app, max_body_size: int) -> None:
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_body_size:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send)
                return

        received = 0

        async def limited_receive() -> dict:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_size:
                    await self._reject(send)
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, limited_receive, send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = b'{"detail":"Request body exceeds the configured maximum size."}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct and return the FastAPI application."""
    settings = settings or get_settings()
    app = FastAPI(title="TBX Finance Assistant", version="0.1.0")

    # Body-size guard must wrap the app ahead of any body parser.
    app.add_middleware(
        RequestBodySizeLimitMiddleware,
        max_body_size=settings.max_request_body_size,
    )

    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:
    """Attach routers as they are implemented.

    Routers are imported lazily so a partially-implemented tree still constructs.
    """
    try:
        from app.routes import health

        app.include_router(health.router)
    except Exception:  # pragma: no cover - health router not yet present
        pass

    try:
        from app.routes import chat

        app.include_router(chat.router)
    except Exception:  # pragma: no cover - chat router optional
        pass

    try:
        from app.routes import voice

        app.include_router(voice.router)
    except Exception:  # pragma: no cover - voice router optional
        pass


app = create_app()
