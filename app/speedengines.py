"""Parsowanie wyników zewnętrznych programów do testu prędkości (bez zależności od reszty aplikacji)."""
import json
import re

# Linia z `librespeed-cli --list`: "51: Amsterdam, Netherlands (Clouvider) (https://ams.example/backend)  [Sponsor: ...]"
_LS_LINE = re.compile(r"^\s*(\d+):\s+(.+?)\s+\((https?://[^)\s]+)\)")


def parse_librespeed_json(text):
    """Wynik `librespeed-cli --json` -> słownik w formacie aplikacji (Mb/s, ms). Rzuca ValueError przy złym wyniku.

    Pola `client` (adres IP itd.) są celowo ignorowane i nigdzie nie zapisywane.
    """
    line = next((l for l in text.strip().splitlines()[::-1] if l.strip().startswith("[")), "")
    if not line:
        raise ValueError("brak wyniku")
    d = json.loads(line)
    if not isinstance(d, list) or not d or not isinstance(d[0], dict):
        raise ValueError("nieoczekiwany format wyniku")
    r = d[0]

    def num(k):
        v = r.get(k)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None

    srv = r.get("server") or {}
    return {"down": num("download"), "up": num("upload"), "ping": num("ping"), "jitter": num("jitter"),
            "loss": None, "url": None, "server": (str(srv.get("name") or "").strip()[:120] or None)}


def parse_librespeed_servers(text):
    """Wynik `librespeed-cli --list` -> [{'id': '51', 'name': 'Amsterdam, Netherlands (Clouvider)', 'url': 'https://...'}, ...]."""
    out = []
    for line in text.splitlines():
        m = _LS_LINE.match(line)
        if m:
            out.append({"id": m.group(1), "name": m.group(2)[:100], "url": m.group(3)})
    return out


def parse_librespeed_list(text):
    """To samo bez adresów: [{'id', 'name'}] - do listy w ustawieniach."""
    return [{"id": s["id"], "name": s["name"]} for s in parse_librespeed_servers(text)]


def pick_candidates(servers, latencies, n=5):
    """`n` serwerów o najniższym opóźnieniu (latencies: {id: ms}); serwery bez pomiaru są pomijane."""
    ok = [s for s in servers if isinstance(latencies.get(s["id"]), (int, float))]
    ok.sort(key=lambda s: latencies[s["id"]])
    return [dict(s, ping=round(latencies[s["id"]], 1)) for s in ok[:n]]


def pick_best(results):
    """Serwer o największej prędkości pobierania z listy wyników [{'id','name','down',...}] albo None."""
    good = [r for r in results if isinstance(r.get("down"), (int, float)) and r["down"] > 0]
    return max(good, key=lambda r: r["down"]) if good else None
