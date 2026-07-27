"""کلاینت Modbus TCP برای دریافت داده از PLC/DCS (FR-DATA-01)."""
from __future__ import annotations

import logging

from pymodbus.client import AsyncModbusTcpClient
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class ModbusConnectionError(RuntimeError):
    """هنگامی که اتصال Modbus TCP برقرار نشود، صادر می‌شود."""


class ModbusClient:
    """اتصال به یک واحد Modbus TCP و خوانش رجیسترهای هولدینگ برای هر سنسور."""

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
        """اتصال به سرور Modbus TCP با Retry Policy نمایی (Exponential Backoff)."""
        connected = await self._client.connect()
        if not connected:
            raise ModbusConnectionError(f"اتصال به {self.host}:{self.port} ناموفق بود.")
        logger.info("اتصال Modbus TCP به %s:%s برقرار شد.", self.host, self.port)

    async def disconnect(self) -> None:
        self._client.close()
        logger.info("اتصال Modbus TCP بسته شد.")

    async def read_once(self) -> dict[str, float]:
        values: dict[str, float] = {}
        for tag, address in self.registers.items():
            try:
                result = await self._client.read_holding_registers(address, 1)
                if result.isError():
                    logger.error("خوانش رجیستر %s برای %s ناموفق بود.", address, tag)
                    continue
                raw_value = result.registers[0]
                values[tag] = raw_value * self.scale.get(tag, 1.0)
            except Exception as exc:  # noqa: BLE001 - می‌خواهیم هر خطای ارتباطی را لاگ کنیم
                logger.error("خطا در خوانش Modbus برای %s: %s", tag, exc)
        return values
