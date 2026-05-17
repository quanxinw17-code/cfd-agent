import pytest

from cfd_agent.core.physics import calculate_mach_number, calculate_reynolds_number, classify_flow


def test_reynolds_number() -> None:
    assert calculate_reynolds_number(1.225, 30.0, 0.1, 1.789e-5) == pytest.approx(205422.0234768027)


def test_mach_number() -> None:
    assert calculate_mach_number(34.0) == 0.1


def test_low_mach_is_incompressible() -> None:
    flow = classify_flow(1000.0, 0.2)
    assert flow["compressibility"] == "incompressible"


def test_high_re_is_turbulent() -> None:
    flow = classify_flow(100000.0, 0.1)
    assert flow["regime"] == "turbulent"
    assert flow["recommended_turbulence_model"] == "k_omega_sst"
