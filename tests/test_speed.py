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
print("test_speed: OK")
