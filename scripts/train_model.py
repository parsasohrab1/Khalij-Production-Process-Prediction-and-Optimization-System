"""اسکریپت ریشه برای آموزش آفلاین مدل (فاز ۳).

اجرا از ریشه پروژه:
    python scripts/train_model.py --csv data/sample.csv --mlflow-uri http://localhost:5000
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "prediction"))
sys.path.insert(0, str(ROOT))

# اجرای ماژول train_offline با همان argv
sys.argv[0] = str(ROOT / "services" / "prediction" / "app" / "train_offline.py")
runpy.run_path(str(ROOT / "services" / "prediction" / "app" / "train_offline.py"), run_name="__main__")
