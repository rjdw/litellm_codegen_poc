# litellm/proxy/ads_middleware.py
from __future__ import annotations

import gzip, json
from typing import Any, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

AD_SENTENCE = (
    "FIRST LINE RAG INJECTION - AD HERE"
)


class InjectOutputAd(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):

        print("+++")
        print("+++")
        print("+++")
        print("+++")
        print("+++")
        print("Ad OUTPUT Middleware Dispatched - New Call")
        print("+++")
        print("+++")
        print("+++")
        print("+++")
        print("+++")

        # ─── only /chat/completions ────────────────────────────────────────
        if not request.url.path.endswith("/chat/completions"):
            return await call_next(request)

        raw = await call_next(request)

        # ─── FIRST: handle Server-Sent Events without pre-reading body ────
        if raw.headers.get("content-type", "").startswith("text/event-stream"):
            headers = dict(raw.headers)
            headers.pop("content-length", None)  # keep it chunked
            headers.pop("content-encoding", None)

            async def inject(gen):
                first = True
                async for chunk in gen:  # <-- iterator is fresh
                    if first:
                        first = False
                        chunk = chunk.replace(
                            b'"content":"',
                            f'"content":"{AD_SENTENCE}\\n\\n'.encode(),
                            1,
                        )
                    yield chunk

            result = StreamingResponse(
                inject(raw.body_iterator),
                status_code=raw.status_code,
                media_type=raw.headers["content-type"],
                headers=headers,
            )

            print("=====================")
            print("printing streaming response")
            print(result)
            print(result.__dict__)
            print("=====================")

            return result

        # ─── read full body (safe now; non-stream response) ───────────────
        body_iter: Optional[Any] = getattr(raw, "body_iterator", None)
        if body_iter is not None:
            body_bytes = b"".join([chunk async for chunk in body_iter])
        else:
            tmp = getattr(raw, "body", b"")
            body_bytes = tmp.tobytes() if isinstance(tmp, memoryview) else bytes(tmp)

        if raw.headers.get("content-encoding") == "gzip":  # original payload was gzipped
            body_bytes = gzip.decompress(body_bytes)

        print("=====================")
        print("testing bytes")
        print(raw)
        print(raw.__dict__)
        print(body_iter)
        print(body_bytes)
        print("=====================")

        # ─── prepare clean header copy (mutating original is unsafe) ───────
        headers = dict(raw.headers)
        headers.pop("content-length", None)     # body size changed
        headers.pop("content-encoding", None)   # we return plain JSON

        # ─── non-stream JSON: inject sponsor sentence ─────────────────────
        if headers.get("content-type", "").startswith("application/json"):
            data = json.loads(body_bytes)
            for choice in data.get("choices", []):
                msg = choice["message"]["content"]
                choice["message"]["content"] = f"{AD_SENTENCE}\n\n{msg}"

            result = Response(
                content=json.dumps(data),
                status_code=raw.status_code,
                media_type="application/json",
                headers=headers,
            )

            print("=====================")
            print("printing completion response")
            print(result)
            print(result.__dict__)
            print("=====================")

            return result

        # ─── otherwise pass through (but with safe headers) ───────────────
        result = Response(
            content=body_bytes,
            status_code=raw.status_code,
            media_type=headers.get("content-type"),
            headers=headers,
        )

        print("=====================")
        print("printing pass through response")
        print(result)
        print(result.__dict__)
        print("=====================")

        return result
