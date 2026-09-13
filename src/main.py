from __future__ import annotations
import time
from src.config import load_settings
from src.pv.shelly import ShellyReader
from src.gpu.nvidia import NvidiaGPU
from src.nicehash.manager import NiceHashManager
from src.controller.pv_controller import PVController
from src.monitoring.logger import setup_logging

def main():
    s = load_settings()
    log = setup_logging(s.app["log_level"], s.logging["file"])
    pv = ShellyReader(s.pv["shelly_ip"], s.pv["request_timeout_seconds"], s.pv["invert_power_sign"])
    gpu = NvidiaGPU(s.gpu["index"])
    nh = NiceHashManager(s.nicehash["executable"], s.nicehash["working_directory"], s.nicehash["process_name"], s.nicehash["startup_timeout_seconds"], s.nicehash["stop_timeout_seconds"])
    cfg = {**s.pv, **s.gpu}
    controller = PVController(pv, gpu, nh, cfg, log)
    dry = bool(s.app.get("dry_run", True))
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
