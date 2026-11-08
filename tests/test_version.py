"""Testy wersjonowania i sprawdzania wydań. Uruchom: python tests/test_version.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import version as V


def rel(tag, pre=False, draft=False, url=None):
    return {"tag_name": tag, "prerelease": pre, "draft": draft, "html_url": url or "https://github.com/x/y/releases/tag/" + tag}


# --- porównywanie wersji
assert V.parse("1.0.0") < V.parse("1.0.1") < V.parse("1.1.0") < V.parse("2.0.0")
assert V.parse("1.1.0-beta.1") < V.parse("1.1.0-beta.2") < V.parse("1.1.0-beta.10") < V.parse("1.1.0")
assert V.parse("1.0.0") < V.parse("1.1.0-beta.1")
assert V.parse("v1.2.3") == V.parse("1.2.3")
assert V.parse("dev") is None and V.parse("") is None and V.parse(None) is None and V.parse("1.2") is None

# --- stabilna wersja widzi tylko stabilne wydania
rs = [rel("v1.0.0"), rel("v1.1.0-beta.1", pre=True), rel("v0.9.0")]
assert V.pick_newer("1.0.0", rs) is None
assert V.pick_newer("0.9.0", rs)["v"] == "1.0.0"
assert V.pick_newer("1.0.0", rs + [rel("v1.0.1")])["v"] == "1.0.1"
# --- wersja testowa widzi też testowe
assert V.pick_newer("1.0.0-beta.1", rs)["v"] == "1.1.0-beta.1"
assert V.pick_newer("1.0.0-beta.1", [rel("v1.0.0")])["v"] == "1.0.0"
assert V.pick_newer("1.0.0", [rel("v1.1.0-beta.1", pre=True)]) is None
assert V.pick_newer("1.1.0-beta.1", [rel("v1.1.0-beta.2", pre=True)])["v"] == "1.1.0-beta.2"
assert V.pick_newer("1.1.0-beta.2", [rel("v1.1.0")])["v"] == "1.1.0"
# --- szkice, śmieci i nieznana wersja bieżąca
assert V.pick_newer("1.0.0", [rel("v2.0.0", draft=True), "x", None, {"tag_name": "latest"}]) is None
assert V.pick_newer("dev", rs) is None
# --- adres musi być z github.com
assert V.pick_newer("0.1.0", [rel("v1.0.0", url="javascript:alert(1)")])["url"].startswith("https://github.com/")
assert V.pick_newer("0.1.0", [rel("v1.0.0", url="https://evil.example/x")])["url"].startswith("https://github.com/")

# --- update_info: cache, praca w tle, odporność na błędy
calls = []
V.ENABLED = True
V._fetch = lambda: (calls.append(1), [rel("v9.0.0")])[1]
V.current = lambda: "1.0.0"
V._state.update(info=None, t=0.0, ttl=0, busy=False)
first = V.update_info()                    # pierwsze wywołanie nie czeka na sieć
for _ in range(50):
    if calls:
        time.sleep(0.05)
        break
    time.sleep(0.05)
second = V.update_info()
assert first is None and second and second["v"] == "9.0.0", (first, second)
V.update_info(); V.update_info()
assert len(calls) == 1, "cache powinien zapobiegać kolejnym zapytaniom"


def boom():
    raise RuntimeError("brak sieci")


V._fetch = boom
V._state.update(t=0.0, ttl=0, busy=False)   # wymuś odświeżenie
V.update_info()
time.sleep(0.3)
assert V.update_info()["v"] == "9.0.0", "po błędzie zostaje poprzedni wynik"
assert V._state["ttl"] == V.TTL_FAIL

V.ENABLED = False
assert V.update_info() is None
print("test_version: OK")
