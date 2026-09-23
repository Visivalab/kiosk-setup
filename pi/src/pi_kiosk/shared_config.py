import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def config() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[3] / "shared" / "kiosk.json"
    return json.loads(path.read_text(encoding="utf-8"))
