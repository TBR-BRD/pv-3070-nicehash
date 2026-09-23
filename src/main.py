from __future__ import annotations
import os
import threading
import time
from src.config import load_settings
from src.pv.shelly import ShellyReader
from src.gpu.nvidia import NvidiaGPU
from src.nicehash.manager import NiceHashManager
from src.nicehash.cloud_api import NiceHashCloudClient, NiceHashCloudError, summarize_managed_rig
from src.controller.pv_controller import PVController
from src.monitoring.logger import setup_logging
from src.monitoring.dashboard import DashboardState, start_dashboard_server

def _start_nicehash_cloud_poller(dashboard, worker_name, poll_interval, log):
    """Polls the NiceHash Platform REST API in the background (separate from
    the main 10s control loop, since this hits an external service) and
    writes a flat summary into the dashboard state. Only ever reads data
    the account itself exposes - see src.nicehash.cloud_api."""
    org_id = os.environ.get("NICEHASH_ORG_ID")
    api_key = os.environ.get("NICEHASH_API_KEY")
    api_secret = os.environ.get("NICEHASH_API_SECRET")
    if not (org_id and api_key and api_secret):
        log.warning("nicehash_cloud enabled but NICEHASH_ORG_ID/API_KEY/API_SECRET not set (see .env.example)")
        return

    client = NiceHashCloudClient(org_id, api_key, api_secret)

    def loop():
        while True:
            try:
                rigs = client.get_rigs()
                summary = summarize_managed_rig(rigs, worker_name=worker_name)
                dashboard.update(nicehash_cloud=summary)
            except NiceHashCloudError as exc:
                log.warning("NiceHash cloud API error: %s", exc)
                dashboard.update(nicehash_cloud=None)
            except Exception as exc:
                log.warning("NiceHash cloud poll failed: %s", exc)
            time.sleep(poll_interval)

    threading.Thread(target=loop, daemon=True, name="nicehash-cloud-poller").start()

def main():
    s = load_settings()
    log = setup_logging(s.app["log_level"], s.logging["file"])
    pv = ShellyReader(s.pv["shelly_ip"], s.pv["request_timeout_seconds"], s.pv["invert_power_sign"])
    gpu = NvidiaGPU(s.gpu["index"])
    nh = NiceHashManager(s.nicehash["executable"], s.nicehash["working_directory"], s.nicehash["process_name"], s.nicehash["startup_timeout_seconds"], s.nicehash["stop_timeout_seconds"])
    cfg = {**s.pv, **s.gpu}
    dry = bool(s.app.get("dry_run", True))

    dashboard_cfg = s.data.get("dashboard", {})
    dashboard = None
    if dashboard_cfg.get("enabled", False):
        dashboard = DashboardState(s.app["name"], s.app["version"], dry, cfg)
        host = dashboard_cfg.get("host", "127.0.0.1")
        port = int(dashboard_cfg.get("port", 8090))
        start_dashboard_server(dashboard, host, port)
        log.info("Dashboard running at http://%s:%d/", host if host != "0.0.0.0" else "localhost", port)

    nicehash_cloud_cfg = s.data.get("nicehash_cloud", {})
    if dashboard and nicehash_cloud_cfg.get("enabled", False):
        _start_nicehash_cloud_poller(
            dashboard,
            nicehash_cloud_cfg.get("worker_name"),
            int(nicehash_cloud_cfg.get("poll_interval_seconds", 60)),
            log,
        )

    controller = PVController(pv, gpu, nh, cfg, log, dashboard=dashboard)
    log.info("PV 3070 NiceHash controller started (dry_run=%s)", dry)
    try:
        while True:
            controller.tick(dry_run=dry)
            time.sleep(float(s.app["poll_interval_seconds"]))
    except KeyboardInterrupt:
        log.info("Controller stopped by user")
        if not dry:
            controller._safe_stop()

if __name__ == "__main__":
    main()
