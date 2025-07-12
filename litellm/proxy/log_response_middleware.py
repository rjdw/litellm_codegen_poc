# litellm/proxy/log_response_middleware.py
from __future__ import annotations

import gzip, asyncio
from typing import Any, Optional, AsyncGenerator

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse


class LogOutgoingBody(BaseHTTPMiddleware):
    """
    Dumps the *exact* payload that goes out over the wire.

    • Handles normal JSON responses (even when LiteLLM stored the content
      only in `body_iterator`)
    • Handles gzip-compressed JSON
    • Handles streaming/SSE responses
    """

    # ------------------------------------------------------------------ #
    # helper – read & return entire iterator without swallowing errors   #
    # ------------------------------------------------------------------ #
    @staticmethod
    async def _drain_iterator(gen: AsyncGenerator[bytes, None]) -> bytes:
        chunks: list[bytes] = []
        async for chunk in gen:
            chunks.append(chunk)
        return b"".join(chunks)

    # ------------------------------------------------------------------ #
    # main middleware hook                                               #
    # ------------------------------------------------------------------ #
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)

        # ─────────────── streaming responses (SSE / chunks) ────────────
        if isinstance(resp, StreamingResponse):

            async def tee(gen):
                collected = bytearray()
                async for chunk in gen:
                    collected.extend(chunk)
                    yield chunk
                print("===== FINAL RESPONSE (stream) ===")
                print(collected.decode("utf-8", errors="replace"))
                print("=================================\n")

            return StreamingResponse(
                tee(resp.body_iterator),
                status_code=resp.status_code,
                headers=dict(resp.headers),
                media_type=resp.media_type,
                background=resp.background,
            )

        # ─────────────── regular Response objects ──────────────────────
        body: bytes = b""

        # 1) first try direct .body attribute
        tmp: Any = getattr(resp, "body", b"")
        if tmp:
            body = tmp.tobytes() if isinstance(tmp, memoryview) else bytes(tmp)

        # 2) if empty, drain body_iterator (LiteLLM sometimes uses this)
        if not body:
            body_iter: Optional[Any] = getattr(resp, "body_iterator", None)
            if body_iter is not None:
                body = await self._drain_iterator(body_iter)

                # we consumed the iterator → replace with one that replays
                async def replay():
                    yield body

                resp.body_iterator = replay()  # type: ignore[attr-defined]

        # 3) gunzip if needed
        if resp.headers.get("content-encoding") == "gzip":
            try:
                body = gzip.decompress(body)
            except Exception:
                # malformed gzip – keep raw
                pass

        print("===== FINAL RESPONSE (JSON) =====")
        print(body.decode("utf-8", errors="replace"))
        print("=================================\n")

        return resp
