"""سرور تست Modbus TCP شبیه‌ساز PLC واحد الفین (فاز ۱).

رجیسترهای هولدینگ ۰ تا ۵ مطابق config/tag_mapping.yaml پر می‌شوند.
مقادیر صحیح (۱۶ بیتی) با ضریب مقیاس تعریف‌شده در YAML به مقادیر واقعی
تبدیل می‌شوند (مثلاً دما: 2501 → 250.1 با scale=0.1).

اجرا:
    python -m hardware_sim.modbus_server
"""
from __future__ import annotations

import logging
import math
import time

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.server import StartTcpServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s | modbus-sim | %(levelname)s | %(message)s")
logger = logging.getLogger("modbus-sim")

HOST = "0.0.0.0"
PORT = 5020

# ترتیب رجیسترها مطابق tag_mapping.yaml (registers: 0..5)
# مقادیر ذخیره‌شده = مقدار واقعی / scale
REGISTER_ORDER = [
    ("reactor_temp_c", 0.1),
    ("reactor_pressure_bar", 0.1),
    ("feed_flow_m3h", 1.0),
    ("tank_level_percent", 0.1),
    ("ethylene_conc_percent", 0.1),
    ("compressor_rpm", 1.0),
]


def _compute_raw_registers(elapsed: float) -> list[int]:
    t = elapsed * 0.05
    values = {
        "reactor_temp_c": 250 + 30 * math.sin(t * 0.5) + 0.0005 * elapsed,
        "reactor_pressure_bar": 25 + 5 * math.sin(t * 0.3) + 0.0002 * elapsed,
        "feed_flow_m3h": 300 + 80 * math.sin(t * 0.2 + 1.2),
        "tank_level_percent": 50 + 20 * math.sin(t * 0.15 + 2.5),
        "ethylene_conc_percent": 18 + 3 * math.sin(t * 0.25 + 0.8) + 0.0001 * elapsed,
        "compressor_rpm": 1500 + 150 * math.sin(t * 0.1 + 3.0),
    }
    raw = []
    for field, scale in REGISTER_ORDER:
        raw.append(max(0, min(65535, int(round(values[field] / scale)))))
    return raw


class UpdatingDataBlock(ModbusSequentialDataBlock):
    """DataBlock که هر بار خوانش، مقادیر را با الگوی سینوسی به‌روز می‌کند."""

    def __init__(self):
        super().__init__(0, [0] * 10)
        self._t0 = time.monotonic()

    def getValues(self, address, count=1):  # noqa: N802 - امضای pymodbus
        self.setValues(0, _compute_raw_registers(time.monotonic() - self._t0))
        return super().getValues(address, count)


def main() -> None:
    store = ModbusSlaveContext(hr=UpdatingDataBlock(), zero_mode=True)
    context = ModbusServerContext(slaves=store, single=True)
    logger.info("سرور Modbus TCP روی %s:%s آماده است.", HOST, PORT)
    StartTcpServer(context=context, address=(HOST, PORT))


if __name__ == "__main__":
    main()
