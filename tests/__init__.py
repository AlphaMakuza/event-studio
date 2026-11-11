"""Keep direct module-based unittest runs away from real application storage."""
import os
from pathlib import Path
import tempfile

if os.environ.get("EVENT_STUDIO_TEST_STORAGE") != "1":
    root = Path(__file__).resolve().parents[1] / "artifacts" / "test-storage"
    root.mkdir(parents=True, exist_ok=True)
    os.environ["EVENT_STUDIO_HOME"] = tempfile.mkdtemp(prefix="unittest-", dir=root)
    os.environ["EVENT_STUDIO_TEST_STORAGE"] = "1"
