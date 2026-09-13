from __future__ import annotations
import requests

class ShellyError(RuntimeError):
    pass

def _find_number(obj, key: str):
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], (int, float)):
            return float(obj[key])
        for value in obj.values():
            found = _find_number(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_number(value, key)
            if found is not None:
                return found
    return None

class ShellyReader:
    def __init__(self, ip: str, timeout: float = 5, invert_power_sign: bool = False):
        self.url = f"http://{ip}/rpc/Shelly.GetStatus"
        self.timeout = timeout
        self.invert = invert_power_sign

    def read_power_watts(self) -> float:
        try:
            response = requests.get(self.url, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise ShellyError(str(exc)) from exc
        total = _find_number(data, "total_act_power")
        if total is None:
            raise ShellyError("Shelly response contains no total_act_power")
        return -total if not self.invert else total
