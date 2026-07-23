"""کلاینت OPC-UA برای دریافت داده از سنسورهای DCS (FR-DATA-01).

در محیط توسعه، در صورت عدم دسترسی به سرور OPC-UA واقعی، از شبیه‌ساز
(app.simulator) به‌عنوان جایگزین استفاده می‌شود.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from asyncua import Client, ua

logger = logging.getLogger(__name__)


class OpcUaClient:
    """اتصال به سرور OPC-UA و خوانش دوره‌ای نودهای تعریف‌شده برای هر سنسور."""

    def __init__(self, endpoint_url: str, node_ids: dict[str, str], sample_rate_s: float = 1.0):
        self.endpoint_url = endpoint_url
        self.node_ids = node_ids  # e.g. {"reactor_temp_c": "ns=2;s=Reactor.Temperature"}
        self.sample_rate_s = sample_rate_s
        self._client: Client | None = None

    async def connect(self) -> None:
        self._client = Client(url=self.endpoint_url)
        await self._client.connect()
        logger.info("اتصال OPC-UA به %s برقرار شد.", self.endpoint_url)

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            logger.info("اتصال OPC-UA بسته شد.")

    async def read_once(self) -> dict[str, float]:
        if self._client is None:
            raise RuntimeError("کلاینت OPC-UA متصل نشده است.")
        values: dict[str, float] = {}
        for tag, node_id in self.node_ids.items():
            try:
                node = self._client.get_node(node_id)
                value = await node.read_value()
                values[tag] = float(value)
            except (ua.UaError, ValueError) as exc:
                logger.error("خوانش نود %s (%s) ناموفق بود: %s", tag, node_id, exc)
        return values

    async def stream(self) -> AsyncIterator[dict[str, float]]:
        import asyncio

        while True:
            yield await self.read_once()
            await asyncio.sleep(self.sample_rate_s)
