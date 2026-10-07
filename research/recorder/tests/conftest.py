import sys
from pathlib import Path

# `python -m pytest tests` from research/recorder, no install needed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
