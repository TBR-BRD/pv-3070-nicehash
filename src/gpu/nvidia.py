from __future__ import annotations
import csv
import subprocess

class NvidiaError(RuntimeError):
    pass

class NvidiaGPU:
    def __init__(self, index: int = 0):
        self.index = index

    def _run(self, args: list[str]) -> str:
        try:
            p = subprocess.run(["nvidia-smi", *args], capture_output=True, text=True, timeout=10)
        except Exception as exc:
            raise NvidiaError(str(exc)) from exc
        if p.returncode != 0:
            raise NvidiaError(p.stderr.strip() or "nvidia-smi failed")
        return p.stdout.strip()

    def status(self) -> dict:
        out = self._run([
            f"--id={self.index}",
            "--query-gpu=name,power.draw,temperature.gpu,utilization.gpu",
            "--format=csv,noheader,nounits",
        ])
        row = next(csv.reader([out]))
        return {"name": row[0].strip(), "power_w": float(row[1]), "temperature_c": float(row[2]), "utilization_pct": float(row[3])}

    def set_power_limit(self, watts: int) -> None:
        self._run([f"--id={self.index}", f"--power-limit={int(watts)}"])
