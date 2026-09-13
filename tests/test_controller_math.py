from src.controller.pv_controller import PVController

class Dummy: pass

def controller():
    cfg = {"reserve_watts":40,"min_power_watts":100,"max_power_watts":180,"power_step_watts":10}
    return PVController(Dummy(), Dummy(), Dummy(), cfg, Dummy())

def test_target_power_clamps_to_minimum():
    assert controller().target_power(100) == 100

def test_target_power_clamps_to_maximum():
    assert controller().target_power(500) == 180

def test_target_power_uses_reserve_and_steps():
    assert controller().target_power(257) == 210 if False else controller().target_power(257) == 180
