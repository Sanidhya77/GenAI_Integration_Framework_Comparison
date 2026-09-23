"""
Flask application — WSGI synchronous framework.

Endpoints:
  /api/inference        — Standard request-response (Endpoint 1)
  /api/inference/stream — SSE streaming token-by-token (Endpoint 2)
  /api/pipeline         — Four-stage compound AI pipeline (Endpoint 3)

Server: Gunicorn 25.3.0 with default sync worker class
Client: Anthropic() — synchronous
Streaming: Generator function with yield
"""

import json
import sys
import os
import time

# Add project root to path so common/ is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, Response, jsonify, request

from common.config import USER_PROMPT
from common.anthropic_client import get_sync_client, inference_sync, stream_sync
from common.pipeline_service import run_pipeline_sync

app = Flask(__name__)

# Create the SDK client at worker startup, not inside the first measured request
get_sync_client()

FRAMEWORK_NAME = "flask"



# Endpoint 1: /api/inference (Standard request-response)


@app.route("/api/inference", methods=["POST"])
def api_inference():
    """Receive prompt, call Anthropic API, return complete JSON response."""
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", USER_PROMPT)

    result = inference_sync(prompt)

    return jsonify(result)



# Endpoint 2: /api/inference/stream (SSE streaming)


@app.route("/api/inference/stream", methods=["POST"])
def api_inference_stream():
    """Receive prompt, stream tokens via Server-Sent Events."""
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", USER_PROMPT)

    def generate():
        token_count = 0
        for chunk in stream_sync(prompt):
            token_count += 1
            event_data = json.dumps({"token": chunk, "index": token_count})
            yield f"data: {event_data}\n\n"

        # Signal stream completion
        yield f"data: {json.dumps({'done': True, 'total_tokens': token_count})}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )



# Endpoint 3: /api/pipeline (Four-stage compound AI pipeline)

@app.route("/api/pipeline", methods=["POST"])
def api_pipeline():
    """Execute the 4-stage RAG pipeline and return result with stage timings."""
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", USER_PROMPT)

    result = run_pipeline_sync(prompt, framework_name=FRAMEWORK_NAME)

    return jsonify(result)

# Health check

@app.route("/health", methods=["GET"])
def health():
    """Simple health check for verifying server is running."""
    return jsonify({"status": "ok", "framework": FRAMEWORK_NAME})



# Development server (Gunicorn)

if __name__ == "__main__":
    from common.config import SERVER_HOST, SERVER_PORT
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=True)