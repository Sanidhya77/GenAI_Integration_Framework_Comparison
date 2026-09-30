"""
Tornado application a Native event loop, asynchronous framework.

Endpoints:
  /api/inference        — Standard request-response (Endpoint 1)
  /api/inference/stream — SSE streaming token-by-token (Endpoint 2)
  /api/pipeline         — Four-stage compound AI pipeline (Endpoint 3)

Server: Built-in HTTP server (no external server)
Integrated with Python asyncio since v5.0
Client: AsyncAnthropic() — asynchronous with await
Streaming: self.write() + self.flush() per chunk
"""

import asyncio
import json
import sys
import os

# Add project root to path so common/ is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tornado.ioloop
import tornado.web
import tornado.httpserver

from common.config import SERVER_HOST, SERVER_PORT, USER_PROMPT
from common.anthropic_client import get_async_client, inference_async, stream_async
from common.pipeline_service import run_pipeline_async

# Create the SDK client at server startup, not inside the first measured request
get_async_client()

FRAMEWORK_NAME = "tornado"



# Endpoint 1: /api/inference (Standard request-response)

class InferenceHandler(tornado.web.RequestHandler):
    """Receive prompt, call Anthropic API, return complete JSON response."""

    async def post(self):
        try:
            data = json.loads(self.request.body) if self.request.body else {}
        except json.JSONDecodeError:
            data = {}

        prompt = data.get("prompt", USER_PROMPT)

        result = await inference_async(prompt)

        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(result))



# Endpoint 2: /api/inference/stream  (SSE streaming)


class InferenceStreamHandler(tornado.web.RequestHandler):
    """Receive prompt, stream tokens via Server-Sent Events."""

    async def post(self):
        try:
            data = json.loads(self.request.body) if self.request.body else {}
        except json.JSONDecodeError:
            data = {}

        prompt = data.get("prompt", USER_PROMPT)

        self.set_header("Content-Type", "text/event-stream")
        self.set_header("Cache-Control", "no-cache")
        self.set_header("X-Accel-Buffering", "no")

        token_count = 0
        async for chunk in stream_async(prompt):
            token_count += 1
            event_data = json.dumps({"token": chunk, "index": token_count})
            self.write(f"data: {event_data}\n\n")
            self.flush()

        # Signal stream completion
        self.write(f"data: {json.dumps({'done': True, 'total_tokens': token_count})}\n\n")
        self.flush()



# Endpoint 3: /api/pipeline (Four-stage compound AI pipeline)


class PipelineHandler(tornado.web.RequestHandler):
    """Execute the 4-stage RAG pipeline and return result with stage timings."""

    async def post(self):
        try:
            data = json.loads(self.request.body) if self.request.body else {}
        except json.JSONDecodeError:
            data = {}

        prompt = data.get("prompt", USER_PROMPT)

        result = await run_pipeline_async(prompt, framework_name=FRAMEWORK_NAME)

        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(result))



# Health check


class HealthHandler(tornado.web.RequestHandler):
    """Simple health check for verifying server is running."""

    def get(self):
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"status": "ok", "framework": FRAMEWORK_NAME}))



# Application setup


def make_app():
    """Create the Tornado application with URL routing."""
    return tornado.web.Application([
        (r"/api/inference", InferenceHandler),
        (r"/api/inference/stream", InferenceStreamHandler),
        (r"/api/pipeline", PipelineHandler),
        (r"/health", HealthHandler),
    ])


if __name__ == "__main__":
    app = make_app()
    server = tornado.httpserver.HTTPServer(app)
    server.listen(SERVER_PORT, address=SERVER_HOST)
    print(f"Tornado listening on {SERVER_HOST}:{SERVER_PORT}")
    tornado.ioloop.IOLoop.current().start()