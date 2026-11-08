"""Proste tłumaczenia: pliki locales/<kod>.json, język w ciasteczku `lang`.

Dodanie języka = skopiowanie locales/en.json do locales/<kod>.json (np. de.json),
przetłumaczenie wartości i ustawienie "_name". Brakujące klucze wracają do angielskiego.
"""
import json
import re
from contextvars import ContextVar
from pathlib import Path

from jinja2 import pass_context
from markupsafe import Markup, escape

DIR = Path(__file__).parent / "locales"
DEFAULT = "en"
COOKIE = "lang"


def _load():
    out = {}
    for f in sorted(DIR.glob("*.json")):
        try:
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return out


LOCALES = _load()


def languages():
    """[(kod, nazwa, czy_jest_flaga)] dla przełącznika; polski pierwszy, reszta alfabetycznie."""
    codes = sorted(LOCALES, key=lambda c: (c != "pl", c))
    return [(c, LOCALES[c].get("_name", c), (DIR / f"{c}.svg").is_file()) for c in codes]


def translate(lang, key, **kw):
    v = LOCALES.get(lang, {}).get(key) or LOCALES.get(DEFAULT, {}).get(key) or key
    if kw:
        try:
            v = v.format(**kw)
        except (KeyError, IndexError, ValueError):
            pass
    return v


def _plural_pl(n):
    if n == 1:
        return "one"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "few"
    return "many"


# Reguły liczby mnogiej dla języków innych niż angielski (domyślnie: 1 = one, reszta = other).
# Dodając język z bardziej złożoną regułą, dopisz ją tutaj.
PLURAL = {"pl": _plural_pl}


def translate_n(lang, key, n, **kw):
    """Klucze <key>.one / .few / .many / .other; brak kategorii -> .other -> angielski."""
    cat = PLURAL.get(lang, lambda k: "one" if k == 1 else "other")(n)
    loc = LOCALES.get(lang, {})
    for c in (cat, "other", "many"):
        if f"{key}.{c}" in loc:
            return translate(lang, f"{key}.{c}", n=n, **kw)
    return translate(DEFAULT, f"{key}.{'one' if n == 1 else 'other'}", n=n, **kw)


def pick_lang(request):
    """Ciasteczko -> nagłówek Accept-Language -> angielski."""
    c = request.cookies.get(COOKIE)
    if c in LOCALES:
        return c
    for part in request.headers.get("accept-language", "").split(","):
        m = re.match(r"\s*([A-Za-z]{2,3})", part)
        if m and m.group(1).lower() in LOCALES:
            return m.group(1).lower()
    return DEFAULT if DEFAULT in LOCALES else next(iter(LOCALES), DEFAULT)


def _lang(ctx):
    return getattr(ctx["request"].state, "lang", DEFAULT)


@pass_context
def t(ctx, key, **kw):
    """Zwykły tekst (escapowany przez Jinja)."""
    return translate(_lang(ctx), key, **kw)


@pass_context
def th(ctx, key, **kw):
    """Tekst z prostym HTML (<b>, <code>) - klucze kończą się na .html; parametry są escapowane."""
    return Markup(translate(_lang(ctx), key, **{k: escape(v) for k, v in kw.items()}))


@pass_context
def tn(ctx, key, n, **kw):
    """Tekst z liczbą mnogą."""
    return translate_n(_lang(ctx), key, n, **kw)


# Język bieżącego żądania (ustawiany w middleware) - pozwala tłumaczyć komunikaty w kodzie serwera.
CURRENT = ContextVar("lang", default=DEFAULT)


def _(key, **kw):
    return translate(CURRENT.get(), key, **kw)
