"""Where data lives, independent of the folder a command is started from.

Default: <project root>/data. Override with the RISK_DATA_DIR environment variable
(e.g. a mounted volume in Docker).
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("RISK_DATA_DIR", PROJECT_ROOT / "data"))
