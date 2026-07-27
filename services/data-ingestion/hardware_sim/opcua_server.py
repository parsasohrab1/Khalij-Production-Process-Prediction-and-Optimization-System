"""سرور تست OPC-UA شبیه‌ساز DCS واحد الفین (فاز ۱).

این سرور نودهایی با همان شناسه‌های تعریف‌شده در config/tag_mapping.yaml
ایجاد می‌کند و هر ثانیه مقادیر سنسورها را با الگوی واقع‌گرایانه به‌روزرسانی
می‌کند تا کلاینت data-ingestion بتواند بدون سخت‌افزار واقعی تست شود.

اجرا:
    python -m hardware_sim.opcua_server
"""
from __future__ import annotations

import asyncio
import logging
import math
import time

from asyncua import Server, ua

logging.basicConfig(level=logging.INFO, format="%(asctime)s | opcua-sim | %(levelname)s | %(message)s")
logger = logging.getLogger("opcua-sim")

ENDPOINT = "opc.tcp://0.0.0.0:4840/khalij/olefin1/"
NAMESPACE_URI = "http://khalij.holding/olefin1"

# شناسه‌های نود مطابق tag_mapping.yaml
NODES = {
    "Reactor.Temperature": ("reactor_temp_c", 250.0),
    "Reactor.Pressure": ("reactor_pressure_bar", 25.0),
    "Feed.Flow": ("feed_flow_m3h", 300.0),
    "Tank.Level": ("tank_level_percent", 50.0),
    "Gas.EthyleneConcentration": ("ethylene_conc_percent", 18.0),
    "Compressor.RPM": ("compressor_rpm", 1500.0),
}


def _compute_values(elapsed: float) -> dict[str, float]:
    t = elapsed * 0.05
    return {
        "reactor_temp_c": round(250 + 30 * math.sin(t * 0.5) + 0.0005 * elapsed, 2),
        "reactor_pressure_bar": round(25 + 5 * math.sin(t * 0.3) + 0.0002 * elapsed, 2),
        "feed_flow_m3h": round(300 + 80 * math.sin(t * 0.2 + 1.2), 2),
        "tank_level_percent": round(50 + 20 * math.sin(t * 0.15 + 2.5), 2),
        "ethylene_conc_percent": round(18 + 3 * math.sin(t * 0.25 + 0.8) + 0.0001 * elapsed, 2),
        "compressor_rpm": round(1500 + 150 * math.sin(t * 0.1 + 3.0), 0),
    }


async def main() -> None:
    server = Server()
    await server.init()
    server.set_endpoint(ENDPOINT)
    server.set_server_name("Khalij Olefin Unit 1 OPC-UA Simulator")

    idx = await server.register_namespace(NAMESPACE_URI)
    objects = server.get_objects_node()

    # ساخت سلسله‌مراتب اشیاء مطابق شناسه‌های tag_mapping
    reactor = await objects.add_object(idx, "Reactor")
    feed = await objects.add_object(idx, "Feed")
    tank = await objects.add_object(idx, "Tank")
    gas = await objects.add_object(idx, "Gas")
    compressor = await objects.add_object(idx, "Compressor")

    variables: dict[str, ua.Node] = {}
    parent_map = {
        "Reactor.Temperature": (reactor, "Temperature"),
        "Reactor.Pressure": (reactor, "Pressure"),
        "Feed.Flow": (feed, "Flow"),
        "Tank.Level": (tank, "Level"),
        "Gas.EthyleneConcentration": (gas, "EthyleneConcentration"),
        "Compressor.RPM": (compressor, "RPM"),
    }

    for browse_path, (parent, name) in parent_map.items():
        _, initial = NODES[browse_path]
        # استفاده از NodeId رشته‌ای (String NodeId) مطابق tag_mapping.yaml: ns=2;s=Reactor.Temperature
        node_id = ua.NodeId(browse_path, idx)
        var = await parent.add_variable(node_id, name, float(initial))
        await var.set_writable()
        variables[browse_path] = var
        logger.info("نود ساخته شد: ns=%s;s=%s", idx, browse_path)

    t0 = time.monotonic()
    logger.info("سرور OPC-UA روی %s آماده است (namespace idx=%s).", ENDPOINT, idx)

    async with server:
        while True:
            values = _compute_values(time.monotonic() - t0)
            field_to_path = {field: path for path, (field, _) in NODES.items()}
            for field, value in values.items():
                path = field_to_path[field]
                await variables[path].write_value(float(value))
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
