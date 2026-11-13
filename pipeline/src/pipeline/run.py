"""
Run the whole pipeline in order: ingest -> clean -> model -> load (the batch run).

    python pipeline/src/pipeline/run.py

Each step is the same script you can run on its own. If one step fails
(for example a FAIL in the data quality checks), the next steps do not run,
so bad data never reaches Neon.
"""

import subprocess
import sys
import time
from pathlib import Path

# ingest, then one big tick over every hour: clean -> model -> load, and the watermark is set
# to the last hour, so the hourly scheduler continues from there instead of starting again.
STEPS = [["ingest.py"], ["tick.py", "--rebuild"]]
HERE = Path(__file__).resolve().parent

start = time.time()

for script, *options in STEPS:
    print(f"\n=== {' '.join([script, *options])} ===", flush=True)
    result = subprocess.run([sys.executable, str(HERE / script), *options])
    if result.returncode != 0:
        print(f"\nPipeline stopped: {script} failed.")
        sys.exit(result.returncode)

print(f"\nPipeline finished in {time.time() - start:.0f}s")