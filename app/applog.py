"""Bufor ostatnich ostrzeżeń i błędów aplikacji (do raportu „Zgłoś problem”) i wycinanie z nich danych wrażliwych.

Bez zależności od reszty aplikacji (łatwo testować). Do bufora trafiają: wszystko, co aplikacja wypisuje przez print,
oraz rekordy logowania od poziomu WARNING (m.in. błędy uvicorn ze śladem stosu). Logi dostępu (INFO, z tokenami routerów
w adresach) nie trafiają do bufora. Bufor żyje tylko w pamięci i znika po restarcie.
"""
import collections
import logging
import re
import sys
import threading
import time

MAX_ENTRIES = 300
MAX_ENTRY_CHARS = 1500
_buf = collections.deque(maxlen=MAX_ENTRIES)  # (czas, tekst)
_lock = threading.Lock()
_installed = False


def add(text, ts=None):
    text = (text or "").strip("\r\n")
    if text.strip():
        _buf.append((ts or time.time(), text[:MAX_ENTRY_CHARS]))


class _Tee:
    """Kopiuje do bufora każdą pełną linię wypisaną przez print; strumień oryginalny działa jak dotąd."""

    def __init__(self, stream):
        self._s = stream
        self._part = ""

    def write(self, text):
        n = self._s.write(text)
        with _lock:
            self._part += text
            *lines, self._part = self._part.split("\n")
        if lines:
            add("\n".join(lines))  # wieloliniowy komunikat wypisany jednym print to jeden wpis
        return n

    def flush(self):
        self._s.flush()

    def __getattr__(self, name):
        return getattr(self._s, name)


class _Handler(logging.Handler):
    def emit(self, record):
        try:
            if record.levelno >= logging.WARNING:
                add("%s %s: %s" % (record.levelname, record.name, self.format(record)), record.created)
        except Exception:  # bufor diagnostyczny nigdy nie może przeszkadzać aplikacji
            pass


def install():
    """Podpina bufor pod print (stdout) i logowanie (root oraz uvicorn). Można wywołać wiele razy."""
    global _installed
    if _installed:
        return
    _installed = True
    sys.stdout = _Tee(sys.stdout)
    handler = _Handler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    for name in ("", "uvicorn"):  # uvicorn.error propaguje do "uvicorn", a "uvicorn" nie propaguje do root
        logging.getLogger(name).addHandler(handler)


def recent(n=40, max_chars=6000):
    """Ostatnie wpisy (najstarszy pierwszy) jako lista (czas, tekst), łącznie najwyżej max_chars znaków."""
    items = list(_buf)[-n:]
    out, total = [], 0
    for ts, text in reversed(items):
        total += len(text)
        if total > max_chars and out:
            break
        out.append((ts, text))
    return out[::-1]


# ---------- wycinanie danych wrażliwych ----------
_RULES = [
    (re.compile(r"([?&]t=)[^&\s\"']+", re.I), r"\1***"),                                    # token routera w adresie
    (re.compile(r"\b(\w*(?:password|passwd|secret|token|api[_-]?key|authorization)\w*)(\s*[=:]\s*)\S+", re.I), r"\1\2***"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    (re.compile(r"(?<![0-9A-Fa-f:])[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}(?![0-9A-Fa-f:])"), "<mac>"),
    (re.compile(r"\b[A-Za-z0-9_-]{28,}\b"), "<secret>"),                                   # długie ciągi podobne do tokenów
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b"), "<ip>"),
]


def scrub(text, names=None):
    """Zastępuje nazwy z `names` ({nazwa: zamiennik}), tokeny, hasła, e-maile, MAC-i, długie sekrety i adresy IP."""
    text = text or ""
    for name, label in sorted((names or {}).items(), key=lambda kv: -len(kv[0])):
        if len(name) >= 3:
            text = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", label, text, flags=re.I)  # tylko całe słowa
    for rx, rep in _RULES:
        text = rx.sub(rep, text)
    return text
