"""
FastAPI application -ASGI asynchronous framework.

Endpoints:
  /api/inference        — Standard request-response (Endpoint 1)
  /api/inference/stream — SSE streaming token-by-token (Endpoint 2)
  /api/pipeline         — Four-stage compound AI pipeline (Endpoint 3)

Server: Uvicorn 0.42.0
Client: AsyncAnthropic() — asynchronous with await
Streaming: StreamingResponse with async generator
"""

import json
import sys
import os

# Add project root to path so common/ is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from common.config import USER_PROMPT
from common.anthropic_client import get_async_client, inference_async, stream_async
from common.pipeline_service import run_pipeline_async

app = FastAPI()

# Create the SDK client at server startup, not inside the first measured request
get_async_client()

FRAMEWORK_NAME = "fastapi"


# Endpoint 1: /api/inference (Standard request-response)

@app.post("/api/inference")
async def api_inference(request: Request):
    """Receive prompt, call Anthropic API, return complete JSON response."""
    try:
        data = await request.json()
    except Exception:
        data = {}

    prompt = data.get("prompt", USER_PROMPT)

    result = await inference_async(prompt)

    return JSONResponse(content=result)



# Endpoint 2: /api/inference/stream  (SSE streaming)

@app.post("/api/inference/stream")
async def api_inference_stream(request: Request):
    """Receive prompt, stream tokens via Server-Sent Events."""
    try:
        data = await request.json()
    except Exception:
        data = {}

    prompt = data.get("prompt", USER_PROMPT)

    async def generate():
        token_count = 0
        async for chunk in stream_async(prompt):
            token_count += 1
            event_data = json.dumps({"token": chunk, "index": token_count})
            yield f"data: {event_data}\n\n"

        # Signal stream completion
        yield f"data: {json.dumps({'done': True, 'total_tokens': token_count})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )



# Endpoint 3: /api/pipeline  (Four-stage compound AI pipeline)


@app.post("/api/pipeline")
async def api_pipeline(request: Request):
    """Execute the 4-stage RAG pipeline and return result with stage timings."""
    try:
        data = await request.json()
    except Exception:
        data = {}

    prompt = data.get("prompt", USER_PROMPT)

    result = await run_pipeline_async(prompt, framework_name=FRAMEWORK_NAME)

    return JSONResponse(content=result)


# Health check


@app.get("/health")
async def health():
    """Simple health check for verifying server is running."""
    return JSONResponse(content={"status": "ok", "framework": FRAMEWORK_NAME})



# Development server (Uvicorn)


if __name__ == "__main__":
    import uvicorn
    from common.config import SERVER_HOST, SERVER_PORT
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)