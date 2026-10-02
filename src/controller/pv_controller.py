from __future__ import annotations
import math
import time

class PVController:
    OFF = "OFF"
    STARTING = "STARTING"
    MINING = "MINING"
    STOPPING = "STOPPING"
    FAULT = "FAULT"

    def __init__(self, pv, gpu, nicehash, cfg, logger, dashboard=None, power=None):
        self.pv, self.gpu, self.nicehash, self.cfg, self.log = pv, gpu, nicehash, cfg, logger
        self.dashboard = dashboard
        self.power = power  # optional WindowsPower - enables auto-shutdown when set
        self.state = self.OFF
        self.above_since = None
        self.below_since = None
        self.idle_since = None  # how long the OFF state has had no usable surplus
        self.shutdown_triggered = False  # armed once per idle episode, see _check_auto_shutdown
        self.errors = 0
        self.action_errors = 0  # consecutive failures of GPU/NiceHash actions,
                                 # tracked separately from input-read errors so
                                 # a run of successful ticks doesn't mask them
        self.smoothed_surplus = None  # EMA state, see _smooth_surplus()
        self._smoothing_last_tick = None
        self.last_applied_target = None  # GPU power last actually set during
                                          # MINING, see the deadband check below -
                                          # None means "always apply the next one"

    def _smooth_surplus(self, raw: float, now: float) -> float:
        """Exponential moving average of the raw Shelly reading, time-constant
        `surplus_smoothing_seconds` (0/unset = no smoothing, used as-is).
        Without this, every short-lived dip or spike (a fridge compressor
        cycling, inverter noise, a cloud edge) fed straight into
        target_power() made the GPU power limit chase it every single
        10-second tick - see the deadband check in tick() for the other half
        of the fix."""
        tau = float(self.cfg.get("surplus_smoothing_seconds", 0) or 0)
        if tau <= 0:
            self.smoothed_surplus = raw
            self._smoothing_last_tick = now
            return raw
        if self.smoothed_surplus is None:
            self.smoothed_surplus = raw
        else:
            # `or now` would be wrong here: a last-tick timestamp of exactly
            # 0 is falsy but perfectly valid, and treating it as "unset"
            # collapses dt to 0 (alpha 0, smoothed value never moves).
            last_tick = self._smoothing_last_tick if self._smoothing_last_tick is not None else now
            dt = max(0.0, now - last_tick)
            alpha = 1 - math.exp(-dt / tau)
            self.smoothed_surplus += alpha * (raw - self.smoothed_surplus)
        self._smoothing_last_tick = now
        return self.smoothed_surplus

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

    def _check_auto_shutdown(self, now: float, dry_run: bool):
        """Mirrors the Ubuntu GPU miner's idle-shutdown logic: if there's no
        usable surplus for auto_shutdown_idle_minutes AND it's already past
        auto_shutdown_not_before_hour (so a brief midday cloud doesn't trigger
        it), shut the PC down. Only armed when self.power is set.

        shutdown_triggered fires this at most once per idle episode: Windows'
        `shutdown /s` (re-)starts a fresh countdown on every call, so calling
        it again every tick while still idle would keep pushing the actual
        shutdown back forever instead of ever completing it."""
        if not (self.power and self.cfg.get("auto_shutdown_enabled")):
            self.idle_since = None
            self.shutdown_triggered = False
            return
        if self.shutdown_triggered:
            return
        self.idle_since = self.idle_since or now
        idle_min = (now - self.idle_since) / 60.0
        hour = time.localtime().tm_hour
        if idle_min >= float(self.cfg["auto_shutdown_idle_minutes"]) and hour >= int(self.cfg["auto_shutdown_not_before_hour"]):
            self.log.info("Kein Ueberschuss seit %.0f min (%d Uhr) -> Auto-Shutdown", idle_min, hour)
            self._event("Auto-Shutdown ausgelöst (%.0f min ohne Überschuss)" % idle_min)
            self.shutdown_triggered = True
            if not dry_run:
                try:
                    self.power.shutdown()
                except Exception as exc:
                    self.log.error("Shutdown fehlgeschlagen: %s", exc)

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
        self.last_applied_target = None

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

        # The dashboard above always shows the raw sensor reading; everything
        # from here on (start/stop thresholds, target_power()) uses the
        # smoothed value instead, so a momentary spike/dip can't flip state
        # or yank the GPU power limit around on its own.
        surplus = self._smooth_surplus(surplus, now)

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
                self.idle_since = None
                self.shutdown_triggered = False
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
                        self.last_applied_target = target
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
                self._check_auto_shutdown(now, dry_run)

        elif self.state == self.MINING:
            self.above_since = None
            if surplus < stop_w:
                self.below_since = self.below_since or now
                if now - self.below_since >= float(self.cfg["min_stop_seconds"]):
                    self.log.info("Stopping NiceHash, surplus=%.1f W", surplus)
                    self._event("Stopp: Überschuss %.0f W unter Schwelle" % surplus)
                    if not dry_run: self._safe_stop()
                    else:
                        self.state = self.OFF
                        self.last_applied_target = None
                    if self.dashboard: self.dashboard.update(controller_state=self.state, target_power_w=None)
                    self.below_since = None
            else:
                self.below_since = None
                target = self.target_power(surplus)
                # Deadband: a target that's only a few watts off the one
                # already applied is almost certainly just smoothing residue,
                # not a real change in surplus - skip the nvidia-smi call and
                # keep reporting/logging the currently-applied value so the
                # dashboard doesn't jitter either.
                deadband = float(self.cfg.get("power_change_deadband_watts", 0) or 0)
                if self.last_applied_target is not None and abs(target - self.last_applied_target) < deadband:
                    target = self.last_applied_target
                else:
                    if not dry_run:
                        if not self._set_gpu_power(target):
                            if self._action_fault_check(dry_run, "GPU-Leistung setzen"):
                                return
                    self.last_applied_target = target
                if self.dashboard: self.dashboard.update(controller_state=self.state, target_power_w=target)
                self.log.info("MINING surplus=%.1f W GPU=%.1f W target=%d W temp=%.1f C", surplus, gpu["power_w"], target, gpu["temperature_c"])
