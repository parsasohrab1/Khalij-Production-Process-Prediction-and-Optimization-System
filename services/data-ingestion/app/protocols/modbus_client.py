"""Modbus TCP client for receiving data from the PLC/DCS (FR-DATA-01)."""
from __future__ import annotations

import logging

from pymodbus.client import AsyncModbusTcpClient
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class ModbusConnectionError(RuntimeError):
    """Raised when the Modbus TCP connection cannot be established."""


class ModbusClient:
    """Connect to a Modbus TCP unit and read the holding registers for each sensor."""

    def __init__(self, host: str, port: int, registers: dict[str, int], scale: dict[str, float] | None = None):
        self.host = host
        self.port = port
        self.registers = registers  # e.g. {"reactor_temp_c": 40001}
        self.scale = scale or {}
        self._client = AsyncModbusTcpClient(host=host, port=port)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((OSError, ConnectionError, TimeoutError)),
        reraise=True,
    )
    async def connect(self) -> None:
        """Connect to the Modbus TCP server with an exponential Retry Policy (Exponential Backoff)."""
        connected = await self._client.connect()
        if not connected:
            raise ModbusConnectionError(f"Connection to {self.host}:{self.port} failed.")
        logger.info("Modbus TCP connection to %s:%s established.", self.host, self.port)

    async def disconnect(self) -> None:
        self._client.close()
        logger.info("Modbus TCP connection closed.")

    async def read_once(self) -> dict[str, float]:
        values: dict[str, float] = {}
        for tag, address in self.registers.items():
            try:
                result = await self._client.read_holding_registers(address, 1)
                if result.isError():
                    logger.error("Reading register %s for %s failed.", address, tag)
                    continue
                raw_value = result.registers[0]
                values[tag] = raw_value * self.scale.get(tag, 1.0)
            except Exception as exc:  # noqa: BLE001 - we want to log any communication error
                logger.error("Error reading Modbus for %s: %s", tag, exc)
        return values
