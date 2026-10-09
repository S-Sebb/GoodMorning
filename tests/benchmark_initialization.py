"""Compare sequential socket-style waits with the bounded setup coordinator."""

import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from setup_check import run_checks


def main():
    command = [sys.executable, "-c", "import time; time.sleep(5)"]
    started = time.monotonic()
    for _ in range(4):
        try:
            subprocess.run(command, timeout=0.15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            pass
    sequential = time.monotonic() - started
    started = time.monotonic()
    results = run_checks({str(index): command for index in range(4)}, 0.15)
    bounded = time.monotonic() - started
    print(json.dumps({"fixture": "four synthetic hanging checks; no providers or user records",
                      "sequential_seconds": round(sequential, 3), "shared_budget_seconds": round(bounded, 3),
                      "speedup": round(sequential / bounded, 2), "all_left_pending": all(row["status"] == "pending" for row in results.values())}))
    if not bounded < 0.75 or not all(row["status"] == "pending" for row in results.values()):
        raise SystemExit("bounded failure experiment did not meet its contract")


if __name__ == "__main__":
    main()
