from __future__ import annotations
import time
from src.config import load_settings
from src.pv.shelly import ShellyReader
from src.gpu.nvidia import NvidiaGPU
from src.nicehash.manager import NiceHashManager
from src.controller.pv_controller import PVController
from src.monitoring.logger import setup_logging
from src.monitoring.dashboard import DashboardState, start_dashboard_server

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
