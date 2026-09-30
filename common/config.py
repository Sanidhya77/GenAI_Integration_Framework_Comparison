"""
Shared configuration for all four framework implementations.
Every parameter which is identical across Flask, Django, FastAPI, and Tornado
is defined here.

"""

import os


# Project paths

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCUMENT_STORE_PATH = os.path.join(BASE_DIR, "document_store", "genai_concepts.txt")
LOG_DIR = os.path.join(BASE_DIR, "logs")


# Anthropic API configuration (Section 3.2)

ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 256
TEMPERATURE = 0.0
SYSTEM_PROMPT = "You are a technical assistant specialising in web development."
USER_PROMPT = (
    "What is generative AI and how is it used in modern web applications?"
)

"""
Pipeline configuration (Section 3.2, Endpoint 3: /api/pipeline)
Stage 2 controlled delay simulating vector database network latency with 
time.sleep(0.05) for sync frameworks, asyncio.sleep(0.05) for async
"""
RETRIEVAL_DELAY_SECONDS = 0.05


# Server configuration

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000

"""
 Simulation mode flag When True, framework apps use the simulated endpoint instead of real API
 Controlled via environment variable: SIMULATE=1 or SIMULATE=0
"""
USE_SIMULATED = os.environ.get("SIMULATE", "0") == "1"

# Simulated Messages API (runs as a separate service); used as the SDK base_url
SIMULATED_ENDPOINT_URL = "http://127.0.0.1:9000"
# Dummy key sent to the simulator; never valid for api.anthropic.com
SIMULATED_API_KEY = "sk-ant-simulated-dummy-key"


# Gunicorn configuration for Flask and Django

GUNICORN_WORKERS = 1  # Single worker to isolate framework behaviour
GUNICORN_BIND = f"{SERVER_HOST}:{SERVER_PORT}"


# Uvicorn configuration for FastAPI

UVICORN_WORKERS = 1