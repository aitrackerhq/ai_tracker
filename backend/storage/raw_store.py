import json
from pathlib import Path
from typing import Any

from backend.config import settings


class RawStore:
    """Append-only JSON store. Each run is one file; nothing here is mutated after write."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, run_id: str) -> Path:
        return self.base_dir / f"{run_id}.json"

    def write(self, run_id: str, payload: dict[str, Any]) -> Path:
        path = self.path_for(run_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read(self, run_id: str) -> dict[str, Any]:
        return json.loads(self.path_for(run_id).read_text(encoding="utf-8"))

    def exists(self, run_id: str) -> bool:
        return self.path_for(run_id).exists()

    def list_ids(self) -> list[str]:
        return sorted(p.stem for p in self.base_dir.glob("*.json"))


raw_store = RawStore(settings.raw_dir)
processed_store = RawStore(settings.processed_dir)
