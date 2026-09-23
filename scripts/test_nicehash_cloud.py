"""Diagnostic script: prints the raw JSON of the NiceHash cloud "mining rigs"
endpoint so the exact response shape can be confirmed before wiring it into
the dashboard. Run manually once, with credentials in .env (copy from
.env.example) or as environment variables.

Usage (from the repo root, with the venv active):
    python scripts/test_nicehash_cloud.py
"""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import load_dotenv
from src.nicehash.cloud_api import NiceHashCloudClient, NiceHashCloudError


def main():
    load_dotenv()
    org_id = os.environ.get("NICEHASH_ORG_ID")
    api_key = os.environ.get("NICEHASH_API_KEY")
    api_secret = os.environ.get("NICEHASH_API_SECRET")

    missing = [name for name, value in
               [("NICEHASH_ORG_ID", org_id), ("NICEHASH_API_KEY", api_key), ("NICEHASH_API_SECRET", api_secret)]
               if not value]
    if missing:
        print("Missing environment variable(s): " + ", ".join(missing))
        print("Copy .env.example to .env and fill in your NiceHash API credentials.")
        sys.exit(1)

    client = NiceHashCloudClient(org_id, api_key, api_secret)
    try:
        data = client.get_rigs()
    except NiceHashCloudError as exc:
        print("Request failed:", exc)
        sys.exit(1)

    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
