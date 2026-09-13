from __future__ import annotations
import time

class PVController:
    OFF = "OFF"
    STARTING = "STARTING"
    MINING = "MINING"
    STOPPING = "STOPPING"
    FAULT = "FAULT"

    def __init__(self, pv, gpu, nicehash, cfg, logger):
        self.pv, self.gpu, self.nicehash, self.cfg, self.log = pv, gpu, nicehash, cfg, logger
        self.state = self.OFF
        self.above_since = None
        self.below_since = None
        self.errors = 0

    def target_power(self, surplus: float) -> int:
        p = surplus - float(self.cfg["reserve_watts"])
        p = max(float(self.cfg["min_power_watts"]), min(float(self.cfg["max_power_watts"]), p))
        step = int(self.cfg["power_step_watts"])
        return int(p // step * step)

    def _safe_stop(self):
        try: self.gpu.set_power_limit(int(self.cfg["safe_power_watts"]))
        except Exception as exc: self.log.error("Could not set safe GPU power: %s", exc)
        try: self.nicehash.stop()
        except Exception as exc: self.log.error("Could not stop NiceHash: %s", exc)
        self.state = self.OFF
        self.above_since = self.below_since = None

    def tick(self, dry_run: bool = False):
        now = time.monotonic()
        try:
            surplus = self.pv.read_power_watts()
            gpu = self.gpu.status()
            self.errors = 0
        except Exception as exc:
            self.errors += 1
            self.log.error("Input error (%d): %s", self.errors, exc)
            if self.errors >= int(self.cfg["error_limit"]):
                self.state = self.FAULT
                if not dry_run: self._safe_stop()
            return

        if gpu["temperature_c"] >= float(self.cfg["temperature_critical_c"]):
            self.log.error("Critical GPU temperature: %.1f C", gpu["temperature_c"])
            if not dry_run: self._safe_stop()
            return
        if gpu["temperature_c"] >= float(self.cfg["temperature_warning_c"]):
            self.log.warning("GPU temperature high: %.1f C", gpu["temperature_c"])

        start_w = float(self.cfg["start_threshold_watts"])
        stop_w = float(self.cfg["stop_threshold_watts"])
        if self.state == self.OFF:
            self.below_since = None
            if surplus >= start_w:
                self.above_since = self.above_since or now
                if now - self.above_since >= float(self.cfg["min_start_seconds"]):
                    target = self.target_power(surplus)
                    self.log.info("Starting NiceHash, surplus=%.1f W target=%d W", surplus, target)
                    if not dry_run:
                        self.gpu.set_power_limit(target)
                        if not self.nicehash.start(): raise RuntimeError("NiceHash did not start")
                    self.state = self.MINING
                    self.above_since = None
            else:
                self.above_since = None

        elif self.state == self.MINING:
            self.above_since = None
            if surplus < stop_w:
                self.below_since = self.below_since or now
                if now - self.below_since >= float(self.cfg["min_stop_seconds"]):
                    self.log.info("Stopping NiceHash, surplus=%.1f W", surplus)
                    if not dry_run: self._safe_stop()
                    else: self.state = self.OFF
                    self.below_since = None
            else:
                self.below_since = None
                target = self.target_power(surplus)
                if not dry_run:
                    self.gpu.set_power_limit(target)
                self.log.info("MINING surplus=%.1f W GPU=%.1f W target=%d W temp=%.1f C", surplus, gpu["power_w"], target, gpu["temperature_c"])
