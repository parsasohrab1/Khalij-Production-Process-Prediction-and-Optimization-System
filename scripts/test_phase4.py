"""Phase 4 unit tests: safety constraints, multivariable optimization, What-if.

Run:
    python scripts/test_phase4.py
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "prediction"))
sys.path.insert(0, str(ROOT))


def test_hard_constraints() -> None:
    from app.safety_constraints import check_hard_constraints, is_feasible

    assert is_feasible(
        reactor_temp_c=250,
        pressure_bar=25,
        feed_flow_m3h=300,
        current_pressure_bar=25,
        current_feed_flow=300,
    )
    # violation of the safe temperature range
    v = check_hard_constraints(
        reactor_temp_c=340,
        pressure_bar=25,
        feed_flow_m3h=300,
        current_pressure_bar=25,
        current_feed_flow=300,
    )
    assert any(x.name == "temp_safe_envelope" for x in v)
    # violation of the feed flow rate of change
    v2 = check_hard_constraints(
        reactor_temp_c=250,
        pressure_bar=25,
        feed_flow_m3h=450,
        current_pressure_bar=25,
        current_feed_flow=300,
    )
    assert any(x.name == "feed_rate_of_change" for x in v2)
    # high P+T combined constraint
    v3 = check_hard_constraints(
        reactor_temp_c=310,
        pressure_bar=33,
        feed_flow_m3h=300,
        current_pressure_bar=30,
        current_feed_flow=300,
    )
    assert any(x.name == "high_p_high_t" for x in v3)
    print("[OK] hard constraints")


def test_multivariable_optimizer() -> None:
    from app.optimizer import MultiVariableEvolutionaryOptimizer

    opt = MultiVariableEvolutionaryOptimizer(population_size=40, generations=40, seed=42)
    result = opt.optimize(reactor_temp_c=250.0, current_pressure_bar=28.0, current_feed_flow=380.0)
    assert result["constraints_satisfied"] is True
    assert "recommended" in result and "feed_flow_m3h" in result["recommended"]
    assert "pressure_bar" in result["recommended"]
    # the recommendation must improve efficiency or at least not worsen it (in the feasible space)
    assert result["recommended"]["estimated_efficiency"] >= result["current"]["estimated_efficiency"] - 0.01
    # the rate of change is respected
    assert abs(result["recommended"]["feed_flow_m3h"] - 380.0) <= 80.0 + 1e-6
    assert abs(result["recommended"]["pressure_bar"] - 28.0) <= 5.0 + 1e-6
    print(
        f"[OK] multivariable optimizer gain={result['expected_efficiency_gain']} "
        f"feed={result['recommended']['feed_flow_m3h']} P={result['recommended']['pressure_bar']}"
    )


def test_whatif() -> None:
    from app.whatif import simulate_whatif

    safe = simulate_whatif(
        reactor_temp_c=250,
        current_pressure_bar=25,
        current_feed_flow=350,
        proposed_pressure_bar=24,
        proposed_feed_flow=310,
    )
    assert safe["constraints_satisfied"] is True
    assert safe["recommendation"] in ("apply", "no_gain")

    unsafe = simulate_whatif(
        reactor_temp_c=250,
        current_pressure_bar=25,
        current_feed_flow=300,
        proposed_pressure_bar=25,
        proposed_feed_flow=500,  # outside the rate of change and/or the safe range
    )
    assert unsafe["constraints_satisfied"] is False
    assert unsafe["recommendation"] == "reject_unsafe"
    print("[OK] what-if simulator")


def test_legacy_recommender() -> None:
    from app.optimizer import EvolutionaryRecommender

    rec = EvolutionaryRecommender(seed=1).recommend(250, 25, 400)
    assert "recommended_value" in rec
    assert rec["expected_efficiency_gain"] >= 0
    print("[OK] legacy single-variable recommender")


if __name__ == "__main__":
    test_hard_constraints()
    test_multivariable_optimizer()
    test_whatif()
    test_legacy_recommender()
    print("\nAll Phase-4 tests passed.")
