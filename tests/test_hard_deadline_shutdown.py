import time
from unittest.mock import patch

from src.controller.pv_controller import PVController


class Dummy:
    def __getattr__(self, name):
        return lambda *a, **k: True


class RecordingPower:
    def __init__(self):
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1


def controller_with_power(extra_cfg=None):
    cfg = {
        "reserve_watts": 0, "min_power_watts": 100, "max_power_watts": 300, "power_step_watts": 10,
        "start_threshold_watts": -30, "stop_threshold_watts": -100,
        "min_start_seconds": 0, "min_stop_seconds": 0,
        "temperature_warning_c": 999, "temperature_critical_c": 9999,
        "error_limit": 3, "safe_power_watts": 100,
        "auto_shutdown_enabled": True, "auto_shutdown_hard_deadline_hour": 19,
    }
    cfg.update(extra_cfg or {})
    power = RecordingPower()
    controller = PVController(Dummy(), Dummy(), Dummy(), cfg, Dummy(), power=power)
    return controller, power


def _localtime_at(hour):
    now = time.localtime()
    return time.struct_time((now.tm_year, now.tm_mon, now.tm_mday, hour, 0, 0, now.tm_wday, now.tm_yday, now.tm_isdst))


def test_hard_deadline_does_not_trigger_before_the_hour():
    controller, power = controller_with_power()
    with patch("src.controller.pv_controller.time.localtime", return_value=_localtime_at(18)):
        triggered = controller._check_hard_deadline_shutdown(dry_run=False)
    assert triggered is False
    assert power.shutdown_calls == 0


def test_hard_deadline_triggers_at_the_hour():
    controller, power = controller_with_power()
    with patch("src.controller.pv_controller.time.localtime", return_value=_localtime_at(19)):
        triggered = controller._check_hard_deadline_shutdown(dry_run=False)
    assert triggered is True
    assert power.shutdown_calls == 1


def test_hard_deadline_only_triggers_once_per_day():
    controller, power = controller_with_power()
    with patch("src.controller.pv_controller.time.localtime", return_value=_localtime_at(19)):
        controller._check_hard_deadline_shutdown(dry_run=False)
        controller._check_hard_deadline_shutdown(dry_run=False)
        controller._check_hard_deadline_shutdown(dry_run=False)
    assert power.shutdown_calls == 1


def test_hard_deadline_resets_after_the_hour_passes():
    controller, power = controller_with_power()
    with patch("src.controller.pv_controller.time.localtime", return_value=_localtime_at(19)):
        controller._check_hard_deadline_shutdown(dry_run=False)
    with patch("src.controller.pv_controller.time.localtime", return_value=_localtime_at(2)):
        controller._check_hard_deadline_shutdown(dry_run=False)  # next day, below deadline -> resets
    with patch("src.controller.pv_controller.time.localtime", return_value=_localtime_at(19)):
        controller._check_hard_deadline_shutdown(dry_run=False)
    assert power.shutdown_calls == 2


def test_hard_deadline_disabled_when_auto_shutdown_off():
    controller, power = controller_with_power({"auto_shutdown_enabled": False})
    with patch("src.controller.pv_controller.time.localtime", return_value=_localtime_at(19)):
        triggered = controller._check_hard_deadline_shutdown(dry_run=False)
    assert triggered is False
    assert power.shutdown_calls == 0


def test_hard_deadline_stops_mining_first():
    controller, power = controller_with_power()
    controller.state = PVController.MINING
    with patch("src.controller.pv_controller.time.localtime", return_value=_localtime_at(19)):
        controller._check_hard_deadline_shutdown(dry_run=False)
    assert controller.state == PVController.OFF
    assert power.shutdown_calls == 1
