"""OPC-UA client for receiving data from DCS sensors (FR-DATA-01).

In the development environment, if a real OPC-UA server is not accessible, the simulator
(app.simulator) is used as a substitute.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from asyncua import Client, ua
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class OpcUaClient:
    """Connect to the OPC-UA server and periodically read the nodes defined for each sensor."""

    def __init__(self, endpoint_url: str, node_ids: dict[str, str], sample_rate_s: float = 1.0):
        self.endpoint_url = endpoint_url
        self.node_ids = node_ids  # e.g. {"reactor_temp_c": "ns=2;s=Reactor.Temperature"}
        self.sample_rate_s = sample_rate_s
        self._client: Client | None = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((OSError, ConnectionError, TimeoutError, ua.UaError)),
        reraise=True,
    )
    async def connect(self) -> None:
        """Connect to the OPC-UA server with an exponential Retry Policy (Exponential Backoff)."""
        self._client = Client(url=self.endpoint_url)
        await self._client.connect()
        logger.info("OPC-UA connection to %s established.", self.endpoint_url)

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            logger.info("OPC-UA connection closed.")

    async def read_once(self) -> dict[str, float]:
        if self._client is None:
            raise RuntimeError("The OPC-UA client is not connected.")
        values: dict[str, float] = {}
        for tag, node_id in self.node_ids.items():
            try:
                node = self._client.get_node(node_id)
                value = await node.read_value()
                values[tag] = float(value)
            except (ua.UaError, ValueError) as exc:
                logger.error("Reading node %s (%s) failed: %s", tag, node_id, exc)
        return values

    async def stream(self) -> AsyncIterator[dict[str, float]]:
        import asyncio

        while True:
            yield await self.read_once()
            await asyncio.sleep(self.sample_rate_s)
