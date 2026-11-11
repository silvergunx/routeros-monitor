"""Testy bufora logów aplikacji i wycinania danych wrażliwych. Uruchom: python tests/test_applog.py"""
import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import applog as A

# --- wycinanie danych wrażliwych
s = A.scrub('POST /api/metrics?t=xNWb3nAHXI2bg9SwySFrJvvYzKikdF5W HTTP/1.1 from 10.12.12.13:5000')
assert "xNWb3" not in s and "10.12.12.13" not in s and "t=***" in s and "<ip>" in s, s
assert A.scrub("password=hunter2 ok") == "password=*** ok"
assert A.scrub("token: abcDEF123") == "token: ***", A.scrub("token: abcDEF123")
assert A.scrub("mail admin@example.com done") == "mail <email> done"
assert A.scrub("mac 02:5A:00:00:04:1C x") == "mac <mac> x"
assert A.scrub("key aB3dE5gH7jK9mN1pQ3sT5vX7zA9cE1gH3jL") == "key <secret>"
assert A.scrub("RouterOS 7.20.4 on port 8728") == "RouterOS 7.20.4 on port 8728"  # wersje i porty zostają
assert A.scrub("BAD BODY from Master and admin", {"Master": "router 1", "admin": "user"}) == "BAD BODY from router 1 and user"
assert A.scrub("id ab", {"ab": "x"}) == "id ab"  # za krótkie nazwy pomijane (ryzyko zniszczenia tekstu)
assert A.scrub("administrator admin", {"admin": "user"}) == "administrator user"  # tylko całe słowa
assert A.scrub("secretvalue=abc123 DB_PASSWORD=x") == "secretvalue=*** DB_PASSWORD=***"

# --- print trafia do bufora (po pełnej linii), strumień oryginalny dostaje wszystko
A._buf.clear()
out = io.StringIO()
tee = A._Tee(out)
tee.write("pierwsza linia\nczęść ")
tee.write("druga\n\n")
tee.write("niedokończona")
assert out.getvalue() == "pierwsza linia\nczęść druga\n\nniedokończona"
assert [t for _, t in A._buf] == ["pierwsza linia", "część druga"], list(A._buf)
tee.flush()
A._buf.clear()
A._Tee(io.StringIO()).write("a\nb\nc\n")
assert [t for _, t in A._buf] == ["a\nb\nc"], list(A._buf)  # wieloliniowy komunikat to jeden wpis

# --- logowanie: tylko WARNING i wyżej
A._buf.clear()
lg = logging.getLogger("test.applog")
lg.propagate = False
h = A._Handler()
h.setFormatter(logging.Formatter("%(message)s"))
lg.addHandler(h)
lg.setLevel(logging.DEBUG)
lg.info("informacja")
lg.warning("ostrzeżenie")
try:
    raise ValueError("boom")
except ValueError:
    lg.exception("wyjątek")
texts = [t for _, t in A._buf]
assert len(texts) == 2 and texts[0].startswith("WARNING test.applog: ostrzeżenie"), texts
assert "Traceback" in texts[1] and "ValueError: boom" in texts[1], texts[1]

# --- recent(): limit liczby wpisów i znaków, kolejność od najstarszego
A._buf.clear()
for i in range(10):
    A.add("wpis %d" % i)
assert [t for _, t in A.recent(3)] == ["wpis 7", "wpis 8", "wpis 9"]
A._buf.clear()
for i in range(5):
    A.add("x" * 100)
assert len(A.recent(10, max_chars=250)) == 2  # 2 wpisy po 100 znaków mieszczą się w 250
A.add("y" * 5000)
assert len(A._buf[-1][1]) == A.MAX_ENTRY_CHARS  # pojedynczy wpis jest przycinany

# --- filtr logów dostępu uvicorn maskuje token routera (t=...) w adresie
acc = logging.getLogger("test.access")
acc.propagate = False
acc.setLevel(logging.INFO)
seen = []


class Cap(logging.Handler):
    def emit(self, record):
        seen.append(self.format(record))


cap = Cap()
cap.setFormatter(logging.Formatter("%(message)s"))
acc.addHandler(cap)
acc.addFilter(A.MaskTokens())
FMT = '%s - "%s %s HTTP/%s" %d'
acc.info(FMT, "10.0.10.1:0", "POST", "/api/metrics?t=xNWb3nAHXI2bg9SwySFrJvvYzKikdF5W&cv=2", "1.1", 200)
acc.info(FMT, "10.0.10.1:0", "POST", "/api/inventory?t=U7mPabV25OivKZKqhb1ODaK0MW_CJ2LO", "1.1", 200)
acc.info(FMT, "10.0.10.19:0", "GET", "/api/blacklist.rsc?list=blacklist&t=SECRETtoken123", "1.1", 200)
acc.info(FMT, "10.0.10.19:0", "GET", "/routers/1?tab=logs", "1.1", 200)   # parametr "tab" to nie token
acc.info(FMT, "10.0.10.19:0", "GET", "/login", "1.1", 200)
acc.info("plain message with ?t=ABC123 inside")
assert seen[0] == '10.0.10.1:0 - "POST /api/metrics?t=***&cv=2 HTTP/1.1" 200', seen[0]
assert seen[1] == '10.0.10.1:0 - "POST /api/inventory?t=*** HTTP/1.1" 200', seen[1]
assert seen[2] == '10.0.10.19:0 - "GET /api/blacklist.rsc?list=blacklist&t=*** HTTP/1.1" 200', seen[2]
assert seen[3] == '10.0.10.19:0 - "GET /routers/1?tab=logs HTTP/1.1" 200', seen[3]
assert seen[4] == '10.0.10.19:0 - "GET /login HTTP/1.1" 200', seen[4]
assert seen[5] == "plain message with ?t=*** inside", seen[5]
assert not any("xNWb3" in s or "U7mPab" in s or "SECRETtoken" in s for s in seen)

print("test_applog: OK")
