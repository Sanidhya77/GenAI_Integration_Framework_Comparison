"""
Derive simulator calibration (v2) from the EXISTING real-API thesis data.

No API calls are made. Every value written to simulated_endpoint/calibration_v2.json
carries its source files, sample size and method under "provenance".

Inputs (read only):
  data/*/pipeline/c1_run*_pipeline_metrics.csv   Stage 3 at c = 1 (real API)
  data/*/stream/c1_run*_stream_metrics.csv       TTFT, TPOT, chunk count at c = 1
  data/*/{inference,pipeline}/c1_run*_stats.csv  Average Content Size at c = 1
  simulated_endpoint/calibration.json            thesis calibration (optional cross-check)

Run command:
  cd /home/sanidhya/experiment
  venv/bin/python scripts/calibrate_from_data.py
"""

import collections
import csv
import glob
import json
import os
import statistics
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from common.config import (  # noqa: E402
    ANTHROPIC_MODEL,
    MAX_TOKENS,
    RETRIEVAL_DELAY_SECONDS,
    USER_PROMPT,
)

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_PATH = os.path.join(BASE_DIR, "simulated_endpoint", "calibration_v2.json")
THESIS_CALIBRATION = os.path.join(BASE_DIR, "simulated_endpoint", "calibration.json")

FRAMEWORKS = ["flask", "django", "fastapi", "tornado"]
PIPELINE_PROMPT_PREFIX = "Context from knowledge base:"

# Thesis calibration values as published (Chapter 3). Cross-checked against the
# local, untracked simulated_endpoint/calibration.json when it exists.
THESIS_INFERENCE_DELAY_S = 2.878
THESIS_INPUT_TOKENS = 33
THESIS_OUTPUT_TOKENS = 256

# Representative stage_timings dict used only to size the pipeline JSON envelope.
_STAGE_TIMINGS_TEMPLATE = {
    "framework": "",
    "timestamp": 1775232874.123456,
    "stage1_query_analysis_ms": 0.001,
    "stage2_context_retrieval_ms": 50.312,
    "stage3_augmented_inference_ms": 2696.243,
    "stage4_postprocessing_ms": 0.002,
    "total_pipeline_ms": 2746.671,
}


def rel(path):
    return os.path.relpath(path, BASE_DIR)


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def serialise(framework, obj):
    """Byte length of obj as each framework serialises it in the thesis apps.

    flask:   jsonify, non-debug DefaultJSONProvider (compact, sort_keys, ascii) + newline
    django:  JsonResponse, json.dumps defaults
    fastapi: JSONResponse, compact separators, ensure_ascii=False
    tornado: json.dumps defaults
    """
    if framework == "flask":
        body = json.dumps(obj, separators=(",", ":"), sort_keys=True) + "\n"
    elif framework == "fastapi":
        body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    else:
        body = json.dumps(obj)
    return len(body.encode("utf-8"))


def mean_content_size(framework, endpoint):
    files = sorted(glob.glob(os.path.join(DATA_DIR, framework, endpoint, "c1_run*_stats.csv")))
    total_bytes, total_n = 0.0, 0
    for path in files:
        row = [r for r in read_rows(path) if r["Name"] != "Aggregated"][0]
        n = int(row["Request Count"])
        total_bytes += float(row["Average Content Size"]) * n
        total_n += n
    return total_bytes / total_n, total_n, files


def text_bytes(endpoint, envelope_fn):
    """Median over frameworks of (real body bytes - envelope bytes with empty text)."""
    per_fw, files_all, n_all = {}, [], 0
    for fw in FRAMEWORKS:
        size, n, files = mean_content_size(fw, endpoint)
        per_fw[fw] = round(size - serialise(fw, envelope_fn(fw)), 1)
        files_all += files
        n_all += n
    return int(round(statistics.median(per_fw.values()))), per_fw, files_all, n_all


