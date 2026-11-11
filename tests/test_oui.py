"""Testy modułu producentów z adresów MAC (bez sieci i bez prawdziwego rejestru). Uruchom: python tests/test_oui.py"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import oui as O

# --- normalizacja adresów MAC
assert O.normalize("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
assert O.normalize("AABB.CCDD.EEFF") == "AA:BB:CC:DD:EE:FF"
assert O.normalize("aabbccddeeff") == "AA:BB:CC:DD:EE:FF"
assert O.normalize("02:5a:00:00:04:1c") == "02:5A:00:00:04:1C"
assert O.normalize("") is None and O.normalize(None) is None and O.normalize("zz:zz") is None and O.normalize("AA:BB:CC") is None

# --- adresy prywatne (administrowane lokalnie): drugi bit pierwszego bajtu
assert O.is_private("02:00:00:00:00:00") and O.is_private("DA:A1:19:00:00:00") and O.is_private("7E:00:00:00:00:00")
assert not O.is_private("00:00:0C:00:00:00") and not O.is_private("F4:F5:D8:00:00:00") and not O.is_private("garbage")

# --- skracanie nazw
assert O.shorten("Cisco Systems, Inc") == "Cisco Systems"
assert O.shorten("Nokia Shanghai Bell Co., Ltd.") == "Nokia Shanghai Bell"
assert O.shorten("SAMSUNG ELECTRO-MECHANICS CO.,LTD.") == "Samsung Electro-Mechanics"
assert O.shorten("Zebra Technologies Inc.") == "Zebra Technologies"
assert O.shorten("Fiberhome Telecommunication Technologies Co.,LTD") == "Fiberhome Telecommunication Technologies"
assert O.shorten("Apple, Inc.") == "Apple"
assert O.shorten("Hon Hai Precision Ind. Co.,Ltd.") == "Hon Hai Precision Ind"
assert O.shorten("Soliton Technologies Pvt Ltd") == "Soliton Technologies"
assert O.shorten("ZOWEE TECHNOLOGY(HEYUAN)Co.,Ltd") == "Zowee Technology(Heyuan)"
assert O.shorten("IBM") == "IBM"          # krótkie wielkie litery zostają
assert O.shorten("") == ""

# --- parsowanie CSV IEEE: cudzysłowy, przecinki w nazwie, adresy wieloliniowe, śmieci, duplikaty
CSV = ('Registry,Assignment,Organization Name,Organization Address\n'
       'MA-L,286FB9,"Nokia Shanghai Bell Co., Ltd.","No.388 Ning Qiao Road,Jin Qiao"\n'
       'MA-L,E80AB9,"Cisco Systems, Inc","80 West Tasman Drive\nSan Jose CA US"\n'
       'MA-L,9075DE,Zebra Technologies Inc.,ONE ZEBRA PLAZA\n'
       'MA-L,bad,Not A Prefix,x\n'
       'MA-L,00000A,,empty name\n'
       'MA-L,00000C,Cisco Systems  Inc ,x\n')
d = O.parse_ieee_csv(CSV)
assert d == {"286FB9": "Nokia Shanghai Bell Co., Ltd.", "E80AB9": "Cisco Systems, Inc", "9075DE": "Zebra Technologies Inc.",
             "00000C": "Cisco Systems Inc"}, d

# --- rejestr w pamięci
R = O.Registry()
R.set(d)
assert len(R) == 4
assert R.lookup("28:6F:B9:12:34:56") == "Nokia Shanghai Bell"
assert R.lookup("28-6f-b9-12-34-56") == "Nokia Shanghai Bell"
assert R.lookup("E8:0A:B9:00:00:01") == "Cisco Systems"
assert R.lookup("AA:BB:CC:DD:EE:FF") == ""                       # nieznany przedrostek
assert R.lookup("2A:6F:B9:12:34:56") == ""                       # losowy adres (bit lokalny), mimo istniejącego przedrostka 286FB9? (2A != 28)
assert R.lookup("02:6F:B9:12:34:56") == "" and R.lookup("not a mac") == "" and R.lookup("") == ""

# --- pobieranie: lokalny serwer, limit rozmiaru
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = CSV.encode() if self.path == "/oui.csv" else b"x" * 5000
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_port
assert O.parse_ieee_csv(O.download(base + "/oui.csv")) == d
try:
    O.download(base + "/big", max_bytes=1000)
    raise AssertionError("an oversized response must be rejected")
except ValueError:
    pass
srv.shutdown()
dead = HTTPServer(("127.0.0.1", 0), H)
port = dead.server_port
dead.server_close()
try:
    O.download("http://127.0.0.1:%d/" % port, timeout=2)
    raise AssertionError("a connection error must raise")
except OSError:
    pass

print("test_oui: OK")
