"""Testy parsowania wyników librespeed-cli. Uruchom: python tests/test_speed.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import speedengines as E

FX = ROOT / "tests" / "fixtures"

# --- prawdziwy wynik librespeed-cli v1.0.14 (--json)
res = E.parse_librespeed_json((FX / "librespeed_run.json").read_text(encoding="utf-8"))
assert res["down"] and 1 < res["down"] < 100000 and res["up"] and res["ping"] and res["jitter"] is not None, res
assert res["server"] and "Poznan" in res["server"], res
assert res["loss"] is None and res["url"] is None
assert "client" not in res and "ip" not in res

# --- prawdziwa lista serwerów (--list)
lst = E.parse_librespeed_list((FX / "librespeed_list.txt").read_text(encoding="utf-8"))
assert len(lst) >= 15, len(lst)
assert all(s["id"].isdigit() and s["name"] for s in lst)
ams = next(s for s in lst if s["id"] == "51")
assert ams["name"] == "Amsterdam, Netherlands (Clouvider)", ams   # nawiasy w nazwie zostają, adres nie

# --- odporność na śmieci
for bad in ("", "nic", "[]", "[1]", '{"a":1}', "Retrieving server list\n"):
    try:
        E.parse_librespeed_json(bad)
    except (ValueError, TypeError):
        continue
    raise AssertionError("powinien być błąd dla %r" % bad)
assert E.parse_librespeed_list("") == [] and E.parse_librespeed_list("Retrieving server list from x\n") == []
# --- zero / ujemne / napisy w polach liczbowych nie psują wyniku
r = E.parse_librespeed_json('[{"download":0,"upload":"x","ping":-1,"jitter":true,"server":{"name":"  A  "}}]')
assert r["down"] is None and r["up"] is None and r["ping"] is None and r["jitter"] is None and r["server"] == "A"
# --- dane klienta nie wyciekają do wyniku
r = E.parse_librespeed_json('[{"download":50,"client":{"ip":"1.2.3.4","org":"X"},"server":{"name":"S"}}]')
assert "1.2.3.4" not in repr(r)
# --- adresy serwerów z listy
srvs = E.parse_librespeed_servers((FX / "librespeed_list.txt").read_text(encoding="utf-8"))
assert len(srvs) == len(lst) and all(x["url"].startswith("http") for x in srvs)
assert next(x for x in srvs if x["id"] == "51")["url"] == "https://ams.speedtest.clouvider.net/backend"

# --- kandydaci wg opóźnienia i wybór najlepszego
S = [{"id": str(i), "name": "S%d" % i, "url": "https://x/%d" % i} for i in range(1, 8)]
lat = {"1": 40.0, "2": 12.5, "3": None, "4": 8.0, "5": 30.0, "6": 15.0}   # 3 bez pomiaru, 7 nieobecny
c = E.pick_candidates(S, lat, 3)
assert [x["id"] for x in c] == ["4", "2", "6"] and c[0]["ping"] == 8.0, c
assert [x["id"] for x in E.pick_candidates(S, lat, 99)] == ["4", "2", "6", "5", "1"]
assert E.pick_candidates(S, {}, 5) == []
res = [{"id": "4", "down": 180.0}, {"id": "2", "down": 519.5}, {"id": "6", "down": None}, {"id": "5", "down": 0}]
assert E.pick_best(res)["id"] == "2"
assert E.pick_best([{"id": "1", "down": None}, {"id": "2"}]) is None and E.pick_best([]) is None
print("test_speed (wybór serwera): OK")
print("test_speed: OK")
