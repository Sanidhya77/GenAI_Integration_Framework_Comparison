"""Cost of the blocking per-request JSONL append done by common/pipeline_service.py:42-52 (makedirs + open(a) + write + close).
Writes only to a scratch directory passed as argv[1]."""
import json, os, sys, time, statistics
d = sys.argv[1]; rec = {"framework": "x", "timestamp": time.time(), "stage1_query_analysis_ms": 0.001, "stage2_context_retrieval_ms": 50.1, "stage3_augmented_inference_ms": 2900.0, "stage4_postprocessing_ms": 0.002, "total_pipeline_ms": 2950.1}
t = []
for _ in range(2000):
    a = time.perf_counter(); os.makedirs(os.path.join(d, "x"), exist_ok=True)
    with open(os.path.join(d, "x", "pipeline_timing.jsonl"), "a", encoding="utf-8") as f: f.write(json.dumps(rec) + "\n")
    t.append((time.perf_counter() - a) * 1e3)
print(f"median {statistics.median(t):.3f} ms, p99 {sorted(t)[int(len(t)*.99)]:.3f} ms")
