#!/usr/bin/env python3
"""Uruchamia panel na fikcyjnych danych demo (patrz tools/demo_data.py) pod http://127.0.0.1:8765

    DATABASE_URL=sqlite:///demo.db python tools/demo_data.py
    DATABASE_URL=sqlite:///demo.db python tools/demo_server.py

W tle odświeża stan „na żywo” (routery online, klienci Wi-Fi, tryb ustawiania), które inaczej wygasają po kilku minutach,
i tworzy fikcyjne kopie zapasowe w katalogu tymczasowym. Konta: admin / demo-admin-2026, viewer / demo-viewer-2026.
"""
import datetime as dt
import math
import os
import random
import sys
import tempfile
import threading
import time
from pathlib import Path

URL = os.environ.get("DATABASE_URL", "")
if not URL.startswith("sqlite:///"):
    sys.exit("Odmowa: serwer demo działa tylko na bazie SQLite (ustaw DATABASE_URL=sqlite:///demo.db).")
ROOT = Path(__file__).resolve().parent.parent
_db = Path(URL.replace("sqlite:///", "", 1)).resolve()           # ścieżka bazy bezwzględnie, bo za chwilę zmieniamy katalog
os.environ["DATABASE_URL"] = "sqlite:///" + _db.as_posix()
sys.path.insert(0, str(ROOT / "app"))
os.chdir(ROOT / "app")                                           # aplikacja szuka szablonów względem katalogu bieżącego
os.environ.setdefault("ADMIN_PASSWORD", "demo-admin-2026")
os.environ.setdefault("SECRET_KEY", "demo-secret-key-not-for-production-use")
os.environ.setdefault("UPDATE_CHECK", "0")
os.environ.pop("DB_PASSWORD", None)

import main  # noqa: E402
import uvicorn  # noqa: E402
from sqlalchemy import select, update  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

# --- fikcyjne kopie zapasowe (7 dni po ~6 MB)
BACKUPS = tempfile.mkdtemp(prefix="rm-demo-backups-")
for i in range(7, 0, -1):
    ts = dt.datetime.now() - dt.timedelta(days=i - 1)
    p = os.path.join(BACKUPS, "monitor-%s_030000.dump" % ts.strftime("%Y-%m-%d"))
    with open(p, "wb") as fh:
        fh.write(b"\0" * int((5.6 + 0.12 * (7 - i)) * 1024 * 1024))
    t = dt.datetime(ts.year, ts.month, ts.day, 3, 0).timestamp()
    os.utime(p, (t, t))
main.BACKUP_DIR = BACKUPS
if not main.LS_BIN:
    main.LS_BIN = "librespeed-cli"          # tylko żeby ustawienia pokazywały silnik jako dostępny; w demo nie uruchamiamy testów

rnd = random.Random(7)
MAC = lambda i: "02:5A:%02X:%02X:%02X:%02X" % (i // 65536 % 256, i // 256 % 256, i % 256, (i * 7) % 256)
LIVE_MACS = [(MAC(2), "wifi2", -54, 866), (MAC(6), "wifi2", -52, 1201), (MAC(9), "wifi2", -58, 866)]
_phase = [0.0]


def keepalive():
    while True:
        try:
            n = main.now()
            with Session(main.engine) as s:
                s.execute(update(main.Router).values(last_seen=n))
                s.execute(update(main.Inv).values(updated=n))
                master = s.scalars(select(main.Router).order_by(main.Router.id)).first()
                master.live_until = n + dt.timedelta(minutes=14)
                s.commit()
                main.LIVE_GW[master.id] = (n, round(1.2 + rnd.random() * 0.6, 1), 0, "192.168.88.1")
            _phase[0] += 1
            for mac, ifc, sig, rate in LIVE_MACS:
                h = main.LIVE_HIST.setdefault(mac, [])
                for k in range(150 if not h else 1):
                    t = n - dt.timedelta(seconds=(150 - k) * 2 if not h else 0)
                    wob = 3 * math.sin((_phase[0] + k) / 7) + rnd.gauss(0, 1.1)
                    h.append((t, round(sig + wob, 1), round(rate * (0.85 + 0.15 * rnd.random())), 3 if sig > -60 else 2, ifc))
                del h[:-400]
        except Exception as e:  # noqa: BLE001
            print("keepalive:", e, flush=True)
        time.sleep(2)


if __name__ == "__main__":
    threading.Thread(target=keepalive, daemon=True).start()
    port = int(os.environ.get("PORT", "8765"))
    print("panel demo: http://127.0.0.1:%d  (admin / demo-admin-2026)" % port, flush=True)
    uvicorn.run(main.app, host="127.0.0.1", port=port, log_level="warning")
