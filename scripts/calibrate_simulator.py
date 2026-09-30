"""
Calibration script for the simulated endpoint.

Runs a small number of real Anthropic API calls to determine:
  - Median response time (becomes the simulated delay)
  - Tokens per second rate (becomes the simulated streaming rate)
  - Average response token count (becomes the simulated payload size)

These values are saved to simulated_endpoint/calibration.json and used by the simulator to produce realistic timing behaviour.

Run command:
  cd /home/sanidhya/experiment
  source venv/bin/activate
  export $(cat .env | xargs)
  python scripts/calibrate_simulator.py

"""

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import (
    ANTHROPIC_MODEL,
    MAX_TOKENS,
    SYSTEM_PROMPT,
    TEMPERATURE,
    USER_PROMPT,
)

from anthropic import Anthropic

# This script calls the real Anthropic API; refuse unless explicitly allowed.
if os.environ.get("ALLOW_REAL_API") != "1":
    sys.exit("Refusing to call the real Anthropic API: set ALLOW_REAL_API=1 to run this script.")

# Number of calibration runs
NUM_RUNS = 5

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "simulated_endpoint",
    "calibration.json",
)


def calibrate_inference():
    """Run standard inference calls and measure response time and token count."""
    client = Anthropic()
    response_times = []
    output_token_counts = []
    input_token_counts = []

    print(f"Running {NUM_RUNS} inference calibration calls...")
    print(f"Model: {ANTHROPIC_MODEL}")
    print(f"Max tokens: {MAX_TOKENS}")
    print()

    for i in range(NUM_RUNS):
        start = time.perf_counter()
        message = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": USER_PROMPT}],
        )
        elapsed = time.perf_counter() - start

        response_times.append(elapsed)
        output_token_counts.append(message.usage.output_tokens)
        input_token_counts.append(message.usage.input_tokens)

        print(f"  Run {i + 1}: {elapsed:.3f}s | "
              f"{message.usage.output_tokens} output tokens | "
              f"{message.usage.input_tokens} input tokens")

    return response_times, output_token_counts, input_token_counts


def calibrate_streaming():
    """Run streaming calls and measure tokens per second."""
    client = Anthropic()
    tps_values = []

    print(f"\nRunning {NUM_RUNS} streaming calibration calls...")

    for i in range(NUM_RUNS):
        token_times = []

        with client.messages.stream(
            model=ANTHROPIC_MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": USER_PROMPT}],
        ) as stream:
            for text in stream.text_stream:
                token_times.append(time.perf_counter())

        if len(token_times) >= 2:
            total_duration = token_times[-1] - token_times[0]
            num_tokens = len(token_times)
            tps = (num_tokens - 1) / total_duration if total_duration > 0 else 0
            tps_values.append(tps)
            print(f"  Run {i + 1}: {tps:.1f} tokens/s | {num_tokens} tokens | {total_duration:.3f}s")

    return tps_values


def main():
    print("=" * 60)
    print("SIMULATOR CALIBRATION")
    print("=" * 60)
    print()

    # Run calibration
    response_times, output_tokens, input_tokens = calibrate_inference()
    tps_values = calibrate_streaming()

    # Compute calibration values
    median_response_time = statistics.median(response_times)
    median_tps = statistics.median(tps_values) if tps_values else 50.0
    median_output_tokens = int(statistics.median(output_tokens))
    median_input_tokens = int(statistics.median(input_tokens))

    calibration = {
        "median_response_time_s": round(median_response_time, 3),
        "tokens_per_second": round(median_tps, 1),
        "total_output_tokens": median_output_tokens,
        "input_tokens": median_input_tokens,
        "model": ANTHROPIC_MODEL,
        "raw_response_times": [round(t, 3) for t in response_times],
        "raw_tps_values": [round(t, 1) for t in tps_values],
        "raw_output_tokens": output_tokens,
    }

    # Save to file
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2)

    # Print summary
    print()
    print("=" * 60)
    print("CALIBRATION RESULTS")
    print("=" * 60)
    print(f"Median response time:  {median_response_time:.3f}s")
    print(f"Median tokens/second:  {median_tps:.1f}")
    print(f"Median output tokens:  {median_output_tokens}")
    print(f"Median input tokens:   {median_input_tokens}")
    print()
    print(f"Response time range:   {min(response_times):.3f}s - {max(response_times):.3f}s")
    print(f"TPS range:             {min(tps_values):.1f} - {max(tps_values):.1f}")
    print()
    print(f"Saved to: {OUTPUT_PATH}")
    print()
    print("Cost estimate: ~$0.01 (10 API calls)")


if __name__ == "__main__":
    main()