from energy_planner.core.normalization import build_price_series, snap_duration, snap_start, snap_end


def test_slot_rounding_and_price_expansion():
    assert snap_start(7) == 5
    assert snap_end(7) == 10
    assert snap_duration(7) == 10
    assert build_price_series(horizon_hours=2, per_hour=[0.1, 0.2]) == [0.1]*12 + [0.2]*12
