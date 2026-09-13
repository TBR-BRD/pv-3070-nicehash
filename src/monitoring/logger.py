import logging
from pathlib import Path

def setup_logging(level: str, filename: str) -> logging.Logger:
    Path(filename).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("pv3070")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)
    file_handler = logging.FileHandler(filename, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    return logger
