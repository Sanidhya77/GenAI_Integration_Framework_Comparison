#!/bin/bash
#
# Optional real-API validation of the simulator at high concurrency (C-I).
# FastAPI, /api/inference, c = 25, 3 runs, real Anthropic API, server restart per run,
# output to data_v2_real/. Compare afterwards with the simulated FastAPI inference c = 25
# runs in data_v2/.
#
# This script spends money and uses rate limit. It refuses to run unless
# ALLOW_REAL_API=1 is set, prints the expected request count and cost, and waits for a
# typed "yes".
#
# Usage:
#   cd /home/sanidhya/experiment
#   export $(cat .env | xargs)          # provides ANTHROPIC_API_KEY
#   ALLOW_REAL_API=1 ./scripts/run_real_validation.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${ALLOW_REAL_API:-}" != "1" ]; then
    echo "Refusing to run: this script calls the real Anthropic API. Set ALLOW_REAL_API=1 to proceed."
    exit 1
fi
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ANTHROPIC_API_KEY is not set (export \$(cat .env | xargs) first)."
    exit 1
fi

PY=venv/bin/python
FRAMEWORK=fastapi
ENDPOINT=inference
CONCURRENCY=25
RUNS=3
DURATION_S=60
WARMUP=3

$PY - "$CONCURRENCY" "$RUNS" "$DURATION_S" "$WARMUP" <<'EOF'
import json, sys
c, runs, dur, warm = (int(x) for x in sys.argv[1:5])
cal = json.load(open("simulated_endpoint/calibration_v2.json"))["values"]
s = cal["service_time_s"]["inference"]
per_min = c / s * 60
per_run = c / s * dur + warm
total = per_run * runs
tin, tout = cal["inference_input_tokens"], cal["output_tokens"]
price_in, price_out = 1.00, 5.00   # USD per million tokens, Claude Haiku 4.5 list price
cost = total * (tin * price_in + tout * price_out) / 1e6
print("Real-API validation: FastAPI /api/inference, c = %d, %d runs x %d s, model %s" % (c, runs, dur, cal["model"]))
print("  expected requests: about %.0f per run (incl. %d warm-up), about %.0f in total" % (per_run, warm, total))
print("  expected tokens per request: %d input, %d output" % (tin, tout))
print("  expected cost at Haiku 4.5 list prices ($%.2f in / $%.2f out per MTok): about $%.2f" % (price_in, price_out, cost))
print("  RATE LIMIT: about %.0f requests per minute and about %.0f output tokens per minute must fit" % (per_min, per_min * tout))
print("  your account's limits for this model; 429 responses would be retried by the SDK and distort the run.")
EOF

read -r -p "Type yes to call the real Anthropic API: " ANSWER
if [ "$ANSWER" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

exec $PY scripts/run_matrix.py --mode real --frameworks "$FRAMEWORK" --endpoints "$ENDPOINT" \
    --concurrency "$CONCURRENCY" --runs 1,2,3 --duration "${DURATION_S}s" --out data_v2_real
