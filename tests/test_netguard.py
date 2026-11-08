"""Testy zabezpieczeń blacklisty. Uruchom: python tests/test_netguard.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from netguard import check_ban

mine = ["203.0.113.7", "192.168.88.1", "2001:db8::1", "", None, "fe80::1%eth0"]
# --- można
assert check_ban("198.51.100.5", mine) == ""
assert check_ban("198.51.100.0/24", mine) == ""
assert check_ban("10.20.30.0/24", mine) == ""            # prywatna sieć, ale bez chronionych adresów
assert check_ban("bad.example.com", mine, "panel.example.org") == ""
assert check_ban("  198.51.100.5  ", mine) == ""
# --- adres chroniony (dokładny i objęty siecią)
assert check_ban("203.0.113.7", mine) == "self"
assert check_ban("203.0.113.0/24", mine) == "self"
assert check_ban("192.168.0.0/16", mine) == "self"
assert check_ban("192.168.88.1/32", mine) == "self"
assert check_ban("panel.example.org", mine, "Panel.Example.org.") == "self"
# --- za szeroko
for broad in ("0.0.0.0/0", "10.0.0.0/7", "128.0.0.0/1", "1.0.0.0/4"):
    assert check_ban(broad, []) in ("broad", "bad"), broad
assert check_ban("10.0.0.0/8", []) == ""                 # dokładnie /8 jeszcze wolno
assert check_ban("10.0.0.0/7", []) == "broad"
# --- adresy specjalne i IPv6
assert check_ban("127.0.0.1", []) == "bad" and check_ban("127.0.0.0/8", []) == "bad"
assert check_ban("0.0.0.0", []) == "bad"
assert check_ban("224.0.0.1", []) == "bad"
assert check_ban("2001:db8::5", []) == "bad"
# --- niepoprawne wpisy nie wywołują wyjątku
assert check_ban("", []) == "" and check_ban(None, []) == ""
print("test_netguard: OK")
