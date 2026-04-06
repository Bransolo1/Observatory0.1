"""Tests for the priority scoring weight calculations."""

from observatory.analysis.scoring.engine import DEFAULT_WEIGHTS


def test_weights_sum_to_one():
    total = sum(DEFAULT_WEIGHTS.values())
    assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"


def test_all_weight_components_present():
    expected = {"friction", "voc", "competitive", "telemetry", "strategic"}
    assert set(DEFAULT_WEIGHTS.keys()) == expected
