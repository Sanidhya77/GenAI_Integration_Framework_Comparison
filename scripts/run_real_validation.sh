#!/bin/bash
#
# Optional real-API validation of the simulator (spends money; see
# scripts/run_real_validation.py for the full description).
#
#   PHASE=A (default)  FastAPI inference: c = 1 anchor x 3 runs, then c = 25 x 3 runs
#   PHASE=B            FastAPI stream:    c = 1 anchor x 3 runs, then c = 25 x 3 runs
#   PHASE=all          A then B
#   BUDGET_USD         refuse if the estimated total exceeds this (default 5.00)
#   REST_MODE=short    fixed 30 s rests instead of the thesis formulas
#
# Output: data_v2_real/. Analysis: venv/bin/python scripts/validate_real_v2.py --phase <a|b|all>
#
# Usage:
#   cd /home/sanidhya/experiment
#   export $(cat .env | xargs)          # provides ANTHROPIC_API_KEY
#   ALLOW_REAL_API=1 PHASE=A ./scripts/run_real_validation.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${ALLOW_REAL_API:-}" != "1" ]; then
    echo "Refusing to run: this script calls the real Anthropic API. Set ALLOW_REAL_API=1 to proceed."
    exit 1
fi

exec venv/bin/python scripts/run_real_validation.py
