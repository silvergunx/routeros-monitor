#!/usr/bin/env python3
"""Fikcyjne dane demonstracyjne do zrzutów ekranu i do oglądania panelu bez własnych routerów.

Użycie (wymaga zależności z app/requirements.txt):
    DATABASE_URL=sqlite:///demo.db python tools/demo_data.py
    DATABASE_URL=sqlite:///demo.db python tools/demo_server.py      # panel na http://127.0.0.1:8765

Wszystkie nazwy, adresy MAC i IP są zmyślone (zakresy dokumentacyjne RFC 5737 i CGNAT 100.64/10).
Skrypt pracuje WYŁĄCZNIE na pliku SQLite i odmawia uruchomienia na innej bazie (nie nadpisze produkcyjnej).
Konta demo: admin / demo-admin-2026 (administrator), viewer / demo-viewer-2026 (tylko podgląd).
"""
import datetime as dt
import json
import math
import os
import random
import sys
from pathlib import Path

URL = os.environ.get("DATABASE_URL", "")
if not URL.startswith("sqlite:///"):
    sys.exit("Odmowa: tools/demo_data.py działa tylko na bazie SQLite (ustaw DATABASE_URL=sqlite:///demo.db).")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("ADMIN_PASSWORD", "demo-admin-2026")
os.environ.setdefault("SECRET_KEY", "demo-secret-key-not-for-production-use")
os.environ.setdefault("UPDATE_CHECK", "0")
os.environ.pop("DB_PASSWORD", None)

import main  # noqa: E402
from sqlalchemy import insert  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

rnd = random.Random(20261108)
N = main.now().replace(second=0, microsecond=0)


def ago(**kw):
    return N - dt.timedelta(**kw)


def day_factor(ts):
    h = ts.hour + ts.minute / 60
    return 0.5 + 0.5 * math.cos((h - 20.5) / 24 * 2 * math.pi)       # szczyt wieczorem


