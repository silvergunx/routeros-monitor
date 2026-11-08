#!/usr/bin/env python3
"""Generuje obraz podglądu repozytorium (social preview, 1280x640) do docs/img/social-preview.png.

    python tools/social_preview.py

Korzysta ze zrzutów w docs/img (patrz tools/screenshots.py) i Microsoft Edge w trybie headless.
Obraz wgrywa się ręcznie: GitHub -> Settings -> Social preview -> Edit -> Upload an image.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "docs" / "img"
OUT = IMG / "social-preview.png"
EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                         shutil.which("msedge") or "", shutil.which("chromium") or "", shutil.which("google-chrome") or "") if p and os.path.exists(p)), None)
if not EDGE:
    sys.exit("Nie znaleziono Edge/Chrome.")

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0}
body{width:1280px;height:640px;overflow:hidden;font-family:"Segoe UI",system-ui,-apple-system,Roboto,Helvetica,Arial,sans-serif;color:#e5e7eb;
background:radial-gradient(1000px 520px at 85% 15%,#16264a 0%,rgba(22,38,74,0) 70%),linear-gradient(135deg,#0b1220 0%,#0f1a30 100%);position:relative}
.left{position:absolute;left:72px;top:0;bottom:0;width:560px;display:flex;flex-direction:column;justify-content:center}
.badge{display:inline-block;align-self:flex-start;font-size:20px;color:#93c5fd;border:1px solid #1e3a6e;background:#10234a;border-radius:999px;padding:6px 16px;margin-bottom:26px}
h1{font-size:68px;line-height:1.05;font-weight:800;color:#fff;letter-spacing:-1px}
h1 span{color:#60a5fa}
p.tag{font-size:27px;line-height:1.35;color:#94a3b8;margin:22px 0 30px;max-width:520px}
.chips{display:flex;flex-wrap:wrap;gap:10px;max-width:540px}
.chips b{font-weight:600;font-size:19px;color:#cbd5e1;background:#131c2e;border:1px solid #22304a;border-radius:10px;padding:7px 14px}
.url{position:absolute;left:72px;bottom:34px;font-size:20px;color:#64748b}
.shot{position:absolute;border-radius:16px;overflow:hidden;border:1px solid #2a3b5e;box-shadow:0 30px 60px rgba(0,0,0,.55),0 0 0 6px rgba(96,165,250,.06)}
.shot img{display:block;width:100%}
#a{left:690px;top:62px;width:560px;height:360px;transform:rotate(-2.2deg)}
#b{left:742px;top:262px;width:520px;height:330px;transform:rotate(1.6deg)}
</style></head><body>
<div class="left">
<div class="badge">Self-hosted &middot; Docker &middot; MIT</div>
<h1>RouterOS <span>Monitor</span></h1>
<p class="tag">Monitoring, link quality, logs and IP lists for MikroTik&nbsp;RouterOS&nbsp;7</p>
<div class="chips"><b>Link quality &amp; speed test</b><b>Log analysis</b><b>Wi-Fi tools</b><b>Whitelist &amp; blacklist</b><b>Backups</b><b>PL &middot; EN</b></div>
</div>
<div class="url">github.com/silvergunx/routeros-monitor</div>
<div class="shot" id="a"><img src="@A@"></div>
<div class="shot" id="b"><img src="@B@"></div>
</body></html>"""


def main():
    a, b = IMG / "routers-dark.png", IMG / "link-quality-dark.png"
    for f in (a, b):
        if not f.exists():
            sys.exit("Brak " + str(f) + " (uruchom najpierw tools/screenshots.py).")
    tmp = Path(tempfile.mkdtemp(prefix="rm-social-"))
    page = tmp / "social.html"
    page.write_text(HTML.replace("@A@", a.as_uri()).replace("@B@", b.as_uri()), encoding="utf-8")
    prof = tmp / "profile"
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1", "--no-first-run",
                    "--user-data-dir=" + str(prof), "--window-size=1280,640", "--virtual-time-budget=4000",
                    "--screenshot=" + str(OUT), page.as_uri()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    shutil.rmtree(tmp, ignore_errors=True)
    if not OUT.exists():
        sys.exit("Nie udało się wykonać zrzutu.")
    w, h = struct.unpack(">II", OUT.read_bytes()[16:24])
    print("%s: %dx%d, %.0f KB" % (OUT.name, w, h, OUT.stat().st_size / 1024))


if __name__ == "__main__":
    main()
