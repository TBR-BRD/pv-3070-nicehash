from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml

@dataclass
class Settings:
    data: dict[str, Any]

    @property
    def app(self): return self.data["application"]
    @property
    def pv(self): return self.data["pv"]
    @property
    def gpu(self): return self.data["gpu"]
    @property
    def nicehash(self): return self.data["nicehash"]
    @property
    def logging(self): return self.data["logging"]

def load_settings(path: str = "config.yaml") -> Settings:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Configuration not found: {p.resolve()}")
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Settings(data)
