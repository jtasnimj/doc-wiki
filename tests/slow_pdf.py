"""Controlled subprocess used to prove hard cancellation, cleanup and slot reuse."""

import json
import os
import signal
import sys
import time
from pathlib import Path

source, output, options = map(str, sys.argv[1:])
Path(source + ".pid").write_text(str(os.getpid()))
Path(source + ".output").write_text(output)
if "slow" in source:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(1)
Path(output).write_text(
    json.dumps(
        {
            "blocks": [
                {
                    "text": "Ready fixture text",
                    "kind": "pdf",
                    "location": {"page": 1},
                    "method": "fake-process",
                }
            ],
            "page_count": 1,
        }
    )
)
