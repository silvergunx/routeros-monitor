"""Testy powiadomień (ntfy i webhook) na lokalnym serwerze HTTP. Uruchom: python tests/test_notify.py"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import notify as N

GOT = []
STATUS = {"code": 200}


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        GOT.append({"path": self.path, "auth": self.headers.get("Authorization"), "ctype": self.headers.get("Content-Type"),
                    "json": json.loads(body.decode("utf-8"))})
        self.send_response(STATUS["code"])
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_port
EV = {"app": "routeros-monitor", "kind": "router_offline", "severity": "warning", "title": "Router Salon: brak łączności",
      "message": "Router Salon nie odpowiada od 5 min.", "router": "Salon", "time": "2026-11-10T12:00:00Z"}

# --- walidacja adresów
assert N.valid_url("https://ntfy.sh") and N.valid_url("http://192.168.1.5:8123/api/webhook/x")
assert not N.valid_url("ftp://x") and not N.valid_url("ntfy.sh") and not N.valid_url("") and not N.valid_url("http://")

# --- ntfy: JSON API, UTF-8, priorytet i tag, token jako Bearer
assert N.send_ntfy(base, "moj-temat", EV["title"], EV["message"], "warning", "tk_123") == ""
g = GOT[-1]
assert g["path"] == "/" and g["auth"] == "Bearer tk_123" and "application/json" in g["ctype"]
assert g["json"] == {"topic": "moj-temat", "title": "Router Salon: brak łączności", "message": EV["message"],
                     "priority": 4, "tags": ["warning"]}, g["json"]
N.send_ntfy(base + "/", "t", "a", "b", "critical")  # adres z ukośnikiem na końcu
assert GOT[-1]["json"]["priority"] == 5 and GOT[-1]["auth"] is None and GOT[-1]["path"] == "/"

# --- webhook: całe zdarzenie jako JSON
assert N.send_webhook(base + "/hook/abc", EV) == ""
assert GOT[-1]["path"] == "/hook/abc" and GOT[-1]["json"] == EV

# --- błędy: kod HTTP, brak połączenia, zły adres
STATUS["code"] = 500
assert N.send_webhook(base + "/x", EV) == "webhook: HTTP 500"
STATUS["code"] = 200
dead = HTTPServer(("127.0.0.1", 0), H)
port = dead.server_port
dead.server_close()
assert N.send_webhook("http://127.0.0.1:%d/" % port, EV).startswith("webhook: ")
assert N.send_ntfy("not a url", "t", "a", "b") == "ntfy: invalid address or topic"
assert N.send_ntfy(base, "  ", "a", "b") == "ntfy: invalid address or topic"
assert N.send_webhook("javascript:alert(1)", EV) == "webhook: invalid address"

# --- dispatch: kanały, brak konfiguracji, limit godzinowy
n0 = len(GOT)
assert N.dispatch({}, EV) == ["no channel configured"] and len(GOT) == n0
cfg = {"ntfy_url": base, "ntfy_topic": "t", "hook_url": base + "/h"}
assert N.dispatch(cfg, EV) == [] and len(GOT) == n0 + 2            # oba kanały
assert N.dispatch({"hook_url": base + "/h"}, EV) == [] and len(GOT) == n0 + 3
STATUS["code"] = 500
assert N.dispatch(cfg, EV) == ["ntfy: HTTP 500", "webhook: HTTP 500"]
STATUS["code"] = 200
N._sent[:] = []
for i in range(N.MAX_PER_HOUR):
    assert N.allow_send(now=1000.0 + i)
assert not N.allow_send(now=1000.0 + N.MAX_PER_HOUR)
assert N.dispatch(cfg, EV, force=True) == []                         # test z przycisku omija limit
assert N.allow_send(now=1000.0 + 3700)                               # po godzinie limit się odnawia

srv.shutdown()
print("test_notify: OK")
