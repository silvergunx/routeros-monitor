"""Powiadomienia (ntfy i webhook): wysyłanie i ograniczanie liczby wiadomości. Bez zależności od reszty aplikacji.

Używa tylko biblioteki standardowej (urllib), żeby dało się to testować bez instalowania pakietów.
Treść powiadomień nie zawiera adresów IP, tokenów ani haseł.
"""
import json
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

TIMEOUT = 10  # serwer ntfy na małym urządzeniu (np. Pi Zero) bywa wolny
MAX_PER_HOUR = 30  # górna granica liczby wiadomości na godzinę (ochrona przed zalaniem kanału)
SEVERITY_PRIORITY = {"info": 3, "warning": 4, "critical": 5}   # priorytety ntfy (1-5)
SEVERITY_TAGS = {"info": "information_source", "warning": "warning", "critical": "rotating_light"}
_lock = threading.Lock()
_sent = []  # czasy ostatnich wysłanych wiadomości (monotoniczne)


def valid_url(url):
    """Adres musi być http(s) z nazwą hosta."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.hostname)


def _post_json(url, payload, headers=None):
    """POST z treścią JSON. Zwraca ("", None) albo (komunikat błędu, kod HTTP)."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    h = {"Content-Type": "application/json; charset=utf-8", "User-Agent": "routeros-monitor"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            r.read(1024)
            return "", r.status
    except urllib.error.HTTPError as e:
        return "HTTP %d" % e.code, e.code
    except (urllib.error.URLError, OSError, ValueError) as e:
        return (str(getattr(e, "reason", e)) or type(e).__name__)[:120], None


def send_ntfy(server, topic, title, message, severity="info", token=""):
    """Publikuje wiadomość przez JSON API ntfy (UTF-8 bez problemów z nagłówkami)."""
    if not valid_url(server) or not (topic or "").strip():
        return "ntfy: invalid address or topic"
    payload = {"topic": topic.strip(), "title": title, "message": message,
               "priority": SEVERITY_PRIORITY.get(severity, 3), "tags": [SEVERITY_TAGS.get(severity, "information_source")]}
    err, _ = _post_json(server.strip().rstrip("/") + "/", payload, {"Authorization": "Bearer " + token} if token else None)
    return ("ntfy: " + err) if err else ""


def send_webhook(url, event):
    """Wysyła zdarzenie jako JSON POST na dowolny adres (Home Assistant, n8n, Discord przez pośrednika itp.)."""
    if not valid_url(url):
        return "webhook: invalid address"
    err, _ = _post_json(url.strip(), event)
    return ("webhook: " + err) if err else ""


def allow_send(now=None):
    """Zwraca True i zapisuje wysyłkę, jeśli limit na godzinę nie jest przekroczony."""
    now = time.monotonic() if now is None else now
    with _lock:
        _sent[:] = [t for t in _sent if now - t < 3600]
        if len(_sent) >= MAX_PER_HOUR:
            return False
        _sent.append(now)
        return True


def dispatch(cfg, event, force=False):
    """Wysyła zdarzenie na skonfigurowane kanały. Zwraca listę błędów (pusta = sukces).

    cfg: ntfy_url, ntfy_topic, ntfy_token, hook_url. event: kind, severity, title, message, router, time, app, version.
    force=True (przycisk „wyślij test”) pomija limit godzinowy.
    """
    channels = []
    if (cfg.get("ntfy_url") or "").strip() and (cfg.get("ntfy_topic") or "").strip():
        channels.append("ntfy")
    if (cfg.get("hook_url") or "").strip():
        channels.append("webhook")
    if not channels:
        return ["no channel configured"]
    if not force and not allow_send():
        return ["rate limit (%d per hour)" % MAX_PER_HOUR]
    errors = []
    if "ntfy" in channels:
        e = send_ntfy(cfg["ntfy_url"], cfg["ntfy_topic"], event["title"], event["message"], event.get("severity", "info"),
                      cfg.get("ntfy_token", ""))
        if e:
            errors.append(e)
    if "webhook" in channels:
        e = send_webhook(cfg["hook_url"], event)
        if e:
            errors.append(e)
    return errors