def main():
    values, provenance = {}, {}

    thesis = {}
    if os.path.exists(THESIS_CALIBRATION):
        with open(THESIS_CALIBRATION, encoding="utf-8") as f:
            thesis = json.load(f)
        for key, expected in (("median_response_time_s", THESIS_INFERENCE_DELAY_S),
                              ("input_tokens", THESIS_INPUT_TOKENS),
                              ("total_output_tokens", THESIS_OUTPUT_TOKENS)):
            if thesis.get(key) != expected:
                sys.exit(f"calibration.json {key}={thesis.get(key)} differs from thesis value {expected}")
    thesis_src = (rel(THESIS_CALIBRATION) + " (local, untracked); thesis Chapter 3"
                  if thesis else "thesis Chapter 3 (calibration.json not present)")

    # Inference delay: kept from the thesis calibration.
    values["inference_delay_s"] = THESIS_INFERENCE_DELAY_S
    provenance["inference_delay_s"] = {
        "source": thesis_src, "n": len(thesis.get("raw_response_times", [])) or None,
        "method": "median of 5 real non-streaming calls (scripts/calibrate_simulator.py); kept unchanged",
    }

    # Pipeline Stage 3 delay: pooled median of real Stage 3 at c = 1.
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*", "pipeline", "c1_run*_pipeline_metrics.csv")))
    stage3 = [float(r["stage3_ms"]) for p in files for r in read_rows(p)
              if r["completed"] == "True" and r["stage3_ms"] not in ("", "None")]
    values["pipeline_delay_s"] = round(statistics.median(stage3) / 1000, 4)
    provenance["pipeline_delay_s"] = {
        "source": [rel(p) for p in files], "n": len(stage3),
        "method": "pooled median of server-side stage3_ms over completed requests, all 4 frameworks, c = 1",
    }
    values["pipeline_prompt_prefix"] = PIPELINE_PROMPT_PREFIX
    provenance["pipeline_prompt_prefix"] = {
        "source": "common/pipeline_service.py _build_augmented_prompt", "n": None,
        "method": "a user message starting with this prefix is treated as a pipeline (Stage 3) call",
    }

    # Streaming: first-chunk delay, inter-chunk interval, modal chunk count at c = 1.
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*", "stream", "c1_run*_stream_metrics.csv")))
    rows = [r for p in files for r in read_rows(p) if r["success"] == "True"]
    ttft = [float(r["ttft_ms"]) for r in rows if r["ttft_ms"] not in ("", "None")]
    tpot = [float(r["tpot_ms"]) for r in rows if r["tpot_ms"] not in ("", "None")]
    counts = collections.Counter(int(r["token_count"]) for r in rows)
    mode_count, mode_n = counts.most_common(1)[0]
    values["stream_first_chunk_delay_s"] = round(statistics.median(ttft) / 1000, 4)
    values["stream_chunk_interval_s"] = round(statistics.median(tpot) / 1000, 4)
    values["chunks_per_second"] = round(1000 / statistics.median(tpot), 3)
    values["stream_chunk_count"] = mode_count
    stream_src = [rel(p) for p in files]
    provenance["stream_first_chunk_delay_s"] = {
        "source": stream_src, "n": len(ttft),
        "method": "pooled median of client-side TTFT (ms) over successful streams, all 4 frameworks, c = 1",
    }
    provenance["stream_chunk_interval_s"] = {
        "source": stream_src, "n": len(tpot),
        "method": "pooled median of TPOT = (last - first text chunk) / (chunks - 1), c = 1",
    }
    provenance["chunks_per_second"] = {
        "source": stream_src, "n": len(tpot), "method": "1 / stream_chunk_interval_s (text chunks, not tokens)",
    }
    provenance["stream_chunk_count"] = {
        "source": stream_src, "n": len(rows),
        "method": f"modal token_count (text chunks) at c = 1; distribution {dict(sorted(counts.items()))}, "
                  f"mode frequency {mode_n}",
    }

    # Response text sizes from real body sizes at c = 1.
    usage = {"input_tokens": THESIS_INPUT_TOKENS, "output_tokens": THESIS_OUTPUT_TOKENS}
    inf_bytes, inf_per_fw, inf_files, inf_n = text_bytes(
        "inference", lambda fw: {"response": "", "model": ANTHROPIC_MODEL, "usage": usage})
    values["inference_text_bytes"] = inf_bytes
    provenance["inference_text_bytes"] = {
        "source": [rel(p) for p in inf_files], "n": inf_n,
        "method": "median over frameworks of (request-weighted mean Average Content Size at c = 1 minus "
                  f"the framework's own JSON envelope with empty text); per framework {inf_per_fw}",
    }

    def pipeline_envelope(fw):
        st = dict(_STAGE_TIMINGS_TEMPLATE, framework=fw)
        return {"pipeline_result": {"answer": "", "model": ANTHROPIC_MODEL, "usage": usage},
                "stage_timings": st}

    pipe_bytes, pipe_per_fw, pipe_files, pipe_n = text_bytes("pipeline", pipeline_envelope)
    values["pipeline_text_bytes"] = pipe_bytes
    provenance["pipeline_text_bytes"] = {
        "source": [rel(p) for p in pipe_files], "n": pipe_n,
        "method": "as inference_text_bytes, envelope = pipeline_result + a representative stage_timings "
                  f"dict; per framework {pipe_per_fw}",
    }

    # Usage and stop reason.
    values["inference_input_tokens"] = THESIS_INPUT_TOKENS
    values["output_tokens"] = THESIS_OUTPUT_TOKENS
    values["stop_reason"] = "max_tokens" if THESIS_OUTPUT_TOKENS >= MAX_TOKENS else "end_turn"
    provenance["inference_input_tokens"] = {"source": thesis_src, "n": 5, "method": "thesis calibration median"}
    provenance["output_tokens"] = {"source": thesis_src, "n": 5,
                                   "method": "thesis calibration median (all 5 calls returned 256 = max_tokens)"}
    provenance["stop_reason"] = {"source": "derived", "n": None,
                                 "method": "output_tokens == MAX_TOKENS (common/config.py) implies max_tokens"}

    from common.retrieval import _search  # local import: reads document_store only
    from common.pipeline_service import _build_augmented_prompt
    augmented = _build_augmented_prompt(USER_PROMPT, _search(USER_PROMPT))
    values["pipeline_input_tokens"] = THESIS_INPUT_TOKENS + round((len(augmented) - len(USER_PROMPT)) / 4)
    provenance["pipeline_input_tokens"] = {
        "source": "document_store/genai_concepts.txt via common.retrieval._search", "n": None,
        "method": "ESTIMATE, not measured: inference input tokens + (augmented prompt chars - prompt chars) / 4; "
                  "only echoed in the usage field",
    }
    values["model"] = ANTHROPIC_MODEL
    provenance["model"] = {"source": "common/config.py", "n": None, "method": "ANTHROPIC_MODEL"}

    # Service time per endpoint (upstream + fixed stage delays), used for spawn rate and ceilings.
    values["retrieval_delay_s"] = RETRIEVAL_DELAY_SECONDS
    provenance["retrieval_delay_s"] = {"source": "common/config.py", "n": None,
                                       "method": "RETRIEVAL_DELAY_SECONDS (Stage 2 sleep)"}
    values["service_time_s"] = {
        "inference": values["inference_delay_s"],
        "stream": round(values["stream_first_chunk_delay_s"]
                        + (values["stream_chunk_count"] - 1) * values["stream_chunk_interval_s"], 4),
        "pipeline": round(RETRIEVAL_DELAY_SECONDS + values["pipeline_delay_s"], 4),
    }
    provenance["service_time_s"] = {
        "source": "derived", "n": None,
        "method": "inference = inference_delay_s; stream = first_chunk_delay + (chunk_count - 1) * interval; "
                  "pipeline = retrieval_delay_s + pipeline_delay_s",
    }

    out = {
        "schema": "calibration_v2",
        "generated_by": "scripts/calibrate_from_data.py",
        "values": values,
        "provenance": provenance,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    print(json.dumps(values, indent=2))
    print(f"Saved to: {rel(OUTPUT_PATH)}")


if __name__ == "__main__":
    main()
