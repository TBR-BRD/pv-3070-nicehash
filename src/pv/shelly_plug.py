from __future__ import annotations
import requests


class ShellyPlugError(RuntimeError):
    pass


class ShellyPlugReader:
    """Reads a Shelly Plug S (Gen2/3, RPC API) placed in front of the PC, used
    purely as an informational power meter for the dashboard - it is not part
    of the control loop."""

    def __init__(self, ip: str, timeout: float = 5):
        self.url = f"http://{ip}/rpc/Switch.GetStatus"
        self.timeout = timeout

    def read(self) -> dict:
        try:
            response = requests.get(self.url, params={"id": 0}, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise ShellyPlugError(str(exc)) from exc
        return {
            "power_w": data.get("apower"),
            "energy_kwh": (data.get("aenergy") or {}).get("total", 0) / 1000.0,
            "on": data.get("output"),
        }
