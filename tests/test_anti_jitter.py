from src.controller.pv_controller import PVController


class Dummy:
    def __getattr__(self, name):
        return lambda *a, **k: True


def controller(cfg_extra=None):
    cfg = {
        "reserve_watts": 0, "min_power_watts": 100, "max_power_watts": 300, "power_step_watts": 10,
        "start_threshold_watts": 50, "stop_threshold_watts": 50,
        "min_start_seconds": 0, "min_stop_seconds": 0,
        "temperature_warning_c": 999, "temperature_critical_c": 9999,
        "error_limit": 3, "safe_power_watts": 100,
    }
    cfg.update(cfg_extra or {})
    return PVController(Dummy(), Dummy(), Dummy(), cfg, Dummy())


def test_smooth_surplus_disabled_returns_raw_value():
    c = controller()  # no surplus_smoothing_seconds key -> disabled
    assert c._smooth_surplus(300, now=0) == 300
    assert c._smooth_surplus(100, now=1) == 100


def test_smooth_surplus_damps_a_sudden_change():
    c = controller({"surplus_smoothing_seconds": 60})
    c._smooth_surplus(300, now=0)
    smoothed = c._smooth_surplus(0, now=1)  # 1s later, tau=60s -> barely moves
    assert 250 < smoothed < 300


def test_smooth_surplus_converges_to_raw_value_given_enough_time():
    c = controller({"surplus_smoothing_seconds": 60})
    c._smooth_surplus(300, now=0)
    smoothed = c._smooth_surplus(0, now=600)  # 10 time constants later
    assert smoothed < 1


class RecordingGPU:
    def __init__(self):
        self.power_limit_calls = []

    def status(self):
        return {"power_w": 150, "temperature_c": 60}

    def set_power_limit(self, watts):
        self.power_limit_calls.append(watts)


def test_deadband_suppresses_small_power_changes_during_mining():
    gpu = RecordingGPU()
    surplus_values = iter([254, 264, 284])  # targets: 250, 260 (+10), 280 (+30 from last applied)

    class StubPV:
        def read_power_watts(self):
            return next(surplus_values)

    cfg = {
        "reserve_watts": 0, "min_power_watts": 100, "max_power_watts": 300, "power_step_watts": 10,
        "start_threshold_watts": 50, "stop_threshold_watts": 50,
        "min_start_seconds": 0, "min_stop_seconds": 0,
        "temperature_warning_c": 999, "temperature_critical_c": 9999,
        "error_limit": 3, "safe_power_watts": 100,
        "power_change_deadband_watts": 20, "surplus_smoothing_seconds": 0,
    }
    c = PVController(StubPV(), gpu, Dummy(), cfg, Dummy())

    c.tick(dry_run=False)  # OFF -> MINING at 250
    c.tick(dry_run=False)  # 260 is only +10 from 250 -> suppressed
    c.tick(dry_run=False)  # 280 is +30 from 250 -> applied

    assert gpu.power_limit_calls == [250, 280]
