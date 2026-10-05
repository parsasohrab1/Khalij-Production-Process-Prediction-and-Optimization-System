"""Loading the DCS/PLC tag mapping from the configuration file (FR-DATA-01/02).

This module reads the YAML file and, for each unit, provides the OPC-UA node addresses and
Modbus registers of each sensor variable to the protocol clients. The server address
(endpoint_url / host) can be overridden with environment variables
so one can switch between the development environment and a real DCS without changing the YAML file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "tag_mapping.yaml"


@dataclass
class OpcUaUnitConfig:
    endpoint_url: str
    nodes: dict[str, str] = field(default_factory=dict)


@dataclass
class ModbusUnitConfig:
    host: str
    port: int
    registers: dict[str, int] = field(default_factory=dict)
    scale: dict[str, float] = field(default_factory=dict)


@dataclass
class UnitTagMapping:
    unit_id: int
    name: str
    opcua: OpcUaUnitConfig
    modbus: ModbusUnitConfig


def load_tag_mapping(config_path: Path | str | None = None) -> dict[int, UnitTagMapping]:
    """Read the tag_mapping.yaml file with the ability to override the server address from environment variables."""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Tag mapping file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    mappings: dict[int, UnitTagMapping] = {}
    for unit_id, unit_cfg in (raw.get("units") or {}).items():
        opcua_cfg = unit_cfg.get("opcua", {})
        modbus_cfg = unit_cfg.get("modbus", {})

        mappings[int(unit_id)] = UnitTagMapping(
            unit_id=int(unit_id),
            name=unit_cfg.get("name", f"Unit {unit_id}"),
            opcua=OpcUaUnitConfig(
                endpoint_url=os.getenv("OPCUA_ENDPOINT_URL", opcua_cfg.get("endpoint_url", "")),
                nodes=opcua_cfg.get("nodes", {}),
            ),
            modbus=ModbusUnitConfig(
                host=os.getenv("MODBUS_HOST", modbus_cfg.get("host", "")),
                port=int(os.getenv("MODBUS_PORT", modbus_cfg.get("port", 502))),
                registers=modbus_cfg.get("registers", {}),
                scale=modbus_cfg.get("scale", {}),
            ),
        )
    return mappings
