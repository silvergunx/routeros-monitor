#!/usr/bin/env python3
"""Robi zrzuty ekranu panelu demo (patrz tools/demo_server.py) do docs/img/ przez Microsoft Edge w trybie headless.

    python tools/screenshots.py [http://127.0.0.1:8765] [katalog_wyjściowy]

Wymaga: zainstalowanego Microsoft Edge (Windows) oraz pakietu `websockets` (jest w zależnościach aplikacji).
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import warnings

from websockets.sync.client import connect

warnings.filterwarnings("ignore", category=DeprecationWarning)

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765").rstrip("/")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "docs" / "img")
OUT.mkdir(parents=True, exist_ok=True)
EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                         shutil.which("msedge") or "", shutil.which("chromium") or "", shutil.which("google-chrome") or "") if p and os.path.exists(p)), None)
if not EDGE:
    sys.exit("Nie znaleziono Edge/Chrome.")
PORT = 9333


class Cdp:
    def __init__(self, ws_url):
        self.ws = connect(ws_url, max_size=64 * 1024 * 1024)
        self.n = 0
        self.events = []

    def call(self, method, timeout=60, **params):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(self.ws.recv(timeout=max(0.1, end - time.time())))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s: %s" % (method, msg["error"]))
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg["method"])
        raise TimeoutError(method)

    def wait_load(self, timeout=40):
        end = time.time() + timeout
        while time.time() < end:
            if "Page.loadEventFired" in self.events:
                return
            try:
                msg = json.loads(self.ws.recv(timeout=0.5))
                if "method" in msg:
                    self.events.append(msg["method"])
            except TimeoutError:
                pass
        raise TimeoutError("load")

    def js(self, code):
        r = self.call("Runtime.evaluate", expression=code, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    def go(self, path, settle=3.0):
        self.events.clear()
        self.call("Page.navigate", url="about:blank")     # nawigacja tylko po fragmencie (#...) nie daje zdarzenia „load”
        self.wait_load()
        self.events.clear()
        self.call("Page.navigate", url=BASE + path)
        self.wait_load()
        time.sleep(settle)

    def view(self, w, h, dpr=1, mobile=False):
        self.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=dpr, mobile=mobile)

    def fit(self, w, min_h, max_h, dpr=1, mobile=False):
        self.view(w, min_h, dpr, mobile)
        time.sleep(0.4)
        h = int(self.js("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)") or min_h)
        self.view(w, max(min_h, min(h, max_h)), dpr, mobile)
        time.sleep(0.6)

    def shot(self, name, clip=None):
        args = {"format": "png"}
        if clip:
            args["clip"] = dict(clip, scale=1)
            args["captureBeyondViewport"] = True
        data = self.call("Page.captureScreenshot", **args)["data"]
        p = OUT / name
        p.write_bytes(base64.b64decode(data))
        print("%-34s %6.0f KB" % (name, p.stat().st_size / 1024), flush=True)

    def theme(self, t):
        self.js("localStorage.setItem('theme','%s'); document.documentElement.dataset.theme='%s'" % (t, t))
        time.sleep(0.3)

    def box(self, selector, pad=0):
        r = self.js("(()=>{const e=document.querySelector(%s);if(!e)return null;e.scrollIntoView();const b=e.getBoundingClientRect();"
                    "return {x:b.left+scrollX,y:b.top+scrollY,width:b.width,height:b.height}})()" % json.dumps(selector))
        if not r:
            raise RuntimeError("brak elementu " + selector)
        return {"x": max(0, r["x"] - pad), "y": max(0, r["y"] - pad), "width": r["width"] + 2 * pad, "height": r["height"] + 2 * pad}


def main():
    prof = tempfile.mkdtemp(prefix="rm-shot-")
    proc = subprocess.Popen([EDGE, "--headless=new", "--remote-debugging-port=%d" % PORT, "--user-data-dir=" + prof, "--hide-scrollbars",
                             "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--mute-audio", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                pages = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % PORT, timeout=2))
                ws = next(p["webSocketDebuggerUrl"] for p in pages if p["type"] == "page")
                break
            except Exception:
                time.sleep(0.5)
        else:
            sys.exit("Edge nie wystartował.")
        c = Cdp(ws)
        c.call("Page.enable")
        c.call("Network.enable")
        c.call("Network.setCookie", name="lang", value="en", url=BASE)
        # logowanie
        c.view(1280, 800)
        c.go("/login", 1)
        c.events.clear()
        c.js("document.querySelector('input[name=username]').value='admin';document.querySelector('input[name=password]').value='demo-admin-2026';document.querySelector('form').submit()")
        c.wait_load()
        time.sleep(2.5)

        # 1. lista routerów
        c.theme("dark")
        c.go("/", 3)
        c.fit(1280, 640, 1100)
        c.shot("routers-dark.png")
        c.theme("light")
        c.shot("routers-light.png")

        # 2. strona routera: kafelki + wykresy System
        c.theme("dark")
        c.go("/routers/1#charts", 4)
        c.js("cTab('sys')")
        c.fit(1280, 900, 1500)
        time.sleep(1.5)
        c.shot("router-system-dark.png")
        c.theme("light")
        c.go("/routers/1#charts", 4)          # motyw musi być ustawiony przed załadowaniem wykresów (kolory siatki)
        c.js("cTab('sys')")
        c.fit(1280, 900, 1500)
        time.sleep(1.5)
        c.shot("router-system-light.png")

        # 3. jakość łącza (sondy, przerwy, test prędkości)
        c.theme("dark")
        c.go("/routers/1#charts", 4)
        c.js("cTab('qual'); localStorage.setItem('nwopen','1'); localStorage.setItem('outopen','1'); location.reload()")
        c.wait_load(); time.sleep(4)
        c.js("cTab('qual'); var n=document.getElementById('nwd'); if(n) n.open=false; var o=document.getElementById('outd'); if(o&&!o.classList.contains('empty')) o.open=true;")
        c.fit(1280, 1000, 2100)
        time.sleep(1.5)
        c.shot("link-quality-dark.png")

        # 4. urządzenia, 5. Wi-Fi, 6. analiza logów
        c.theme("light")
        c.go("/routers/1#dev", 3)
        c.fit(1280, 700, 1300)
        c.shot("devices-light.png")
        c.theme("dark")
        c.go("/routers/1#wifi", 3)
        c.fit(1280, 560, 1200)
        c.shot("wifi-dark.png")
        c.go("/routers/1#logs", 3)
        c.js("lTab('ana')")
        time.sleep(2.5)
        c.fit(1280, 900, 1900)
        c.shot("log-analysis-dark.png")

        # 7. blacklista, 8. ustawienia, 9. tryb Wi-Fi na żywo
        c.theme("light")
        c.go("/blacklist", 2)
        c.fit(1280, 700, 1500)
        c.shot("blacklist-light.png")
        c.go("/settings", 3)
        c.fit(1280, 900, 4200)
        c.shot("settings-speedtest-light.png", clip=c.box("#spdset", 6))
        c.go("/settings", 3)
        c.js("var d=document.querySelector('#lsbesttab details'); if(d) d.open=true")
        c.fit(1280, 900, 4200)
        c.shot("settings-speedtest-expanded-light.png", clip=c.box("#spdset", 6))
        c.shot("settings-backups-light.png", clip=c.box("#backup", 6))
        c.theme("dark")
        c.js("localStorage.setItem('lvdev','%s')" % "02:5A:00:00:02:0E")
        c.go("/live", 5)
        c.fit(1280, 900, 2000)
        time.sleep(1.5)
        c.shot("live-wifi-dark.png")

        # 10. widok mobilny
        c.theme("light")
        c.go("/", 3)
        c.view(390, 900, 2, True)
        time.sleep(1.2)
        c.shot("mobile-routers-light.png")
        c.theme("dark")
        c.go("/routers/1#charts", 4)
        c.js("cTab('sys')")
        c.view(390, 1100, 2, True)
        time.sleep(1.5)
        c.shot("mobile-router-dark.png")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        shutil.rmtree(prof, ignore_errors=True)


if __name__ == "__main__":
    main()
