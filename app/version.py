"""Wersja aplikacji i sprawdzanie, czy na GitHubie jest nowsze wydanie.

- Wersja pochodzi z pliku VERSION (np. 1.0.0 albo 1.1.0-beta.1).
- Stabilna wersja widzi tylko stabilne wydania; wersja testowa (-beta) widzi też wydania testowe.
- Zapytanie do GitHub API (publiczne repozytorium) leci z serwera aplikacji najwyżej raz na kilka godzin,
  w tle (nie spowalnia strony). Wyłączenie: UPDATE_CHECK=0 w .env.
"""
import os
import re
import threading
import time
from pathlib import Path

REPO = os.getenv("UPDATE_REPO", "silvergunx/routeros-monitor")
ENABLED = os.getenv("UPDATE_CHECK", "1").strip() != "0"
TTL_OK, TTL_FAIL = 6 * 3600, 1800

_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?$")


def current():
    try:
        return (Path(__file__).parent / "VERSION").read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


def parse(v):
    """'1.2.3' / 'v1.2.3-beta.2' -> krotka porównywalna; wersja końcowa jest wyższa od testowej tej samej liczby."""
    m = _SEMVER.match((v or "").strip())
    if not m:
        return None
    pre = m.group(4)
    n = re.search(r"(\d+)$", pre) if pre else None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if pre else 1, int(n.group(1)) if n else 0


def pick_newer(cur, releases):
    """Najwyższe wydanie nowsze niż `cur` albo None. Wydania testowe tylko dla wersji testowej."""
    c = parse(cur)
    if not c:
        return None
    allow_pre = c[3] == 0
    best = None
    for r in releases:
        if not isinstance(r, dict) or r.get("draft"):
            continue
        if r.get("prerelease") and not allow_pre:
            continue
        p = parse(r.get("tag_name"))
        if p and p > c and (best is None or p > best[0]):
            best = (p, r)
    if not best:
        return None
    r = best[1]
    url = str(r.get("html_url") or "")
    if not url.startswith("https://github.com/"):
        url = "https://github.com/%s/releases" % REPO
    return {"v": str(r["tag_name"]).lstrip("v"), "url": url}


def _fetch():
    import httpx  # import leniwy: moduł da się testować bez zależności
    r = httpx.get("https://api.github.com/repos/%s/releases?per_page=20" % REPO, timeout=5,
                  headers={"Accept": "application/vnd.github+json", "User-Agent": "routeros-monitor/" + current()})
    r.raise_for_status()
    return r.json()


_state = {"info": None, "t": 0.0, "ttl": 0, "busy": False}
_lock = threading.Lock()


def _refresh():
    ok = False
    try:
        info = pick_newer(current(), _fetch())
        ok = True
    except Exception:
        info = _state["info"]  # przy błędzie zostaje poprzedni wynik
    with _lock:
        _state.update(info=info, t=time.time(), ttl=TTL_OK if ok else TTL_FAIL, busy=False)


def update_info():
    """Zwraca {'v': '1.2.0', 'url': ...} gdy jest nowsze wydanie, inaczej None. Nigdy nie czeka na sieć."""
    if not ENABLED:
        return None
    with _lock:
        stale = time.time() - _state["t"] >= _state["ttl"]
        if stale and not _state["busy"]:
            _state["busy"] = True
            threading.Thread(target=_refresh, daemon=True).start()
        return _state["info"]
