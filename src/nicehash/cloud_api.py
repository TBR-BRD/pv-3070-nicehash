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
        """Raw response of GET /main/api/v2/mining/rigs2 - shape not finalized yet,
        see scripts/test_nicehash_cloud.py to inspect a real response first."""
        return self.request("GET", "/main/api/v2/mining/rigs2")
