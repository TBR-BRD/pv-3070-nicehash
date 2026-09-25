from __future__ import annotations
import hmac
import time
import uuid
from hashlib import sha256
import requests


class NiceHashCloudError(RuntimeError):
    pass


class NiceHashCloudClient:
    """Minimal read-only client for the NiceHash Platform REST API.

    Auth scheme (HMAC-SHA256 over key/time/nonce/org/method/path/query) ported
    from the official demo: https://github.com/nicehash/rest-clients-demo
    """

    def __init__(self, organization_id: str, api_key: str, api_secret: str,
                 host: str = "https://api2.nicehash.com", timeout: float = 10):
        self.organization_id = organization_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.host = host
        self.timeout = timeout

    def _headers_and_url(self, method: str, path: str, query: str = ""):
        xtime = int(time.time() * 1000)
        xnonce = str(uuid.uuid4())

        message = bytearray(self.api_key, "utf-8")
        message += b"\x00" + bytearray(str(xtime), "utf-8")
        message += b"\x00" + bytearray(xnonce, "utf-8")
        message += b"\x00\x00"
        message += bytearray(self.organization_id, "utf-8")
        message += b"\x00\x00"
        message += bytearray(method, "utf-8")
        message += b"\x00" + bytearray(path, "utf-8")
        message += b"\x00" + bytearray(query, "utf-8")

        digest = hmac.new(bytearray(self.api_secret, "utf-8"), message, sha256).hexdigest()
        headers = {
            "X-Time": str(xtime),
            "X-Nonce": xnonce,
            "X-Auth": f"{self.api_key}:{digest}",
            "Content-Type": "application/json",
            "X-Organization-Id": self.organization_id,
            "X-Request-Id": str(uuid.uuid4()),
        }
        url = self.host + path
        if query:
            url += "?" + query
        return headers, url

    def request(self, method: str, path: str, query: str = "") -> dict:
        headers, url = self._headers_and_url(method, path, query)
        try:
            response = requests.request(method, url, headers=headers, timeout=self.timeout)
        except Exception as exc:
            raise NiceHashCloudError(str(exc)) from exc
        if response.status_code != 200:
            raise NiceHashCloudError(f"{response.status_code}: {response.text[:300]}")
        return response.json()

    def get_rigs(self) -> dict:
        return self.request("GET", "/main/api/v2/mining/rigs2")


def _odv_value(odv_list, key: str, unit: str | None = None):
    """NiceHash reports per-device/-rig values as a flat list of
    {"key": ..., "unit": ..., "value": ...} dicts (the "odv" arrays), and the
    same key can appear more than once with different units (e.g. "Power
    Limit" in both "%" and "W") - so a lookup dict would silently pick the
    wrong one. This walks the list and matches on key (+ unit if given)."""
    for item in odv_list or []:
        if item.get("key") == key and (unit is None or item.get("unit") == unit):
            return item.get("value")
    return None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def summarize_managed_rig(rigs_response: dict, worker_name: str | None = None) -> dict | None:
    """Find the NHM-managed ("v4") rig - optionally the one matching
    worker_name - and return a flat summary for the dashboard. Returns None
    if no matching managed rig is present in the response.

    Confirmed against a real account response (2026-09-23); GPU device is
    matched by deviceClass "2" (falls back to name containing nvidia/rtx/
    geforce for older accounts where that might differ).
    """
    for rig in rigs_response.get("miningRigs", []):
        v4 = rig.get("v4")
        if not v4:
            continue
        rig_worker = (v4.get("mmv") or {}).get("workerName")
        if worker_name and rig_worker != worker_name:
            continue

        rig_odv = v4.get("odv") or []
        gpu_device = None
        for device in v4.get("devices", []):
            dsv = device.get("dsv", {})
            name = (dsv.get("name") or "").lower()
            if dsv.get("deviceClass") == "2" or any(s in name for s in ("nvidia", "geforce", "rtx")):
                gpu_device = device
                break
        gpu_odv = (gpu_device or {}).get("odv") or []

        speed = None
        if gpu_device:
            algo_speeds = (gpu_device.get("mdv") or {}).get("algorithmsSpeed") or []
            if algo_speeds:
                # Confirmed against a live mining response (2026-09-25): value
                # is raw H/s, "algorithm" is NiceHash's internal numeric
                # algorithm ID (e.g. "57"), not a human-readable name - so it
                # is kept but not shown as if it were one.
                first = algo_speeds[0]
                value_hs = _to_float(first.get("speed"))
                speed = {
                    "algorithm_id": first.get("algorithm"),
                    "value_hs": value_hs,
                    "value_mhs": (value_hs / 1_000_000) if value_hs is not None else None,
                }

        return {
            "worker_name": rig_worker,
            "gpu_name": (gpu_device or {}).get("dsv", {}).get("name"),
            "miner_status": rig.get("minerStatus"),
            "active_miner": _odv_value(gpu_odv, "Miner") or None,
            "uptime_s": _to_float(_odv_value(rig_odv, "Uptime", "s")),
            "unpaid_amount_btc": _to_float(rig.get("unpaidAmount")),
            "profitability_btc_day": rig.get("profitability"),
            "gpu_temperature_c": _to_float(_odv_value(gpu_odv, "Temperature", "°C")),
            "gpu_load_pct": _to_float(_odv_value(gpu_odv, "Load", "%")),
            "gpu_power_w": _to_float(_odv_value(gpu_odv, "Power usage", "W")),
            "gpu_power_limit_w": _to_float(_odv_value(gpu_odv, "Power Limit", "W")),
            "speed": speed,
        }
    return None
