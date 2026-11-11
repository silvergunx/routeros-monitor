"""Producent urządzenia z adresu MAC (przedrostek OUI z rejestru IEEE MA-L). Bez zależności od reszty aplikacji.

Rejestr nie jest częścią projektu ani obrazu: serwer użytkownika sam pobiera publiczną listę IEEE (patrz THIRD_PARTY.md)
i trzyma ją w bazie. Z adresów MAC nic nie jest nigdzie wysyłane, bo wyszukiwanie odbywa się lokalnie.
"""
import csv
import io
import re
import urllib.request

URL = "https://standards-oui.ieee.org/oui/oui.csv"
MAX_BYTES = 20 * 1024 * 1024  # rejestr ma ok. 4 MB; większy plik to nie jest ten rejestr
_HEX12 = re.compile(r"^[0-9A-F]{12}$")
_SUFFIXES = re.compile(
    r"(?:(?:[\s,]+|(?<=\)))(?:inc|incorporated|llc|ltd|ltda|limited|corp|corporation|co|company|gmbh|ag|s\.?a|b\.?v|oy|ab|plc|pte|pvt|"
    r"s\.?r\.?l|spa|kg|nv|as|sdn|bhd|jsc|ooo|zao|sa de cv|pty)\b\.?)+\s*$", re.I)


def normalize(mac):
    """'aa-bb-cc-dd-ee-ff', 'AABB.CCDD.EEFF' itp. -> 'AA:BB:CC:DD:EE:FF'; None, gdy to nie jest adres MAC."""
    h = re.sub(r"[^0-9A-Fa-f]", "", mac or "").upper()
    if not _HEX12.match(h):
        return None
    return ":".join(h[i:i + 2] for i in range(0, 12, 2))


def is_private(mac):
    """Adres administrowany lokalnie (drugi najmniej znaczący bit pierwszego bajtu): np. losowy, prywatny adres telefonu.
    Z takiego adresu nie da się ustalić producenta."""
    m = normalize(mac)
    return bool(m) and bool(int(m[:2], 16) & 0x02)


def shorten(vendor):
    """Nazwa do wyświetlenia: bez form prawnych (Inc., Co., Ltd.), a pełne WIELKIE LITERY zamienione na zwykłe."""
    v = " ".join((vendor or "").split())
    v = _SUFFIXES.sub("", v).strip(" ,.")
    if v.isupper() and len(v) > 4:
        v = v.title()
    return v or " ".join((vendor or "").split())


def parse_ieee_csv(text):
    """Plik CSV IEEE (Registry,Assignment,Organization Name,Organization Address) -> {'AABBCC': 'Nazwa'}."""
    out = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 3 and re.fullmatch(r"[0-9A-Fa-f]{6}", row[1].strip() or ""):
            name = " ".join(row[2].split())
            if name:
                out[row[1].strip().upper()] = name
    return out


def download(url=URL, timeout=60, max_bytes=MAX_BYTES):
    """Pobiera rejestr i zwraca jego tekst. Rzuca wyjątek przy błędzie sieci albo gdy plik jest za duży."""
    req = urllib.request.Request(url, headers={"User-Agent": "routeros-monitor"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("response too large")
    return data.decode("utf-8", "replace")


class Registry:
    """Przedrostki w pamięci. Zastępowane w całości po odświeżeniu (bez blokowania odczytów)."""

    def __init__(self):
        self.data = {}

    def set(self, data):
        self.data = dict(data)

    def __len__(self):
        return len(self.data)

    def lookup(self, mac):
        """Producent (skrócona nazwa) albo "" dla nieznanego oraz losowych/prywatnych adresów MAC."""
        m = normalize(mac)
        if not m or is_private(m):
            return ""
        return shorten(self.data.get(m[:8].replace(":", ""), ""))
