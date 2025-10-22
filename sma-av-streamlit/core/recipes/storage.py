from __future__ import annotations
from pathlib import Path
from dataclasses import asdict, is_dataclass
import yaml

BASE = Path("data")

def save_yaml(obj, subdir: str, filename: str) -> Path:
    d = BASE / subdir
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    payload = asdict(obj) if is_dataclass(obj) else obj
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False)
    return p