def mac(i):
    return "02:5A:%02X:%02X:%02X:%02X" % (i // 65536 % 256, i // 256 % 256, i % 256, (i * 7) % 256)


ROUTERS = [
    dict(name="Master", edge=True, ident="master", ver="7.20.4 (stable)", up="23d4h12m", log_ip="192.168.88.1", scale=1.0,
         ifaces=[("ether1", "ether", 1.0), ("ether2", "ether", 0.22), ("ether3", "ether", 0.18), ("ether4", "ether", 0.05),
                 ("ether5", "ether", 0.10), ("sfp-sfpplus1", "ether", 0.30), ("bridge", "bridge", 0.85), ("vlan10-guest", "vlan", 0.06),
                 ("wireguard1", "wg", 0.03)],
         sys=dict(model="RB5009UG+S+IN", caps="manager", capsn="2", wq="0", fwc="7.20.4", fwu="7.20.4", tm="1073741824", wifi="0", wl="0", dhs="1", wgs="1")),
    dict(name="AP Upstairs", edge=False, ident="ap-upstairs", ver="7.20.4 (stable)", up="23d4h09m", log_ip="192.168.88.2", scale=0.28,
         ifaces=[("ether1", "ether", 1.0), ("bridge", "bridge", 1.0), ("wifi1", "wifi", 0.35), ("wifi2", "wifi", 0.65)],
         sys=dict(model="cAP ax", caps="cap", wq="1", fwc="7.20.4", fwu="7.20.4", tm="1073741824", wifi="2", wl="0", dhs="0", wgs="0")),
    dict(name="AP Garage", edge=False, ident="ap-garage", ver="7.19.6 (stable)", up="9d18h41m", log_ip="192.168.88.3", scale=0.10,
         ifaces=[("ether1", "ether", 1.0), ("bridge", "bridge", 1.0), ("wifi1", "wifi", 1.0)],
         sys=dict(model="cAP ac", caps="cap", wq="0", fwc="7.19.6", fwu="7.20.4", tm="134217728", wifi="0", wl="1", dhs="0", wgs="0")),
    dict(name="Branch office", edge=False, ident="branch-hex", ver="7.20.4 (stable)", up="61d2h5m", log_ip="192.168.20.1", scale=0.16,
         ifaces=[("ether1", "ether", 1.0), ("ether2", "ether", 0.4), ("ether3", "ether", 0.25), ("bridge", "bridge", 0.7), ("wireguard1", "wg", 0.2)],
         sys=dict(model="hEX S", caps="", wq="0", fwc="7.20.4", fwu="7.20.4", tm="536870912", wifi="0", wl="0", dhs="1", wgs="1")),
]

DEVICES = [  # (komentarz, host, ip-końcówka, Wi-Fi?, statyczny)
    ("Living-room TV", "lg-webos", 21, True, False), ("Anna iPhone", "iPhone-Anna", 22, True, False), ("NAS", "ds-home", 5, False, True),
    ("Printer", "hp-laserjet", 8, False, True), ("Smart plug 1", "tapo-p110", 31, True, False), ("Work laptop", "THINKPAD-X1", 23, True, False),
    ("Raspberry Pi", "raspberrypi", 6, False, True), ("Garage camera", "cam-garage", 41, True, False), ("Thermostat", "nest-thermo", 32, True, False),
    ("Tom Android", "Pixel-8", 24, True, False), ("Kitchen speaker", "echo-dot-k", 33, True, False), ("Desktop PC", "DESKTOP-GAMER", 25, False, False),
    ("Tablet", "iPad-kids", 26, True, False), ("Robot vacuum", "roborock-s7", 34, True, False), ("Doorbell", "ring-door", 42, True, False),
    ("Home Assistant", "homeassistant", 7, False, True), ("Guest phone", "Galaxy-S23", 101, True, False), ("E-reader", "kindle-pw5", 35, True, False),
]


def build(s):
    # ---------------------------------------------------------------- użytkownicy, routery
    now = main.now()
    s.add(main.User(username="admin", pw=main.hash_pw("demo-admin-2026", 1000), role="admin", created=ago(days=60), last_login=ago(hours=2)))
    s.add(main.User(username="viewer", pw=main.hash_pw("demo-viewer-2026", 1000), role="viewer", created=ago(days=20), last_login=ago(days=1)))
    rs = []
    for i, spec in enumerate(ROUTERS):
        r = main.Router(name=spec["name"], token="demo-token-%d-%s" % (i + 1, "x" * 24), ident=spec["ident"], ver=spec["ver"], uptime=spec["up"],
                        wan="ether1", last_seen=now, pos=i + 1, log_ip=spec["log_ip"], edge=spec["edge"],
                        iface_types=json.dumps({n: t for n, t, _ in spec["ifaces"]}))
        s.add(r)
        rs.append(r)
    s.flush()
    master = rs[0]

    # ---------------------------------------------------------------- pomiary: 7 dni co minutę
    MIN = 7 * 24 * 60
    outages = [(52 * 60, 11, "inet"), (3 * 24 * 60 + 7 * 60, 7, "dns"), (5 * 24 * 60 + 130, 4, "http")]   # (minut temu: początek, czas trwania, rodzaj)

    def outage_kind(mins_ago):
        for start, dur, kind in outages:
            if start - dur < mins_ago <= start:
                return kind
        return None

    for r, spec in zip(rs, ROUTERS):
        rows, irows, crows = [], [], []
        rxc = rnd.randint(10**12, 3 * 10**12)
        txc = rnd.randint(10**11, 6 * 10**11)
        icnt = {n: [rnd.randint(10**11, 10**12), rnd.randint(10**10, 10**11)] for n, _, _ in spec["ifaces"]}
        devs = 14 if spec["name"] == "Master" else 3 + rnd.randint(0, 4)
        for k in range(MIN):
            mins_ago = MIN - 1 - k
            ts = ago(minutes=mins_ago)
            f = day_factor(ts)
            jit = rnd.random()
            rx_bps = (4e6 + 190e6 * f * (0.45 + 0.55 * rnd.random()) * (1 if spec["edge"] else 0.6)) * spec["scale"]
            tx_bps = (1e6 + 22e6 * f * (0.4 + 0.6 * rnd.random())) * spec["scale"]
            rxc += int(rx_bps * 60 / 8)
            txc += int(tx_bps * 60 / 8)
            cpu = max(2, 7 + 14 * f * spec["scale"] ** 0.3 + rnd.gauss(0, 2.5) + (25 if rnd.random() < 0.004 else 0))
            mem = 41 + 8 * (spec["scale"] ** 0.2) + 2 * math.sin(k / 600) + rnd.gauss(0, 0.4)
            kind = outage_kind(mins_ago) if spec["edge"] else None
            d = dict(router_id=r.id, ts=ts, cpu=round(min(cpu, 95), 1), mem=round(mem, 1),
                     temp=round(43 + 6 * f + rnd.gauss(0, 0.6), 1), conns=int(900 + 1700 * f * spec["scale"] ** 0.5 + rnd.gauss(0, 60)),
                     rx=rxc, tx=txc, rx_bps=rx_bps, tx_bps=tx_bps, dhcp=devs)
            if spec["edge"]:
                down = kind == "inet"
                d.update(inet_up=not down, dns_up=False if kind in ("inet", "dns") else True, http_up=False if kind in ("inet", "dns", "http") else True,
                         inet_rtt=None if down else round(9.5 + 3 * jit + (14 if rnd.random() < 0.01 else 0), 1),
                         inet_jit=None if down else round(0.8 + 1.6 * rnd.random(), 1),
                         inet_loss=100.0 if down else (0.0 if mins_ago < 90 else rnd.choice([0.0] * 80 + [2.5, 5.0])),
                         gw_rtt=round(1.1 + 0.9 * rnd.random(), 1), gw_jit=round(0.2 + 0.4 * rnd.random(), 1), gw_loss=0.0,
                         dns_ms=None if kind in ("inet", "dns") else round(13 + 8 * rnd.random(), 1),
                         http_ms=None if kind in ("inet", "dns", "http") else round(82 + 40 * rnd.random(), 1))
                d["ping_ms"], d["loss"] = d["inet_rtt"], d["inet_loss"]
            else:
                d.update(gw_rtt=round(0.9 + 1.1 * rnd.random(), 1), gw_jit=round(0.2 + 0.5 * rnd.random(), 1), gw_loss=0.0 if mins_ago < 90 else rnd.choice([0.0] * 60 + [1.0]))
                d["ping_ms"], d["loss"] = d["gw_rtt"], d["gw_loss"]
            rows.append(d)
            if mins_ago < 48 * 60:        # interfejsy: 48 h
                for name, typ, share in spec["ifaces"]:
                    ib = rx_bps * share * (0.8 + 0.4 * rnd.random()) * (0.12 if typ == "wg" else 1)
                    ob = tx_bps * share * (0.8 + 0.4 * rnd.random()) * (0.12 if typ == "wg" else 1)
                    icnt[name][0] += int(ib * 60 / 8)
                    icnt[name][1] += int(ob * 60 / 8)
                    irows.append(dict(router_id=r.id, ts=ts, name=name, rx=icnt[name][0], tx=icnt[name][1], rx_bps=ib, tx_bps=ob))
                crows.append(dict(router_id=r.id, ts=ts, dev_on=devs - (1 if rnd.random() < 0.2 else 0) + int(2 * f), dev_total=devs + 4,
                                  wifi=max(0, int(devs * 0.7 + 3 * f + rnd.gauss(0, 0.7))) if spec["name"] != "Branch office" else 1, vpn_on=2 if spec["name"] in ("Master", "Branch office") else 0))
        for chunk in range(0, len(rows), 4000):
            s.execute(insert(main.Metric), rows[chunk:chunk + 4000])
        for chunk in range(0, len(irows), 4000):
            s.execute(insert(main.IfaceMetric), irows[chunk:chunk + 4000])
        s.execute(insert(main.ClientStat), crows)

    # ---------------------------------------------------------------- sondy Netwatch (router brzegowy)
    master.nw_state = json.dumps([
        {"name": "@gw", "host": "192.0.2.1", "status": "up", "rtt": 1.4, "jit": 0.3, "loss": 0, "time": None, "since": "2026-10-15 03:11:09"},
        {"name": "DNS 1.1.1.1", "host": "1.1.1.1", "status": "up", "rtt": 9.8, "jit": 1.1, "loss": 0, "time": None, "since": "2026-10-15 03:11:09"},
        {"name": "DNS 8.8.8.8", "host": "8.8.8.8", "status": "up", "rtt": 10.9, "jit": 1.4, "loss": 0, "time": None, "since": "2026-10-15 03:11:09"},
        {"name": "DNS 9.9.9.9", "host": "9.9.9.9", "status": "up", "rtt": 12.2, "jit": 1.9, "loss": 0, "time": None, "since": "2026-10-15 03:11:09"},
        {"name": "@dns", "host": "example.com", "status": "up", "rtt": None, "jit": None, "loss": None, "time": 16, "since": "2026-10-15 03:11:09"},
        {"name": "@http", "host": "https://example.com", "status": "up", "rtt": None, "jit": None, "loss": None, "time": 94, "since": "2026-10-15 03:11:09"}])
    for r, spec in zip(rs[1:], ROUTERS[1:]):
        r.nw_state = json.dumps([{"name": "@gw", "host": "192.168.88.1", "status": "up", "rtt": 1.2, "jit": 0.3, "loss": 0, "time": None, "since": ""}])

    # ---------------------------------------------------------------- inwentarz
    def inv(r, kind, key, data):
        s.add(main.Inv(router_id=r.id, kind=kind, key=key, data=json.dumps(dict(data, key=key)), seq="1", updated=now))
    for r, spec in zip(rs, ROUTERS):
        inv(r, "sys", "sys", spec["sys"])
    # porty Ethernet (zakładka Porty): nazwa -> (running, disabled, rate, full-duplex, bridge, komentarz)
    PORTS = {
        0: [("ether1", "true", "false", "1Gbps", "true", "", "ISP"), ("ether2", "true", "false", "1Gbps", "true", "bridge", "Office switch"),
            ("ether3", "true", "false", "100Mbps", "true", "bridge", "Printer (bad cable?)"), ("ether4", "false", "false", "", "", "bridge", ""),
            ("ether5", "true", "false", "1Gbps", "true", "bridge", "NAS"), ("ether6", "true", "false", "2.5Gbps", "true", "bridge", "Workstation"),
            ("ether7", "false", "true", "", "", "", "unused"), ("ether8", "false", "false", "", "", "bridge", ""),
            ("sfp-sfpplus1", "true", "false", "10Gbps", "true", "bridge", "Uplink to rack")],
        1: [("ether1", "true", "false", "1Gbps", "true", "bridge", "")],
        2: [("ether1", "true", "false", "1Gbps", "true", "bridge", "")],
        3: [("ether1", "true", "false", "1Gbps", "true", "", ""), ("ether2", "true", "false", "100Mbps", "false", "bridge", "Old phone"),
            ("ether3", "false", "false", "", "", "bridge", "")]}
    for ri, plist in PORTS.items():
        for n, run, dis, rate, dup, br, cm in plist:
            inv(rs[ri], "eth", n, dict(run=run, dis=dis, rate=rate, dup=dup, ld="0", br=br, cm=cm))
    LEASES = {}
    for i, (comment, host, last, wifi, static) in enumerate(DEVICES):
        ip = "192.168.88.%d" % last
        online = i % 7 != 5
        LEASES[i] = dict(ip=ip, host=host, comment=comment, status="bound", arp="reachable" if online else "stale",
                         bh="1" if online else "0", last="%dm%02ds" % (rnd.randint(0, 40), rnd.randint(0, 59)), dyn="false" if static else "true")
        inv(rs[0], "dhcp", mac(i + 1), LEASES[i])
    for i in range(1, 6):
        inv(rs[3], "dhcp", mac(300 + i), dict(ip="192.168.20.%d" % (10 + i), host=["office-pc-%d" % i, "mfp-canon", "voip-phone", "nas-branch", "laptop-sales"][i - 1],
                                              comment=["Reception PC", "Copier", "VoIP phone", "Branch NAS", "Sales laptop"][i - 1], status="bound", arp="reachable", bh="1", last="2m", dyn="false" if i in (2, 4) else "true"))
    wifi_clients = [  # (indeks urządzenia, router, interfejs, sygnał, tx, rx, SNR, czas)
        (0, 1, "wifi2", -49, "1201Mbps-80MHz/2S/SGI", "1080Mbps-80MHz/2S/SGI", 46, "5d3h"), (1, 1, "wifi2", -56, "866.6Mbps-80MHz/2S/SGI", "720Mbps-80MHz/2S/SGI", 39, "3h12m"),
        (4, 1, "wifi1", -61, "144.4Mbps-20MHz/2S", "130Mbps-20MHz/2S", 31, "23d"), (5, 1, "wifi2", -52, "1201Mbps-80MHz/2S/SGI", "1201Mbps-80MHz/2S/SGI", 43, "7h45m"),
        (8, 1, "wifi1", -66, "72.2Mbps-20MHz/1S", "65Mbps-20MHz/1S", 25, "12d"), (9, 1, "wifi2", -58, "866.6Mbps-80MHz/2S/SGI", "780Mbps-80MHz/2S/SGI", 36, "1h20m"),
        (7, 2, "wifi1", -63, "130Mbps-20MHz/2S", "117Mbps-20MHz/2S", 28, "9d"), (14, 2, "wifi1", -71, "58.5Mbps-20MHz/1S", "52Mbps-20MHz/1S", 21, "9d"),
        (12, 1, "wifi2", -73, "288.7Mbps-40MHz/1S", "240Mbps-40MHz/1S", 18, "2h02m"), (13, 1, "wifi1", -77, "28.9Mbps-20MHz/1S", "24Mbps-20MHz/1S", 14, "15d"),
    ]
    cap_names = {1: "cap-upstairs", 2: "cap-garage"}
    for i, ri, ifc, sig, tx, rxr, snr, up in wifi_clients:
        data = {"interface": ifc, "signal": str(sig), "tx-rate": tx, "rx-rate": rxr, "signal-to-noise": str(snr), "uptime": up}
        if ifc == "wifi1":
            data["band"] = "2ghz-n"                                 # radio 2,4 GHz
        inv(rs[ri], "wifi", mac(i + 1), data)                       # klient widziany przez swój AP (nazwę zna z dzierżawy DHCP kontrolera)
        inv(rs[ri], "dhcp", mac(i + 1), LEASES[i])
        inv(rs[0], "wifi", mac(i + 1), dict(data, interface="%s-%s" % (cap_names[ri], "5g" if "wifi2" == ifc else "2g")))   # kontroler CAPsMAN widzi wszystkich
    inv(rs[0], "wg", "k1" + "A" * 20, dict(name="phone-anna", iface="wireguard1", endpoint="100.64.12.8:51820", hs="34s", rx="184532991", tx="92311034", disabled="false"))
    inv(rs[0], "wg", "k2" + "B" * 20, dict(name="laptop-work", iface="wireguard1", endpoint="100.64.40.17:51820", hs="1m12s", rx="9845321", tx="5134213", disabled="false"))
    inv(rs[0], "wg", "k3" + "C" * 20, dict(name="tom-tablet", iface="wireguard1", endpoint="", hs="", rx="0", tx="0", disabled="true"))
    inv(rs[3], "wg", "k4" + "D" * 20, dict(name="hq-tunnel", iface="wireguard1", endpoint="100.64.1.1:51820", hs="19s", rx="3421091845", tx="1209384112", disabled="false"))

    # ---------------------------------------------------------------- logi z routerów (ostatnie 24 h)
    log_rows = []

    def L(router, minutes_ago, sev, topics, msg):
        log_rows.append(dict(router_id=rs[router].id, ts=ago(minutes=minutes_ago, seconds=rnd.randint(0, 50)), sev=sev, topics=topics, msg=msg))
    attackers = ["100.64.18.202", "100.64.77.31", "100.64.91.35", "100.64.150.4"]
    for k in range(90):
        L(0, rnd.randint(5, 1400), 4, "system,error,critical", "login failure for user %s from %s via %s" % (rnd.choice(["admin", "root", "user", "test"]), rnd.choice(attackers[:2]), rnd.choice(["ssh", "ssh", "winbox"])))
    for k in range(14):
        L(0, rnd.randint(5, 1400), 4, "system,error,critical", "login failure for user admin from %s via winbox" % attackers[2])
    for k in range(40):
        i = rnd.randint(1, 18)
        L(0, rnd.randint(1, 1400), 6, "dhcp,info", "dhcp1 assigned 192.168.88.%d for %s %s" % (20 + i, mac(i), "host-%d" % i))
    for k in range(22):
        L(1, rnd.randint(1, 1400), 6, "wifi,info", "%s@wifi2 connected" % mac(rnd.randint(1, 12)))
        L(1, rnd.randint(1, 1400), 6, "wifi,info", "%s@wifi2 disconnected, %s" % (mac(rnd.randint(1, 12)), rnd.choice(["roamed", "inactivity", "received deauth"])))
    for k in range(6):
        L(2, rnd.randint(1, 1400), 4, "wifi,warning", "%s@wifi1 disconnected, 4-way handshake timeout" % mac(9))
    L(2, 190, 4, "interface,warning", "ether1 link down")
    L(2, 188, 6, "interface,info", "ether1 link up (speed 100M, full duplex)")
    L(0, 3010, 3, "interface,error", "ether1 link down")
    L(0, 2998, 6, "interface,info", "ether1 link up (speed 1G, full duplex)")
    L(0, 640, 6, "system,info", "ntp change time nov/08/2026 02:03:11 => nov/08/2026 02:03:14")
    L(0, 1380, 4, "system,warning", "failure: connection timeout")
    L(0, 800, 6, "system,info,account", "user admin logged in from 192.168.88.25 via winbox")
    L(0, 30, 6, "system,info,account", "user admin logged in from 192.168.88.25 via web")
    L(0, 95, 5, "system,info", "filter rule changed by admin")
    L(3, 1300, 3, "wireguard,error", "wireguard1: handshake for peer did not complete")
    L(0, 9, 5, "firewall,info", "input: in:ether1 out:(unknown 0), proto TCP (SYN), 100.64.18.202:51822->192.168.88.1:8291, len 60")
    for row in sorted(log_rows, key=lambda x: x["ts"]):
        s.add(main.LogEntry(**row))

    # ---------------------------------------------------------------- testy prędkości, transfer, listy, ustawienia
    servers = ["Poznan, Poland (INEA)", "Amsterdam, Netherlands (Clouvider)", "Frankfurt, Germany (Clouvider)"]
    for d in range(13, -1, -1):
        t_night = (N - dt.timedelta(days=d)).replace(hour=2, minute=30) + dt.timedelta(minutes=rnd.randint(0, 3))
        if t_night > N:
            continue
        down = 500 + rnd.gauss(0, 18) if d != 6 else 392.5
        s.add(main.SpeedTest(router_id=master.id, ts=t_night, ok=True, down_mbps=round(down, 1), up_mbps=round(94 + rnd.gauss(0, 2.5), 1),
                             ping_ms=round(11 + rnd.gauss(0, 1.2), 1), source="librespeed", jitter_ms=round(2 + rnd.random(), 1), secs=38.0, server=servers[0 if d % 5 else 1]))
    for d in range(45, -1, -1):
        day = (N - dt.timedelta(days=d)).date()
        s.add(main.TrafficDay(router_id=master.id, day=day, iface="ether1", rx=int((18 + 40 * rnd.random() + (25 if day.weekday() >= 5 else 0)) * 1024**3),
                              tx=int((2 + 6 * rnd.random()) * 1024**3)))
    wl = [("203.0.113.10", "Office", None, None), ("198.51.100.0/24", "Partner VPN", ago(days=-30), None), ("home.example.org", "Dynamic DNS home", None, None)]
    for ip, c, exp, rid in wl:
        s.add(main.Whitelist(kind="white", ip=ip, comment=c, expires=exp, router_id=rid))
    bl = [("100.64.18.202", "SSH brute force", ago(days=-6), None), ("100.64.77.0/24", "Port scanner network", ago(days=-29), None),
          ("100.64.91.35", "Winbox brute force", None, None), ("bad-actor.example.net", "Reported phishing host", ago(days=-13), None),
          ("100.64.150.4", "Scanning AP only", ago(days=-2), rs[2].id)]
    for ip, c, exp, rid in bl:
        s.add(main.Whitelist(kind="black", ip=ip, comment=c, expires=exp, router_id=rid))
    for i, (act, det, who) in enumerate([("logowanie", "admin", "admin"), ("interwał", "60 s", "admin"), ("blacklist+", "100.64.18.202 (SSH brute force) zakres=wszystkie", "admin"),
                                         ("whitelist+", "203.0.113.10 (Office) zakres=wszystkie", "admin"), ("test prędkości", "z serwera za routerem: Master", "admin")]):
        s.add(main.AuditLog(ts=ago(hours=10 - 2 * i), action=act, detail=det, who=who))
    best = {"at": ago(hours=5).isoformat(timespec="seconds"), "best": {"id": "74", "name": servers[0], "ping": 9.1, "down": 519.5},
            "tested": [{"id": "74", "name": servers[0], "ping": 9.1, "down": 519.5}, {"id": "51", "name": servers[1], "ping": 12.3, "down": 518.9},
                       {"id": "94", "name": "Amsterdam, Netherlands (Sharktech)", "ping": 14.0, "down": 353.3},
                       {"id": "50", "name": servers[2], "ping": 18.2, "down": 308.1},
                       {"id": "105", "name": "Frankfurt, Germany (FS IT-Systeme GmbH)", "ping": 19.0, "down": 255.4},
                       {"id": "85", "name": "Prague, Czech Republic (Turris)", "ping": 21.0, "down": 134.2}]}
    for k, v in (("speed_router", str(master.id)), ("speed_engine", "librespeed"), ("speed_server_librespeed", "best"),
                 ("speed_ls_best", json.dumps(best)), ("interval", "60")):
        main.sset(s, k, v)
    s.add(main.LiveSpot(ts=ago(hours=3), mac=mac(2), label="Living room by the window", device="Anna iPhone", iface="wifi2", signal=-54.0, rate=866.0, quality=3))
    s.add(main.LiveSpot(ts=ago(hours=3, minutes=-12), mac=mac(2), label="Kitchen", device="Anna iPhone", iface="wifi1", signal=-66.0, rate=144.0, quality=2))
    s.add(main.LiveSpot(ts=ago(hours=2), mac=mac(2), label="Garage", device="Anna iPhone", iface="wifi1", signal=-79.0, rate=29.0, quality=0))
    s.commit()


if __name__ == "__main__":
    p = URL.replace("sqlite:///", "")
    if p and p != ":memory:" and os.path.exists(p) and os.path.getsize(p) > 0:
        os.remove(p)
        print("usunięto poprzednią bazę demo:", p)
    main.Base.metadata.create_all(main.engine)
    with Session(main.engine) as session:
        build(session)
    print("dane demo gotowe:", URL)
