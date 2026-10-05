"""Phase 1 integration test: tag mapping loading, Circuit Breaker, AES-256 encryption.

Run (from the project root):
    python scripts/test_phase1.py
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-ingestion"))

from shared.crypto import decrypt_at_rest, encrypt_at_rest, generate_key_b64  # noqa: E402


def test_tag_mapping() -> None:
    from app.tag_mapping import load_tag_mapping

    mapping = load_tag_mapping(ROOT / "services" / "data-ingestion" / "config" / "tag_mapping.yaml")
    assert 1 in mapping
    unit = mapping[1]
    assert "reactor_temp_c" in unit.opcua.nodes
    assert unit.opcua.nodes["reactor_temp_c"] == "ns=2;s=Reactor.Temperature"
    assert unit.modbus.registers["reactor_temp_c"] == 0
    assert unit.modbus.scale["reactor_temp_c"] == 0.1
    print("[OK] tag_mapping.yaml loaded")


def test_circuit_breaker() -> None:
    from app.circuit_breaker import CircuitBreaker, CircuitState

    cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout_s=0.01)
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert not cb.allow_request()
    import time

    time.sleep(0.02)
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    print("[OK] Circuit Breaker OK")


def test_aes256() -> None:
    import os

    key = generate_key_b64()
    os.environ["DATA_ENCRYPTION_KEY"] = key
    plaintext = "critical reactor temperature alert"
    encrypted = encrypt_at_rest(plaintext)
    assert encrypted.startswith("aes256gcm:")
    assert encrypted != plaintext
    assert decrypt_at_rest(encrypted) == plaintext
    print("[OK] AES-256-GCM OK")


def test_shift_window() -> None:
    import importlib.util

    path = ROOT / "services" / "alerting" / "app" / "shift_report.py"
    spec = importlib.util.spec_from_file_location("shift_report", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    name, start, end = module.resolve_shift_window()
    assert name in ("morning", "evening", "night")
    assert end > start
    print(f"[OK] current shift: {name} ({start.isoformat()} -> {end.isoformat()})")


if __name__ == "__main__":
    test_tag_mapping()
    test_circuit_breaker()
    test_aes256()
    test_shift_window()
    print("\nAll Phase-1 / SRS requirement tests passed.")
