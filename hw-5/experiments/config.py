import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "hw5"
IMAGE = "skill-pairs:hw5"
RUSTFS = "rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c"


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
