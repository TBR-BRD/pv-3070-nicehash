from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os
import yaml


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no extra dependency). Existing environment
    variables always take precedence over the file. Silently does nothing
    if the file does not exist."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

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
    load_dotenv()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Configuration not found: {p.resolve()}")
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Settings(data)
