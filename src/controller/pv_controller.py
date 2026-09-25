from __future__ import annotations
import time

class PVController:
    OFF = "OFF"
    STARTING = "STARTING"
    MINING = "MINING"
    STOPPING = "STOPPING"
    FAULT = "FAULT"

    def __init__(self, pv, gpu, nicehash, cfg, logger, dashboard=None):
        self.pv, self.gpu, self.nicehash, self.cfg, self.log = pv, gpu, nicehash, cfg, logger
        self.dashboard = dashboard
        self.state = self.OFF
        self.above_since = None
        self.below_since = None
        self.errors = 0
        self.action_errors = 0  # consecutive failures of GPU/NiceHash actions,
                                 # tracked separately from input-read errors so
                                 # a run of successful ticks doesn't mask them

    def target_power(self, surplus: float) -> int:
        p = surplus - float(self.cfg["reserve_watts"])
        p = max(float(self.cfg["min_power_watts"]), min(float(self.cfg["max_power_watts"]), p))
        step = int(self.cfg["power_step_watts"])
        return int(p // step * step)

    def _event(self, message: str):
        if self.dashboard: self.dashboard.event(message)

    def _set_gpu_power(self, watts: int) -> bool:
        try:
            self.gpu.set_power_limit(watts)
        except Exception as exc:
            self.action_errors += 1
            self.log.error("Could not set GPU power limit (%d): %s", self.action_errors, exc)
            if self.dashboard: self.dashboard.update(system={"nvidia_ok": False})
            return False
        self.action_errors = 0
        return True

    def _start_nicehash_process(self) -> bool:
        try:
            if not self.nicehash.start():
                raise RuntimeError("NiceHash did not start")
        except Exception as exc:
            self.action_errors += 1
            self.log.error("Could not start NiceHash (%d): %s", self.action_errors, exc)
            if self.dashboard: self.dashboard.update(system={"nicehash_ok": False})
            return False
        self.action_errors = 0
        if self.dashboard: self.dashboard.update(system={"nicehash_ok": True})
        return True

    def _action_fault_check(self, dry_run: bool, context: str) -> bool:
        """Returns True if the action-error limit was hit and a FAULT/safe-stop
        was triggered."""
        if self.action_errors >= int(self.cfg["error_limit"]):
            self.state = self.FAULT
            self._event("FAULT: Aktionsfehler-Limit erreicht (%s)" % context)
            if not dry_run: self._safe_stop()
            return True
        return False

    def _safe_stop(self):
        try:
            self.gpu.set_power_limit(int(self.cfg["safe_power_watts"]))
        except Exception as exc:
            self.log.error("Could not set safe GPU power: %s", exc)
        try:
            self.nicehash.stop()
            if self.dashboard: self.dashboard.update(system={"nicehash_ok": True})
        except Exception as exc:
            self.log.error("Could not stop NiceHash: %s", exc)
            if self.dashboard: self.dashboard.update(system={"nicehash_ok": False})
        self.state = self.OFF
        self.above_since = self.below_since = None

    def tick(self, dry_run: bool = False):
        now = time.monotonic()

        # Read both inputs independently so a failure in one (e.g. Shelly
        # unreachable) doesn't hide the real status of the other (e.g. GPU) -
        # both are reported to the dashboard regardless of which one failed.
        surplus = gpu = None
        shelly_ok = nvidia_ok = True
        surplus_exc = gpu_exc = None
        try:
            surplus = self.pv.read_power_watts()
        except Exception as exc:
            shelly_ok = False
            surplus_exc = exc
        try:
            gpu = self.gpu.status()
        except Exception as exc:
            nvidia_ok = False
            gpu_exc = exc

        if not shelly_ok or not nvidia_ok:
            self.errors += 1
            if surplus_exc is not None:
                self.log.error("Input error (%d): %s", self.errors, surplus_exc)
            if gpu_exc is not None:
                self.log.error("Input error (%d): %s", self.errors, gpu_exc)
            if self.dashboard:
                update = {"errors": self.errors, "system": {"shelly_ok": shelly_ok, "nvidia_ok": nvidia_ok}}
                if gpu is not None: update["gpu"] = gpu
                self.dashboard.update(**update)
            if self.errors >= int(self.cfg["error_limit"]):
                self.state = self.FAULT
                reasons = []
                if not shelly_ok: reasons.append("Shelly nicht erreichbar")
                if not nvidia_ok: reasons.append("nvidia-smi nicht erreichbar")
                self._event("FAULT: Eingabefehler-Limit erreicht (%s)" % ", ".join(reasons))
                if not dry_run: self._safe_stop()
            return
        self.errors = 0

        if self.dashboard:
            nh_running = None
            try:
                nh_running = self.nicehash.is_running()
            except Exception:
                pass
            self.dashboard.update(
                surplus_w=surplus, gpu=gpu, nicehash_running=nh_running, errors=0,
                system={"shelly_ok": True, "nvidia_ok": True},
            )

        if gpu["temperature_c"] >= float(self.cfg["temperature_critical_c"]):
            self.log.error("Critical GPU temperature: %.1f C", gpu["temperature_c"])
            self._event("Kritische GPU-Temperatur: %.1f °C – Notstopp" % gpu["temperature_c"])
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
                    self._event("Start: Überschuss %.0f W, Ziel %d W" % (surplus, target))
                    ok = True
                    if not dry_run:
                        ok = self._set_gpu_power(target) and self._start_nicehash_process()
                    if ok:
                        self.state = self.MINING
                        if self.dashboard: self.dashboard.update(controller_state=self.state, target_power_w=target)
                        self.above_since = None
                    else:
                        self._event("Start fehlgeschlagen, wird erneut versucht")
                        self._action_fault_check(dry_run, "Start fehlgeschlagen")
                        # above_since intentionally left as-is: surplus already
                        # satisfied the threshold, so retry on the next tick
                        # instead of waiting min_start_seconds again
            else:
                self.above_since = None

        elif self.state == self.MINING:
            self.above_since = None
            if surplus < stop_w:
                self.below_since = self.below_since or now
                if now - self.below_since >= float(self.cfg["min_stop_seconds"]):
                    self.log.info("Stopping NiceHash, surplus=%.1f W", surplus)
                    self._event("Stopp: Überschuss %.0f W unter Schwelle" % surplus)
                    if not dry_run: self._safe_stop()
                    else: self.state = self.OFF
                    if self.dashboard: self.dashboard.update(controller_state=self.state, target_power_w=None)
                    self.below_since = None
            else:
                self.below_since = None
                target = self.target_power(surplus)
                if not dry_run:
                    if not self._set_gpu_power(target):
                        if self._action_fault_check(dry_run, "GPU-Leistung setzen"):
                            return
                if self.dashboard: self.dashboard.update(controller_state=self.state, target_power_w=target)
                self.log.info("MINING surplus=%.1f W GPU=%.1f W target=%d W temp=%.1f C", surplus, gpu["power_w"], target, gpu["temperature_c"])
