import unicodedata
import platform
import collections
import statistics
import os, re, csv, io, json, math, asyncio, socket, hashlib, hmac, secrets, time, ipaddress, datetime as dt
from urllib.parse import quote, urlparse, urlencode
import i18n
import version as appver
import speedengines
import netguard
import backups as backuplib
import applog
import notify
import httpx
from fastapi import FastAPI, Request, Form, Depends, HTTPException, Body
from fastapi.responses import JSONResponse, RedirectResponse, PlainTextResponse, Response, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.concurrency import run_in_threadpool
from sqlalchemy.engine import URL
from sqlalchemy import inspect as sa_inspect, extract, create_engine, Date, Text, UniqueConstraint, String, Float, DateTime, Integer, Boolean, BigInteger, ForeignKey, Index, select, delete, func, or_, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

applog.install()  # bufor ostatnich ostrzeżeń i błędów (raport „Zgłoś problem”)
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
SECRET_KEY = os.environ["SECRET_KEY"]
_EXAMPLES = {"zmien_to_haslo", "wygeneruj_dlugi_losowy_ciag", ""}
if ADMIN_PASSWORD in _EXAMPLES or SECRET_KEY in _EXAMPLES or len(SECRET_KEY) < 16:
    raise SystemExit("BLAD KONFIGURACJI: ustaw w pliku .env wlasne ADMIN_PASSWORD i SECRET_KEY "
                     "(SECRET_KEY min. 16 znakow, np. openssl rand -hex 32), potem: docker compose up -d")
RETENTION = int(os.getenv("RETENTION_DAYS", "30"))
IFACE_RETENTION = max(1, int(os.getenv("IFACE_RETENTION_DAYS", "7")))  # pomiary interfejsów to największa tabela
CADDY = os.getenv("CADDY_ADMIN", "http://caddy:2019")
if os.getenv("DB_PASSWORD"):
    DB_URL = URL.create("postgresql+psycopg2", username="monitor", password=os.environ["DB_PASSWORD"],
                        host=os.getenv("DB_HOST", "db"), database="monitor")
else:
    DB_URL = os.environ["DATABASE_URL"]
engine = create_engine(DB_URL, pool_pre_ping=True, pool_size=10, max_overflow=10)  # niezależne zadania w tle + żądania WWW
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400 * 7)
templates = Jinja2Templates(directory="templates")
templates.env.globals["t"] = i18n.t
tr = i18n._


def L(v):
    """Stała z poziomu modułu: klucz tłumaczenia (an.NNN) -> tekst w języku żądania; inne wartości bez zmian."""
    return tr(v) if isinstance(v, str) and v.startswith("an.") else v

templates.env.globals["th"] = i18n.th
templates.env.globals["tn"] = i18n.tn
templates.env.globals["app_version"] = appver.current()
templates.env.globals["update_info"] = appver.update_info
templates.env.globals["languages"] = i18n.languages


@app.middleware("http")
async def set_lang(request: Request, call_next):
    request.state.lang = i18n.pick_lang(request)
    i18n.CURRENT.set(request.state.lang)
    return await call_next(request)


@app.get("/flag/{code}.svg")
def flag(code: str):
    f = i18n.DIR / f"{code}.svg"
    if code not in i18n.LOCALES or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/lang/{code}")
def set_language(code: str, request: Request):
    back = request.headers.get("referer", "/")
    path = urlparse(back).path or "/"
    r = RedirectResponse(path if path.startswith("/") and not path.startswith("//") else "/", 303)
    if code in i18n.LOCALES:
        r.set_cookie(i18n.COOKIE, code, max_age=365 * 86400, samesite="lax", httponly=True)
    return r


def fm(v, unit="", d=0):
    return "-" if v is None else "%.*f%s" % (d, v, unit)


templates.env.globals["fm"] = fm
templates.env.filters["iso"] = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S") if d else ""
templates.env.globals["ago"] = lambda d: _age((now() - d).total_seconds()) if d else ""  # np. "5 min", "2 h", "3 d"


def now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


# Status routera zależy od jego zwykłego odstępu między pomiarami (mierzonego na bieżąco z ostatnich pomiarów; do czasu
# zebrania próbek używamy interwału z ustawień):
#   "brak odpowiedzi" (żółty) po: odstęp + odstęp/5 + 1 s   (5 s -> 7 s, 10 s -> 13 s, 15 s -> 19 s, 60 s -> 73 s)
#   "offline" (czerwony) po:      czas "brak odpowiedzi" x mnożnik z ustawień (domyślnie 1,5)
# Użytkownik może dla każdego routera wpisać własne progi (w sekundach, bez górnego limitu). Jedyne dolne granice:
# "brak odpowiedzi" nie wcześniej niż zmierzony odstęp + 1 s, "offline" nie wcześniej niż "brak odpowiedzi" + 1 s.
_GAPS = {}             # id routera -> ostatnie odstępy (s) między kolejnymi pomiarami
_SEEN = set()          # id routerów, które przysłały pomiar od startu aplikacji (po starcie oceniamy tylko je od razu)
_INTERVAL_S = [60]     # interwał monitoringu z ustawień (odświeżany w interval())
_OFFLINE_MULT = [1.5]  # mnożnik czasu "brak odpowiedzi" dający próg offline (odświeżany w interval())
_THR = {}              # id routera -> {"nr": własny próg "brak odpowiedzi" (s) albo None, "off": własny próg offline albo None}


def reporting_gap(rid):
    """Zmierzony typowy odstęp między pomiarami routera (s, ułamek) albo None, gdy próbek jest mniej niż trzy."""
    g = _GAPS.get(rid)
    return statistics.median(g) if g and len(g) >= 3 else None


def _gap(rid):
    return reporting_gap(rid) or _INTERVAL_S[0]


def auto_no_response(rid):
    return _gap(rid) * 1.2 + 1


def auto_offline(rid):
    """Automatyczny próg offline; bez własnych próbek (tuż po starcie) minimum 90 s, żeby restart nie robił z routerów „offline”."""
    t = no_response_after(rid) * _OFFLINE_MULT[0]
    return max(t, 90) if reporting_gap(rid) is None else t


def no_response_after(rid):
    """Po ilu sekundach bez pomiaru router ma status „brak odpowiedzi”: własny próg albo automatyczny, nie mniej niż odstęp + 1 s."""
    own = _THR.get(rid, {}).get("nr")
    return max(own if own is not None else auto_no_response(rid), _gap(rid) + 1)


def online_after(rid):
    """Po ilu sekundach bez pomiaru router jest offline: własny próg albo automatyczny, nie mniej niż „brak odpowiedzi” + 1 s."""
    own = _THR.get(rid, {}).get("off")
    return max(own if own is not None else auto_offline(rid), no_response_after(rid) + 1)


def router_thresholds(s):
    """Własne progi routerów z ustawień ({id: {"nr":…, "off":…}}); błędne wpisy są pomijane."""
    out = {}
    try:
        raw = json.loads(sget(s, "router_thr", "{}") or "{}")
    except ValueError:
        return out
    if isinstance(raw, dict):
        for k, v in raw.items():
            if str(k).isdigit() and isinstance(v, dict):
                nr, off = v.get("nr"), v.get("off")
                out[int(k)] = {"nr": float(nr) if isinstance(nr, (int, float)) and nr >= 1 else None,
                               "off": float(off) if isinstance(off, (int, float)) and off >= 1 else None}
    return out


class Base(DeclarativeBase):
    pass


class Router(Base):
    __tablename__ = "routers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    token: Mapped[str] = mapped_column(String(64), unique=True)
    ident: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ver: Mapped[str | None] = mapped_column(String(40), nullable=True)
    uptime: Mapped[str | None] = mapped_column(String(40), nullable=True)
    wan: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_seen: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    pos: Mapped[int | None] = mapped_column(Integer, nullable=True)  # kolejność na liście
    log_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)  # adres, z którego router wysyła syslog
    log_ip_fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    ping_target: Mapped[str | None] = mapped_column(String(64), nullable=True)
    edge: Mapped[bool] = mapped_column(Boolean, default=False)  # router brzegowy: mierzy internet i prędkość
    nw_state: Mapped[str | None] = mapped_column(Text, nullable=True)  # ostatnie wyniki sond Netwatch (JSON)
    live_until: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)  # tryb ustawiania sieci

    @property
    def live(self):
        return bool(self.live_until and self.live_until > now())
    iface_types: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON {nazwa: typ RouterOS}

    @property
    def online(self):
        return bool(self.last_seen) and (now() - self.last_seen).total_seconds() < online_after(self.id)

    @property
    def no_response(self):
        """Router jeszcze nie jest offline, ale spóźnia się z pomiarem (żółty status „brak odpowiedzi”)."""
        return self.online and (now() - self.last_seen).total_seconds() >= no_response_after(self.id)


class Metric(Base):
    __tablename__ = "metrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("routers.id"))
    ts: Mapped[dt.datetime] = mapped_column(DateTime)
    cpu: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem: Mapped[float | None] = mapped_column(Float, nullable=True)
    temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    conns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rx: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tx: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rx_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    tx_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    dhcp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ping_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    inet_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    inet_rtt: Mapped[float | None] = mapped_column(Float, nullable=True)
    inet_jit: Mapped[float | None] = mapped_column(Float, nullable=True)
    inet_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    gw_rtt: Mapped[float | None] = mapped_column(Float, nullable=True)
    gw_jit: Mapped[float | None] = mapped_column(Float, nullable=True)
    gw_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    dns_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    http_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    dns_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    http_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    __table_args__ = (Index("ix_m_r_ts", "router_id", "ts"),)

    @property
    def rx_mbps(self):
        return None if self.rx_bps is None else self.rx_bps / 1e6

    @property
    def tx_mbps(self):
        return None if self.tx_bps is None else self.tx_bps / 1e6


class IfaceMetric(Base):
    __tablename__ = "iface_metrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("routers.id"))
    ts: Mapped[dt.datetime] = mapped_column(DateTime)
    name: Mapped[str] = mapped_column(String(40))
    rx: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tx: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rx_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    tx_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    __table_args__ = (Index("ix_if_r_n_ts", "router_id", "name", "ts"), Index("ix_if_r_ts", "router_id", "ts"))

    @property
    def rx_mbps(self):
        return None if self.rx_bps is None else self.rx_bps / 1e6

    @property
    def tx_mbps(self):
        return None if self.tx_bps is None else self.tx_bps / 1e6


class AuditLog(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime)
    action: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(String(250), default="")
    who: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Inv(Base):
    """Dane „inwentarzowe” z routera: dzierżawy DHCP, klienci Wi-Fi, peery WireGuard, sesje PPP."""
    __tablename__ = "inventory"
    id: Mapped[int] = mapped_column(primary_key=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("routers.id"))
    kind: Mapped[str] = mapped_column(String(10))
    key: Mapped[str] = mapped_column(String(100))
    data: Mapped[str] = mapped_column(Text, default="{}")
    seq: Mapped[str] = mapped_column(String(20), default="")
    updated: Mapped[dt.datetime] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("router_id", "kind", "key", name="uq_inv"),)


class LogEntry(Base):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("routers.id"))
    ts: Mapped[dt.datetime] = mapped_column(DateTime)
    sev: Mapped[int] = mapped_column(Integer, default=6)  # 0-2 krytyczny, 3 błąd, 4 ostrzeżenie, 5-6 info, 7 debug
    topics: Mapped[str] = mapped_column(String(100), default="")
    msg: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (Index("ix_logs_r_ts", "router_id", "ts"), Index("ix_logs_r_sev_ts", "router_id", "sev", "ts"))


class LiveSpot(Base):
    """Zapisany pomiar miejsca w trybie ustawiania (np. 'Salon': średni sygnał i jakość)."""
    __tablename__ = "live_spots"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime)
    mac: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(60))
    device: Mapped[str] = mapped_column(String(80), default="")
    iface: Mapped[str] = mapped_column(String(40), default="")
    signal: Mapped[float | None] = mapped_column(Float, nullable=True)
    rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SpeedTest(Base):
    __tablename__ = "speed_tests"
    id: Mapped[int] = mapped_column(primary_key=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("routers.id"))
    ts: Mapped[dt.datetime] = mapped_column(DateTime)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    down_mbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    secs: Mapped[float | None] = mapped_column(Float, nullable=True)
    up_mbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    ping_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(10), nullable=True)  # server / router / ookla
    jitter_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    server: Mapped[str | None] = mapped_column(String(120), nullable=True)
    url: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    __table_args__ = (Index("ix_spd_r_ts", "router_id", "ts"),)


class TrafficDay(Base):
    """Dzienny transfer interfejsu WAN (przechowywany dłużej niż surowe metryki)."""
    __tablename__ = "traffic_days"
    id: Mapped[int] = mapped_column(primary_key=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("routers.id"))
    day: Mapped[dt.date] = mapped_column(Date)
    iface: Mapped[str] = mapped_column(String(40), default="")
    rx: Mapped[int] = mapped_column(BigInteger, default=0)
    tx: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (UniqueConstraint("router_id", "day", name="uq_traffic_day"),)


class ClientStat(Base):
    """Liczba klientów w czasie (zapisywana co minutę z danych inwentarza)."""
    __tablename__ = "client_stats"
    id: Mapped[int] = mapped_column(primary_key=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("routers.id"))
    ts: Mapped[dt.datetime] = mapped_column(DateTime)
    dev_on: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dev_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wifi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vpn_on: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (Index("ix_cs_r_ts", "router_id", "ts"),)


ROLES = {"admin": "administrator", "viewer": "tylko podgląd"}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    pw: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(10), default="viewer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    ver: Mapped[int] = mapped_column(Integer, default=1)  # zmiana hasła/roli wylogowuje stare sesje
    prefs: Mapped[str | None] = mapped_column(Text, nullable=True)  # ustawienia widoku (JSON)
    created: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_login: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def is_admin(self):
        return self.role == "admin"


class Whitelist(Base):
    __tablename__ = "whitelist"
    id: Mapped[int] = mapped_column(primary_key=True)
    ip: Mapped[str] = mapped_column(String(255))
    comment: Mapped[str] = mapped_column(String(60), default="")
    expires: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    router_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(5), default="white", server_default="white")  # white = whitelista, black = blacklista


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")  # TEXT: np. wynik wyboru serwera LibreSpeed ma kilkaset znaków


MIGRATIONS = [
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS dhcp INTEGER",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS ping_ms DOUBLE PRECISION",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS loss DOUBLE PRECISION",
    "ALTER TABLE whitelist ADD COLUMN IF NOT EXISTS router_id INTEGER",
    "ALTER TABLE whitelist ADD COLUMN IF NOT EXISTS kind VARCHAR(5) NOT NULL DEFAULT 'white'",
    "ALTER TABLE settings ALTER COLUMN value TYPE TEXT",
    "ALTER TABLE routers ADD COLUMN IF NOT EXISTS wan VARCHAR(40)",
    "ALTER TABLE whitelist ALTER COLUMN ip TYPE VARCHAR(255)",
    "ALTER TABLE audit ADD COLUMN IF NOT EXISTS who VARCHAR(40)",
    "ALTER TABLE routers ADD COLUMN IF NOT EXISTS pos INTEGER",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS prefs TEXT",
    "ALTER TABLE routers ADD COLUMN IF NOT EXISTS log_ip VARCHAR(45)",
    "ALTER TABLE routers ADD COLUMN IF NOT EXISTS log_ip_fixed BOOLEAN DEFAULT FALSE",
    "ALTER TABLE routers ADD COLUMN IF NOT EXISTS ping_target VARCHAR(64)",
    "ALTER TABLE routers ADD COLUMN IF NOT EXISTS edge BOOLEAN DEFAULT FALSE",
    "ALTER TABLE routers ADD COLUMN IF NOT EXISTS nw_state TEXT",
    "ALTER TABLE routers ADD COLUMN IF NOT EXISTS live_until TIMESTAMP",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS dns_up BOOLEAN",
    "ALTER TABLE speed_tests ADD COLUMN IF NOT EXISTS up_mbps DOUBLE PRECISION",
    "ALTER TABLE speed_tests ADD COLUMN IF NOT EXISTS ping_ms DOUBLE PRECISION",
    "ALTER TABLE speed_tests ADD COLUMN IF NOT EXISTS source VARCHAR(10)",
    "ALTER TABLE speed_tests ADD COLUMN IF NOT EXISTS jitter_ms DOUBLE PRECISION",
    "ALTER TABLE speed_tests ADD COLUMN IF NOT EXISTS loss DOUBLE PRECISION",
    "ALTER TABLE speed_tests ADD COLUMN IF NOT EXISTS server VARCHAR(120)",
    "ALTER TABLE speed_tests ADD COLUMN IF NOT EXISTS url VARCHAR(200)",
    "ALTER TABLE speed_tests ADD COLUMN IF NOT EXISTS error VARCHAR(200)",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS http_up BOOLEAN",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS inet_up BOOLEAN",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS inet_rtt DOUBLE PRECISION",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS inet_jit DOUBLE PRECISION",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS inet_loss DOUBLE PRECISION",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS gw_rtt DOUBLE PRECISION",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS gw_jit DOUBLE PRECISION",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS gw_loss DOUBLE PRECISION",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS dns_ms DOUBLE PRECISION",
    "ALTER TABLE metrics ADD COLUMN IF NOT EXISTS http_ms DOUBLE PRECISION",
    "ALTER TABLE routers ADD COLUMN IF NOT EXISTS iface_types TEXT",
]
# Poprawki danych wykonywane RAZ (znacznik w tabeli settings); wcześniej szły przy każdym starcie i czytały całą tabelę metrics.
ONCE_MIGRATIONS = [
    ("migr_metrics_clamp", ["UPDATE metrics SET mem = NULL WHERE mem < 0 OR mem > 100",
                            "UPDATE metrics SET cpu = NULL WHERE cpu < 0 OR cpu > 100"]),
]
_ADD_COL = re.compile(r"^ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+) ", re.I)
_COL_TYPE = re.compile(r"^ALTER TABLE (\w+) ALTER COLUMN (\w+) TYPE (\w+)(?:\((\d+)\))?$", re.I)


def migration_needed(insp, stmt):
    """Czy komenda migracji coś zmieni? ALTER TABLE zawsze bierze blokadę wyłączną (czeka m.in. na trwającą kopię pg_dump),
    więc wykonujemy ją tylko wtedy, gdy kolumny brakuje albo ma inny typ. Nieznana postać komendy = wykonaj."""
    m = _ADD_COL.match(stmt)
    if m:
        return m.group(2) not in {c["name"] for c in insp.get_columns(m.group(1))}
    m = _COL_TYPE.match(stmt)
    if m:
        col = next((c for c in insp.get_columns(m.group(1)) if c["name"] == m.group(2)), None)
        if col is None:
            return True
        t, want = col["type"], m.group(3).upper()
        if want == "TEXT":
            return not isinstance(t, Text)
        if want == "VARCHAR" and m.group(4):
            return not (isinstance(t, String) and not isinstance(t, Text) and getattr(t, "length", None) == int(m.group(4)))
    return True


def apply_migrations(c):
    insp = sa_inspect(c)
    for stmt in MIGRATIONS:
        if migration_needed(insp, stmt):
            c.execute(text(stmt))
            insp.clear_cache()
    for key, stmts in ONCE_MIGRATIONS:
        if not c.execute(text('SELECT 1 FROM settings WHERE "key" = :k'), {"k": key}).first():
            for st in stmts:
                c.execute(text(st))
            c.execute(text('INSERT INTO settings ("key", value) VALUES (:k, \'1\')'), {"k": key})


@app.on_event("startup")
def start():
    err = None
    for _ in range(30):
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as c:
                if engine.dialect.name == "postgresql":
                    c.execute(text("SET LOCAL lock_timeout = '15s'"))  # nie wisi bez końca na trwającej kopii; pętla ponawia
                apply_migrations(c)
            with Session(engine) as s:
                if not s.scalar(select(func.count(User.id))):
                    s.add(User(username=ADMIN_USER[:40], pw=hash_pw(ADMIN_PASSWORD), role="admin", created=now()))
                    s.add(AuditLog(ts=now(), action="użytkownik+", detail="%s (admin, z pliku .env)" % ADMIN_USER,
                                   who="system"))
                    s.commit()
            return
        except Exception as e:
            err = e
            time.sleep(1)
    raise RuntimeError("Brak polaczenia z baza danych: %s" % err)


def db():
    with Session(engine) as s:
        yield s


class NeedLogin(Exception):
    pass


def hash_pw(p, it=200_000):
    salt = secrets.token_bytes(16)
    return "pbkdf2$%d$%s$%s" % (it, salt.hex(), hashlib.pbkdf2_hmac("sha256", p.encode(), salt, it).hex())


def check_pw(p, stored):
    try:
        _, it, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(salt), int(it)).hex()
        return hmac.compare_digest(calc, h)
    except Exception:
        return False


_PANEL_IPS = {}  # adres -> czas ostatniego zalogowanego żądania do panelu (auto-ban nigdy nie blokuje adresów, z których ostatnio korzystano)


def user(request: Request, s: Session = Depends(db)):
    uid = request.session.get("uid")
    u = s.get(User, uid) if isinstance(uid, int) else None
    if not u or not u.active or request.session.get("v") != u.ver:
        request.session.clear()
        raise NeedLogin()
    request.state.user = u
    if request.client and request.client.host:
        _PANEL_IPS[request.client.host] = time.time()
    s.info["who"] = u.username
    return u


def admin(u: User = Depends(user)):
    if not u.is_admin:
        raise HTTPException(403, tr("err.admin_required"))
    return u


@app.exception_handler(NeedLogin)
async def _need_login(request, exc):
    return RedirectResponse("/login", 303)


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def sget(s, k, d=""):
    o = s.get(Setting, k)
    return o.value if o else d


def sset(s, k, v):
    o = s.get(Setting, k)
    if o:
        o.value = v
    else:
        s.add(Setting(key=k, value=v))


def log(s, action, detail=""):
    s.add(AuditLog(ts=now(), action=action[:40], detail=detail[:250], who=s.info.get("who", "system")))


# ---------- login ----------
@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"err": False})


@app.post("/login")
def login(request: Request, username: str = Form(), password: str = Form(), s: Session = Depends(db)):
    u = s.scalar(select(User).where(User.username == username.strip()))
    if u and u.active and check_pw(password, u.pw):
        request.session.clear()
        request.session["uid"], request.session["v"] = u.id, u.ver
        u.last_login = now()
        s.info["who"] = u.username
        log(s, "logowanie", u.username)
        s.commit()
        return RedirectResponse("/", 303)
    if not u:
        check_pw(password, hash_pw("x", 200_000))  # podobny czas odpowiedzi dla nieistniejącego loginu
    time.sleep(1.5)
    return templates.TemplateResponse(request, "login.html", {"err": True}, status_code=401)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)


# ---------- routers ----------
def wan_info(s, r):
    """(interface names, chosen WAN name, latest IfaceMetric of WAN)"""
    last = s.scalar(select(func.max(IfaceMetric.ts)).where(IfaceMetric.router_id == r.id))
    if not last:
        return [], r.wan or "", None
    by = {x.name: x for x in s.scalars(select(IfaceMetric).where(IfaceMetric.router_id == r.id,
                                                                 IfaceMetric.ts == last))}
    if r.wan in by:
        wan = r.wan
    elif "ether1" in by:
        wan = "ether1"
    else:
        wan = max(by.values(), key=lambda x: (x.rx or 0) + (x.tx or 0)).name
    return sorted(by), wan, by[wan]


@app.get("/", dependencies=[Depends(user)])
def index(request: Request, s: Session = Depends(db)):
    routers = ordered_routers(s)
    latest = {r.id: s.scalar(select(Metric).where(Metric.router_id == r.id).order_by(Metric.ts.desc()).limit(1))
              for r in routers}
    return templates.TemplateResponse(request, "routers.html", {"routers": routers, "latest": latest,
                                                              "refresh": max(interval(s), 5),
                                                              "wans": {r.id: wan_info(s, r)[2] for r in routers},
                                                              "invs": {r.id: inventory_view(s, r) for r in routers},
                                                              "upds": {r.id: update_available(r) for r in routers},
                                                              "stale": {r.id: script_stale(r) for r in routers} if request.state.user.is_admin else {},
                                                              "sis": {r.id: sys_info(s, r) for r in routers},
                                                              "lcs": {r.id: unread_counts(s, request.state.user, r.id)
                                                                      for r in routers}})


@app.post("/routers", dependencies=[Depends(admin)])
def add_router(name: str = Form(), edge: str = Form(""), s: Session = Depends(db)):
    if not name.strip():
        return RedirectResponse("/", 303)
    r = Router(name=name.strip()[:80], token=secrets.token_urlsafe(24), edge=edge == "1")
    s.add(r)
    log(s, "router+", "%s%s" % (name.strip()[:80], " (brzegowy)" if r.edge else ""))
    s.commit()
    return RedirectResponse("/routers/%d#cfg" % r.id, 303)


def q(text):
    """Encode text for a RouterOS double-quoted string (hex-escape special chars)."""
    out = []
    for c in text:
        if c in '\\"$[]':
            out.append("\\%02X" % ord(c))
        elif c == "\n":
            out.append("\\n")
        else:
            out.append(c)
    return "".join(out)


# Wersja skryptów na routerze. Zwiększ ją TYLKO wtedy, gdy zmiana skryptów wymaga ponownego wklejenia komendy konfiguracyjnej:
# panel pokazuje wtedy administratorowi, że skrypt routera jest nieaktualny. Router podaje swoją wersję w każdym zapytaniu (cv).
SCRIPT_VERSION = 1
_ROUTER_CV = {}  # id routera -> wersja skryptu zgłoszona w ostatnim zapytaniu (0 = skrypt bez znacznika wersji); po restarcie pusto do pierwszego pomiaru


def script_stale(r):
    cv = _ROUTER_CV.get(r.id)
    return cv is not None and cv < SCRIPT_VERSION


MON = r'''
:if ([:len [/system script job find where script="app-monitor"]] <= 1) do={
  :local cpu [/system resource get cpu-load]
  :local tm [/system resource get total-memory]
  :local fm [/system resource get free-memory]
  :local up [/system resource get uptime]
  :local ver [/system resource get version]
  :local id [/system identity get name]
  :global appTemp "null"
  :set appTemp "null"
  :do {
    :local f [:parse ":global appTemp; :foreach h in=\5B/system health find where name~\"temperature\"\5D do={:if (\$appTemp = \"null\") do={:set appTemp \5B/system health get \$h value\5D}}"]
    $f
  } on-error={}
  :if ($appTemp = "null") do={:do {:local f [:parse ":global appTemp; :set appTemp \5B/system health get temperature\5D"]; $f} on-error={}}
  :if ($appTemp = "null") do={:do {:local f [:parse ":global appTemp; :set appTemp \5B/system health get cpu-temperature\5D"]; $f} on-error={}}
  :local temp $appTemp
  :if ([:len $temp] = 0) do={:set temp "null"}
  :local conns "null"
  :do {:set conns [/ip firewall connection tracking get total-entries]} on-error={}
  :local dhcp "null"
  :do {:set dhcp [:len [/ip dhcp-server lease find where status=bound]]} on-error={}
  :local ifs ""
  :foreach i in=[/interface find where running] do={
    :do {
      :local n [/interface get $i name]
      :local irx [/interface get $i rx-byte]
      :local itx [/interface get $i tx-byte]
      :local ity ""
      :do {:set ity [/interface get $i type]} on-error={}
      :if ([:len $ifs] > 0) do={:set ifs ($ifs . ",")}
      :set ifs ($ifs . "{\"n\":\"$n\",\"rx\":$irx,\"tx\":$itx,\"y\":\"$ity\"}")
    } on-error={}
  }
  :local nw ""
  :do {
    :foreach n in=[/tool netwatch find where comment~"^app-nw:"] do={
      :do {
        :local a [/tool netwatch get $n]
        :local o ""
        :foreach k,v in=$a do={
          :if ($k ~ "^(comment|host|status|type|since)\$" || $k ~ "(rtt|loss|time|code)") do={
            :set o ($o . ",\"" . $k . "\":\"" . [:tostr $v] . "\"")
          }
        }
        :if ([:len $o] > 0) do={
          :if ([:len $nw] > 0) do={:set nw ($nw . ",")}
          :set nw ($nw . "{" . [:pick $o 1 [:len $o]] . "}")
        }
      } on-error={}
    }
  } on-error={}
  :local j "{\"id\":\"$id\",\"ver\":\"$ver\",\"up\":\"$up\",\"cpu\":$cpu,\"tm\":$tm,\"fm\":$fm,\"temp\":$temp,\"conns\":$conns,\"dhcp\":$dhcp,\"nw\":\5B$nw\5D,\"ifs\":\5B$ifs\5D}"
  :local resp ""
  :do {:set resp ([/tool fetch url="@URL@/api/metrics?t=@TOKEN@&cv=@CV@" http-method=post http-data=$j http-header-field="Content-Type: application/json" output=user as-value]->"data")} on-error={
    :delay 3s
    :do {:set resp ([/tool fetch url="@URL@/api/metrics?t=@TOKEN@&cv=@CV@" http-method=post http-data=$j http-header-field="Content-Type: application/json" output=user as-value]->"data")} on-error={:log warning "app-monitor: brak polaczenia z serwerem aplikacji"}
  }
  :if ($resp ~ "\"live\":1") do={
    :if ([:len [/system script job find where script="app-live"]] = 0) do={:execute script="/system script run app-live"}
  }
}
'''

INV_DHCP = '\n:local url "@URL@/api/inventory?t=@TOKEN@"\n:local seq [:tostr [:rndnum from=100000 to=999999999]]\n:local esc do={\n  :local o ""\n  :if ([:len $s] > 0) do={\n    :for k from=0 to=([:len $s] - 1) do={\n      :local ch [:pick $s $k]\n      :if ($ch = "\\"" || $ch = "\\\\") do={:set o ($o . "\\\\" . $ch)} else={\n        :if ($ch = "\\n" || $ch = "\\r" || $ch = "\\t") do={:set o ($o . " ")} else={:set o ($o . $ch)}\n      }\n    }\n  }\n  :return $o\n}\n:local send do={\n  :do {/tool fetch url=$u http-method=post http-data=$d http-header-field="Content-Type: application/json" output=none} on-error={\n    :delay 5s\n    /tool fetch url=$u http-method=post http-data=$d http-header-field="Content-Type: application/json" output=none\n  }\n}\n\n:local buf ""\n:foreach i in=[/ip dhcp-server lease find] do={\n  :do {\n    :local m [/ip dhcp-server lease get $i mac-address]\n    :local a [/ip dhcp-server lease get $i address]\n    :local hr [/ip dhcp-server lease get $i host-name]\n    :local h [$esc s=$hr]\n    :local cr [/ip dhcp-server lease get $i comment]\n    :local c [$esc s=$cr]\n    :local st [/ip dhcp-server lease get $i status]\n    :local ls [/ip dhcp-server lease get $i last-seen]\n    :local dy [/ip dhcp-server lease get $i dynamic]\n    :local arp ""\n    :local ai [/ip arp find where mac-address=$m]\n    :if ([:len $ai] > 0) do={:set arp [/ip arp get ($ai->0) status]}\n    :local bh 0\n    :do {:set bh [:len [/interface bridge host find where mac-address=$m]]} on-error={}\n    :if ([:len $buf] > 0) do={:set buf ($buf . ",")}\n    :set buf ($buf . "{\\"key\\":\\"$m\\",\\"ip\\":\\"$a\\",\\"host\\":\\"$h\\",\\"comment\\":\\"$c\\",\\"status\\":\\"$st\\",\\"last\\":\\"$ls\\",\\"dyn\\":\\"$dy\\",\\"arp\\":\\"$arp\\",\\"bh\\":\\"$bh\\"}")\n  } on-error={}\n  :if ([:len $buf] > 3000) do={\n    $send u=$url d=("{\\"k\\":\\"dhcp\\",\\"seq\\":\\"$seq\\",\\"done\\":false,\\"items\\":\\5B" . $buf . "\\5D}")\n    :set buf ""\n  }\n}\n$send u=$url d=("{\\"k\\":\\"dhcp\\",\\"seq\\":\\"$seq\\",\\"done\\":true,\\"items\\":\\5B" . $buf . "\\5D}")'
INV_WIFI = '\n:local url "@URL@/api/inventory?t=@TOKEN@"\n:local seq [:tostr [:rndnum from=100000 to=999999999]]\n:local esc do={\n  :local o ""\n  :if ([:len $s] > 0) do={\n    :for k from=0 to=([:len $s] - 1) do={\n      :local ch [:pick $s $k]\n      :if ($ch = "\\"" || $ch = "\\\\") do={:set o ($o . "\\\\" . $ch)} else={\n        :if ($ch = "\\n" || $ch = "\\r" || $ch = "\\t") do={:set o ($o . " ")} else={:set o ($o . $ch)}\n      }\n    }\n  }\n  :return $o\n}\n:local send do={\n  :do {/tool fetch url=$u http-method=post http-data=$d http-header-field="Content-Type: application/json" output=none} on-error={\n    :delay 5s\n    /tool fetch url=$u http-method=post http-data=$d http-header-field="Content-Type: application/json" output=none\n  }\n}\n\n:local buf ""\n:foreach i in=[/interface wifi registration-table find] do={\n  :do {\n    :local a [/interface wifi registration-table get $i]\n    :local o ""\n    :foreach k,v in=$a do={\n      :if ($k ~ "^(interface|ssid|signal|band|uptime|last-ip|tx-ccq|signal-to-noise)\\$" || $k ~ "(rate|snr|noise|mcs|width|stream|strength)") do={\n        :local vs [$esc s=[:tostr $v]]\n        :set o ($o . ",\\"" . $k . "\\":\\"" . $vs . "\\"")\n      }\n    }\n    :local mac [/interface wifi registration-table get $i mac-address]\n    :if ([:len $buf] > 0) do={:set buf ($buf . ",")}\n    :set buf ($buf . "{\\"key\\":\\"" . $mac . "\\"" . $o . "}")\n  } on-error={}\n  :if ([:len $buf] > 3000) do={\n    $send u=$url d=("{\\"k\\":\\"wifi\\",\\"seq\\":\\"$seq\\",\\"done\\":false,\\"items\\":\\5B" . $buf . "\\5D}")\n    :set buf ""\n  }\n}\n$send u=$url d=("{\\"k\\":\\"wifi\\",\\"seq\\":\\"$seq\\",\\"done\\":true,\\"items\\":\\5B" . $buf . "\\5D}")'
INV_WIRELESS = '\n:local url "@URL@/api/inventory?t=@TOKEN@"\n:local seq [:tostr [:rndnum from=100000 to=999999999]]\n:local esc do={\n  :local o ""\n  :if ([:len $s] > 0) do={\n    :for k from=0 to=([:len $s] - 1) do={\n      :local ch [:pick $s $k]\n      :if ($ch = "\\"" || $ch = "\\\\") do={:set o ($o . "\\\\" . $ch)} else={\n        :if ($ch = "\\n" || $ch = "\\r" || $ch = "\\t") do={:set o ($o . " ")} else={:set o ($o . $ch)}\n      }\n    }\n  }\n  :return $o\n}\n:local send do={\n  :do {/tool fetch url=$u http-method=post http-data=$d http-header-field="Content-Type: application/json" output=none} on-error={\n    :delay 5s\n    /tool fetch url=$u http-method=post http-data=$d http-header-field="Content-Type: application/json" output=none\n  }\n}\n\n:local buf ""\n:foreach i in=[/interface wireless registration-table find] do={\n  :do {\n    :local a [/interface wireless registration-table get $i]\n    :local o ""\n    :foreach k,v in=$a do={\n      :if ($k ~ "^(interface|ssid|signal|band|uptime|last-ip|tx-ccq|signal-to-noise)\\$" || $k ~ "(rate|snr|noise|mcs|width|stream|strength)") do={\n        :local vs [$esc s=[:tostr $v]]\n        :set o ($o . ",\\"" . $k . "\\":\\"" . $vs . "\\"")\n      }\n    }\n    :local mac [/interface wireless registration-table get $i mac-address]\n    :if ([:len $buf] > 0) do={:set buf ($buf . ",")}\n    :set buf ($buf . "{\\"key\\":\\"" . $mac . "\\"" . $o . "}")\n  } on-error={}\n  :if ([:len $buf] > 3000) do={\n    $send u=$url d=("{\\"k\\":\\"wireless\\",\\"seq\\":\\"$seq\\",\\"done\\":false,\\"items\\":\\5B" . $buf . "\\5D}")\n    :set buf ""\n  }\n}\n$send u=$url d=("{\\"k\\":\\"wireless\\",\\"seq\\":\\"$seq\\",\\"done\\":true,\\"items\\":\\5B" . $buf . "\\5D}")'
INV_VPN = '\n:local url "@URL@/api/inventory?t=@TOKEN@"\n:local seq [:tostr [:rndnum from=100000 to=999999999]]\n:local esc do={\n  :local o ""\n  :if ([:len $s] > 0) do={\n    :for k from=0 to=([:len $s] - 1) do={\n      :local ch [:pick $s $k]\n      :if ($ch = "\\"" || $ch = "\\\\") do={:set o ($o . "\\\\" . $ch)} else={\n        :if ($ch = "\\n" || $ch = "\\r" || $ch = "\\t") do={:set o ($o . " ")} else={:set o ($o . $ch)}\n      }\n    }\n  }\n  :return $o\n}\n:local send do={\n  :do {/tool fetch url=$u http-method=post http-data=$d http-header-field="Content-Type: application/json" output=none} on-error={\n    :delay 5s\n    /tool fetch url=$u http-method=post http-data=$d http-header-field="Content-Type: application/json" output=none\n  }\n}\n\n:local buf ""\n:foreach i in=[/interface wireguard peers find] do={\n  :do {\n    :local pk [/interface wireguard peers get $i public-key]\n    :local ifn [/interface wireguard peers get $i interface]\n    :local nm ""\n    :do {:set nm [/interface wireguard peers get $i name]} on-error={}\n    :local nme [$esc s=$nm]\n    :local cm ""\n    :do {:set cm [/interface wireguard peers get $i comment]} on-error={}\n    :local cme [$esc s=$cm]\n    :local ep ""\n    :do {:set ep [/interface wireguard peers get $i current-endpoint-address]} on-error={}\n    :local hs ""\n    :do {:set hs [/interface wireguard peers get $i last-handshake]} on-error={}\n    :local rx ""\n    :local tx ""\n    :do {:set rx [/interface wireguard peers get $i rx]; :set tx [/interface wireguard peers get $i tx]} on-error={}\n    :local dis [/interface wireguard peers get $i disabled]\n    :if ([:len $buf] > 0) do={:set buf ($buf . ",")}\n    :set buf ($buf . "{\\"key\\":\\"$pk\\",\\"iface\\":\\"$ifn\\",\\"name\\":\\"$nme\\",\\"comment\\":\\"$cme\\",\\"endpoint\\":\\"$ep\\",\\"hs\\":\\"$hs\\",\\"rx\\":\\"$rx\\",\\"tx\\":\\"$tx\\",\\"disabled\\":\\"$dis\\"}")\n  } on-error={}\n  :if ([:len $buf] > 3000) do={\n    $send u=$url d=("{\\"k\\":\\"wg\\",\\"seq\\":\\"$seq\\",\\"done\\":false,\\"items\\":\\5B" . $buf . "\\5D}")\n    :set buf ""\n  }\n}\n$send u=$url d=("{\\"k\\":\\"wg\\",\\"seq\\":\\"$seq\\",\\"done\\":true,\\"items\\":\\5B" . $buf . "\\5D}")\n:set buf ""\n:set seq [:tostr [:rndnum from=100000 to=999999999]]\n:foreach i in=[/ppp active find] do={\n  :do {\n    :local nmr [/ppp active get $i name]\n    :local nm [$esc s=$nmr]\n    :local sv [/ppp active get $i service]\n    :local ad [/ppp active get $i address]\n    :local up [/ppp active get $i uptime]\n    :local cir ""\n    :do {:set cir [/ppp active get $i caller-id]} on-error={}\n    :local ci [$esc s=$cir]\n    :if ([:len $buf] > 0) do={:set buf ($buf . ",")}\n    :local ky ($nm . "/" . $sv)\n    :set buf ($buf . "{\\"key\\":\\"$ky\\",\\"name\\":\\"$nm\\",\\"service\\":\\"$sv\\",\\"address\\":\\"$ad\\",\\"uptime\\":\\"$up\\",\\"caller\\":\\"$ci\\"}")\n  } on-error={}\n  :if ([:len $buf] > 3000) do={\n    $send u=$url d=("{\\"k\\":\\"ppp\\",\\"seq\\":\\"$seq\\",\\"done\\":false,\\"items\\":\\5B" . $buf . "\\5D}")\n    :set buf ""\n  }\n}\n$send u=$url d=("{\\"k\\":\\"ppp\\",\\"seq\\":\\"$seq\\",\\"done\\":true,\\"items\\":\\5B" . $buf . "\\5D}")'
INV_SYS = '\n:local url "@URL@/api/inventory?t=@TOKEN@"\n:local seq [:tostr [:rndnum from=100000 to=999999999]]\n:local send do={\n  :do {/tool fetch url=$u http-method=post http-data=$d http-header-field="Content-Type: application/json" output=none} on-error={\n    :delay 5s\n    /tool fetch url=$u http-method=post http-data=$d http-header-field="Content-Type: application/json" output=none\n  }\n}\n:global appCaps ""\n:set appCaps ""\n:do {:local f [:parse ":global appCaps; :if (\\5B:tostr \\5B/interface wifi capsman get enabled\\5D\\5D ~ \\"^(true|yes)\\") do={:set appCaps (\\$appCaps . \\"manager,\\")}"]; $f} on-error={}\n:do {:local f [:parse ":global appCaps; :if (\\5B:tostr \\5B/interface wifi cap get enabled\\5D\\5D ~ \\"^(true|yes)\\") do={:set appCaps (\\$appCaps . \\"cap,\\")}"]; $f} on-error={}\n:do {:local f [:parse ":global appCaps; :if (\\5B:tostr \\5B/caps-man manager get enabled\\5D\\5D ~ \\"^(true|yes)\\") do={:set appCaps (\\$appCaps . \\"manager,\\")}"]; $f} on-error={}\n:do {:local f [:parse ":global appCaps; :if (\\5B:tostr \\5B/interface wireless cap get enabled\\5D\\5D ~ \\"^(true|yes)\\") do={:set appCaps (\\$appCaps . \\"cap,\\")}"]; $f} on-error={}\n:global appCapsN ""\n:set appCapsN ""\n:do {:local f [:parse ":global appCapsN; :set appCapsN \\5B:len \\5B/interface wifi capsman remote-cap find\\5D\\5D"]; $f} on-error={}\n:if ([:len [:tostr $appCapsN]] = 0) do={:do {:local f [:parse ":global appCapsN; :set appCapsN \\5B:len \\5B/caps-man remote-cap find\\5D\\5D"]; $f} on-error={}}\n:local model ""\n:local fwc ""\n:local fwu ""\n:do {:set model [/system routerboard get model]} on-error={}\n:do {:set fwc [/system routerboard get current-firmware]} on-error={}\n:do {:set fwu [/system routerboard get upgrade-firmware]} on-error={}\n:local wq [:len [/system package find where name~"^wifi-qcom" and disabled=no]]\n:local tm [/system resource get total-memory]\n:global appHasWifi\n:global appHasWl\n:set appHasWifi 0\n:set appHasWl 0\n:do {:local f [:parse ":global appHasWifi; :set appHasWifi [:len [/interface wifi find]]"]; $f} on-error={}\n:do {:local f [:parse ":global appHasWl; :set appHasWl [:len [/interface wireless find]]"]; $f} on-error={}\n:local dhs [:len [/ip dhcp-server find]]\n:local wgs 0\n:do {:set wgs [:len [/interface wireguard find]]} on-error={}\n:local mdl ""\n:for k from=0 to=([:len $model] - 1) do={:local ch [:pick $model $k]; :if ($ch != "\\"" && $ch != "\\\\") do={:set mdl ($mdl . $ch)}}\n$send u=$url d=("{\\"k\\":\\"sys\\",\\"seq\\":\\"$seq\\",\\"done\\":true,\\"items\\":\\5B{\\"key\\":\\"sys\\",\\"caps\\":\\"$appCaps\\",\\"capsn\\":\\"$appCapsN\\",\\"model\\":\\"$mdl\\",\\"fwc\\":\\"$fwc\\",\\"fwu\\":\\"$fwu\\",\\"wq\\":\\"$wq\\",\\"tm\\":\\"$tm\\",\\"wifi\\":\\"$appHasWifi\\",\\"wl\\":\\"$appHasWl\\",\\"dhs\\":\\"$dhs\\",\\"wgs\\":\\"$wgs\\"}\\5D}")\n'
INV_MAIN = '\n:if ([:len [/system script find where name="app-inv-dhcp"]] > 0) do={:do {/system script run app-inv-dhcp} on-error={}}\n:global appHasWifi\n:global appHasWl\n:set appHasWifi 0\n:set appHasWl 0\n:do {:local f [:parse ":global appHasWifi; :set appHasWifi [:len [/interface wifi find]]"]; $f} on-error={}\n:do {:local f [:parse ":global appHasWl; :set appHasWl [:len [/interface wireless find]]"]; $f} on-error={}\n:if ($appHasWifi > 0) do={:do {/system script run app-inv-wifi} on-error={}}\n:if ($appHasWl > 0) do={:do {/system script run app-inv-wireless} on-error={}}\n:do {/system script run app-inv-vpn} on-error={}\n:do {/system script run app-inv-sys} on-error={}\n'

LIVE = r'''
:local gw ""
:do {:set gw [/tool netwatch get [find where comment="app-nw:gw"] host]} on-error={}
:global appHasWifi
:global appHasWl
:set appHasWifi 0
:set appHasWl 0
:do {:local f [:parse ":global appHasWifi; :set appHasWifi [:len [/interface wifi find]]"]; $f} on-error={}
:do {:local f [:parse ":global appHasWl; :set appHasWl [:len [/interface wireless find]]"]; $f} on-error={}

:local n 0
:local go 1
:while ($go = 1 && $n < 1000) do={
  :set n ($n + 1)
  :if ($appHasWifi > 0) do={:do {/system script run app-inv-wifi} on-error={}}
  :if ($appHasWl > 0) do={:do {/system script run app-inv-wireless} on-error={}}
  :local rtt ""
  :local recv 0
  :if ([:len $gw] > 0) do={
    :do {
      :local t1 [:timestamp]
      :local ok1 [/ping $gw count=1]
      :if ($ok1 > 0) do={:set rtt [:tostr ([:timestamp] - $t1)]}
      :set recv [/ping $gw count=4 interval=100ms]
    } on-error={}
  }
  :local d ("{\"rtt\":\"" . $rtt . "\",\"recv\":" . $recv . ",\"gw\":\"" . $gw . "\"}")
  :local resp ""
  :do {:set resp ([/tool fetch url="@URL@/api/live?t=@TOKEN@" http-method=post http-data=$d http-header-field="Content-Type: application/json" output=user as-value]->"data")} on-error={}
  :if (!($resp ~ "\"live\":1")) do={:set go 0}
  :delay 2s
}
'''

SPEED = r'''
:global appSpdDone
:global appSpdFail
:set appSpdDone 0
:set appSpdFail 0
:local t1 [:timestamp]
:for k from=1 to=@SPEEDN@ do={
  :execute script=(":global appSpdDone; :global appSpdFail; :do {/tool fetch url=\"@SPEEDURL@\" check-certificate=no output=none} on-error={:set appSpdFail (\$appSpdFail + 1)}; :set appSpdDone (\$appSpdDone + 1)")
}
:local w 0
:while ($appSpdDone < @SPEEDN@ && $w < 240) do={:delay 500ms; :set w ($w + 1)}
:local sec [:tostr ([:timestamp] - $t1)]
:local ok "false"
:if ($appSpdDone = @SPEEDN@ && $appSpdFail = 0) do={:set ok "true"}
:local j "{\"ok\":$ok,\"sec\":\"$sec\",\"bytes\":@SPEEDBYTES@}"
:do {/tool fetch url="@URL@/api/speedtest?t=@TOKEN@" http-method=post http-data=$j http-header-field="Content-Type: application/json" output=none} on-error={
  :delay 5s
  /tool fetch url="@URL@/api/speedtest?t=@TOKEN@" http-method=post http-data=$j http-header-field="Content-Type: application/json" output=none
}
'''

WL = r'''
:do {/tool fetch url="@URL@/api/whitelist.rsc?t=@TOKEN@&list=@LIST@" dst-path=app-whitelist.rsc} on-error={
  :delay 5s
  /tool fetch url="@URL@/api/whitelist.rsc?t=@TOKEN@&list=@LIST@" dst-path=app-whitelist.rsc
}
:delay 2s
/import file-name=app-whitelist.rsc
'''


BLK = r'''
:do {/tool fetch url="@URL@/api/blacklist.rsc?t=@TOKEN@&list=blacklist" dst-path=app-blacklist.rsc} on-error={
  :delay 5s
  /tool fetch url="@URL@/api/blacklist.rsc?t=@TOKEN@&list=blacklist" dst-path=app-blacklist.rsc
}
:delay 2s
/import file-name=app-blacklist.rsc
'''


def clean(v, default):
    return re.sub(r"[^\w\-.]", "", v)[:30] or default


def get_router(s, t):
    r = s.scalar(select(Router).where(Router.token == t))
    if not r:
        raise HTTPException(403, "bad token")
    return r


SYSLOG_PORT = int(os.getenv("SYSLOG_PORT", "514"))  # port na serwerze (hoście), na który routery wysyłają logi


def syslog_target(request):
    host = os.getenv("SYSLOG_HOST") or request.url.hostname or ""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        try:
            return socket.gethostbyname(host)
        except OSError:
            return None


def syslog_lines(request):
    ip = syslog_target(request)
    lines = [":do {/system logging remove [find action=appsyslog]} on-error={}",
             ":do {/system logging action remove [find name=appsyslog]} on-error={}"]
    if not ip:
        return lines
    # bez bsd-syslog / remote-log-format: nazwy tych opcji różnią się między wersjami RouterOS,
    # a domyślny format ("tematy treść") parser rozumie
    lines.append("/system logging action add name=appsyslog target=remote remote=%s remote-port=%d"
                 % (ip, SYSLOG_PORT))
    lines += ["/system logging add topics=%s action=appsyslog" % x for x in ("critical", "error", "warning")]
    lines.append("/system logging add topics=info,!fetch action=appsyslog")  # bez 'Download ... FINISHED' co 5 minut
    return lines


SPEED_STREAMS_ROUTER = 4
SPEED_URL = os.getenv("SPEEDTEST_URL", "https://speed.cloudflare.com/__down?bytes=25000000")
SPEED_BYTES = int(os.getenv("SPEEDTEST_BYTES", "25000000")) * SPEED_STREAMS_ROUTER  # łącznie ze wszystkich pobrań
SPEED_TIME = os.getenv("SPEEDTEST_TIME", "03:30:00")
INET_TARGETS = ("1.1.1.1", "8.8.8.8", "9.9.9.9")


def _guarded(cmd):
    """Polecenie RouterOS uruchamiane przez :parse - nieobsługiwany parametr w danej wersji nie przerwie importu."""
    return ':do {:local f [:parse "%s"]; $f} on-error={}' % cmd.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")


def netwatch_lines(r):
    out = [':do {/tool netwatch remove [find where comment~"^app-nw:"]} on-error={}',
           # brama domyślna (pierwsza aktywna trasa 0.0.0.0/0), bez części %interfejs
           ':global appGw ""',
           _guarded(':global appGw; :set appGw [:tostr [/ip route get ([/ip route find where dst-address=0.0.0.0/0 and active]->0) gateway]]'),
           ':do {:if ([:typeof [:find $appGw "%"]] = "num") do={:set appGw [:pick $appGw 0 [:find $appGw "%"]]}} on-error={}',
           ':if ($appGw ~ "^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+") do={' + _guarded(
               ":global appGw; /tool netwatch add type=icmp host=$appGw interval=30s packet-count=10 packet-interval=50ms "
               "comment=app-nw:gw") + '}']
    if r.edge:
        for ip in INET_TARGETS:
            out.append(_guarded("/tool netwatch add type=icmp host=%s interval=60s packet-count=20 packet-interval=100ms "
                                "comment=app-nw:inet:%s" % (ip, ip)))
        out.append(_guarded("/tool netwatch add type=dns host=www.google.com interval=60s comment=app-nw:dns"))
        out.append(_guarded("/tool netwatch add type=http-get host=www.msftconnecttest.com interval=60s comment=app-nw:http"))
    return out


@app.get("/api/setup.rsc", response_class=PlainTextResponse)
def setup_rsc(request: Request, t: str, iface: str = "ether1", list: str = "whitelist",
               ping: str = "1.1.1.1", every: int = 60, s: Session = Depends(db)):
    r = get_router(s, t)
    wl = 1 if whitelist_on(s) else 0
    bl = 1 if blacklist_on(s) else 0
    base = str(request.base_url).rstrip("/")
    rep = {"@URL@": base, "@TOKEN@": t, "@IFACE@": clean(iface, "ether1"), "@LIST@": clean(list, "whitelist"),
           "@CV@": str(SCRIPT_VERSION), "@SPEEDURL@": SPEED_URL, "@SPEEDBYTES@": str(SPEED_BYTES), "@SPEEDN@": str(SPEED_STREAMS_ROUTER)}

    def fill(x):
        for k, v in rep.items():
            x = x.replace(k, v)
        return x.strip()

    return "\n".join([
        '/system script remove [find name~"^app-"]',
        '/system script add name=app-monitor source="%s"' % q(fill(MON)),
    ] + ['/system script add name=app-whitelist source="%s"' % q(fill(WL))] * wl + [
        '/system script add name=app-blacklist source="%s"' % q(fill(BLK))] * bl + [
        ':global appHasWifi 0',
        ':global appHasWl 0',
        ':do {:local f [:parse ":global appHasWifi; :set appHasWifi [:len [/interface wifi find]]"]; $f} on-error={}',
        ':do {:local f [:parse ":global appHasWl; :set appHasWl [:len [/interface wireless find]]"]; $f} on-error={}',
        ':if ([:len [/ip dhcp-server find]] > 0) do={/system script add name=app-inv-dhcp source="%s"}' % q(fill(INV_DHCP)),
        ':if ($appHasWifi > 0) do={/system script add name=app-inv-wifi source="%s"}' % q(fill(INV_WIFI)),
        ':if ($appHasWl > 0) do={/system script add name=app-inv-wireless source="%s"}' % q(fill(INV_WIRELESS)),
        '/system script add name=app-inv-vpn source="%s"' % q(fill(INV_VPN)),
        '/system script add name=app-inv-sys source="%s"' % q(fill(INV_SYS)),
        '/system script add name=app-inventory source="%s"' % q(fill(INV_MAIN)),
        '/system script add name=app-speed source="%s"' % q(fill(SPEED)),
        '/system script add name=app-live source="%s"' % q(fill(LIVE)),
        '/system scheduler remove [find name~"^app-"]',
        "/system scheduler add name=app-mon interval=%ds on-event=app-monitor" % (every if every in INTERVALS else 60),
    ] + ["/system scheduler add name=app-wl interval=5m on-event=app-whitelist"] * wl + [
        "/system scheduler add name=app-bl interval=5m on-event=app-blacklist"] * bl + [
        "/system scheduler add name=app-inv interval=1m on-event=app-inventory",
    ] + netwatch_lines(r) + [
        "/system scheduler add name=app-spd start-time=%s interval=1d on-event=app-speed" % SPEED_TIME
    ] * bool(r.edge and sget(s, "speed_router") != str(r.id)) + [
        "/system script run app-monitor",
    ] + ["/system script run app-whitelist"] * wl + ["/system script run app-blacklist"] * bl + [
        "/system script run app-inventory",
    ] + syslog_lines(request) + [
        ':put ("RouterOS Monitor: installed. Wi-Fi (wifi package): " . [:tostr ($appHasWifi > 0)] . ", Wi-Fi (wireless): " '
        '. [:tostr ($appHasWl > 0)] . ", DHCP server: " . [:tostr ([:len [/ip dhcp-server find]] > 0)])',
    ]) + "\n"


@app.get("/routers/{rid}", dependencies=[Depends(user)])
def router_page(rid: int, request: Request, s: Session = Depends(db)):
    r = s.get(Router, rid)
    if not r:
        raise HTTPException(404)
    base = str(request.base_url).rstrip("/")
    every = interval(s)
    cmd = ('/tool fetch url="%s/api/setup.rsc?t=%s&every=%d" dst-path=app-setup.rsc; '
           ':delay 1s; /import app-setup.rsc') % (base, r.token, every)
    m = s.scalar(select(Metric).where(Metric.router_id == r.id).order_by(Metric.ts.desc()).limit(1))
    names, wan, w = wan_info(s, r)
    return templates.TemplateResponse(request, "router.html", {"r": r, "cmd": cmd, "m": m, "names": names,
                                                              "inv": inventory_view(s, r), "upd": update_available(r),
                                                              "stale": script_stale(r) and request.state.user.is_admin,
                                                              "si": sys_info(s, r),
                                                              "hours": router_hours(request.state.user, r.id),
                                                              "nw": nw_view(r),
                                                              "speed_srv": sget(s, "speed_router") == str(r.id),
                                                              "log_err": unread_errors(s, request.state.user, r.id),
                                                              "log_last": s.scalar(select(func.max(LogEntry.ts)).where(
                                                                  LogEntry.router_id == r.id)),
                                                              "log_rejected": sorted(_log_rejected.items(),
                                                                                     key=lambda x: x[1][1], reverse=True)[:10],
                                                              "syslog_port": SYSLOG_PORT,
                                                              "ranges": RANGES,
                                                              "refresh": max(every, 5),
                                                              "wan": wan, "w": w})


def ordered_routers(s):
    """Kolejność ustawiona ręcznie; nowe routery (bez pozycji) na końcu, w kolejności dodania."""
    return s.scalars(select(Router).order_by(func.coalesce(Router.pos, 1000000 + Router.id), Router.id)).all()


RANGES = (1, 6, 24, 168, 720)


def get_prefs(u):
    try:
        p = json.loads(u.prefs or "{}")
        return p if isinstance(p, dict) else {}
    except ValueError:
        return {}


def router_hours(u, rid):
    h = get_prefs(u).get("range", {}).get(str(rid))
    return h if h in RANGES else 24


@app.post("/routers/{rid}/view")
def set_view(rid: int, hours: int = Form(24), wan: str | None = Form(None), me: User = Depends(user),
             s: Session = Depends(db)):
    r = s.get(Router, rid)
    if not r:
        raise HTTPException(404)
    if hours in RANGES:
        p = get_prefs(me)
        p.setdefault("range", {})[str(rid)] = hours
        me.prefs = json.dumps(p)
    if wan is not None and me.is_admin and (wan.strip()[:40] or None) != r.wan:
        r.wan = wan.strip()[:40] or None
        log(s, "WAN", "%s: %s" % (r.name, r.wan or "auto"))
    s.commit()
    return RedirectResponse("/routers/%d#charts" % rid, 303)


@app.post("/routers/{rid}/move", dependencies=[Depends(admin)])
def move_router(rid: int, dir: str = Form(), s: Session = Depends(db)):
    rs = list(ordered_routers(s))
    i = next((k for k, x in enumerate(rs) if x.id == rid), None)
    if i is not None:
        j = i - 1 if dir == "up" else i + 1
        if 0 <= j < len(rs):
            rs[i], rs[j] = rs[j], rs[i]
            log(s, "kolejność", "%s %s" % (rs[j].name, "w górę" if dir == "up" else "w dół"))
        for k, x in enumerate(rs):
            x.pos = k
        s.commit()
    return RedirectResponse("/settings#order", 303)


@app.post("/routers/{rid}/wan", dependencies=[Depends(admin)])
def set_wan(rid: int, wan: str = Form(""), s: Session = Depends(db)):
    r = s.get(Router, rid)
    if r:
        r.wan = wan.strip()[:40] or None
        log(s, "WAN", "%s: %s" % (r.name, r.wan or "auto"))
        s.commit()
    return RedirectResponse("/routers/%d" % rid, 303)


@app.post("/routers/{rid}/clear", dependencies=[Depends(admin)])
def clear_router(rid: int, s: Session = Depends(db)):
    s.execute(delete(Metric).where(Metric.router_id == rid))
    s.execute(delete(IfaceMetric).where(IfaceMetric.router_id == rid))
    s.execute(delete(Inv).where(Inv.router_id == rid))
    s.execute(delete(LogEntry).where(LogEntry.router_id == rid))
    s.execute(delete(TrafficDay).where(TrafficDay.router_id == rid))
    s.execute(delete(ClientStat).where(ClientStat.router_id == rid))
    s.execute(delete(SpeedTest).where(SpeedTest.router_id == rid))
    log(s, "wyczyszczono dane", str(rid))
    s.commit()
    return RedirectResponse("/routers/%d" % rid, 303)


@app.post("/routers/{rid}/delete", dependencies=[Depends(admin)])
def del_router(rid: int, s: Session = Depends(db)):
    s.execute(delete(Metric).where(Metric.router_id == rid))
    s.execute(delete(IfaceMetric).where(IfaceMetric.router_id == rid))
    s.execute(delete(Whitelist).where(Whitelist.router_id == rid))
    s.execute(delete(Inv).where(Inv.router_id == rid))
    s.execute(delete(LogEntry).where(LogEntry.router_id == rid))
    s.execute(delete(TrafficDay).where(TrafficDay.router_id == rid))
    s.execute(delete(ClientStat).where(ClientStat.router_id == rid))
    s.execute(delete(SpeedTest).where(SpeedTest.router_id == rid))
    r = s.get(Router, rid)
    log(s, "router-", r.name if r else str(rid))
    s.execute(delete(Router).where(Router.id == rid))
    s.commit()
    return RedirectResponse("/", 303)


INTERVALS = (1, 5, 10, 15, 30, 60)
FAST_INTERVALS = (1, 5)  # wymagają potwierdzenia w panelu


def interval(s):
    v = sget(s, "interval", "60")
    iv = int(v) if v.isdigit() and int(v) in INTERVALS else 60
    _INTERVAL_S[0] = iv
    _OFFLINE_MULT[0] = offline_mult(s)
    _THR.clear()
    _THR.update(router_thresholds(s))
    return iv


def offline_mult(s):
    """Mnożnik czasu „brak odpowiedzi” dający próg offline: od 1,0 (bez górnego limitu), domyślnie 1,5."""
    try:
        return max(1.0, float(sget(s, "offline_mult", "1.5").replace(",", ".")))
    except ValueError:
        return 1.5


def refresh_interval_cache():
    with Session(engine) as s:
        interval(s)


def fl(v, f=lambda x: x):
    return None if v is None else f(float(v))


def buckets(hours):
    return max(1, hours * 3600 // 600)  # max ~600 punktów na wykres, wartości uśrednione


def mb(v):
    return None if v is None else round(v / 1e6, 3)


@app.get("/api/routers/{rid}/series", dependencies=[Depends(user)])
def series(rid: int, hours: int = 24, s: Session = Depends(db)):
    hours = max(1, min(hours, 720))
    b = func.floor(extract("epoch", Metric.ts) / buckets(hours))
    cols = [Metric.cpu, Metric.mem, Metric.temp, Metric.conns, Metric.dhcp, Metric.ping_ms, Metric.loss,
            Metric.rx_bps, Metric.tx_bps]
    rows = s.execute(select(func.min(Metric.ts), *[func.avg(c) for c in cols])
                     .where(Metric.router_id == rid, Metric.ts > now() - dt.timedelta(hours=hours))
                     .group_by(b).order_by(b)).all()
    rnd = lambda x: round(x, 1)
    return {"t": [x[0].isoformat(timespec="seconds") for x in rows],
            "cpu": [pct(fl(x[1], rnd)) for x in rows], "mem": [pct(fl(x[2], rnd)) for x in rows],
            "temp": [fl(x[3], rnd) for x in rows], "conns": [fl(x[4], round) for x in rows],
            "dhcp": [fl(x[5], round) for x in rows], "ping": [fl(x[6], rnd) for x in rows],
            "loss": [pct(fl(x[7], rnd)) for x in rows], "rx": [mb(fl(x[8])) for x in rows],
            "tx": [mb(fl(x[9])) for x in rows]}


@app.get("/api/routers/{rid}/ifaces", dependencies=[Depends(user)])
def ifaces(rid: int, hours: int = 24, name: str = "", s: Session = Depends(db)):
    hours = max(1, min(hours, 720))
    last = s.scalar(select(func.max(IfaceMetric.ts)).where(IfaceMetric.router_id == rid))
    names = sorted(s.scalars(select(IfaceMetric.name).where(IfaceMetric.router_id == rid, IfaceMetric.ts == last)).all()) if last else []
    if name not in names:
        name = names[0] if names else ""
    b = func.floor(extract("epoch", IfaceMetric.ts) / buckets(hours))
    rows = s.execute(select(func.min(IfaceMetric.ts), func.avg(IfaceMetric.rx_bps), func.avg(IfaceMetric.tx_bps))
                     .where(IfaceMetric.router_id == rid, IfaceMetric.name == name,
                            IfaceMetric.ts > now() - dt.timedelta(hours=hours))
                     .group_by(b).order_by(b)).all() if name else []
    return {"names": names, "name": name, "t": [x[0].isoformat(timespec="seconds") for x in rows],
            "rx": [mb(fl(x[1])) for x in rows], "tx": [mb(fl(x[2])) for x in rows]}


def pct(v):
    return v if v is not None and 0 <= v <= 100 else None


def parse_rtt(v):
    v = str(v or "").strip()
    m = re.fullmatch(r"(\d+):(\d\d):(\d\d)(?:\.(\d+))?", v)
    if m:
        h, mi, sec, fr = m.groups()
        return ((int(h) * 60 + int(mi)) * 60 + int(sec)) * 1000 + (float("0." + fr) * 1000 if fr else 0)
    toks = re.findall(r"(\d+)(ms|us|ns|w|d|h|m|s)", v)
    if not toks or "".join(a + b for a, b in toks) != v:
        return None
    mult = {"w": 6.048e8, "d": 8.64e7, "h": 3.6e6, "m": 6e4, "s": 1e3, "ms": 1, "us": 1e-3, "ns": 1e-6}
    return sum(int(a) * mult[b] for a, b in toks)


def rate(cur, old, sec):
    if None in (cur[0], cur[1], old[0], old[1]) or sec <= 0 or cur[0] < old[0] or cur[1] < old[1]:
        return None, None
    return (cur[0] - old[0]) * 8 / sec, (cur[1] - old[1]) * 8 / sec


@app.post("/api/metrics")
async def metrics(request: Request, t: str, cv: str = ""):
    raw = (await request.body()).decode("utf-8", "replace")
    return await run_in_threadpool(store_metrics, t, raw, request.client.host if request.client else None, int(cv) if cv.isdigit() else 0)


def store_metrics(t, raw, ip=None, cv=0):
    with Session(engine) as s:
        return _store_metrics(s, t, raw, ip, cv)


def _median(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    k = len(v) // 2
    return v[k] if len(v) % 2 else (v[k - 1] + v[k]) / 2


def _loss(v):
    return pct(num(str(v or "").replace("%", "").strip()))


def _probe_time(p):
    for k, v in p.items():
        if k.endswith("time") and k != "since":
            ms = parse_rtt(v)
            if ms is not None:
                return ms
    return None


def nw_metrics(r, d):
    """Wyniki sond Netwatch -> kolumny metryk. Starsze skrypty (własny ping) nadal obsługiwane."""
    probes = [p for p in (d.get("nw") or []) if isinstance(p, dict)] if isinstance(d.get("nw"), list) else []
    if not probes:
        r.nw_state = None
        return {"ping_ms": parse_rtt(d.get("rtt")), "loss": pct(num(d.get("loss")))}
    out, state = {}, []
    inet = [p for p in probes if str(p.get("comment", "")).startswith("app-nw:inet")]
    up = lambda p: str(p.get("status", "")).lower() == "up"
    if inet:
        ups = [p for p in inet if up(p)]
        known = [p for p in inet if str(p.get("status", "")).lower() in ("up", "down")]
        # stan "unknown" (np. tuż po utworzeniu sond, zanim wykonają pierwszy test) nie jest przerwą - brak danych
        out["inet_up"] = bool(ups) if known else None
        out["inet_rtt"] = _median([parse_rtt(p.get("rtt-avg")) for p in ups])
        out["inet_jit"] = _median([parse_rtt(p.get("rtt-jitter")) for p in ups])
        # utrata z działających celów; jeden niedostępny serwer nie fałszuje wyniku, wszystkie niedostępne = 100%
        out["inet_loss"] = _median([_loss(p.get("loss-percent")) for p in ups]) if ups else 100.0
    gw = next((p for p in probes if p.get("comment") == "app-nw:gw"), None)
    if gw:
        out["gw_rtt"] = parse_rtt(gw.get("rtt-avg")) if up(gw) else None
        out["gw_jit"] = parse_rtt(gw.get("rtt-jitter")) if up(gw) else None
        out["gw_loss"] = _loss(gw.get("loss-percent")) if gw.get("loss-percent") not in (None, "") else (0.0 if up(gw) else 100.0)
    for key in ("dns", "http"):
        p = next((x for x in probes if x.get("comment") == "app-nw:" + key), None)
        if p:
            st = str(p.get("status", "")).lower()
            out[key + "_up"] = True if st == "up" else False if st == "down" else None
            if st == "up":
                out[key + "_ms"] = _probe_time(p)
    if inet:
        out["ping_ms"], out["loss"] = out.get("inet_rtt"), out.get("inet_loss")
    elif gw:
        out["ping_ms"], out["loss"] = out.get("gw_rtt"), out.get("gw_loss")
    names = {"app-nw:gw": "@gw", "app-nw:dns": "@dns", "app-nw:http": "@http"}
    for p in probes:
        c = str(p.get("comment", ""))
        state.append({"name": names.get(c, "DNS " + c.split(":")[-1] if c.startswith("app-nw:inet") else c[7:]),
                      "host": str(p.get("host", ""))[:60], "status": str(p.get("status", ""))[:10],
                      "rtt": parse_rtt(p.get("rtt-avg")), "jit": parse_rtt(p.get("rtt-jitter")),
                      "loss": _loss(p.get("loss-percent")), "time": _probe_time(p), "since": str(p.get("since", ""))[:30]})
    r.nw_state = json.dumps(state)
    return out


def _store_metrics(s, t, raw, ip=None, cv=0):
    r = get_router(s, t)
    _ROUTER_CV[r.id] = cv
    if ip and not r.log_ip_fixed and r.log_ip != ip:
        r.log_ip = ip
    try:
        d = json.loads(raw)
        assert isinstance(d, dict)
    except Exception:
        try:  # RouterOS sometimes sends an empty value, e.g. "temp":, -> treat as null
            d = json.loads(re.sub(r":(?=\s*[,}\]])", ":null", raw))
            assert isinstance(d, dict)
        except Exception:
            print("BAD METRICS BODY from %s: %r" % (r.name, raw[:1500]), flush=True)
            raise HTTPException(400, "bad json")
    n = now()
    prev = s.scalar(select(Metric).where(Metric.router_id == r.id).order_by(Metric.ts.desc()).limit(1))
    sec = (n - prev.ts).total_seconds() if prev else 0
    old = {}
    if prev:
        old = {x.name: x for x in s.scalars(select(IfaceMetric).where(IfaceMetric.router_id == r.id,
                                                                     IfaceMetric.ts == prev.ts))}
    cur, types = {}, {}
    ifs = d.get("ifs")
    for it in (ifs if isinstance(ifs, list) else [])[:64]:
        if not isinstance(it, dict):
            continue
        name, irx, itx = str(it.get("n", ""))[:40], num(it.get("rx")), num(it.get("tx"))
        if not name or irx is None or itx is None:
            continue
        p = old.get(name)
        ib, ob = rate((irx, itx), (p.rx, p.tx), sec) if p else (None, None)
        s.add(IfaceMetric(router_id=r.id, ts=n, name=name, rx=int(irx), tx=int(itx), rx_bps=ib, tx_bps=ob))
        cur[name] = (irx, itx, ib, ob)
        if it.get("y"):
            types[name] = str(it.get("y"))[:20]
    if types:
        tj = json.dumps(types, sort_keys=True)
        if r.iface_types != tj:
            r.iface_types = tj
    wan = r.wan if r.wan in cur else ("ether1" if "ether1" in cur else None)
    if not wan and cur:  # same auto rule as wan_info(): interface with the most traffic
        wan = max(cur, key=lambda k: cur[k][0] + cur[k][1])
    w = cur.get(wan, (None, None, None, None))
    tm, fr = num(d.get("tm")), num(d.get("fm"))
    mem = (tm - fr) * 100 / tm if tm and fr is not None and tm > 0 else num(d.get("mem"))
    cpu, temp = num(d.get("cpu")), num(d.get("temp"))
    conns, dhcp = num(d.get("conns")), num(d.get("dhcp"))
    s.add(Metric(router_id=r.id, ts=n, cpu=pct(cpu), mem=pct(mem), temp=temp if temp is not None and -50 <= temp <= 150 else None,
                 conns=None if conns is None else int(conns), rx=None if w[0] is None else int(w[0]),
                 tx=None if w[1] is None else int(w[1]), rx_bps=w[2], tx_bps=w[3],
                 dhcp=None if dhcp is None else int(dhcp), **nw_metrics(r, d)))
    r.ident, r.ver, r.uptime = str(d.get("id", ""))[:80], str(d.get("ver", ""))[:40], str(d.get("up", ""))[:40]
    _SEEN.add(r.id)
    if r.last_seen:  # zapamiętujemy rzeczywisty odstęp między pomiarami (dłuższe przerwy to awarie, nie rytm routera)
        gap = (n - r.last_seen).total_seconds()
        if 0.5 < gap < 600:
            _GAPS.setdefault(r.id, collections.deque(maxlen=7)).append(gap)
    r.last_seen = n
    cutoff = n - dt.timedelta(days=RETENTION)
    s.execute(delete(Metric).where(Metric.router_id == r.id, Metric.ts < cutoff))
    s.commit()
    return {"ok": True, "live": 1 if r.live else 0}


# ---------- inventory (DHCP / Wi-Fi / VPN) ----------
INV_KINDS = {"dhcp", "wifi", "wireless", "wg", "ppp", "sys"}


def parse_body(raw, rname):
    try:
        d = json.loads(raw)
        assert isinstance(d, dict)
        return d
    except Exception:
        try:
            d = json.loads(re.sub(r":(?=\s*[,}\]])", ":null", raw))
            assert isinstance(d, dict)
            return d
        except Exception:
            print("BAD BODY from %s: %r" % (rname, raw[:1500]), flush=True)
            raise HTTPException(400, "bad json")


@app.post("/api/inventory")
async def inventory(request: Request, t: str):
    raw = (await request.body()).decode("utf-8", "replace")
    return await run_in_threadpool(store_inventory, t, raw)


def store_inventory(t, raw):
    with Session(engine) as s:
        r = get_router(s, t)
        d = parse_body(raw, r.name)
        kind, seq = str(d.get("k", "")), str(d.get("seq", ""))[:20]
        if kind not in INV_KINDS or not seq:
            raise HTTPException(400, "bad kind")
        n = now()
        items = d.get("items")
        items = items if isinstance(items, list) else []
        existing = {x.key: x for x in s.scalars(select(Inv).where(Inv.router_id == r.id, Inv.kind == kind))}
        for it in items[:400]:
            if not isinstance(it, dict):
                continue
            key = str(it.get("key") or "").strip()[:100]
            if not key:
                continue
            data = json.dumps({str(k)[:20]: ("" if v is None else str(v))[:200] for k, v in it.items()})
            row = existing.get(key)
            if row:
                row.data, row.seq, row.updated = data, seq, n
            else:
                row = Inv(router_id=r.id, kind=kind, key=key, data=data, seq=seq, updated=n)
                s.add(row)
                existing[key] = row
        if d.get("done") in (True, "true"):
            for key, row in existing.items():
                if row.seq != seq:
                    s.delete(row)
        if kind in ("wifi", "wireless"):
            for it in items[:400]:
                if isinstance(it, dict) and it.get("key"):
                    q = wifi_quality({k: str(v) for k, v in it.items()})
                    h = LIVE_HIST.setdefault(str(it["key"]).upper(), [])
                    h.append((n, q["signal"], q["rate"], q["q"], str(it.get("interface", ""))[:40]))
                    if len(h) > 900:
                        del h[:len(h) - 900]
        s.commit()
        return {"ok": True}


def dbm(v):
    m = re.search(r"-\d+", v or "")
    return int(m.group(0)) if m else None


def sig_class(v):
    return "" if v is None else ("ok" if v >= -67 else "warn" if v >= -75 else "bad")


PHY_PER_STREAM = {  # Mb/s na strumień przy danej szerokości kanału (najwyższe MCS, krótki odstęp)
    "ax": {20: 143.4, 40: 286.8, 80: 600.4, 160: 1201.0},
    "ac": {20: 86.7, 40: 200.0, 80: 433.3, 160: 866.7},
    "n": {20: 72.2, 40: 150.0},
}
QLABEL = {3: "q.3", 2: "q.2", 1: "q.1", 0: "q.0"}


def _mbps(v):
    v = (v or "").strip()
    if re.fullmatch(r"\d+(\.\d+)?", v):
        return float(v) / 1e6
    m = re.match(r"([\d.]+)\s*([kMG])bps", v)
    return float(m.group(1)) * {"k": 0.001, "M": 1, "G": 1000}[m.group(2)] if m else None


def wifi_quality(d):
    """Ocena jakości połączenia klienta: głównie wynegocjowana prędkość (vs. maksimum kanału), potem SNR/CCQ, sygnał."""
    sig = dbm(d.get("signal") or d.get("signal-strength") or "")
    txs, rxs = d.get("tx-rate") or d.get("tx") or "", d.get("rx-rate") or d.get("rx") or ""
    tx, rx = _mbps(txs), _mbps(rxs)
    info = " ".join(str(x) for x in (txs, rxs, d.get("band", ""), d.get("tx-rate-set", "")))
    width = next((int(x) for x in re.findall(r"(\d+)\s*MHz", info)), None)
    streams = next((int(x) for x in re.findall(r"/(\d)S\b", info)), None)
    low = info.lower()
    std = "ax" if ("ax" in low or "he" in low) else "ac" if ("ac" in low or "vht" in low) else "n" if ("2ghz" in low or "ht" in low or "-n" in low) else None
    is24 = "2ghz" in low or "2.4" in low or (d.get("band", "") == "" and width == 20 and std == "n")
    rates = [x for x in (tx, rx) if x]
    rate = max(rates) if rates else None  # lepszy kierunek pokazuje możliwości łącza (wysyłanie klienta bywa niższe)
    pct = None
    if rate and width and streams and (std or "ax") in PHY_PER_STREAM and width in PHY_PER_STREAM[std or "ax"]:
        pct = min(100, round(rate * 100 / (PHY_PER_STREAM[std or "ax"][width] * streams)))
    if pct is not None:
        rc = 3 if pct >= 50 else 2 if pct >= 30 else 1 if pct >= 15 else 0
    elif rate:
        lim = (150, 72, 30) if is24 else (400, 200, 80)
        rc = 3 if rate >= lim[0] else 2 if rate >= lim[1] else 1 if rate >= lim[2] else 0
    else:
        rc = None
    snr, ccq = num(d.get("signal-to-noise")), num(str(d.get("tx-ccq", "")).replace("%", ""))
    sc = None if sig is None else (3 if sig >= -60 else 2 if sig >= -67 else 1 if sig >= -75 else 0)
    if rc is not None:
        q = rc if sc is None else max(rc, sc - 1)  # bezczynne urządzenie ma chwilowo niską prędkość mimo dobrego sygnału
    elif snr is not None:
        q = 3 if snr >= 30 else 2 if snr >= 25 else 1 if snr >= 15 else 0
    elif ccq is not None:
        q = 3 if ccq >= 90 else 2 if ccq >= 75 else 1 if ccq >= 50 else 0
    else:
        q = sc
    if q is not None:
        if sig is not None and sig < -80:
            q = min(q, 1)
        if snr is not None and snr < 10:
            q = 0
    return {"q": q, "qlabel": tr(QLABEL[q]) if q in QLABEL else "-", "qc": "" if q is None else "ok" if q >= 2 else "warn" if q == 1 else "bad",
            "signal": sig, "sc": sig_class(sig), "rate": round(rate) if rate else None, "pct": pct, "snr": snr, "ccq": ccq,
            "width": width, "streams": streams, "std": {"ax": "Wi-Fi 6", "ac": "Wi-Fi 5", "n": "Wi-Fi 4"}.get(std, ""),
            "band": "2,4 GHz" if is24 else ("5 GHz" if (rate or width) else ""),
            "tx": fmt_rate(txs), "rx": fmt_rate(rxs)}


def bytes_h(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or u == "TB":
            return "%.0f %s" % (v, u) if u == "B" else "%.1f %s" % (v, u)
        v /= 1024


def fmt_rate(v):
    """Szybkość łącza Wi-Fi w czytelnej postaci: liczba bitów/s albo tekst RouterOS (np. '866.6Mbps-80MHz/2S/SGI')."""
    v = (v or "").strip()
    if not v:
        return "-"
    if re.fullmatch(r"\d+(\.\d+)?", v):
        f = float(v)
        return "%.0f Mb/s" % (f / 1e6) if f >= 1e6 else "%.0f kb/s" % (f / 1e3)
    m = re.match(r"([\d.]+)\s*([kMG])bps", v)
    if m:
        f = float(m.group(1)) * {"k": 0.001, "M": 1, "G": 1000}[m.group(2)]
        return "%.0f Mb/s" % f
    return v.split("-")[0][:20]


NW_NAMES = {"@gw": "nw.gw", "@dns": "nw.dns", "@http": "nw.http",
            "Brama": "nw.gw", "Test DNS (rozwiązywanie nazw)": "nw.dns", "Test HTTP (otwieranie strony)": "nw.http"}  # starsze wpisy w bazie


def nw_view(r):
    out = json.loads(r.nw_state) if r.nw_state else []
    return [{**p, "name": tr(NW_NAMES[p["name"]]) if p.get("name") in NW_NAMES else p.get("name")} for p in out]


def sys_info(s, r):
    """Model, firmware, rola CAPsMAN, pakiet wifi-qcom (progi RAM) i całkowita pamięć - z inwentarza 'sys'."""
    row = s.scalar(select(Inv).where(Inv.router_id == r.id, Inv.kind == "sys"))
    try:
        d = json.loads(row.data) if row else {}
    except ValueError:
        d = {}
    caps = {x for x in (d.get("caps") or "").split(",") if x}
    n = num(d.get("capsn"))
    role = None
    if "manager" in caps:
        role = tr("si.manager") + (" · %d AP" % n if n else "")
    if "cap" in caps:
        role = (role + " + CAP") if role else "CAP · AP"
    wq = (num(d.get("wq")) or 0) > 0
    fwc, fwu = d.get("fwc") or "", d.get("fwu") or ""
    tm = num(d.get("tm"))
    wifi_n, wl_n = int(num(d.get("wifi")) or 0), int(num(d.get("wl")) or 0)
    feats = []
    if wifi_n:
        feats.append(tr("si.wifi_pkg") % wifi_n)
    if wl_n:
        feats.append(tr("si.wireless_pkg") % wl_n)
    if role:
        feats.append(role)
    if num(d.get("dhs")):
        feats.append(tr("si.dhcp_server"))
    if num(d.get("wgs")):
        feats.append("WireGuard")
    return {"model": d.get("model") or "", "role": role, "manager": "manager" in caps, "fw": fwc, "fw_upd": fwu if fwu and fwc and fwu != fwc else "",
            "qcom": wq, "ram_w": 90 if wq else 75, "ram_b": 94 if wq else 90, "mem_total": tm,
            "has_wifi": bool(wifi_n or wl_n or role), "feats": feats, "known": bool(d)}


def ram_mb(m, si):
    if not m or m.mem is None or not si["mem_total"]:
        return ""
    tot = si["mem_total"] / 1048576
    return "%.0f/%.0f MB" % (tot * m.mem / 100, tot)


templates.env.globals["ram_mb"] = ram_mb
_WIFI_ANY = [None, 0.0]


def wifi_any():
    if time.time() - _WIFI_ANY[1] < 60:
        return _WIFI_ANY[0]
    try:
        with Session(engine) as s:
            val = any(sys_info(s, r)["has_wifi"] for r in s.scalars(select(Router)).all()) or bool(
                s.scalar(select(func.count(Inv.id)).where(Inv.kind.in_(("wifi", "wireless")))))
    except Exception:
        val = True
    _WIFI_ANY[:] = [val, time.time()]
    return val


templates.env.globals["wifi_any"] = wifi_any
_WL_ON = [None, 0.0]


def whitelist_on(s):
    """Moduł whitelisty: ustawienie z panelu; domyślnie włączony tylko jeśli whitelista ma już wpisy."""
    v = sget(s, "whitelist_on", "")
    if v in ("0", "1"):
        return v == "1"
    return bool(s.scalar(select(func.count(Whitelist.id)).where(Whitelist.kind == "white")))


def wl_on():
    if time.time() - _WL_ON[1] < 30:
        return _WL_ON[0]
    try:
        with Session(engine) as s:
            val = whitelist_on(s)
    except Exception:
        val = True
    _WL_ON[:] = [val, time.time()]
    return val


templates.env.globals["wl_on"] = wl_on
_BL_ON = [None, 0.0]


BL_RULE = ('/ip firewall raw remove [find comment="app-blacklist"]\n'
           '/ip firewall raw add chain=prerouting in-interface-list=WAN src-address-list=blacklist action=drop comment="app-blacklist"')


def blacklist_on(s):
    """Moduł blacklisty: ustawienie z panelu; domyślnie włączony tylko jeśli blacklista ma już wpisy."""
    v = sget(s, "blacklist_on", "")
    if v in ("0", "1"):
        return v == "1"
    return bool(s.scalar(select(func.count(Whitelist.id)).where(Whitelist.kind == "black")))


def bl_on():
    if time.time() - _BL_ON[1] < 30:
        return _BL_ON[0]
    try:
        with Session(engine) as s:
            val = blacklist_on(s)
    except Exception:
        val = True
    _BL_ON[:] = [val, time.time()]
    return val


templates.env.globals["bl_on"] = bl_on


def inventory_view(s, r):
    # adresy monitorowanych routerów/AP, które są online - jeśli występują w DHCP tego routera, to na pewno są aktywne
    online_ips = {x.log_ip for x in s.scalars(select(Router)).all() if x.log_ip and x.online}
    rows = s.scalars(select(Inv).where(Inv.router_id == r.id)).all()
    by = {k: [] for k in INV_KINDS}
    upd = None
    for x in rows:
        if x.kind in ("wifi", "wireless") and (now() - x.updated).total_seconds() > 300:
            continue  # klient nie zgłaszany od 5 min - nie pokazuj "zamrożonego" odczytu
        try:
            d = json.loads(x.data)
        except ValueError:
            continue
        by[x.kind].append(d)
        upd = x.updated if upd is None or x.updated > upd else upd
    leases = {d.get("key", "").upper(): d for d in by["dhcp"]}
    wifi = []
    for d in by["wifi"] + by["wireless"]:
        mac = d.get("key", "").upper()
        l = leases.get(mac, {})
        wq = wifi_quality(d)
        wifi.append({"mac": mac, "name": l.get("comment") or l.get("host") or "-",
                     "ip": l.get("ip") or d.get("last-ip") or d.get("lastip") or "-",
                     "iface": d.get("interface") or d.get("iface", ""), "uptime": d.get("uptime") or "-", **wq})
    wifi.sort(key=lambda w: (-(w["q"] if w["q"] is not None else -1), -(w["signal"] if w["signal"] is not None else -999)))
    wmacs = {w["mac"]: w for w in wifi}
    devices = []
    for mac, d in leases.items():
        arp, st = d.get("arp", ""), d.get("status", "")
        seen_l2 = (num(d.get("bh")) or 0) > 0  # MAC w tablicy hostów bridge = ruch w ostatnich minutach
        if mac in wmacs or seen_l2 or d.get("ip") in online_ips or (
                st == "bound" and arp in ("reachable", "delay", "probe", "permanent")):
            state = "online"
        elif st == "bound" and arp == "stale":
            state = "idle"
        else:
            state = "offline"
        w = wmacs.get(mac)
        devices.append({"state": state, "name": d.get("comment") or d.get("host") or "-",
                        "host": d.get("host") if d.get("comment") else "", "ip": d.get("ip") or "-", "mac": mac,
                        "static": d.get("dyn") == "false", "last": d.get("last") or "-",
                        "signal": w["signal"] if w else None, "sc": w["sc"] if w else ""})
    order = {"online": 0, "idle": 1, "offline": 2}
    devices.sort(key=lambda x: (order[x["state"]], x["name"].lower()))
    vpn = []
    for d in by["wg"]:
        ms = parse_rtt(d.get("hs"))
        dis = d.get("disabled") == "true"
        vpn.append({"type": "WireGuard", "name": d.get("name") or d.get("comment") or d.get("key", "")[:10] + "…",
                    "iface": d.get("iface", ""), "remote": d.get("endpoint") or "-",
                    "state": "disabled" if dis else ("online" if ms is not None and ms <= 180_000 else "offline"),
                    "info": tr("vpn.hs_ago", t=d["hs"]) if d.get("hs") else tr("vpn.no_hs"),
                    "rx": bytes_h(d.get("rx")), "tx": bytes_h(d.get("tx"))})
    for d in by["ppp"]:
        vpn.append({"type": (d.get("service") or "ppp").upper(), "name": d.get("name", "-"), "iface": "",
                    "remote": d.get("caller") or "-", "state": "online", "info": "uptime " + (d.get("uptime") or "-"),
                    "rx": d.get("address") or "-", "tx": ""})
    vpn.sort(key=lambda v: ({"online": 0, "offline": 1, "disabled": 2}[v["state"]], v["name"].lower()))
    return {"devices": devices, "wifi": wifi, "vpn": vpn, "updated": upd,
            "dev_on": sum(1 for x in devices if x["state"] == "online"),
            "vpn_on": sum(1 for x in vpn if x["state"] == "online"),
            "stale": bool(upd and (now() - upd).total_seconds() > 600)}


# ---------- syslog (logi z routerów) ----------
SYSLOG_LISTEN = 5514  # port wewnątrz kontenera (docker-compose mapuje SYSLOG_PORT -> 5514/udp)
LOG_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "14"))
SEV_WORDS = {"critical": 2, "error": 3, "warning": 4, "info": 6, "debug": 7}
TOPIC_WORDS = set(SEV_WORDS) | {
    "system", "account", "firewall", "dhcp", "wireless", "wifi", "interface", "script", "ppp", "pppoe", "l2tp",
    "pptp", "sstp", "ovpn", "wireguard", "dns", "route", "bgp", "ospf", "ipsec", "caps", "certificate", "e-mail",
    "ntp", "web-proxy", "hotspot", "radius", "snmp", "ssh", "telnet", "ftp", "update", "health", "bridge", "lte",
    "gps", "upnp", "event", "manager", "packet", "raw", "read", "write", "state", "watchdog", "fetch", "backup",
    "container", "ipv6", "vrrp", "rip", "mpls", "ups", "timer", "async", "smb", "tftp", "disk", "dot1x", "stp",
    "netwatch", "rsvp", "l2tp-ipsec", "store", "calc", "sertcp", "socks", "isdn", "pim", "igmp-proxy", "mme"}
TS_RE = re.compile(r"^(?:[A-Z][a-z]{2}\s+\d{1,2}\s+\d\d:\d\d:\d\d|\d{4}-\d\d-\d\d[T ]\S+)\s+")
_log_buf = []
_log_ipmap = {}
_log_rejected = {}
_BG_TASKS = []  # referencje do zadań w tle (żeby nie zostały sprzątnięte przez GC)


def is_topics(tok):
    parts = tok.rstrip(":").split(",")
    return all(re.fullmatch(r"[a-z0-9-]+", p) for p in parts) and any(p in TOPIC_WORDS for p in parts)


def parse_syslog(data):
    """Zwraca (waga 0-7, tematy 'system,info', treść). Obsługuje format BSD i domyślny RouterOS."""
    s = data.decode("utf-8", "replace").strip()
    pri = None
    m = re.match(r"^<(\d{1,3})>", s)
    if m:
        pri, s = int(m.group(1)), s[m.end():]
    s = TS_RE.sub("", s, count=1)
    topics, msg = "", s
    toks = s.split(" ", 2)
    if toks and is_topics(toks[0]):
        topics, msg = toks[0].rstrip(":"), s[len(toks[0]):].strip()
    elif len(toks) > 1 and is_topics(toks[1]):  # pierwszy token to nazwa hosta (identity)
        topics, msg = toks[1].rstrip(":"), (toks[2] if len(toks) > 2 else "").strip()
    sev = None
    for w in topics.split(","):
        if w in SEV_WORDS:
            sev = SEV_WORDS[w] if sev is None else min(sev, SEV_WORDS[w])
    if sev is None:
        sev = (pri & 7) if pri is not None else 6
    return sev, topics, msg


class SyslogProto(asyncio.DatagramProtocol):
    def datagram_received(self, data, addr):
        ip = addr[0]
        rid = _log_ipmap.get(ip)
        if rid is None:
            c = _log_rejected.setdefault(ip, [0, None])
            c[0], c[1] = c[0] + 1, now()
            if len(_log_rejected) > 30:
                _log_rejected.pop(next(iter(_log_rejected)))
            return
        if len(_log_buf) < 20000:
            _log_buf.append((rid, now(), data[:2000]))


def refresh_ipmap():
    global _log_ipmap
    with Session(engine) as s:
        _log_ipmap = {r.log_ip: r.id for r in s.scalars(select(Router).where(Router.log_ip.is_not(None)))}


def flush_logs(batch):
    rows, seen = [], {}
    try:
        muted = muted_set()
    except Exception:  # wyciszanie nie może zatrzymać zapisu logów
        muted = set()
    for rid, ts, data in batch:
        sev, topics, msg = parse_syslog(data)
        if not msg:
            continue
        if sev >= 4 and (rid, _mute_norm(msg)) in muted:  # błędy i komunikaty krytyczne nigdy nie są pomijane
            continue
        k = (rid, topics, msg)
        if k in seen and (ts - seen[k]).total_seconds() < 2:  # ten sam wpis z kilku reguł logowania
            continue
        seen[k] = ts
        rows.append(LogEntry(router_id=rid, ts=ts, sev=sev, topics=topics[:100], msg=msg[:1000]))
    if rows:
        fresh = [(x.ts, x.msg) for x in rows]  # po commit obiekty są odłączone od sesji, więc kopiujemy potrzebne pola wcześniej
        with Session(engine) as s:
            s.add_all(rows)
            s.commit()
        try:
            autoban_check(fresh)
        except Exception as e:  # auto-ban nie może zatrzymać zapisu logów
            print("autoban: %s" % e, flush=True)


# ---------- powiadomienia (ntfy, webhook) ----------
NOTIF_BAN_EVERY = 600  # zbiorcze powiadomienie o automatycznych banach najczęściej co 10 min
_PENDING_BANS = {"n": 0, "h": 1, "sent": 0.0}
_NOTIF_NEXT = {}   # klucz zdarzenia -> czas (time.time()), przed którym nie ponawiamy próby po błędzie wysyłki (tylko to zdarzenie)
_NOTIF_FAILS = {}  # klucz zdarzenia -> liczba kolejnych błędów (wydłuża przerwę: 15, 30, 60, 120 s)
_NOTIF_STATS = {"check": 0.0, "sent": 0, "error": "", "error_ts": 0.0}  # do strony „Zgłoś problem”


def notif_cfg(s):
    def g(k, d=""):
        return sget(s, "notif_" + k, d)

    def num(k, d, lo, hi):
        v = g(k)
        return min(hi, max(lo, int(v))) if v.isdigit() else d
    return {"on": g("on", "0") == "1", "ntfy_url": g("ntfy_url", "https://ntfy.sh"), "ntfy_topic": g("ntfy_topic"),
            "ntfy_token": g("ntfy_token"), "hook_url": g("hook_url"), "lang": g("lang") if g("lang") in i18n.LOCALES else "en",
            "offline_min": num("offline_min", 5, 1, 120), "inet_min": num("inet_min", 3, 1, 120),
            **{"r_" + r: g("r_" + r, "1") == "1" for r in ("offline", "inet", "backup", "ban")}}


def notif_event(cfg, kind, severity, tkey, router=None, **kw):
    """Zdarzenie do wysłania; treść w języku z ustawień. Bez adresów IP, tokenów i haseł."""
    return {"app": "routeros-monitor", "version": appver.current(), "kind": kind, "severity": severity,
            "title": i18n.translate(cfg["lang"], "notif.%s.title" % tkey, **kw),
            "message": i18n.translate(cfg["lang"], "notif.%s.msg" % tkey, **kw),
            "router": router, "time": now().isoformat(timespec="seconds") + "Z"}


def _notif_state(s):
    try:
        d = json.loads(sget(s, "notif_state", "{}") or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _mins(a, b):
    return max(1, int((b - a).total_seconds() // 60))


def notify_check():
    """Co 15 s: sprawdza routery, internet i kopie i wysyła powiadomienie przy zmianie stanu (jedno na zdarzenie).
    Błąd wysyłki jednego zdarzenia nie wstrzymuje pozostałych: to zdarzenie jest ponawiane po krótkiej, rosnącej przerwie."""
    _NOTIF_STATS["check"] = time.time()
    with Session(engine) as s:
        cfg = notif_cfg(s)
        if not cfg["on"]:
            return
        state = _notif_state(s)
        before = json.dumps(state, sort_keys=True)
        events = []  # (klucz stanu, nowa wartość albo None = usuń, zdarzenie)
        # Tuż po starcie czas ostatniego kontaktu w bazie jest stary, więc router, który jeszcze się nie zgłosił od startu, nie jest
        # oceniany jako offline do końca krótkiej rozgrzewki (ok. 2 interwały). Router, który już się zgłosił, jest oceniany od razu.
        warmup = time.time() - _STARTED < min(300, max(30, 2 * _INTERVAL_S[0] + 15))
        for r in ordered_routers(s):
            if r.last_seen is None:
                continue
            gap = (now() - r.last_seen).total_seconds()
            k, st = "router:%d" % r.id, state.get("router:%d" % r.id)
            if cfg["r_offline"] and (not warmup or r.id in _SEEN) and gap >= cfg["offline_min"] * 60 and not st:
                events.append((k, {"t": r.last_seen.isoformat(timespec="seconds")},
                               notif_event(cfg, "router_offline", "critical", "offline", r.name, name=r.name, min=int(gap // 60))))
            elif r.online and st:
                since = dt.datetime.fromisoformat(st["t"]) if st.get("t") else r.last_seen
                events.append((k, None, notif_event(cfg, "router_online", "info", "online", r.name, name=r.name, min=_mins(since, now()))))
            if cfg["r_inet"] and r.edge and r.online:
                ik = "inet:%d" % r.id
                ist = state.get(ik)
                rows = s.execute(select(Metric.ts, Metric.inet_up).where(
                    Metric.router_id == r.id, Metric.inet_up.is_not(None), Metric.ts > now() - dt.timedelta(hours=2))
                    .order_by(Metric.ts.desc()).limit(2000)).all()
                if rows and (now() - rows[0][0]).total_seconds() < 300:
                    down_since = None
                    for ts, up in rows:  # od najnowszego: jak długo trwa ciągła przerwa
                        if up is not False:
                            break
                        down_since = ts
                    if down_since and not ist and (now() - down_since).total_seconds() >= cfg["inet_min"] * 60:
                        events.append((ik, {"t": down_since.isoformat(timespec="seconds")},
                                       notif_event(cfg, "internet_down", "critical", "inet", r.name, name=r.name,
                                                   min=_mins(down_since, now()))))
                    elif not down_since and ist:
                        t0 = dt.datetime.fromisoformat(ist["t"]) if ist.get("t") else now()
                        events.append((ik, None, notif_event(cfg, "internet_up", "info", "inet_ok", r.name, name=r.name,
                                                             min=_mins(t0, now()))))
        if cfg["r_backup"]:
            b = backups_info()
            problem = ""
            if b.get("error"):
                problem = " ".join(b["error"].split())[:120]
            elif b.get("available") and b.get("files") and b.get("stale"):
                problem = i18n.translate(cfg["lang"], "notif.backup.stale")
            if problem and "backup" not in state:
                events.append(("backup", {"d": problem[:60]}, notif_event(cfg, "backup_failed", "warning", "backup", detail=problem)))
            elif not problem and "backup" in state:
                events.append(("backup", None, notif_event(cfg, "backup_ok", "info", "backup_ok")))
        if cfg["r_ban"] and _PENDING_BANS["n"] and time.time() - _PENDING_BANS["sent"] >= NOTIF_BAN_EVERY:
            events.append((None, None, notif_event(cfg, "auto_ban", "warning", "ban", n=_PENDING_BANS["n"], h=_PENDING_BANS["h"])))
        for key, new, ev in events:
            ek = key or "ban"
            if time.time() < _NOTIF_NEXT.get(ek, 0):
                continue  # to zdarzenie czeka na ponowienie po błędzie; pozostałe idą normalnie
            errs = notify.dispatch(cfg, ev)
            if errs:
                fails = _NOTIF_FAILS[ek] = _NOTIF_FAILS.get(ek, 0) + 1
                wait = min(120, 15 * 2 ** (fails - 1))
                _NOTIF_NEXT[ek] = time.time() + wait
                _NOTIF_STATS.update(error="; ".join(errs), error_ts=time.time())
                print("notify: sending %s failed (%s), retry in %d s" % (ev["kind"], "; ".join(errs), wait), flush=True)
                continue
            _NOTIF_FAILS.pop(ek, None)
            _NOTIF_NEXT.pop(ek, None)
            _NOTIF_STATS["sent"] += 1
            print("notify: sent %s: %s" % (ev["kind"], ev["message"]), flush=True)
            if key is None:
                _PENDING_BANS.update(n=0, sent=time.time())
            elif new is None:
                state.pop(key, None)
            else:
                state[key] = new
        if json.dumps(state, sort_keys=True) != before:
            sset(s, "notif_state", json.dumps(state))
            s.commit()


# ---------- wyciszanie komunikatów logu: wybrane powtarzające się wpisy routera nie są zapisywane ----------
MUTE_MAX = 100
_MAC_RX = re.compile(r"(?<![0-9A-Fa-f:])[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}(?![0-9A-Fa-f:])")
_MUTE_CACHE = [0.0, set()]


def _mute_norm(msg):
    """Wzorzec komunikatu do wyciszania: adresy MAC i liczby zastąpione znacznikami (jak _norm, ale z MAC-ami)."""
    return _norm(_MAC_RX.sub("MAC", msg))


def mutes_get(s):
    try:
        return [m for m in json.loads(sget(s, "log_mutes", "[]")) if isinstance(m, dict) and m.get("pat")]
    except ValueError:
        return []


def muted_set():
    """Zbiór (id routera, wzorzec) wyciszonych komunikatów; odświeżany co 30 s albo po zmianie."""
    if time.time() - _MUTE_CACHE[0] > 30:
        with Session(engine) as s:
            _MUTE_CACHE[1] = {(m.get("rid"), m["pat"]) for m in mutes_get(s)}
        _MUTE_CACHE[0] = time.time()
    return _MUTE_CACHE[1]


def unmutable(msg, topics=""):
    """Komunikaty, których nie wolno wyciszyć: próby logowania (liczone przez auto-ban) i wpisy oceniane jako problem."""
    if _FAIL_RX.search(msg or ""):
        return True
    res = translate_log(msg or "", topics or "")
    return bool(res and res["level"] == "bad")


@app.post("/api/routers/{rid}/logs/mute", dependencies=[Depends(admin)])
def log_mute(rid: int, msg: str = Form(), s: Session = Depends(db)):
    row = s.scalars(select(LogEntry).where(LogEntry.router_id == rid, LogEntry.msg == msg[:1000])
                    .order_by(LogEntry.id.desc()).limit(1)).first()
    if not row or row.sev <= 3:
        return JSONResponse({"ok": False, "msg": tr("msg.mu_err")}, 400)
    if unmutable(row.msg, row.topics):  # ataki i problemy muszą zostać widoczne (i liczone przez auto-ban)
        return JSONResponse({"ok": False, "msg": tr("msg.mu_bad")}, 400)
    pat = _mute_norm(row.msg)
    lst = mutes_get(s)
    if any(m["pat"] == pat and m.get("rid") == rid for m in lst):
        return {"ok": True, "pat": pat}
    if len(lst) >= MUTE_MAX:
        return JSONResponse({"ok": False, "msg": tr("msg.mu_max")}, 400)
    lst.append({"pat": pat, "rid": rid, "ts": now().isoformat(timespec="seconds")})
    sset(s, "log_mutes", json.dumps(lst, ensure_ascii=False))
    deleted = purge_muted(s, rid, pat)
    log(s, "log wyciszony", "router %d: %s (usunięto %d starych wpisów, zostawiono najnowszy)" % (rid, pat, deleted))
    s.commit()
    _MUTE_CACHE[0] = 0
    return {"ok": True, "pat": pat, "deleted": deleted}


def purge_muted(s, rid, pat):
    """Usuwa stare wpisy routera pasujące do wzorca (tylko ostrzeżenia i niżej), zostawiając najnowszy (znacznik 🔕 w liście).
    Zwraca liczbę usuniętych. Przeszukuje najwyżej 300 tys. najnowszych wpisów routera."""
    prefix = re.split(r"#|MAC", pat)[0]  # stały początek wzorca przyspiesza wyszukiwanie
    q = select(LogEntry.id, LogEntry.msg).where(LogEntry.router_id == rid, LogEntry.sev >= 4)
    if len(prefix) >= 3:
        q = q.where(LogEntry.msg.startswith(prefix, autoescape=True))
    ids = [i for i, msg in s.execute(q.order_by(LogEntry.id.desc()).limit(300000)) if _mute_norm(msg) == pat]
    old = ids[1:]  # ids[0] to najnowszy wpis, zostaje
    for k in range(0, len(old), 1000):
        s.execute(delete(LogEntry).where(LogEntry.id.in_(old[k:k + 1000])))
    return len(old)


@app.post("/api/routers/{rid}/logs/unmute", dependencies=[Depends(admin)])
def log_unmute(rid: int, msg: str = Form(), s: Session = Depends(db)):
    pat = _mute_norm(msg)
    lst = mutes_get(s)
    new = [m for m in lst if not (m["pat"] == pat and m.get("rid") == rid)]
    if len(new) != len(lst):
        sset(s, "log_mutes", json.dumps(new, ensure_ascii=False))
        log(s, "log: wyciszenie zdjęte", "router %d: %s" % (rid, pat))
        s.commit()
        _MUTE_CACHE[0] = 0
    return {"ok": True, "pat": pat}


@app.post("/settings/log-mutes/delete", dependencies=[Depends(admin)])
def settings_mute_delete(request: Request, rid: str = Form(""), pat: str = Form(), s: Session = Depends(db)):
    lst = mutes_get(s)
    new = [m for m in lst if not (m["pat"] == pat and str(m.get("rid")) == rid)]
    if len(new) != len(lst):
        sset(s, "log_mutes", json.dumps(new, ensure_ascii=False))
        log(s, "log: wyciszenie zdjęte", "router %s: %s" % (rid, pat))
        s.commit()
        _MUTE_CACHE[0] = 0
    return settings_view(request, s, tr("msg.mu_removed"), True)


# ---------- auto-ban (fail2ban): czasowa blokada adresów z wieloma nieudanymi logowaniami z internetu ----------
AUTOBAN_HOURS = (1, 6, 24, 72)
AUTOBAN_MAX_ACTIVE = 500  # górna granica liczby wpisów auto-banu naraz (ochrona przed zalaniem listy)
_FAIL_RX = re.compile(r"login failure for user \S+ from (?P<ip>\d{1,3}(?:\.\d{1,3}){3}) via [\w-]+", re.I)
_AB_HITS = {}  # adres -> czasy ostatnich nieudanych logowań


def autoban_cfg(s):
    def num(k, d, lo, hi):
        v = sget(s, k, "")
        return min(hi, max(lo, int(v))) if v.isdigit() else d
    return {"on": blacklist_on(s) and sget(s, "autoban_on", "0") == "1",
            "n": num("autoban_n", 5, 3, 50), "min": num("autoban_min", 10, 1, 120), "h": num("autoban_h", 1, 1, 168)}


def _list_networks(s, kind):
    out = []
    for w in s.scalars(select(Whitelist).where(Whitelist.kind == kind, Whitelist.active == True)):  # noqa: E712
        try:
            out.append(ipaddress.ip_network(w.ip, strict=False))
        except ValueError:  # domena
            continue
    return out


def autoban_check(rows):
    """Dodaje do blacklisty (na czas z ustawień) adresy publiczne, z których było >= N nieudanych logowań w oknie M minut."""
    cand = []
    for ts, msg in rows:  # rows: krotki (czas, treść)
        m = _FAIL_RX.search(msg or "")
        if m and is_public(m.group("ip")):
            cand.append((ts, m.group("ip")))
    if not cand:
        return
    with Session(engine) as s:
        cfg = autoban_cfg(s)
        if not cfg["on"]:
            _AB_HITS.clear()
            return
        window = dt.timedelta(minutes=cfg["min"])
        hit = []
        for ts, ip in cand:
            lst = _AB_HITS.setdefault(ip, [])
            lst.append(ts)
            lst[:] = [t for t in lst if ts - t <= window]
            if len(lst) >= cfg["n"] and ip not in hit:
                hit.append(ip)
        for ip in [k for k, v in _AB_HITS.items() if not v or now() - v[-1] > window]:
            del _AB_HITS[ip]
        if not hit:
            return
        mine = [os.getenv("SYSLOG_HOST", "")] + [r.log_ip for r in s.scalars(select(Router)) if r.log_ip]
        mine += [ip for ip, t in _PANEL_IPS.items() if time.time() - t < 86400]  # adresy, z których ostatnio korzystano z panelu
        white = _list_networks(s, "white")
        active = s.scalars(select(Whitelist).where(Whitelist.kind == "black", Whitelist.active == True)).all()  # noqa: E712
        banned = {w.ip for w in active if not (w.expires and w.expires < now())}
        auto_n = sum(1 for w in active if (w.comment or "").startswith("auto-ban"))
        for ip in hit:
            n_hits = len(_AB_HITS.get(ip, []))
            _AB_HITS.pop(ip, None)
            try:
                net = parse_ip(ip)
                a = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if net in banned or any(a in n for n in white) or netguard.check_ban(net, mine, ""):
                continue
            if auto_n >= AUTOBAN_MAX_ACTIVE:
                break
            auto_n += 1
            s.add(Whitelist(kind="black", ip=net, comment=cmt("auto-ban %d failed logins" % n_hits),
                            expires=now() + dt.timedelta(hours=cfg["h"]), router_id=None))
            log(s, "blacklist+ (auto)", "%s: %d nieudanych logowan w %d min, ban na %d h" % (net, n_hits, cfg["min"], cfg["h"]))
            _PENDING_BANS["n"] += 1  # zbiorcze powiadomienie wysyła notify_check
            _PENDING_BANS["h"] = cfg["h"]
        s.commit()


def purge_logs():
    with Session(engine) as s:
        s.execute(delete(LogEntry).where(LogEntry.ts < now() - dt.timedelta(days=LOG_DAYS)))
        s.execute(delete(ClientStat).where(ClientStat.ts < now() - dt.timedelta(days=RETENTION)))
        s.execute(delete(Inv).where(Inv.kind.in_(("wifi", "wireless")), Inv.updated < now() - dt.timedelta(hours=1)))
        s.execute(delete(TrafficDay).where(TrafficDay.day < (now() - dt.timedelta(days=800)).date()))
        s.commit()


def purge_iface_metrics(chunk=20000, max_seconds=20):
    """Usuwa pomiary interfejsów starsze niż IFACE_RETENTION_DAYS: porcjami, osobno dla każdego routera (po indeksie),
    żeby jednorazowe skasowanie milionów wierszy nie blokowało bazy ani zgłoszeń routerów. Zwraca liczbę usuniętych."""
    cutoff = now() - dt.timedelta(days=IFACE_RETENTION)
    t0, total = time.monotonic(), 0
    with Session(engine) as s:
        rids = list(s.scalars(select(Router.id)))
    for rid in rids:
        while time.monotonic() - t0 < max_seconds:
            with Session(engine) as s:
                sub_q = select(IfaceMetric.id).where(IfaceMetric.router_id == rid, IfaceMetric.ts < cutoff).limit(chunk)
                n = s.execute(delete(IfaceMetric).where(IfaceMetric.id.in_(sub_q))).rowcount or 0
                s.commit()
            total += n
            if n < chunk:
                break
    return total


def record_clients():
    """Co minutę: zapisz liczbę urządzeń online, klientów Wi-Fi i VPN online dla routerów z aktualnym inwentarzem."""
    with Session(engine) as s:
        for r in s.scalars(select(Router)).all():
            v = inventory_view(s, r)
            if not v["updated"] or v["stale"]:
                continue
            s.add(ClientStat(router_id=r.id, ts=now(), dev_on=v["dev_on"], dev_total=len(v["devices"]),
                             wifi=len(v["wifi"]), vpn_on=v["vpn_on"]))
        s.commit()


LOCAL_TZ = os.getenv("TZ", "Europe/Warsaw")


def update_traffic():
    """Co 10 minut: przelicz dzienny transfer WAN (z liczników bajtów) dla ostatnich dni i zapisz w traffic_days."""
    with Session(engine) as s:
        for r in s.scalars(select(Router)).all():
            _, wan, _ = wan_info(s, r)
            if not wan:
                continue
            have = s.scalar(select(func.count(TrafficDay.id)).where(TrafficDay.router_id == r.id))
            since = now() - dt.timedelta(days=RETENTION if not have else 3)
            rows = s.execute(text("""
                SELECT d, SUM(drx), SUM(dtx) FROM (
                  SELECT CAST((ts AT TIME ZONE 'UTC') AT TIME ZONE :tz AS DATE) AS d,
                         rx - LAG(rx) OVER (ORDER BY ts) AS drx, tx - LAG(tx) OVER (ORDER BY ts) AS dtx
                  FROM iface_metrics WHERE router_id = :rid AND name = :n AND ts > :since) q
                WHERE drx >= 0 AND dtx >= 0 GROUP BY d ORDER BY d"""),
                {"tz": LOCAL_TZ, "rid": r.id, "n": wan, "since": since}).all()
            first = True
            for d, rx, tx in rows:
                if first and have:  # pierwszy dzień okna może być niepełny - nie nadpisuj go
                    first = False
                    continue
                first = False
                row = s.scalar(select(TrafficDay).where(TrafficDay.router_id == r.id, TrafficDay.day == d))
                if row:
                    row.rx, row.tx, row.iface = int(rx or 0), int(tx or 0), wan
                else:
                    s.add(TrafficDay(router_id=r.id, day=d, iface=wan, rx=int(rx or 0), tx=int(tx or 0)))
        s.commit()


async def _run_timed(fn, *args):
    """Uruchamia zadanie w puli wątków i zapisuje w logu aplikacji te, które trwają dłużej niż 10 s (blokują pętlę zadań w tle)."""
    t0 = time.monotonic()
    try:
        return await run_in_threadpool(fn, *args)
    finally:
        d = time.monotonic() - t0
        if d > 10:
            print("slow background task: %s took %.0f s" % (fn.__name__, d), flush=True)


async def notify_loop():
    """Powiadomienia mają własną pętlę, żeby ciężkie zadania (czyszczenie, statystyki) nie opóźniały alertów."""
    await asyncio.sleep(10)
    while True:
        try:
            await _run_timed(notify_check)
        except Exception as e:
            print("notify loop error: %s" % e, flush=True)
        await asyncio.sleep(15)


_HEAVY = None  # kolejka ciężkich zadań bazodanowych (po jednym naraz); lekkie zadania i powiadomienia nigdy na nią nie czekają


async def _periodic(name, fn, every, first=0.0, heavy=False):
    """Własna, niezależna pętla jednego zadania w tle: nie czeka na inne zadania, a samo nie nakłada się na siebie
    (kolejne uruchomienie dopiero `every` sekund po zakończeniu poprzedniego). Ciężkie zadania idą pojedynczo przez _HEAVY."""
    await asyncio.sleep(first)
    while True:
        try:
            if heavy:
                async with _HEAVY:
                    await _run_timed(fn)
            else:
                await _run_timed(fn)
        except Exception as e:
            print("background task %s error: %s" % (name, e), flush=True)
        await asyncio.sleep(every)


async def _ingest_loop():
    """Zapis logów z routerów (syslog): co 2 s, niezależnie od pozostałych zadań."""
    while True:
        try:
            if _log_buf:
                batch = _log_buf[:]
                del _log_buf[:len(batch)]
                await _run_timed(flush_logs, batch)
        except Exception as e:
            print("log ingest error: %s" % e, flush=True)
        await asyncio.sleep(2)


async def _speed_loop():
    """Co 30 s sprawdza, czy pora na nocny test prędkości z serwera, i uruchamia go jako osobne zadanie."""
    await asyncio.sleep(14)
    while True:
        try:
            rid = await _run_timed(speed_due)
            if rid:
                asyncio.create_task(server_speedtest(rid))
        except Exception as e:
            print("background task speed_due error: %s" % e, flush=True)
        await asyncio.sleep(30)


def start_background_tasks():
    """Uruchamia niezależne zadania w tle z własnymi harmonogramami (pierwsze uruchomienia rozłożone w czasie)."""
    global _HEAVY
    _HEAVY = asyncio.Semaphore(1)
    jobs = [  # (nazwa, funkcja, co ile s, opóźnienie pierwszego uruchomienia, ciężkie)
        ("refresh_ipmap", refresh_ipmap, 30, 0, False),
        ("refresh_interval_cache", refresh_interval_cache, 60, 1, False),
        ("record_clients", record_clients, 60, 10, False),
        ("update_traffic", update_traffic, 600, 20, True),
        ("enforce_backup_limit", enforce_backup_limit, 300, 40, True),
        ("purge_iface_metrics", purge_iface_metrics, 300, 60, True),
        ("purge_logs", purge_logs, 3600, 90, True),
    ]
    tasks = [asyncio.create_task(_periodic(*j[:4], heavy=j[4])) for j in jobs]
    tasks += [asyncio.create_task(_ingest_loop()), asyncio.create_task(_speed_loop()), asyncio.create_task(notify_loop())]
    return tasks


async def push_caddy_config():
    for _ in range(40):
        try:
            with Session(engine) as s:
                cfg = caddyfile(sget(s, "domain"), sget(s, "email"))
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(CADDY + "/load", content=cfg.encode(), headers={"Content-Type": "text/caddyfile"})
            if r.status_code == 200:
                return
        except Exception:
            pass
        await asyncio.sleep(5)
    print("caddy: nie udało się wysłać konfiguracji", flush=True)


@app.on_event("startup")
async def start_caddy_cfg():
    asyncio.create_task(push_caddy_config())


@app.on_event("startup")
async def start_syslog():
    try:
        await asyncio.get_running_loop().create_datagram_endpoint(SyslogProto, local_addr=("0.0.0.0", SYSLOG_LISTEN))
    except OSError as e:
        print("syslog: nie można nasłuchiwać na UDP %d: %s" % (SYSLOG_LISTEN, e), flush=True)
    _BG_TASKS[:] = start_background_tasks()


LOG_CATS = {"error": (0, 1, 2, 3), "warning": (4,), "info": (5, 6), "debug": (7,)}


def sev_cls(v):
    return "crit" if v <= 2 else "err" if v == 3 else "warn" if v == 4 else "dbg" if v == 7 else "info"


SEV_LABEL = {"crit": "sev.crit", "err": "sev.err", "warn": "sev.warn", "info": "sev.info", "dbg": "sev.dbg"}


@app.get("/api/routers/{rid}/logs", dependencies=[Depends(user)])
def logs_api(request: Request, rid: int, sev: str = "", topic: str = "", q: str = "", limit: int = 300,
             s: Session = Depends(db)):
    limit = max(10, min(limit, 1000))
    cond = [LogEntry.router_id == rid]
    if sev in LOG_CATS:
        cond.append(LogEntry.sev.in_(LOG_CATS[sev]))
    topic = topic.strip().lower()
    if topic:
        cond.append(or_(LogEntry.topics == topic, LogEntry.topics.like(topic + ",%"),
                        LogEntry.topics.like("%," + topic), LogEntry.topics.like("%," + topic + ",%")))
    if q.strip():
        cond.append(LogEntry.msg.ilike("%" + q.strip()[:100].replace("%", r"\%").replace("_", r"\_") + "%"))
    rows = s.scalars(select(LogEntry).where(*cond).order_by(LogEntry.id.desc()).limit(limit)).all()
    unread = unread_counts(s, request.state.user, rid)
    day = now() - dt.timedelta(hours=24)
    counts = {k: 0 for k in LOG_CATS}
    for v, c in s.execute(select(LogEntry.sev, func.count()).where(LogEntry.router_id == rid, LogEntry.ts > day)
                          .group_by(LogEntry.sev)).all():
        for k, vals in LOG_CATS.items():
            if v in vals:
                counts[k] += c
    words = set()
    for (tp,) in s.execute(select(LogEntry.topics).where(LogEntry.router_id == rid,
                                                         LogEntry.ts > now() - dt.timedelta(days=7))
                           .distinct().limit(1000)).all():
        words.update(w for w in (tp or "").split(",") if w and w not in SEV_WORDS)
    admin_ = request.state.user.is_admin
    mset = muted_set() if admin_ else set()
    return {"items": [{"t": x.ts.isoformat(timespec="seconds"), "cls": sev_cls(x.sev), "label": tr(SEV_LABEL[sev_cls(x.sev)]),
                       "topics": [w for w in x.topics.split(",") if w and w not in SEV_WORDS], "msg": x.msg,
                       "muted": x.sev >= 4 and (rid, _mute_norm(x.msg)) in mset,
                       "nomute": bool(admin_ and x.sev >= 4 and unmutable(x.msg, x.topics))}  # bez przycisku wyciszania
                      for x in rows],
            "counts": counts, "topics": sorted(words),
            "ack": (log_ack_time(request.state.user, rid) or dt.datetime(2000, 1, 1)).isoformat(timespec="seconds"),
            "unread": unread[0], "unread_warn": unread[1]}


def log_ack_time(u, rid):
    try:
        return dt.datetime.fromisoformat(get_prefs(u).get("logack", {}).get(str(rid), ""))
    except (ValueError, TypeError):
        return None


def unread_errors(s, u, rid):
    """Błędy (krytyczne + error) z ostatnich 24 h, które pojawiły się po ostatnim 'Zatwierdź' tego użytkownika."""
    since = now() - dt.timedelta(hours=24)
    ack = log_ack_time(u, rid)
    if ack and ack > since:
        since = ack
    return s.scalar(select(func.count(LogEntry.id)).where(LogEntry.router_id == rid, LogEntry.sev <= 3, LogEntry.ts > since))


def unread_counts(s, u, rid):
    """(błędy, ostrzeżenia) z ostatnich 24 h od ostatniego 'Zatwierdź' - do wskaźnika na stronie głównej."""
    since = now() - dt.timedelta(hours=24)
    ack = log_ack_time(u, rid)
    if ack and ack > since:
        since = ack
    err = warn = 0
    for v, c in s.execute(select(LogEntry.sev, func.count()).where(LogEntry.router_id == rid, LogEntry.sev <= 4,
                                                                   LogEntry.ts > since).group_by(LogEntry.sev)).all():
        if v <= 3:
            err += c
        else:
            warn += c
    return err, warn


@app.post("/routers/{rid}/logack")
def log_ack(rid: int, me: User = Depends(user), s: Session = Depends(db)):
    p = get_prefs(me)
    p.setdefault("logack", {})[str(rid)] = now().isoformat(timespec="seconds")
    me.prefs = json.dumps(p)
    s.commit()
    return {"ok": True, "ack": p["logack"][str(rid)]}


def parse_utc(v):
    """ISO z przeglądarki (np. 2026-10-01T08:00:00.000Z) -> naiwny datetime UTC."""
    try:
        d = dt.datetime.fromisoformat((v or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(dt.timezone.utc).replace(tzinfo=None) if d.tzinfo else d


@app.get("/api/routers/{rid}/logs/export")
def logs_export(rid: int, start: str, end: str, fmt: str = "csv", sev: str = "", topic: str = "", q: str = "",
                me: User = Depends(user), s: Session = Depends(db)):
    from zoneinfo import ZoneInfo
    r = s.get(Router, rid)
    a, b = parse_utc(start), parse_utc(end)
    if not r or not a or not b or b <= a:
        raise HTTPException(400, tr("err.bad_range"))
    cond = [LogEntry.router_id == rid, LogEntry.ts >= a, LogEntry.ts <= b]
    if sev in LOG_CATS:
        cond.append(LogEntry.sev.in_(LOG_CATS[sev]))
    topic = topic.strip().lower()
    if topic:
        cond.append(or_(LogEntry.topics == topic, LogEntry.topics.like(topic + ",%"),
                        LogEntry.topics.like("%," + topic), LogEntry.topics.like("%," + topic + ",%")))
    if q.strip():
        cond.append(LogEntry.msg.ilike("%" + q.strip()[:100].replace("%", r"\%").replace("_", r"\_") + "%"))
    try:
        tz = ZoneInfo(LOCAL_TZ)
    except Exception:
        tz = dt.timezone.utc
    loc = lambda d: d.replace(tzinfo=dt.timezone.utc).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
    log(s, "eksport logów", "%s: %s - %s" % (r.name, loc(a), loc(b)))
    s.commit()
    name = re.sub(r"[^\w.-]", "_", r.name)
    fname = "logi-%s-%s-%s.%s" % (name, loc(a)[:16].replace(" ", "_").replace(":", ""), loc(b)[:16].replace(" ", "_").replace(":", ""),
                                  "csv" if fmt == "csv" else "txt")

    lang_ = i18n.CURRENT.get()

    def gen():
        with Session(engine) as s2:
            if fmt == "csv":
                yield "\ufeffczas;waga;tematy;wiadomosc\r\n"
            rows = s2.execute(select(LogEntry.ts, LogEntry.sev, LogEntry.topics, LogEntry.msg).where(*cond)
                              .order_by(LogEntry.ts).limit(500000).execution_options(yield_per=2000))
            for ts, sv, tp, msg in rows:
                lab = i18n.translate(lang_, SEV_LABEL[sev_cls(sv)])
                if fmt == "csv":
                    buf = io.StringIO()
                    csv.writer(buf, delimiter=";").writerow([loc(ts), lab, tp, msg])
                    yield buf.getvalue().replace("\n", "\r\n") if not buf.getvalue().endswith("\r\n") else buf.getvalue()
                else:
                    yield "%s %-11s %-30s %s\n" % (loc(ts), lab, tp, msg)

    return StreamingResponse(gen(), media_type="text/csv; charset=utf-8" if fmt == "csv" else "text/plain; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="%s"' % fname})


LIVE_HIST = {}   # MAC -> [(ts, sygnał, prędkość Mb/s, jakość, interfejs)] - ostatnie ~30-45 min, w pamięci
LIVE_GW = {}     # router_id -> (ts, rtt ms, utrata %, brama)


@app.post("/routers/{rid}/live", dependencies=[Depends(admin)])
def set_live(rid: int, minutes: int = Form(15), s: Session = Depends(db)):
    """Włącza/wyłącza tryb ustawiania. Włączenie obejmuje też kontrolery CAPsMAN (to one widzą klientów Wi-Fi AP)."""
    r = s.get(Router, rid)
    if not r:
        raise HTTPException(404)
    minutes = minutes if minutes in (0, 5, 15, 30) else 15
    until = now() + dt.timedelta(minutes=minutes) if minutes else None
    targets = {r.id: r}
    if until:
        for x in s.scalars(select(Router)).all():
            if sys_info(s, x)["manager"]:
                targets[x.id] = x
    else:
        targets = {x.id: x for x in s.scalars(select(Router)).all() if x.live}
        targets[r.id] = r
    for x in targets.values():
        x.live_until = until
    log(s, "tryb ustawiania", "%s: %s" % (", ".join(x.name for x in targets.values()), "%d min" % minutes if minutes else "wyłączony"))
    s.commit()
    return {"ok": True}


@app.post("/api/live")
async def live_in(request: Request, t: str):
    raw = (await request.body()).decode("utf-8", "replace")

    def store():
        with Session(engine) as s:
            r = get_router(s, t)
            d = parse_body(raw, r.name)
            recv = num(d.get("recv"))
            LIVE_GW[r.id] = (now(), parse_rtt(d.get("rtt")), None if recv is None else round((4 - recv) * 25),
                             str(d.get("gw", ""))[:45])
            return {"ok": True, "live": 1 if r.live else 0}
    return await run_in_threadpool(store)


@app.get("/live", dependencies=[Depends(user)])
def live_page(request: Request, rid: int = 0, s: Session = Depends(db)):
    routers = ordered_routers(s)
    return templates.TemplateResponse(request, "live.html", {"routers": routers, "rid": rid or (routers[0].id if routers else 0)})


@app.get("/api/live/state", dependencies=[Depends(user)])
def live_state(mac: str = "", s: Session = Depends(db)):
    routers = ordered_routers(s)
    n = now()
    rts = []
    for r in routers:
        g = LIVE_GW.get(r.id)
        fresh = g and (n - g[0]).total_seconds() < 30
        rts.append({"id": r.id, "name": r.name, "live": r.live, "left": int((r.live_until - n).total_seconds()) if r.live else 0,
                    "gw": g[3] if g else "", "gw_rtt": g[1] if fresh else None, "gw_loss": g[2] if fresh else None})
    names = {r.id: r.name for r in routers}
    clients = {}
    for row in s.scalars(select(Inv).where(Inv.kind.in_(("wifi", "wireless")),
                                           Inv.updated > n - dt.timedelta(minutes=5))).all():
        try:
            d = json.loads(row.data)
        except ValueError:
            continue
        k = row.key.upper()
        if k in clients and clients[k]["_u"] >= row.updated:
            continue
        clients[k] = {"_u": row.updated, "mac": k, "router": names.get(row.router_id, ""),
                      "iface": d.get("interface") or d.get("iface", ""), **wifi_quality(d),
                      "age": int((n - row.updated).total_seconds())}
    leases = {}
    for row in s.scalars(select(Inv).where(Inv.kind == "dhcp")).all():
        try:
            d = json.loads(row.data)
        except ValueError:
            continue
        leases[row.key.upper()] = d
    out = []
    for c in clients.values():
        l = leases.get(c["mac"], {})
        c["name"] = l.get("comment") or l.get("host") or c["mac"]
        c["ip"] = l.get("ip", "")
        c.pop("_u")
        out.append(c)
    out.sort(key=lambda c: ((c["q"] if c["q"] is not None else -1), c["signal"] if c["signal"] is not None else -999))
    hist = []
    mac = mac.upper()
    if mac in LIVE_HIST:
        hist = [{"t": h[0].isoformat(timespec="seconds"), "s": h[1], "r": h[2], "q": h[3], "i": h[4]}
                for h in LIVE_HIST[mac] if (n - h[0]).total_seconds() < 1800]
    spots = [{"id": x.id, "t": x.ts.isoformat(timespec="seconds"), "label": x.label, "device": x.device, "iface": x.iface,
              "signal": x.signal, "rate": x.rate, "q": x.quality, "qlabel": tr(QLABEL[x.quality]) if x.quality in QLABEL else "-"}
             for x in s.scalars(select(LiveSpot).order_by(LiveSpot.id.desc()).limit(30)).all()]
    return {"routers": rts, "clients": out, "hist": hist, "spots": spots}


@app.post("/api/live/spot", dependencies=[Depends(user)])
def live_spot(mac: str = Form(), label: str = Form(), s: Session = Depends(db)):
    mac = mac.upper()
    h = [x for x in LIVE_HIST.get(mac, []) if (now() - x[0]).total_seconds() <= 30]
    if not h:
        raise HTTPException(400, tr("err.no_samples"))
    avg = lambda vals: (sum(vals) / len(vals)) if vals else None
    sigs, rts, qs = [x[1] for x in h if x[1] is not None], [x[2] for x in h if x[2]], [x[3] for x in h if x[3] is not None]
    lease = s.scalar(select(Inv).where(Inv.kind == "dhcp", func.upper(Inv.key) == mac))
    dev = mac
    if lease:
        try:
            ld = json.loads(lease.data)
            dev = ld.get("comment") or ld.get("host") or mac
        except ValueError:
            pass
    s.add(LiveSpot(ts=now(), mac=mac, label=re.sub(r"[^\w .,\-/]", "", label)[:60] or "miejsce", device=dev[:80],
                   iface=h[-1][4], signal=round(avg(sigs), 1) if sigs else None, rate=round(avg(rts)) if rts else None,
                   quality=round(avg(qs)) if qs else None))
    s.commit()
    return {"ok": True}


@app.post("/api/live/spot/{sid}/delete", dependencies=[Depends(user)])
def live_spot_del(sid: int, s: Session = Depends(db)):
    s.execute(delete(LiveSpot).where(LiveSpot.id == sid))
    s.commit()
    return {"ok": True}


@app.post("/routers/{rid}/edge", dependencies=[Depends(admin)])
def set_edge(rid: int, edge: str = Form(""), s: Session = Depends(db)):
    r = s.get(Router, rid)
    if r:
        r.edge = edge == "1"
        log(s, "router brzegowy", "%s: %s" % (r.name, "tak" if r.edge else "nie"))
        s.commit()
    return RedirectResponse("/routers/%d#cfg" % rid, 303)


@app.post("/api/speedtest")
async def speedtest_in(request: Request, t: str):
    raw = (await request.body()).decode("utf-8", "replace")

    def store():
        with Session(engine) as s:
            r = get_router(s, t)
            d = parse_body(raw, r.name)
            secs = (parse_rtt(d.get("sec")) or 0) / 1000
            nbytes = num(d.get("bytes")) or 0
            ok = d.get("ok") in (True, "true") and secs > 0 and nbytes > 0
            s.add(SpeedTest(router_id=r.id, ts=now(), ok=ok, secs=secs or None, source="router",
                            down_mbps=round(nbytes * 8 / secs / 1e6, 1) if ok else None))
            s.commit()
            return {"ok": True}
    return await run_in_threadpool(store)


# ---------- test prędkości z serwera aplikacji (wiele równoległych połączeń, pobieranie + wysyłanie + ping) ----------
SPD_STREAMS = int(os.getenv("SPEEDTEST_STREAMS", "6"))
SPD_DOWN = os.getenv("SPEEDTEST_DOWN_URL", "https://speed.cloudflare.com/__down")
SPD_UP = os.getenv("SPEEDTEST_UP_URL", "https://speed.cloudflare.com/__up")
SPD_STATE = {"running": False, "phase": "", "rid": None}


async def _measure(worker, seconds, warm=1.5):
    """Uruchamia SPD_STREAMS równoległych połączeń; liczy przepływ po rozgrzewce (pomija start TCP)."""
    cnt = [0]
    t0 = time.monotonic()
    end = t0 + seconds
    async with httpx.AsyncClient(timeout=httpx.Timeout(seconds + 10), http2=False,
                                 limits=httpx.Limits(max_connections=SPD_STREAMS + 2)) as c:
        tasks = [asyncio.create_task(worker(c, end, cnt)) for _ in range(SPD_STREAMS)]
        await asyncio.sleep(warm)
        b0, w0 = cnt[0], time.monotonic()
        await asyncio.gather(*tasks, return_exceptions=True)
        b1, w1 = cnt[0], min(time.monotonic(), end)
    return (b1 - b0) * 8 / max(w1 - w0, 0.1) / 1e6 if b1 > b0 else None


async def _dl(c, end, cnt):
    while time.monotonic() < end:
        async with c.stream("GET", SPD_DOWN, params={"bytes": 100_000_000}) as r:
            async for ch in r.aiter_bytes(65536):
                cnt[0] += len(ch)
                if time.monotonic() >= end:
                    return


async def _ul(c, end, cnt):
    block = os.urandom(256 * 1024)

    async def body():
        sent = 0
        while time.monotonic() < end and sent < 50_000_000:
            cnt[0] += len(block)
            sent += len(block)
            yield block
    while time.monotonic() < end:
        await c.post(SPD_UP, content=body(), headers={"Content-Type": "application/octet-stream"})


async def _ping():
    vals = []
    async with httpx.AsyncClient(timeout=10) as c:
        await c.get(SPD_DOWN, params={"bytes": 0})
        for _ in range(8):
            t = time.monotonic()
            await c.get(SPD_DOWN, params={"bytes": 0})
            vals.append((time.monotonic() - t) * 1000)
    vals.sort()
    return round(vals[len(vals) // 2], 1) if vals else None


import shutil

OOKLA_BIN = shutil.which("speedtest")
OOKLA_ARGS = ["--accept-license", "--accept-gdpr"]
LS_BIN = shutil.which("librespeed-cli")  # LibreSpeed CLI (LGPL-3.0), dołączony do obrazu
SPEED_ENGINES = ("librespeed", "ookla", "cloudflare")


def default_engine():
    """Silnik, gdy nic nie zapisano: Ookla (jeśli jest, zachowanie jak dawniej), inaczej LibreSpeed, inaczej Cloudflare."""
    return "ookla" if OOKLA_BIN else "librespeed" if LS_BIN else "cloudflare"


async def _run(args, timeout):
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(p.communicate(), timeout)
    except asyncio.TimeoutError:
        p.kill()
        raise RuntimeError(tr("err.test_timeout"))
    return p.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def ookla_test(server_id=""):
    """Oficjalny test speedtest.net (Ookla Speedtest CLI): pobieranie, wysyłanie, ping, jitter, utrata, serwer, link."""
    args = [OOKLA_BIN, *OOKLA_ARGS, "-f", "json", "-p", "no"]
    if server_id.isdigit():
        args += ["-s", server_id]
    code, out, err = await _run(args, 180)
    line = next((l for l in out.splitlines()[::-1] if l.strip().startswith("{") and '"type":"result"' in l.replace(" ", "")), "")
    if not line:
        msg = (err or out).strip().splitlines()
        raise RuntimeError((msg[-1] if msg else tr("err.no_result", code=code))[:180])
    d = json.loads(line)
    srv = d.get("server") or {}
    bw = lambda k: (d.get(k) or {}).get("bandwidth")
    return {"down": bw("download") * 8 / 1e6 if bw("download") else None, "up": bw("upload") * 8 / 1e6 if bw("upload") else None,
            "ping": (d.get("ping") or {}).get("latency"), "jitter": (d.get("ping") or {}).get("jitter"),
            "loss": d.get("packetLoss"), "url": (d.get("result") or {}).get("url"),
            "server": ", ".join(x for x in (srv.get("name"), srv.get("location")) if x)[:120] or None}


async def librespeed_test(server_id=""):
    """Test LibreSpeed (librespeed.org): pobieranie, wysyłanie, ping, jitter. Bez --share, więc nic nie jest wysyłane do LibreSpeed."""
    args = [LS_BIN, "--json", "--duration", "10", "--timeout", "15", "--concurrent", "8"]  # 8 połączeń: przy 3 wysyłanie nie wysycało łącza
    if server_id.isdigit():
        args += ["--server", server_id]
    code, out, err = await _run(args, 180)
    try:
        return speedengines.parse_librespeed_json(out)
    except (ValueError, TypeError) as e:
        msg = (err or out).strip().splitlines()
        raise RuntimeError((msg[-1] if msg else tr("err.bad_result", err=e, code=code))[:180])


@app.get("/api/speedtest/servers", dependencies=[Depends(admin)])
async def speed_servers(engine: str = "ookla"):
    if engine == "librespeed":
        if not LS_BIN:
            return {"available": False, "servers": []}
        try:
            code, out, err = await _run([LS_BIN, "--list"], 40)
            return {"available": True, "servers": speedengines.parse_librespeed_list(out)}
        except Exception as e:
            return {"available": True, "servers": [], "error": str(e)[:200]}
    if not OOKLA_BIN:
        return {"available": False, "servers": []}
    try:
        code, out, err = await _run([OOKLA_BIN, *OOKLA_ARGS, "-L", "-f", "json"], 40)
        d = json.loads(out.strip().splitlines()[-1])
        return {"available": True, "servers": [{"id": x.get("id"), "name": "%s, %s (%s)" % (x.get("name"), x.get("location"), x.get("country"))}
                                               for x in d.get("servers", [])]}
    except Exception as e:
        return {"available": True, "servers": [], "error": str(e)[:200]}


async def server_speedtest(rid):
    if SPD_STATE["running"] or BEST_STATE["running"]:
        return
    SPD_STATE.update(running=True, rid=rid)
    res = {"ok": False, "down": None, "up": None, "ping": None, "jitter": None, "loss": None, "server": None, "url": None}
    src, error = "server", None
    t0 = time.monotonic()

    def cfg():
        with Session(engine) as s:
            e = sget(s, "speed_engine", "") or default_engine()
            return e, server_setting(s, e)
    eng, sid = await run_in_threadpool(cfg)
    runners = {"librespeed": (LS_BIN, librespeed_test, "LibreSpeed"), "ookla": (OOKLA_BIN, ookla_test, "Ookla")}
    try:
        if eng in runners and runners[eng][0]:
            src = eng
            if eng == "librespeed" and sid == "best":
                SPD_STATE["phase"] = "spd.best"
                sid = await resolve_best_server()
            SPD_STATE["phase"] = "spd." + eng
            try:
                res.update(await runners[eng][1](sid))
            except Exception as e:
                error = "%s: %s" % (runners[eng][2], e)
                print("speedtest %s: %s" % (eng, e), flush=True)
        if eng not in runners or not runners[eng][0] or not res["down"]:
            if src != "server":
                src = "server"
            SPD_STATE["phase"] = "spd.ping"
            res["ping"] = await _ping()
            SPD_STATE["phase"] = "spd.down"
            res["down"] = await _measure(_dl, 10)
            SPD_STATE["phase"] = "spd.up"
            res["up"] = await _measure(_ul, 8)
            res["server"] = "Cloudflare"
        res["ok"] = bool(res["down"])
    except Exception as e:
        error = (error + "; " if error else "") + str(e)
        print("speedtest: %s" % e, flush=True)
    finally:
        r1 = lambda v: round(v, 1) if v is not None else None

        def store():
            with Session(engine) as s:
                s.add(SpeedTest(router_id=rid, ts=now(), ok=res["ok"], source=src, secs=round(time.monotonic() - t0, 1),
                                down_mbps=r1(res["down"]), up_mbps=r1(res["up"]), ping_ms=r1(res["ping"]),
                                jitter_ms=r1(res["jitter"]), loss=r1(res["loss"]), server=res["server"],
                                url=res["url"], error=(error or "")[:200] or None))
                s.commit()
        await run_in_threadpool(store)
        SPD_STATE.update(running=False, phase="", rid=None)


BEST_STATE = {"running": False, "phase": None, "error": None}  # phase: (klucz tłumaczenia, parametry)
BEST_MAX_AGE = 7 * 86400  # wybór najlepszego serwera jest powtarzany co 7 dni
BEST_CANDIDATES = 8       # tylu najbliższych (wg opóźnienia) serwerów porównujemy (lista ma ok. 20)


def best_result(s):
    try:
        d = json.loads(sget(s, "speed_ls_best", "") or "null")
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


async def _server_latency(client, url):
    """Najkrótszy z dwóch czasów odpowiedzi serwera (pierwsze zapytanie zawiera nawiązanie połączenia)."""
    best = None
    for _ in range(2):
        t = time.monotonic()
        try:
            async with client.stream("GET", url):
                pass  # wystarczą nagłówki
        except Exception:
            continue
        ms = (time.monotonic() - t) * 1000
        best = ms if best is None else min(best, ms)
    return best


async def find_best_librespeed():
    """Porównuje kilka najbliższych serwerów LibreSpeed krótkim testem pobierania i zapamiętuje najszybszy."""
    BEST_STATE.update(running=True, phase=("best.ping", {}), error=None)
    try:
        code, out, err = await _run([LS_BIN, "--list"], 40)
        servers = speedengines.parse_librespeed_servers(out)
        if not servers:
            raise RuntimeError(tr("err.no_server_list"))
        async with httpx.AsyncClient(timeout=4, follow_redirects=True) as c:
            lats = await asyncio.gather(*[_server_latency(c, sv["url"]) for sv in servers])
        cands = speedengines.pick_candidates(servers, {sv["id"]: l for sv, l in zip(servers, lats)}, BEST_CANDIDATES)
        if not cands:
            raise RuntimeError(tr("err.no_server_reply"))
        results = []
        for i, sv in enumerate(cands, 1):
            BEST_STATE["phase"] = ("best.test", {"i": i, "n": len(cands), "name": sv["name"]})
            row = {"id": sv["id"], "name": sv["name"], "ping": sv["ping"], "down": None}
            try:
                code, out, err = await _run([LS_BIN, "--json", "--no-upload", "--duration", "5", "--timeout", "10",
                                             "--concurrent", "8", "--server", sv["id"]], 60)
                d = speedengines.parse_librespeed_json(out)
                row["down"] = round(d["down"], 1) if d["down"] else None
            except Exception as e:
                print("librespeed best: serwer %s: %s" % (sv["id"], e), flush=True)
            results.append(row)
        best = speedengines.pick_best(results)
        if not best:
            raise RuntimeError(tr("err.no_test_result"))
        data = {"at": now().isoformat(timespec="seconds"), "best": best, "tested": results}

        def save():
            with Session(engine) as s:
                sset(s, "speed_ls_best", json.dumps(data))
                s.commit()
        await run_in_threadpool(save)
        return data
    except Exception as e:
        BEST_STATE["error"] = str(e)[:200]
        raise
    finally:
        BEST_STATE.update(running=False, phase=None)


async def resolve_best_server():
    """Id serwera do testu: zapamiętany najlepszy; gdy go brak lub jest starszy niż 7 dni, szuka od nowa. Błąd = "" (wybór programu)."""
    def load():
        with Session(engine) as s:
            return best_result(s)
    d = await run_in_threadpool(load)
    try:
        age = (now() - dt.datetime.fromisoformat(d["at"])).total_seconds() if d else None
    except (KeyError, ValueError, TypeError):
        age = None
    if d is None or age is None or age > BEST_MAX_AGE:
        try:
            d = await find_best_librespeed()
        except Exception as e:
            print("librespeed best: %s" % e, flush=True)
    sid = str(((d or {}).get("best") or {}).get("id") or "")
    return sid if sid.isdigit() else ""


async def _best_task():
    try:
        await find_best_librespeed()
    except Exception as e:
        print("librespeed best: %s" % e, flush=True)


@app.post("/api/speedtest/best", dependencies=[Depends(admin)])
async def best_start():
    if not LS_BIN:
        raise HTTPException(400, tr("err.ls_missing"))
    if BEST_STATE["running"] or SPD_STATE["running"]:
        return {"ok": False, "busy": True}
    asyncio.create_task(_best_task())
    return {"ok": True}


@app.get("/api/speedtest/best", dependencies=[Depends(admin)])
def best_status(s: Session = Depends(db)):
    ph = BEST_STATE["phase"]
    return {"running": BEST_STATE["running"], "phase": tr(ph[0], **ph[1]) if ph else "",
            "error": BEST_STATE["error"], "result": best_result(s)}


def server_setting(s, engine):
    """Serwer testowy zapisany osobno dla każdego silnika (numeracja serwerów różni się między silnikami)."""
    default = sget(s, "speed_server", "") if engine == "ookla" else "best" if engine == "librespeed" else ""
    return sget(s, "speed_server_" + engine, default)


def speed_due():
    """Czy pora na nocny test z serwera (SPEEDTEST_TIME wg strefy TZ, raz na dobę)."""
    from zoneinfo import ZoneInfo
    try:
        loc = dt.datetime.now(ZoneInfo(LOCAL_TZ))
    except Exception:
        loc = dt.datetime.now()
    hh, mm = (int(x) for x in SPEED_TIME.split(":")[:2])
    if (loc.hour, loc.minute) != (hh, mm):
        return None
    with Session(engine) as s:
        rid = sget(s, "speed_router")
        if not rid.isdigit() or sget(s, "speed_last") == loc.date().isoformat():
            return None
        sset(s, "speed_last", loc.date().isoformat())
        s.commit()
        return int(rid)


@app.post("/routers/{rid}/speedtest", dependencies=[Depends(admin)])
async def speedtest_now(rid: int):
    def check():
        with Session(engine) as s:
            return sget(s, "speed_router") == str(rid)
    if not await run_in_threadpool(check):
        raise HTTPException(400, tr("err.speed_router"))
    if not SPD_STATE["running"] and not BEST_STATE["running"]:
        asyncio.create_task(server_speedtest(rid))
    return {"ok": True}


@app.post("/settings/speed", dependencies=[Depends(admin)])
def settings_speed(request: Request, rid: str = Form(""), engine_: str = Form("", alias="engine"),
                   server: str = Form(""), s: Session = Depends(db)):
    sset(s, "speed_router", rid if rid.isdigit() else "")
    engine_ = engine_ if engine_ in SPEED_ENGINES else default_engine()
    sset(s, "speed_engine", engine_)
    sset(s, "speed_server_" + engine_, server if server.isdigit() or (engine_ == "librespeed" and server == "best") else "")
    r = s.get(Router, int(rid)) if rid.isdigit() else None
    log(s, "test prędkości", "z serwera za routerem: %s" % (r.name if r else "wyłączony"))
    s.commit()
    return settings_view(request, s, tr("msg.saved") + (" " + tr("msg.speed_paste") if r else ""), True)


@app.get("/api/routers/{rid}/quality", dependencies=[Depends(user)])
def quality_api(rid: int, hours: int = 24, s: Session = Depends(db)):
    """Jakość łącza: szeregi czasowe sond, dostępność internetu, przerwy, testy prędkości."""
    hours = max(1, min(hours, 720))
    b = func.floor(extract("epoch", Metric.ts) / buckets(hours))
    cols = [Metric.inet_rtt, Metric.inet_jit, Metric.inet_loss, Metric.gw_rtt, Metric.gw_jit, Metric.gw_loss,
            Metric.dns_ms, Metric.http_ms]
    rows = s.execute(select(func.min(Metric.ts), *[func.avg(c) for c in cols])
                     .where(Metric.router_id == rid, Metric.ts > now() - dt.timedelta(hours=hours))
                     .group_by(b).order_by(b)).all()
    rnd = lambda x: round(x, 1)
    keys = ["inet_rtt", "inet_jit", "inet_loss", "gw_rtt", "gw_jit", "gw_loss", "dns", "http"]
    out = {"t": [x[0].isoformat(timespec="seconds") for x in rows]}
    for i, k in enumerate(keys):
        out[k] = [fl(x[i + 1], rnd) for x in rows]
    avail = {}
    for label, h in (("24h", 24), ("7d", 168), ("30d", 720)):
        tot, upc = s.execute(select(func.count(Metric.id), func.count(Metric.id).filter(Metric.inet_up == True))  # noqa: E712
                             .where(Metric.router_id == rid, Metric.inet_up.is_not(None),
                                    Metric.ts > now() - dt.timedelta(hours=h))).one()
        avail[label] = round(upc * 100 / tot, 2) if tot else None
    first = s.scalar(select(func.min(Metric.ts)).where(Metric.router_id == rid, Metric.inet_up.is_not(None)))
    # przerwy i problemy: brak internetu (żaden cel ICMP nie odpowiada) albo działa ping, ale nie DNS / HTTP
    outages, start, kind = [], None, None
    for ts, iu, du, hu in s.execute(select(Metric.ts, Metric.inet_up, Metric.dns_up, Metric.http_up).where(
            Metric.router_id == rid, Metric.inet_up.is_not(None), Metric.ts > now() - dt.timedelta(days=7))
            .order_by(Metric.ts)).all():
        k = "inet" if iu is False else "dns" if du is False else "http" if hu is False else None
        if k != kind:
            if kind is not None:
                outages.append((start, ts, kind))
            start, kind = (ts, k) if k else (None, None)
    if kind is not None:
        outages.append((start, None, kind))
    outages = [{"from": a.isoformat(timespec="seconds"), "to": z.isoformat(timespec="seconds") if z else None,
                "min": round(((z or now()) - a).total_seconds() / 60, 1), "code": k, "type": tr("out." + k)} for a, z, k in outages][-20:][::-1]
    sp = s.scalars(select(SpeedTest).where(SpeedTest.router_id == rid).order_by(SpeedTest.ts.desc()).limit(60)).all()[::-1]
    return {**out, "avail": avail, "outages": outages,
            "since": first.isoformat(timespec="seconds") if first else None,
            "speed": [{"t": x.ts.isoformat(timespec="seconds"), "ok": x.ok, "down": x.down_mbps, "up": x.up_mbps,
                       "ping": x.ping_ms, "jitter": x.jitter_ms, "loss": x.loss, "server": x.server, "url": x.url,
                       "err": x.error, "src": x.source or "router"} for x in sp],
            "speed_running": SPD_STATE["running"] and SPD_STATE["rid"] == rid, "speed_phase": tr(SPD_STATE["phase"]) if SPD_STATE["phase"] else ""}


@app.post("/routers/{rid}/logip", dependencies=[Depends(admin)])
def set_logip(rid: int, ip: str = Form(""), s: Session = Depends(db)):
    r = s.get(Router, rid)
    if r:
        ip = ip.strip()
        if ip:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                return RedirectResponse("/routers/%d#cfg" % rid, 303)
            r.log_ip, r.log_ip_fixed = ip, True
        else:
            r.log_ip_fixed = False
        log(s, "adres logów", "%s: %s" % (r.name, ip or "auto"))
        s.commit()
        refresh_ipmap()
    return RedirectResponse("/routers/%d#cfg" % rid, 303)


# ---------- interfejsy, transfer, klienci (API dla wykresów) ----------
IF_GROUPS = [("Ethernet", ("ether", "sfp", "combo", "qsfp")), ("VLAN", ("vlan",)), ("Bridge", ("bridge",)),
             ("Wi-Fi", ("wlan", "wifi", "cap", "wifiwave2")), ("PPPoE", ("pppoe",)),
             ("VPN i tunele", ("wg", "l2tp", "ovpn", "sstp", "pptp", "gre", "eoip", "ipip", "6to4", "vxlan", "ipsec")),
             ("LTE", ("lte",)), ("Bonding", ("bond",))]


def if_group(name, typ):
    key = (typ or "").lower() or name.lower()
    for g, prefixes in IF_GROUPS:
        if any(key.startswith(p) for p in prefixes):
            return g
    if not typ:  # stary skrypt bez typu: zgadnij po nazwie
        for g, prefixes in IF_GROUPS:
            if any(p in name.lower() for p in prefixes):
                return g
    return "Inne"


@app.get("/api/routers/{rid}/ifaces/overview", dependencies=[Depends(user)])
def ifaces_overview(rid: int, s: Session = Depends(db)):
    r = s.get(Router, rid)
    if not r:
        raise HTTPException(404)
    names, wan, _ = wan_info(s, r)
    last = s.scalar(select(func.max(IfaceMetric.ts)).where(IfaceMetric.router_id == rid))
    curr = {x.name: x for x in s.scalars(select(IfaceMetric).where(IfaceMetric.router_id == rid,
                                                                   IfaceMetric.ts == last))} if last else {}
    b = func.floor(extract("epoch", IfaceMetric.ts) / 120)
    spark = {}
    for name, _, rx, tx in s.execute(select(IfaceMetric.name, b, func.avg(IfaceMetric.rx_bps), func.avg(IfaceMetric.tx_bps))
                                     .where(IfaceMetric.router_id == rid, IfaceMetric.ts > now() - dt.timedelta(hours=1))
                                     .group_by(IfaceMetric.name, b).order_by(IfaceMetric.name, b)).all():
        sp = spark.setdefault(name, {"rx": [], "tx": []})
        sp["rx"].append(mb(fl(rx)))
        sp["tx"].append(mb(fl(tx)))
    try:
        types = json.loads(r.iface_types or "{}")
    except ValueError:
        types = {}
    groups = {}
    for name in names:
        x = curr.get(name)
        groups.setdefault(if_group(name, types.get(name)), []).append({
            "name": name, "type": types.get(name, ""), "wan": name == wan,
            "rx": mb(x.rx_bps) if x else None, "tx": mb(x.tx_bps) if x else None,
            "spark": spark.get(name, {"rx": [], "tx": []})})
    order = [g for g, _ in IF_GROUPS] + ["Inne"]
    out = []
    for g in order:
        if g in groups:
            items = sorted(groups[g], key=lambda i: -((i["rx"] or 0) + (i["tx"] or 0)))
            out.append({"group": g, "items": items, "rx": round(sum(i["rx"] or 0 for i in items), 3),
                        "tx": round(sum(i["tx"] or 0 for i in items), 3)})
    return {"groups": out}


@app.get("/api/routers/{rid}/traffic", dependencies=[Depends(user)])
def traffic_api(rid: int, days: int = 30, s: Session = Depends(db)):
    days = max(7, min(days, 400))
    rows = s.scalars(select(TrafficDay).where(TrafficDay.router_id == rid).order_by(TrafficDay.day)).all()
    gb = lambda v: round((v or 0) / 1e9, 2)
    daily = [{"day": x.day.isoformat(), "rx": gb(x.rx), "tx": gb(x.tx)} for x in rows][-days:]
    months = {}
    for x in rows:
        k = x.day.strftime("%Y-%m")
        m = months.setdefault(k, [0, 0])
        m[0] += x.rx
        m[1] += x.tx
    mlist = [{"month": k, "rx": gb(v[0]), "tx": gb(v[1])} for k, v in sorted(months.items())][-12:]
    return {"daily": daily, "months": mlist, "iface": rows[-1].iface if rows else ""}


@app.get("/api/routers/{rid}/clients", dependencies=[Depends(user)])
def clients_api(rid: int, hours: int = 24, s: Session = Depends(db)):
    hours = max(1, min(hours, 720))
    b = func.floor(extract("epoch", ClientStat.ts) / buckets(hours))
    rows = s.execute(select(func.min(ClientStat.ts), func.avg(ClientStat.dev_on), func.avg(ClientStat.dev_total),
                            func.avg(ClientStat.wifi), func.avg(ClientStat.vpn_on))
                     .where(ClientStat.router_id == rid, ClientStat.ts > now() - dt.timedelta(hours=hours))
                     .group_by(b).order_by(b)).all()
    return {"t": [x[0].isoformat(timespec="seconds") for x in rows],
            "dev_on": [fl(x[1], round) for x in rows], "dev_total": [fl(x[2], round) for x in rows],
            "wifi": [fl(x[3], round) for x in rows], "vpn_on": [fl(x[4], round) for x in rows]}


# ---------- analiza logów (tłumacz komunikatów RouterOS) ----------
MGMT_PORTS = {"21": "FTP", "22": "SSH", "23": "Telnet", "80": "WWW", "443": "WWW (HTTPS)", "8291": "Winbox",
              "8728": "API", "8729": "API-SSL", "3389": "an.001", "53": "DNS", "161": "SNMP"}
SVC_NAMES = {"ssh": "SSH", "telnet": "Telnet", "winbox": "Winbox", "web": "an.002", "www": "an.002",
             "api": "API", "ftp": "FTP", "rest-api": "REST API", "local": "an.003", "dude": "The Dude"}
SVC_PLAIN = {"web": "WWW / WebFig", "www": "WWW / WebFig", "local": "an.004", "rest-api": "REST API"}
WIFI_REASONS = [
    ("extensive data loss", "an.005"),
    ("group key exchange timeout", "an.006"),
    ("4-way handshake timeout", "an.007"),
    ("handshake timeout", "an.007"),
    ("inactivity", "an.008"),
    ("received deauth", "an.009"),
    ("received disassoc", "an.009"),
    ("roamed", "an.010"),
    ("ok", "an.011"),
]


def is_public(ip):
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
        return not (a.is_private or a.is_loopback or a.is_link_local)
    except ValueError:
        return False


def _r(rx):
    return re.compile(rx, re.I)


# Każda reguła: (id, wyrażenie, funkcja(match, topics) -> dict albo None)
# dict: title, level ('bad'|'warn'|'info'), explain, advice, det {etykieta: wartość}
def _login_fail(m, tp):
    ip, svc = m.group("ip"), L(SVC_NAMES.get(m.group("svc").lower(), m.group("svc")))
    if is_public(ip):
        return {"id": "login_fail_wan", "level": "bad", "title": tr("an.012") % svc,
                "explain": tr("an.013"),
                "advice": tr("an.014") % m.group("svc").lower(),
                "det": {tr("an.015"): ip, tr("an.016"): m.group("user"), tr("an.017"): svc}}
    return {"id": "login_fail_lan", "level": "warn", "title": tr("an.018") % svc,
            "explain": tr("an.019"),
            "advice": tr("an.020"),
            "det": {tr("an.015"): ip, tr("an.016"): m.group("user"), tr("an.017"): svc}}


def _login_ok(m, tp):
    ip, k = m.group("ip"), m.group("svc").lower()
    svc = L(SVC_PLAIN.get(k) or SVC_NAMES.get(k, m.group("svc")))
    if is_public(ip):
        return {"id": "login_ok_wan", "level": "warn", "title": tr("an.021") % svc,
                "explain": tr("an.022"),
                "advice": tr("an.023"),
                "det": {tr("an.015"): ip, tr("an.016"): m.group("user"), tr("an.017"): svc}}
    return {"id": "login_ok", "level": "info", "title": tr("an.024") % svc,
            "explain": tr("an.025"),
            "advice": "", "det": {tr("an.016"): m.group("user"), tr("an.015"): ip}}


def _logout(m, tp):
    return {"id": "logout", "level": "info", "title": tr("an.026"),
            "explain": tr("an.027"), "advice": "", "det": {tr("an.016"): m.group("user")}}


def _cfg_change(m, tp):
    return {"id": "cfg_change", "level": "info", "title": tr("an.028"),
            "explain": tr("an.029"),
            "advice": tr("an.030"),
            "det": {tr("an.031"): m.group("user"), tr("an.032"): m.group("what")[:60]}}


def _dhcp_assigned(m, tp):
    return {"id": "dhcp_assigned", "level": "info", "title": tr("an.033"),
            "explain": tr("an.034"),
            "advice": "", "det": {tr("an.035"): (m.group("host") or "").strip() or m.group("mac"), tr("an.015"): m.group("ip")}}


def _dhcp_deassigned(m, tp):
    return {"id": "dhcp_deassigned", "level": "info", "title": tr("an.036"),
            "explain": tr("an.037"),
            "advice": "", "det": {tr("an.015"): m.group("ip"), tr("an.038"): m.group("mac")}}


def _dhcp_nosuccess(m, tp):
    return {"id": "dhcp_fail", "level": "warn", "title": tr("an.039"),
            "explain": tr("an.040"),
            "advice": tr("an.041"), "det": {tr("an.038"): m.group("mac")}}


def _dhcp_pool(m, tp):
    return {"id": "dhcp_pool", "level": "bad", "title": tr("an.042"),
            "explain": tr("an.043"),
            "advice": tr("an.044"),
            "det": {}}


def _conflict(m, tp):
    return {"id": "ip_conflict", "level": "warn", "title": tr("an.045"),
            "explain": tr("an.046"),
            "advice": tr("an.047"),
            "det": {}}


def _link_down(m, tp):
    return {"id": "link_down", "level": "warn", "title": tr("an.048"),
            "explain": tr("an.049"),
            "advice": tr("an.050"),
            "det": {tr("an.051"): m.group("iface")}}


def _link_up(m, tp):
    sp = (m.group("speed") or "").strip()
    if re.match(r"^(10|100)M", sp):
        return {"id": "link_slow", "level": "warn", "title": tr("an.052"),
                "explain": tr("an.053") % sp,
                "advice": tr("an.054"),
                "det": {tr("an.051"): m.group("iface"), tr("an.055"): sp}}
    return {"id": "link_up", "level": "info", "title": tr("an.056"),
            "explain": tr("an.057"), "advice": "", "det": {tr("an.051"): m.group("iface")}}


def _wifi_conn(m, tp):
    return {"id": "wifi_conn", "level": "info", "title": tr("an.058"),
            "explain": tr("an.059"), "advice": "",
            "det": {tr("an.051"): m.group("iface"), tr("an.038"): m.group("mac")}}


def _wifi_disc(m, tp):
    reason = (m.group("reason") or "").strip().lower()
    why = next((tr(txt) for key, txt in WIFI_REASONS if key in reason), reason or tr("an.060"))
    bad = any(k in reason for k in ("data loss", "handshake", "key exchange"))
    return {"id": "wifi_disc_bad" if bad else "wifi_disc", "level": "warn" if bad else "info",
            "title": tr("an.061") + why.split(":")[0],
            "explain": tr("an.062") % why,
            "advice": (tr("an.063")) if bad else "",
            "det": {tr("an.051"): m.group("iface"), tr("an.038"): m.group("mac")}}


def _caps(m, tp):
    up = "disconn" not in m.group(0).lower() and "lost" not in m.group(0).lower()
    return {"id": "caps_up" if up else "caps_down", "level": "info" if up else "warn",
            "title": tr("an.064") if up else tr("an.065"),
            "explain": tr("an.066") if up else
                       tr("an.067"),
            "advice": "" if up else tr("an.068"), "det": {}}


def _reboot_bad(m, tp):
    return {"id": "reboot_unclean", "level": "bad", "title": tr("an.069"),
            "explain": tr("an.070"),
            "advice": tr("an.071"), "det": {}}


def _reboot(m, tp):
    return {"id": "reboot", "level": "warn", "title": tr("an.072"),
            "explain": tr("an.073"),
            "advice": tr("an.074"), "det": {}}


def _script_fail(m, tp):
    txt = m.group(0).lower()
    if "502" in txt or "bad gateway" in txt:
        why = tr("an.075")
    elif "timeout" in txt or "timed out" in txt or "connection refused" in txt or "could not connect" in txt:
        why = tr("an.076")
    elif "bad command" in txt or "syntax error" in txt:
        why = tr("an.077")
    else:
        why = tr("an.078")
    return {"id": "script_fail", "level": "warn", "title": tr("an.079") + why,
            "explain": tr("an.080"),
            "advice": tr("an.081"), "det": {}}


def _firewall(m, tp):
    src, dst, dport, chain = m.group("src"), m.group("dst"), m.group("dport") or "", m.group("chain").lower()
    svc = L(MGMT_PORTS.get(dport))
    if chain == "input" and is_public(src) and svc:
        return {"id": "fw_mgmt_probe", "level": "warn", "title": tr("an.082") % svc,
                "explain": tr("an.083") % (dport, svc),
                "advice": tr("an.084"), "det": {tr("an.085"): src, tr("an.086"): "%s (%s)" % (dport, svc)}}
    return {"id": "fw_log", "level": "info", "title": tr("an.087") % chain,
            "explain": tr("an.088"),
            "advice": tr("an.089"),
            "det": {tr("an.085"): src, tr("an.090"): "%s:%s" % (dst, dport) if dport else dst}}


def _pppoe(m, tp):
    return {"id": "pppoe_down", "level": "bad", "title": tr("an.091"),
            "explain": tr("an.092"),
            "advice": tr("an.093"), "det": {tr("an.051"): m.group("iface")}}


def _wg(m, tp):
    return {"id": "wg_handshake", "level": "warn", "title": tr("an.094"),
            "explain": tr("an.095"),
            "advice": tr("an.096"), "det": {}}


def _loop(m, tp):
    return {"id": "loop", "level": "bad", "title": tr("an.097"),
            "explain": tr("an.098"),
            "advice": tr("an.099"),
            "det": {tr("an.051"): m.group("iface")}}


def _poe(m, tp):
    return {"id": "poe", "level": "warn", "title": tr("an.100"),
            "explain": tr("an.101"),
            "advice": tr("an.102"),
            "det": {tr("an.051"): m.group("iface")}}


def _memory(m, tp):
    return {"id": "memory", "level": "bad", "title": tr("an.103"),
            "explain": tr("an.104"),
            "advice": tr("an.105"),
            "det": {}}


_ANA_SERVER = set()  # adresy serwera aplikacji (ustawiane przy każdej analizie)
CFG_ACTIONS = [("new script scheduled", "an.106"), ("removed from scheduler", "an.107"),
               ("scheduler changed", "an.108"), ("new script added", "an.109"),
               ("script added", "an.109"), ("script removed", "an.110"), ("script changed", "an.111"),
               ("added", "an.112"), ("removed", "an.113"), ("changed", "an.114"),
               ("moved", "an.115"), ("enabled", "an.116"), ("disabled", "an.117")]


def _client(c):
    c = c.lower()
    for k, v in (("winbox", "Winbox"), ("ssh", "SSH"), ("telnet", "Telnet"), ("web", "WebFig"), ("www", "WebFig"),
                 ("api", "API"), ("import", tr("an.118")), ("scheduler", tr("an.119")), ("script", tr("an.120"))):
        if k in c:
            return v
    return c[:30]


def _cfg_by(m, tp):
    what, cmd = m.group("what").strip(), (m.group("cmd") or "").strip()
    act = next((tr(v) for k, v in CFG_ACTIONS if k in what.lower()), tr("an.121"))
    det = {tr("an.031"): m.group("user"), tr("an.122"): act, tr("an.123"): _client(m.group("client")), tr("an.124"): m.group("addr")}
    if "app-" in cmd or "app-" in what:
        return {"id": "cfg_app", "level": "info", "title": tr("an.125"),
                "explain": tr("an.126"),
                "advice": tr("an.127"),
                "det": det}
    det[tr("an.128")] = cmd[:70]
    return {"id": "cfg_change", "level": "info", "title": tr("an.028"),
            "explain": tr("an.129"),
            "advice": tr("an.130"),
            "det": det}


def _script_fragment(m, tp):
    return {"id": "script_fragment", "level": "info", "title": tr("an.131"),
            "explain": tr("an.132"),
            "advice": tr("an.133"), "det": {}}


def _bad_cmd(m, tp):
    cmd = m.group("cmd") if "cmd" in m.groupdict() and m.group("cmd") else ""
    known = {"wireless": tr("an.134"),
             "wifi": tr("an.135"),
             "health": tr("an.136")}
    why = known.get(cmd.lower(), tr("an.137") % cmd if cmd else
                    tr("an.138"))
    return {"id": "script_syntax", "level": "warn", "title": tr("an.139"),
            "explain": tr("an.140") % why,
            "advice": tr("an.141"),
            "det": {tr("an.128"): cmd, tr("an.142"): "linia %s, kolumna %s" % (m.group("line"), m.group("col"))}}


def _exec_script(m, tp):
    name = m.group("name")
    return {"id": "script_exec_fail", "level": "warn", "title": tr("an.143") % (tr("an.144") if name.startswith("app-") else tr("an.145")),
            "explain": tr("an.146"),
            "advice": tr("an.147"),
            "det": {tr("an.148"): name}}


def _fetch(m, tp):
    ip, ok = m.group("host"), m.group("res").upper() == "FINISHED"
    ours = ip in _ANA_SERVER
    if ok:
        return {"id": "fetch_ok_app" if ours else "fetch_ok", "level": "info",
                "title": tr("an.149") if ours else tr("an.150") % ip,
                "explain": (tr("an.151")) if ours else
                           tr("an.152"),
                "advice": (tr("an.153"))
                          if ours else "", "det": {tr("an.154"): ip}}
    return {"id": "fetch_fail", "level": "warn", "title": tr("an.155") % ip,
            "explain": tr("an.156"),
            "advice": tr("an.157"), "det": {tr("an.154"): ip}}


def _cap_connected(m, tp):
    return {"id": "cap_connected", "level": "info", "title": tr("an.158"),
            "explain": tr("an.159")
                       % m.group("name"), "advice": "", "det": {tr("an.160"): "%s (%s)" % (m.group("name"), m.group("ip"))}}


def _cap_selected(m, tp):
    return {"id": "cap_selected", "level": "info", "title": tr("an.161"),
            "explain": tr("an.162") % m.group("name"), "advice": "",
            "det": {tr("an.160"): "%s (%s)" % (m.group("name"), m.group("ip"))}}


def _cap_lost(m, tp):
    return {"id": "cap_lost", "level": "warn", "title": tr("an.163"),
            "explain": tr("an.164") % m.group("name"),
            "advice": tr("an.165"),
            "det": {tr("an.160"): "%s (%s)" % (m.group("name"), m.group("ip"))}}



def _time_change(m, tp):
    src_ = (m.group("src") or "").lower()
    who = {"cloud": tr("an.166"), "ntp": tr("an.167"), "sntp": tr("an.167")}.get(src_, tr("an.168"))
    diff = None
    try:
        a = dt.datetime.strptime(m.group("a"), "%b/%d/%Y %H:%M:%S")
        b = dt.datetime.strptime(m.group("b"), "%b/%d/%Y %H:%M:%S")
        diff = int((b - a).total_seconds())
    except ValueError:
        pass
    big = diff is not None and abs(diff) > 300
    nom = {"cloud": "MikroTik IP Cloud", "ntp": "NTP", "sntp": "NTP"}.get(src_, "synchronizacja czasu")
    det = {tr("an.085"): nom, tr("an.169"): ("%+d s" % diff) if diff is not None else "?"}
    return {"id": "time_change_big" if big else "time_change", "level": "warn" if big else "info",
            "title": tr("an.170") if big else tr("an.171"),
            "explain": (tr("an.172") % who) +
                       (tr("an.173")
                        if big else tr("an.174")),
            "advice": tr("an.175") if big or src_ == "cloud" else "",
            "det": det}


def _dhcp_client(m, tp):
    got = m.group("act").lower() == "got"
    return {"id": "dhcp_client_got" if got else "dhcp_client_lost", "level": "info" if got else "warn",
            "title": tr("an.176") if got else tr("an.177"),
            "explain": (tr("an.178") % m.group("iface")) if got else
                       (tr("an.179") % m.group("iface")),
            "advice": "" if got else tr("an.180"),
            "det": {tr("an.051"): m.group("iface"), tr("an.015"): m.group("ip") or ""}}


def _pkg(m, tp):
    name, ver, inst = m.group("pkg"), m.group("ver"), m.group("act").lower() == "installed"
    label = "RouterOS (system)" if name in ("system", "routeros") else name
    return {"id": "pkg_installed" if inst else "pkg_removed", "level": "info",
            "title": tr("an.181") if inst else tr("an.182"),
            "explain": (tr("an.183")
                        % (label, ver)) if inst else tr("an.184") % (label, ver),
            "advice": tr("an.185") if inst and name in ("system", "routeros") else "",
            "det": {tr("an.186"): "%s %s" % (label, ver)}}


LOG_RULES = [
    (_r(r"\\; ?\\n|\\5B|on-error=\{\}|\$send u=\$url|\$buf \.|\[:len \\?\$buf\]"), _script_fragment),
    (_r(r"^(?P<what>.+?) by (?P<client>[^\s:]+):(?P<user>[^@\s]+)@(?P<addr>[0-9a-f:.]+?)/(?P<path>\S*)(?:\s+\((?P<cmd>.*)\))?\s*$"), _cfg_by),
    (_r(r"(?:download from|upload to) (?P<host>\S+) (?P<res>finished|failed)"), _fetch),
    (_r(r"bad command name (?P<cmd>\S+) \(line (?P<line>\d+) column (?P<col>\d+)\)"), _bad_cmd),
    (_r(r"(?:syntax error|bad parameter (?P<cmd>\S+)) \(line (?P<line>\d+) column (?P<col>\d+)\)"), _bad_cmd),
    (_r(r"^executing script (?P<name>\S+)"), _exec_script),
    (_r(r"selected capsman (?P<name>\S+?)@(?P<ip>[\d.]+)"), _cap_selected),
    (_r(r"^connected to (?P<name>\S+?)@(?P<ip>[\d.]+)"), _cap_connected),
    (_r(r"^(?:disconnected from|lost connection to) (?P<name>\S+?)@(?P<ip>[\d.]+)"), _cap_lost),
    (_r(r"(?:(?P<src>cloud|ntp|sntp) )?change time (?P<a>\w{3}/\d\d/\d{4} \d\d:\d\d:\d\d) => (?P<b>\w{3}/\d\d/\d{4} \d\d:\d\d:\d\d)"), _time_change),
    (_r(r"^(?P<client>\S+) on (?P<iface>\S+) (?P<act>got|lost) ip address(?: (?P<ip>[\d.]+))?"), _dhcp_client),
    (_r(r"^(?P<act>installed|uninstalled) (?P<pkg>[a-z0-9-]+?)-(?P<ver>\d+(?:\.\d+)+(?:beta\d+|rc\d+)?)\b"), _pkg),
    (_r(r"login failure for user (?P<user>\S+) from (?P<ip>[0-9a-f.:]+) via (?P<svc>[\w-]+)"), _login_fail),
    (_r(r"user (?P<user>\S+) logged in from (?P<ip>[0-9a-f.:]+) via (?P<svc>[\w-]+)"), _login_ok),
    (_r(r"user (?P<user>\S+) logged out from (?P<ip>[0-9a-f.:]+) via (?P<svc>[\w-]+)"), _logout),
    (_r(r"rebooted without proper shutdown|unexpected (reboot|shutdown)|kernel failure|watchdog"), _reboot_bad),
    (_r(r"router rebooted|system rebooted|rebooted by"), _reboot),
    (_r(r"out of memory|memory (is )?low"), _memory),
    (_r(r"(?P<iface>\S+?):? excessive (broadcasts|multicasts)|loop detected|probably a loop"), _loop),
    (_r(r"(?P<iface>\S+?):? poe[- ]out status: (short|overload|current_too_low|power_reset|voltage)"), _poe),
    (_r(r"failure: .*|script error|executing script .* failed"), _script_fail),
    (_r(r"(?P<chain>input|forward|output|srcnat|dstnat|prerouting|postrouting): in:\S+ out:\S+.*?proto (?P<proto>\w+).*?"
        r"(?P<src>\d+\.\d+\.\d+\.\d+)(?::\d+)?->(?P<dst>\d+\.\d+\.\d+\.\d+)(?::(?P<dport>\d+))?"), _firewall),
    (_r(r"(?P<srv>\S+) assigned (?P<ip>\d+\.\d+\.\d+\.\d+) (?:for|to) (?P<mac>[0-9a-f]{2}(?::[0-9a-f]{2}){5})\s*(?P<host>.*)"), _dhcp_assigned),
    (_r(r"(?P<srv>\S+) deassigned (?P<ip>\d+\.\d+\.\d+\.\d+) (?:for|from) (?P<mac>[0-9a-f]{2}(?::[0-9a-f]{2}){5})"), _dhcp_deassigned),
    (_r(r"offering lease \S+ for (?P<mac>[0-9a-f]{2}(?::[0-9a-f]{2}){5}) without success"), _dhcp_nosuccess),
    (_r(r"failed to give out ip address|no (more )?free (ip )?address|pool .* (is )?empty"), _dhcp_pool),
    (_r(r"conflict|address already (in )?use|duplicate address"), _conflict),
    (_r(r"(?P<iface>\S+?):? link down"), _link_down),
    (_r(r"(?P<iface>\S+?):? link up(?: \(speed (?P<speed>[^,)]+))?"), _link_up),
    (_r(r"(?P<mac>[0-9a-f]{2}(?::[0-9a-f]{2}){5})@(?P<iface>[\w.-]+):? disconnected,?\s*(?P<reason>.*)"), _wifi_disc),
    (_r(r"(?P<mac>[0-9a-f]{2}(?::[0-9a-f]{2}){5})@(?P<iface>[\w.-]+):? (?:connected|established)"), _wifi_conn),
    (_r(r"\bcap\b.*\b(connected|disconnected|lost|joined)\b|capsman.*\b(connected|disconnected|lost)\b"), _caps),
    (_r(r"(?P<iface>pppoe[\w-]*):? (?:terminating|disconnected)|peer is not responding"), _pppoe),
    (_r(r"handshake for peer did not complete"), _wg),
    (_r(r"(?P<what>.+?) (?:changed|added|removed) by (?P<user>[\w.@-]+)"), _cfg_change),
]


def translate_log(msg, topics=""):
    for rx, fn in LOG_RULES:
        m = rx.search(msg)
        if m:
            try:
                res = fn(m, topics)
            except (IndexError, AttributeError):
                res = None
            if res:
                return res
    return None


def _norm(msg):
    return re.sub(r"\d+", "#", msg)[:120]


@app.get("/api/routers/{rid}/logs/analysis", dependencies=[Depends(user)])
def logs_analysis(request: Request, rid: int, hours: int = 24, s: Session = Depends(db)):
    global _ANA_SERVER
    _ANA_SERVER = {x for x in (syslog_target(request), os.getenv("SYSLOG_HOST"), request.url.hostname) if x}
    hours = max(1, min(hours, 168))
    rows = s.execute(select(LogEntry.ts, LogEntry.sev, LogEntry.topics, LogEntry.msg)
                     .where(LogEntry.router_id == rid, LogEntry.ts > now() - dt.timedelta(hours=hours))
                     .order_by(LogEntry.ts.desc()).limit(20000)).all()
    groups, unknown = {}, {}
    for ts, sev, tp, msg in rows:
        res = translate_log(msg, tp)
        if not res:
            u = unknown.setdefault(_norm(msg), {"msg": msg, "count": 0, "last": ts, "cls": sev_cls(sev)})
            u["count"] += 1
            continue
        g = groups.get(res["id"])
        if not g:
            g = groups[res["id"]] = {"id": res["id"], "level": res["level"], "title": res["title"], "explain": res["explain"],
                                     "advice": res["advice"], "count": 0, "first": ts, "last": ts, "det": {}, "examples": []}
        g["count"] += 1
        g["first"] = min(g["first"], ts)
        g["last"] = max(g["last"], ts)
        if res["level"] == "bad" and g["level"] != "bad":
            g["level"] = "bad"
        for k, v in res["det"].items():
            if v:
                d = g["det"].setdefault(k, {})
                d[v] = d.get(v, 0) + 1
        if len(g["examples"]) < 3:
            g["examples"].append(msg)
    # brute force: wiele nieudanych logowań z jednego publicznego adresu
    lf = groups.get("login_fail_wan")
    if lf:
        top = max(lf["det"].get(tr("an.015"), {}).values() or [0])
        if top >= 5:
            lf["title"] = tr("an.187")
            lf["explain"] = (tr("an.188")) % top + " " + lf["explain"].split(". ", 1)[-1]
    # częste zmiany stanu łącza na tym samym porcie = flapping
    ld = groups.get("link_down")
    if ld and max(ld["det"].get(tr("an.051"), {}).values() or [0]) >= 5:
        ld["level"] = "bad"
        ld["title"] = tr("an.189")
    out = []
    for g in groups.values():
        g["det"] = {k: sorted(v.items(), key=lambda x: -x[1])[:5] for k, v in g["det"].items()}
        g["first"], g["last"] = g["first"].isoformat(timespec="seconds"), g["last"].isoformat(timespec="seconds")
        out.append(g)
    order = {"bad": 0, "warn": 1, "info": 2}
    out.sort(key=lambda g: (order[g["level"]], -g["count"]))
    unk = sorted(unknown.values(), key=lambda u: -u["count"])[:15]
    for u in unk:
        u["last"] = u["last"].isoformat(timespec="seconds")
    can_ban = bool(request.state.user.is_admin and blacklist_on(s))
    banned = []
    if can_ban:
        for g in out:
            if g["id"] == "login_fail_wan":
                g["ban_key"] = tr("an.015")
        banned = [w.ip for w in s.scalars(select(Whitelist).where(Whitelist.kind == "black", Whitelist.active == True))]  # noqa: E712
    return {"groups": out, "unknown": unk, "total": len(rows), "can_ban": can_ban, "banned": banned, "rule": BL_RULE,
            "summary": {k: sum(g["count"] for g in out if g["level"] == k) for k in order}}


@app.post("/api/blacklist/ban", dependencies=[Depends(admin)])
def ban_from_log(request: Request, ip: str = Form(), rid: str = Form(""), s: Session = Depends(db)):
    """Przycisk 'Banuj' w analizie logów: dodaje adres do blacklisty (bez wygaśnięcia, dla wszystkich routerów)."""
    try:
        net = parse_ip(ip)
    except ValueError:
        return JSONResponse({"ok": False, "msg": tr("msg.wl_bad_addr")}, 400)
    why = ban_error(net, request, s)
    if why:
        return JSONResponse({"ok": False, "msg": why}, 400)
    if s.scalar(select(Whitelist.id).where(Whitelist.kind == "black", Whitelist.ip == net, Whitelist.active == True)):  # noqa: E712
        return {"ok": True, "msg": tr("msg.ban_dup"), "ip": net}
    s.add(Whitelist(kind="black", ip=net, comment=cmt(tr("msg.ban_comment")), expires=None, router_id=None))
    log(s, "blacklist+", "%s (%s) zakres=wszystkie, z analizy logów routera %s" % (net, cmt(tr("msg.ban_comment")), rid or "?"))
    s.commit()
    return {"ok": True, "msg": tr("msg.ban_ok"), "ip": net}


# ---------- RouterOS update check ----------
_VER = {}


def vtuple(v):
    m = re.match(r"(\d+(?:\.\d+)*)(?:(beta|rc)(\d+))?", v or "")
    if not m:
        return None
    nums = tuple(int(x) for x in m.group(1).split("."))
    nums = nums + (0,) * (4 - len(nums))
    pre = (0 if m.group(2) == "beta" else 1, int(m.group(3))) if m.group(2) else (2, 0)
    return nums + pre


def latest_version(major, channel):
    key = (major, channel)
    c = _VER.get(key)
    if c and time.time() - c[1] < (6 * 3600 if c[0] else 1800):
        return c[0]
    v = None
    try:
        url = "https://upgrade.mikrotik.com/routeros/NEWEST%s.%s" % ("a7" if major >= 7 else "6", channel)
        resp = httpx.get(url, timeout=5)
        tok = resp.text.split()[0] if resp.status_code == 200 and resp.text.strip() else ""
        if re.fullmatch(r"\d+(\.\d+)+((beta|rc)\d+)?", tok):
            v = tok
    except Exception:
        pass
    _VER[key] = (v, time.time())
    return v


def update_available(r):
    """Zwraca nowszą wersję RouterOS z tego samego kanału (stable/long-term/testing) albo None."""
    m = re.match(r"\s*(\S+)\s*(?:\((\S+)\))?", r.ver or "")
    cur = vtuple(m.group(1)) if m else None
    if not cur:
        return None
    channel = (m.group(2) or "stable").lower()
    if channel not in ("stable", "long-term", "testing", "development"):
        channel = "stable"
    new = latest_version(cur[0], channel)
    return new if new and vtuple(new) > cur else None


# ---------- whitelist ----------
HOST_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$")


def parse_ip(ip):
    """Adres IPv4, sieć IPv4 (CIDR) albo nazwa domeny (router sam ją rozwiązuje przez DNS)."""
    ip = ip.strip().lower().rstrip(".")
    try:
        net = str(ipaddress.ip_network(ip, strict=False))
    except ValueError:
        if HOST_RE.match(ip) and not re.fullmatch(r"[\d.]+", ip):
            return ip
        raise
    if ":" in net:
        raise ValueError("ipv4 only")
    return net[:-3] if net.endswith("/32") else net


def cmt(c):
    return re.sub(r"[^\w .\-@]", "", c or "")[:60]


def scope(v):
    return int(v) if str(v).strip().isdigit() else None


def parse_exp(x):
    """liczba dni | RRRR-MM-DD (ważne do końca tego dnia) | RRRR-MM-DD GG:MM (dokładny czas, UTC)"""
    x = (x or "").strip()
    if x.isdigit() and int(x) > 0:
        return now() + dt.timedelta(days=int(x))
    try:
        return dt.datetime.strptime(x, "%Y-%m-%d %H:%M")
    except ValueError:
        pass
    try:
        return dt.datetime.strptime(x, "%Y-%m-%d") + dt.timedelta(days=1)
    except ValueError:
        return None


def fmt_exp(e):
    if not e:
        return ""
    if e.time() == dt.time(0):
        return (e - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    return e.strftime("%Y-%m-%d %H:%M")


def list_kind(request):
    return "black" if request.url.path.startswith("/blacklist") else "white"


def back(kind="white", msg="", level="err"):
    return RedirectResponse(("/blacklist" if kind == "black" else "/whitelist") + ("?%s=%s" % (level, quote(msg)) if msg else ""), 303)


def ban_error(net, request, s):
    """Zabezpieczenie blacklisty przed odcięciem sobie dostępu: tekst błędu albo ""."""
    mine = [request.client.host if request.client else "", syslog_target(request), os.getenv("SYSLOG_HOST", "")]
    mine += [ip for ip in s.scalars(select(Router.log_ip)) if ip]
    code = netguard.check_ban(net, mine, request.url.hostname or "")
    return {"": "", "bad": tr("msg.bl_bad"), "broad": tr("msg.bl_broad"), "self": tr("msg.bl_self")}[code]


@app.get("/whitelist", dependencies=[Depends(user)])
@app.get("/blacklist", dependencies=[Depends(user)])
def wl_page(request: Request, s: Session = Depends(db), err: str = "", ok: str = ""):
    kind = list_kind(request)
    items = s.scalars(select(Whitelist).where(Whitelist.kind == kind).order_by(Whitelist.id)).all()
    routers = ordered_routers(s)
    return templates.TemplateResponse(request, "whitelist.html", {
        "items": items, "routers": routers, "names": {r.id: r.name for r in routers},
        "err": err, "ok": ok, "now": now(), "kind": kind, "base": "/blacklist" if kind == "black" else "/whitelist",
        "wl_enabled": whitelist_on(s), "bl_enabled": blacklist_on(s), "bl_rule": BL_RULE})


@app.post("/whitelist", dependencies=[Depends(admin)])
@app.post("/blacklist", dependencies=[Depends(admin)])
def wl_add(request: Request, ip: str = Form(), comment: str = Form(""), days: str = Form(""), router: str = Form(""),
           s: Session = Depends(db)):
    kind = list_kind(request)
    try:
        net = parse_ip(ip)
    except ValueError:
        return back(kind, tr("msg.wl_bad_addr"))
    if kind == "black":
        why = ban_error(net, request, s)
        if why:
            return back(kind, why)
    s.add(Whitelist(kind=kind, ip=net, comment=cmt(comment), expires=parse_exp(days), router_id=scope(router)))
    log(s, ("blacklist+" if kind == "black" else "whitelist+"), "%s (%s) zakres=%s" % (net, cmt(comment), scope(router) or "wszystkie"))
    s.commit()
    return back(kind)


@app.post("/whitelist/import", dependencies=[Depends(admin)])
@app.post("/blacklist/import", dependencies=[Depends(admin)])
def wl_import(request: Request, data: str = Form(""), router: str = Form(""), s: Session = Depends(db)):
    kind = list_kind(request)
    default = scope(router)
    ids = {r.name: r.id for r in s.scalars(select(Router))}
    have = {(w.ip, w.router_id) for w in s.scalars(select(Whitelist).where(Whitelist.kind == kind))}
    added = bad = 0
    for line in data.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = [x.strip() for x in next(csv.reader([line]))]
        if p[0].lower() == "ip":
            continue
        try:
            ip = parse_ip(p[0])
        except ValueError:
            bad += 1
            continue
        if kind == "black" and ban_error(ip, request, s):
            bad += 1
            continue
        if len(p) > 3 and p[3]:
            if p[3] not in ids:  # nieznany router: nie rozszerzaj po cichu na wszystkie routery
                bad += 1
                continue
            rid = ids[p[3]]
        else:
            rid = default
        if (ip, rid) in have:
            continue
        s.add(Whitelist(kind=kind, ip=ip, comment=cmt(p[1] if len(p) > 1 else ""),
                        expires=parse_exp(p[2]) if len(p) > 2 else None, router_id=rid))
        have.add((ip, rid))
        added += 1
    log(s, ("blacklist" if kind == "black" else "whitelist") + " import", "dodano %d, błędnych %d" % (added, bad))
    s.commit()
    return back(kind, tr("msg.wl_imported", added=added, bad=bad), "ok")


@app.get("/whitelist/export", dependencies=[Depends(admin)])
@app.get("/blacklist/export", dependencies=[Depends(admin)])
def wl_export(request: Request, s: Session = Depends(db)):
    kind = list_kind(request)
    names = {r.id: r.name for r in s.scalars(select(Router))}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ip", "comment", "expires", "router"])
    for x in s.scalars(select(Whitelist).where(Whitelist.kind == kind).order_by(Whitelist.id)):
        w.writerow([x.ip, x.comment, fmt_exp(x.expires), names.get(x.router_id, "")])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=%slist.csv" % ("black" if kind == "black" else "white")})


@app.post("/whitelist/{wid}/toggle", dependencies=[Depends(admin)])
@app.post("/blacklist/{wid}/toggle", dependencies=[Depends(admin)])
def wl_toggle(request: Request, wid: int, s: Session = Depends(db)):
    kind = list_kind(request)
    w = s.get(Whitelist, wid)
    if w and w.kind == kind:
        w.active = not w.active
        log(s, ("blacklist " if kind == "black" else "whitelist ") + ("włączono" if w.active else "wyłączono"), w.ip)
        s.commit()
    return back(kind)


@app.post("/whitelist/{wid}/delete", dependencies=[Depends(admin)])
@app.post("/blacklist/{wid}/delete", dependencies=[Depends(admin)])
def wl_del(request: Request, wid: int, s: Session = Depends(db)):
    kind = list_kind(request)
    w = s.get(Whitelist, wid)
    if w and w.kind == kind:
        log(s, "blacklist-" if kind == "black" else "whitelist-", "%s (%s)" % (w.ip, w.comment))
        s.delete(w)
        s.commit()
    return back(kind)


def ascii_rsc(text):
    """Skrypt .rsc trafia do terminala RouterOS, który psuje znaki spoza ASCII (także w komentarzach): ąęł... -> aeł..."""
    text = (text or "").translate(str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D"}))
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if ord(c) < 128)


def list_rsc(t, lst, kind, s):
    """Skrypt .rsc synchronizujący /ip firewall address-list z wpisami danego rodzaju (wl: / bl: w komentarzu)."""
    r = get_router(s, t)
    pfx = "bl" if kind == "black" else "wl"
    lst = clean(lst, "blacklist" if kind == "black" else "whitelist")
    items = s.scalars(select(Whitelist).where(Whitelist.kind == kind, Whitelist.active == True,  # noqa: E712
                                              or_(Whitelist.router_id.is_(None), Whitelist.router_id == r.id))).all()
    keep, lines = [], []
    for w in items:
        if (w.expires and w.expires < now()) or w.ip in keep:
            continue
        keep.append(w.ip)
        lines.append(':do {/ip firewall address-list add list="%s" address=%s comment="%s:%s"} on-error={}'
                     % (lst, w.ip, pfx, ascii_rsc(w.comment)))
    cond = "".join(' and address!="%s"' % ip for ip in keep)
    lines.append('/ip firewall address-list remove [find where list="%s" and dynamic=no and comment~"^%s:"%s]' % (lst, pfx, cond))
    return "\n".join(lines) + "\n"


@app.get("/api/whitelist.rsc", response_class=PlainTextResponse)
def wl_rsc(t: str, list: str = "whitelist", s: Session = Depends(db)):
    return list_rsc(t, list, "white", s)


@app.get("/api/blacklist.rsc", response_class=PlainTextResponse)
def bl_rsc(t: str, list: str = "blacklist", s: Session = Depends(db)):
    return list_rsc(t, list, "black", s)


_STARTED = time.time()


def _age(sec):
    sec = int(max(0, sec))
    if sec < 90:
        return "%d s" % sec
    if sec < 5400:
        return "%d min" % (sec // 60)
    if sec < 172800:
        return "%d h" % (sec // 3600)
    return "%d d" % (sec // 86400)


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _diag_env(s):
    mem = {}
    for line in _read_text("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        if k in ("MemTotal", "MemAvailable") and v.split():
            mem[k] = int(v.split()[0]) * 1024
    lim = _read_text("/sys/fs/cgroup/memory.max")
    out = ["- Application version: %s" % appver.current(),
           "- Image channel: %s" % (os.getenv("APP_CHANNEL", "").strip() or "-"),
           "- Platform: %s, Python %s" % (platform.machine() or "?", platform.python_version()),
           "- OS: %s %s" % (platform.system(), platform.release()),
           "- Time zone: %s (UTC%s), TZ=%s" % (time.strftime("%Z"), time.strftime("%z"), os.getenv("TZ", "-")),
           "- Application uptime: %s" % _age(time.time() - _STARTED)]
    if mem.get("MemTotal"):
        out.append("- Server memory: %s available of %s" % (bytes_h(mem.get("MemAvailable", 0)), bytes_h(mem["MemTotal"])))
    if lim.isdigit():
        out.append("- Container memory limit: %s" % bytes_h(int(lim)))
    return out


def _diag_db(s):
    out = []
    if engine.dialect.name == "postgresql":
        out.append("- Database: PostgreSQL %s, size %s" % (s.scalar(text("show server_version")),
                                                          bytes_h(s.scalar(text("select pg_database_size(current_database())")))))
        for n, est, sz in s.execute(text(
                "select relname, reltuples::bigint, pg_total_relation_size(oid) from pg_class where relkind = 'r' "
                "and relname in ('iface_metrics', 'metrics', 'logs', 'client_stats', 'audit') order by 3 desc")).all():
            out.append("  - table %s: ~%d rows, %s" % (n, max(est, 0), bytes_h(sz)))
    else:
        out.append("- Database: %s" % engine.dialect.name)
    out.append("- Retention (days): measurements %d, interface samples %d, logs %d" % (RETENTION, IFACE_RETENTION, LOG_DAYS))
    out.append("- Monitoring interval: %d s" % interval(s))
    return out


def _diag_routers(s):
    rs = ordered_routers(s)
    hour = dict(s.execute(select(LogEntry.router_id, func.count()).where(LogEntry.ts > now() - dt.timedelta(hours=1))
                          .group_by(LogEntry.router_id)).all())
    out = ["- Monitored routers: %d (%d online)" % (len(rs), sum(1 for r in rs if r.online))]
    for i, r in enumerate(rs, 1):
        si = sys_info(s, r)
        p = [si["model"] or "?", "RouterOS " + (r.ver or "?")]
        if si["fw"]:
            p.append("firmware " + si["fw"])
        p.append("online" if r.online else "offline")
        p.append("last contact %s ago" % _age((now() - r.last_seen).total_seconds()) if r.last_seen else "never contacted")
        gap = reporting_gap(r.id)
        own = " (own thresholds)" if any(v is not None for v in _THR.get(r.id, {}).values()) else ""
        p.append("reports every ~%.1f s, no response after %.0f s, offline after %.0f s%s" % (gap, no_response_after(r.id), online_after(r.id), own)
                 if gap else "reporting rhythm not measured yet (offline after %.0f s%s)" % (online_after(r.id), own))
        if r.edge:
            p.append("edge")
        if si["manager"]:
            p.append("CAPsMAN manager")
        p.append("script %s" % ("outdated (v%s, current v%d)" % (_ROUTER_CV.get(r.id), SCRIPT_VERSION) if script_stale(r) else "ok" if r.id in _ROUTER_CV else "version not reported yet"))
        p.append("syslog %s, %d log entries in the last hour" % ("source set" if r.log_ip else "source not set", hour.get(r.id, 0)))
        out.append("  - Router %d: %s" % (i, ", ".join(p)))
    out.append("- Syslog packets rejected (unknown source): %d from %d sources" % (
        sum(c[0] for c in _log_rejected.values()), len(_log_rejected)))
    return out


def _diag_backups(s):
    b = backups_view(s)
    if not b.get("available"):
        return ["- Backups: directory not available"]
    if b["files"]:
        n = b["files"][0]
        out = ["- Backups: %d files, total %s, newest %s ago (%s)" % (len(b["files"]), b["total"],
                                                                      _age((now() - n["ts"]).total_seconds()), n["size"])]
    else:
        out = ["- Backups: none"]
    out.append("- Backup settings: size limit %s, keep %s days, chart history in backups %s, free disk %s" % (
        b.get("limit_h") or "none", b["keep"], "yes" if os.getenv("BACKUP_INCLUDE_METRICS", "0") == "1" else "no", b.get("free") or "?"))
    if b.get("error"):
        out.append("- Last backup error: %s" % " ".join(b["error"].split())[:120])
    return out


def _diag_features(s):
    cnt = dict(s.execute(select(Whitelist.kind, func.count()).where(Whitelist.active == True)  # noqa: E712
                         .group_by(Whitelist.kind)).all())
    out = ["- Modules: whitelist %s (%d entries), blacklist %s (%d entries)" % (
        "on" if whitelist_on(s) else "off", cnt.get("white", 0), "on" if blacklist_on(s) else "off", cnt.get("black", 0)),
        "- Update check: %s" % appver.status(),
        "- Speed test engine: %s (Ookla %s, LibreSpeed %s)" % (sget(s, "speed_engine", "") or default_engine(),
                                                              "installed" if OOKLA_BIN else "not installed",
                                                              "installed" if LS_BIN else "not installed")]
    for i, r in enumerate(ordered_routers(s), 1):
        t = s.scalars(select(SpeedTest).where(SpeedTest.router_id == r.id).order_by(SpeedTest.ts.desc()).limit(1)).first() if r.edge else None
        if t:
            out.append("- Last speed test (router %d): %s via %s, %s ago" % (
                i, "ok" if t.ok else "failed", t.source or "?", _age((now() - t.ts).total_seconds())))
    return out


def _diag_applog(s):
    """Końcówka logu aplikacji (ostrzeżenia, błędy i komunikaty print) z wyciętymi tokenami, adresami IP, e-mailami,
    nazwami routerów, użytkowników i domeny. Wycinanie nie jest nieomylne, dlatego strona raportu pozwala przejrzeć i poprawić tekst."""
    names = {}
    for i, r in enumerate(ordered_routers(s), 1):
        for n in (r.name, r.ident):
            if n:
                names[n] = "router %d" % i
    for u in s.scalars(select(User)):
        names[u.username] = "user"
    domain = sget(s, "domain")
    if domain:
        names[domain] = "<domain>"
    out = ["- Application started %s ago; entries below are warnings, errors and printed messages since then (newest last)"
           % _age(time.time() - _STARTED)]
    items = applog.recent()
    if not items:
        out.append("- (none)")
    for ts, text in items:
        stamp = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        out.append("[%s UTC] %s" % (stamp, applog.scrub(text, names)))
    return out


def _diag_notify(s):
    c = notif_cfg(s)
    ago = lambda ts: _age(time.time() - ts) + " ago" if ts else "never"
    out = ["- Notifications: %s; channels: ntfy %s, webhook %s" % (
        "on" if c["on"] else "off", "configured" if c["ntfy_url"] and c["ntfy_topic"] else "not configured",
        "configured" if c["hook_url"] else "not configured")]
    out.append("- Rules: router offline %s (after %d min), internet down %s (after %d min), backup %s, auto-ban %s" % (
        "on" if c["r_offline"] else "off", c["offline_min"], "on" if c["r_inet"] else "off", c["inet_min"],
        "on" if c["r_backup"] else "off", "on" if c["r_ban"] else "off"))
    out.append("- Last check: %s; sent since start: %d; last error: %s" % (
        ago(_NOTIF_STATS["check"]), _NOTIF_STATS["sent"],
        ("%s (%s)" % (_NOTIF_STATS["error"][:80], ago(_NOTIF_STATS["error_ts"]))) if _NOTIF_STATS["error"] else "none"))
    waiting = [k for k, v in _NOTIF_NEXT.items() if v > time.time()]
    st = _notif_state(s)
    out.append("- Events waiting for a retry: %d; open states (routers offline, internet down, backup problem): %d" % (len(waiting), len(st)))
    return out


def report_data(s):
    """Dane diagnostyczne do zgłoszenia błędu. Celowo bez haseł, tokenów, adresów IP, nazw i identyfikatorów routerów."""
    parts = []
    for title, fn in (("Environment", _diag_env), ("Database", _diag_db), ("Routers", _diag_routers),
                      ("Backups", _diag_backups), ("Features", _diag_features), ("Notifications", _diag_notify),
                      ("Application log", _diag_applog)):
        try:
            lines = fn(s)
        except Exception as e:  # jedna sekcja nie może zepsuć całej strony
            s.rollback()
            lines = ["- (unavailable: %s)" % type(e).__name__]
        parts.append("## " + title + "\n" + "\n".join(lines))
    routers = []
    for r in ordered_routers(s):
        item = ", ".join(x for x in (sys_info(s, r)["model"], ("RouterOS " + r.ver) if r.ver else "") if x)
        if item:
            routers.append(item)
    ros = "; ".join(dict.fromkeys(routers))[:300]
    d = {"version": appver.current(), "platform": "%s, Python %s" % (platform.machine() or "?", platform.python_version()),
         "routeros": ros}
    qs = urlencode({"template": "bug.yml", "version": d["version"], "platform": d["platform"], "routeros": ros})
    return d, "\n\n".join(parts), "https://github.com/%s/issues/new?%s" % (appver.REPO, qs)


@app.get("/report", dependencies=[Depends(admin)])
def report_page(request: Request, s: Session = Depends(db)):
    d, text, url = report_data(s)
    return templates.TemplateResponse(request, "report.html", {"d": d, "text": text, "issue_url": url})


@app.get("/log", dependencies=[Depends(admin)])
def log_page(request: Request, s: Session = Depends(db)):
    rows = s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(300)).all()
    return templates.TemplateResponse(request, "log.html", {"rows": rows})


# ---------- users ----------
UNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{3,40}$")


def users_view(request, s, msg="", ok=True):
    rows = s.scalars(select(User).order_by(User.username)).all()
    return templates.TemplateResponse(request, "users.html", {"users": rows, "roles": ROLES, "msg": msg, "ok": ok})


def active_admins(s):
    return s.scalar(select(func.count(User.id)).where(User.role == "admin", User.active == True))  # noqa: E712


@app.get("/users", dependencies=[Depends(admin)])
def users_page(request: Request, s: Session = Depends(db)):
    return users_view(request, s)


@app.post("/users", dependencies=[Depends(admin)])
def user_add(request: Request, username: str = Form(), password: str = Form(), role: str = Form("viewer"),
             s: Session = Depends(db)):
    username = username.strip()
    if not UNAME_RE.match(username):
        return users_view(request, s, tr("msg.u_login_rule"), False)
    if len(password) < 8:
        return users_view(request, s, tr("msg.pw_short"), False)
    if role not in ROLES:
        return users_view(request, s, tr("msg.u_bad_role"), False)
    if s.scalar(select(User).where(User.username == username)):
        return users_view(request, s, tr("msg.u_exists"), False)
    s.add(User(username=username, pw=hash_pw(password), role=role, created=now()))
    log(s, "użytkownik+", "%s (%s)" % (username, role))
    s.commit()
    return users_view(request, s, tr("msg.u_added", name=username))


def guard(request, s, target, me):
    """Nie pozwól zablokować sobie dostępu ani usunąć ostatniego administratora."""
    if not target:
        return users_view(request, s, tr("msg.u_none"), False)
    if target.id == me.id:
        return users_view(request, s, tr("msg.u_self"), False)
    return None


@app.post("/users/{uid}/role")
def user_role(request: Request, uid: int, role: str = Form(), me: User = Depends(admin), s: Session = Depends(db)):
    t = s.get(User, uid)
    err = guard(request, s, t, me)
    if err:
        return err
    if role not in ROLES:
        return users_view(request, s, tr("msg.u_bad_role"), False)
    if t.role == "admin" and role != "admin" and t.active and active_admins(s) <= 1:
        return users_view(request, s, "To ostatni aktywny administrator.", False)
    t.role, t.ver = role, t.ver + 1
    log(s, "rola", "%s: %s" % (t.username, role))
    s.commit()
    return users_view(request, s, tr("msg.u_role", name=t.username))


@app.post("/users/{uid}/toggle")
def user_toggle(request: Request, uid: int, me: User = Depends(admin), s: Session = Depends(db)):
    t = s.get(User, uid)
    err = guard(request, s, t, me)
    if err:
        return err
    if t.active and t.role == "admin" and active_admins(s) <= 1:
        return users_view(request, s, "To ostatni aktywny administrator.", False)
    t.active, t.ver = not t.active, t.ver + 1
    log(s, "użytkownik " + ("włączony" if t.active else "wyłączony"), t.username)
    s.commit()
    return users_view(request, s, "Zapisano.")


@app.post("/users/{uid}/password")
def user_reset(request: Request, uid: int, password: str = Form(), me: User = Depends(admin),
               s: Session = Depends(db)):
    t = s.get(User, uid)
    if not t:
        return users_view(request, s, tr("msg.u_none"), False)
    if len(password) < 8:
        return users_view(request, s, tr("msg.pw_short"), False)
    t.pw, t.ver = hash_pw(password), t.ver + 1
    log(s, "reset hasła", t.username)
    s.commit()
    if t.id == me.id:
        request.session["v"] = t.ver
    return users_view(request, s, tr("msg.u_pw_set", name=t.username))


@app.post("/users/{uid}/delete")
def user_del(request: Request, uid: int, me: User = Depends(admin), s: Session = Depends(db)):
    t = s.get(User, uid)
    err = guard(request, s, t, me)
    if err:
        return err
    if t.role == "admin" and t.active and active_admins(s) <= 1:
        return users_view(request, s, "To ostatni aktywny administrator.", False)
    log(s, "użytkownik-", t.username)
    s.delete(t)
    s.commit()
    return users_view(request, s, tr("msg.u_deleted"))


@app.get("/account")
def account_page(request: Request, me: User = Depends(user)):
    return templates.TemplateResponse(request, "account.html", {"msg": "", "ok": True})


@app.post("/account")
def account_save(request: Request, current: str = Form(), password: str = Form(), password2: str = Form(),
                 me: User = Depends(user), s: Session = Depends(db)):
    def view(msg, ok):
        return templates.TemplateResponse(request, "account.html", {"msg": msg, "ok": ok})
    if not check_pw(current, me.pw):
        time.sleep(1.5)
        return view(tr("msg.a_bad_current"), False)
    if len(password) < 8:
        return view(tr("msg.a_short"), False)
    if password != password2:
        return view(tr("msg.a_mismatch"), False)
    me.pw, me.ver = hash_pw(password), me.ver + 1
    log(s, "zmiana hasła", me.username)
    s.commit()
    request.session["v"] = me.ver
    return view(tr("msg.a_changed"), True)


# ---------- settings / HTTPS ----------
DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


def caddyfile(domain, email):
    g = "{\n\tadmin 0.0.0.0:2019 {\n\t\torigins caddy:2019\n\t}\n"
    if email:
        g += "\temail %s\n" % email
    g += "}\n"
    body = "\treverse_proxy app:8000 {\n\t\ttransport http {\n\t\t\tkeepalive 30s\n\t\t}\n\t}\n"
    out = g + ":80 {\n" + body + "}\n"
    if domain:
        out += "%s {\n%s}\n" % (domain, body)
    return out


BACKUP_DIR = "/backups"
BACKUP_RE = re.compile(r"^monitor-\d{4}-\d\d-\d\d_\d{6}\.dump$")


def backups_info():
    files = []
    try:
        for n in os.listdir(BACKUP_DIR):
            p = os.path.join(BACKUP_DIR, n)
            if BACKUP_RE.match(n) and os.path.isfile(p):
                st = os.stat(p)
                files.append({"name": n, "size": bytes_h(st.st_size), "bytes": st.st_size,
                              "ts": dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).replace(tzinfo=None)})
    except OSError:
        return {"available": False, "files": [], "pending": False, "error": None, "stale": False}
    files.sort(key=lambda f: f["ts"], reverse=True)
    err = None
    try:
        with open(os.path.join(BACKUP_DIR, ".last_error"), encoding="utf-8") as fh:
            err = fh.read().strip()
    except OSError:
        pass
    try:
        free = shutil.disk_usage(BACKUP_DIR).free
    except OSError:
        free = None
    total_b = sum(f["bytes"] for f in files)
    return {"available": True, "files": files, "pending": os.path.exists(os.path.join(BACKUP_DIR, ".now")),
            "error": err, "stale": not files or (now() - files[0]["ts"]).total_seconds() > 2 * 86400,
            "total": bytes_h(total_b), "total_b": total_b, "newest_b": files[0]["bytes"] if files else 0,
            "free_b": free, "free": bytes_h(free) if free is not None else "",
            "hour": os.getenv("BACKUP_HOUR", "3"), "keep": os.getenv("BACKUP_KEEP_DAYS", "14")}


def backup_limit_mb(s):
    v = sget(s, "backup_limit_mb", "")
    return int(v) if v.isdigit() and int(v) > 0 else None


def enforce_backup_limit(s=None):
    """Usuwa najstarsze kopie ponad limit rozmiaru (najnowsza zostaje zawsze). Zwraca nazwy usuniętych."""
    own = s is None
    s = Session(engine) if own else s
    try:
        lim = backup_limit_mb(s)
        removed = []
        if lim:
            files = [(f["name"], f["bytes"], f["ts"].timestamp()) for f in backups_info()["files"]]
            for name in backuplib.plan_prune(files, lim * 1024 * 1024):
                try:
                    os.remove(os.path.join(BACKUP_DIR, name))
                    removed.append(name)
                except OSError:
                    pass
            if removed:
                log(s, "limit kopii", ("usunięto %d: %s" % (len(removed), ", ".join(removed)))[:250])
                s.commit()
        return removed
    finally:
        if own:
            s.close()


def backups_view(s):
    bk = backups_info()
    lim = backup_limit_mb(s)
    bk["limit_gb"] = round(lim / 1024, 2) if lim else ""
    bk["min_gb"] = max(0.1, math.ceil(bk.get("newest_b", 0) / 1024 ** 3 * 100) / 100)  # nie mniej niż jedna (najnowsza) kopia
    if lim and bk.get("available"):
        lim_b = lim * 1024 * 1024
        bk["limit_h"] = bytes_h(lim_b)
        bk["fits"] = lim_b // bk["newest_b"] if bk.get("newest_b") else 0
        bk["too_big"] = bool(bk.get("newest_b") and bk["newest_b"] > lim_b)
    if bk.get("available") and bk.get("free_b") is not None:
        bk["low_disk"] = bk["free_b"] < 1024 ** 3 or bk["free_b"] < 3 * bk.get("newest_b", 0)
    return bk


def settings_view(request, s, msg="", ok=True):
    return templates.TemplateResponse(request, "settings.html", {
        "domain": sget(s, "domain"), "email": sget(s, "email"), "msg": msg, "ok": ok,
        "interval": interval(s), "intervals": INTERVALS, "routers": ordered_routers(s), "bk": backups_view(s),
        "wl_enabled": whitelist_on(s), "bl_enabled": blacklist_on(s), "ab": autoban_cfg(s), "ab_hours": AUTOBAN_HOURS,
        "off_mult": offline_mult(s),
        "thr_rows": [{"id": r.id, "name": r.name, "gap": reporting_gap(r.id), "auto_nr": auto_no_response(r.id),
                      "auto_off": auto_offline(r.id), "own_nr": _THR.get(r.id, {}).get("nr"), "own_off": _THR.get(r.id, {}).get("off"),
                      "eff_nr": no_response_after(r.id), "eff_off": online_after(r.id)} for r in ordered_routers(s)], "nf": notif_view(s), "langs": i18n.languages(),
        "mutes": [{"pat": m["pat"], "rid": m.get("rid"), "ts": m.get("ts", ""),
                   "router": next((r.name for r in ordered_routers(s) if r.id == m.get("rid")), "?")} for m in mutes_get(s)],
        "speed_router": sget(s, "speed_router"), "speed_time": SPEED_TIME[:5],
        "speed_engine": sget(s, "speed_engine", "") or default_engine(),
        "speed_server": server_setting(s, sget(s, "speed_engine", "") or default_engine()),
        "ookla": bool(OOKLA_BIN), "librespeed": bool(LS_BIN), "ls_best": best_result(s)})


@app.post("/settings/whitelist", dependencies=[Depends(admin)])
def settings_whitelist(request: Request, on: str = Form(""), s: Session = Depends(db)):
    sset(s, "whitelist_on", "1" if on == "1" else "0")
    log(s, "moduł whitelisty", "włączony" if on == "1" else "wyłączony")
    s.commit()
    _WL_ON[1] = 0
    return settings_view(request, s, (tr("msg.wl_on") if on == "1" else tr("msg.wl_off")) + " " + tr("msg.wl_paste"), True)


@app.post("/settings/blacklist", dependencies=[Depends(admin)])
def settings_blacklist(request: Request, on: str = Form(""), s: Session = Depends(db)):
    sset(s, "blacklist_on", "1" if on == "1" else "0")
    log(s, "moduł blacklisty", "włączony" if on == "1" else "wyłączony")
    s.commit()
    _BL_ON[1] = 0
    return settings_view(request, s, (tr("msg.bl_on") if on == "1" else tr("msg.bl_off")) + " " + tr("msg.wl_paste"), True)


def notif_view(s):
    """Ustawienia powiadomień do formularza: bez sekretów (token ntfy i adres webhooka są tylko oznaczone jako zapisane)."""
    c = notif_cfg(s)
    hook = urlparse(c["hook_url"]).hostname if c["hook_url"] else ""
    return {**{k: v for k, v in c.items() if k not in ("ntfy_token", "hook_url")},
            "token_set": bool(c["ntfy_token"]), "hook_set": bool(c["hook_url"]), "hook_host": hook or ""}


@app.post("/settings/notify", dependencies=[Depends(admin)])
def settings_notify(request: Request, on: str = Form(""), ntfy_url: str = Form(""), ntfy_topic: str = Form(""),
                    ntfy_token: str = Form(""), clear_token: str = Form(""), hook_url: str = Form(""), clear_hook: str = Form(""),
                    lang: str = Form("en"), offline_min: str = Form("5"), inet_min: str = Form("3"),
                    r_offline: str = Form(""), r_inet: str = Form(""), r_backup: str = Form(""), r_ban: str = Form(""),
                    s: Session = Depends(db)):
    ntfy_url, ntfy_topic, hook_url = ntfy_url.strip(), ntfy_topic.strip(), hook_url.strip()
    if ntfy_topic and (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", ntfy_topic) or not notify.valid_url(ntfy_url)):
        return settings_view(request, s, tr("msg.nf_bad_ntfy"), False)
    if hook_url and not notify.valid_url(hook_url):
        return settings_view(request, s, tr("msg.nf_bad_hook"), False)
    old = notif_cfg(s)
    sset(s, "notif_on", "1" if on == "1" else "0")
    sset(s, "notif_ntfy_url", ntfy_url or "https://ntfy.sh")
    sset(s, "notif_ntfy_topic", ntfy_topic)
    sset(s, "notif_ntfy_token", "" if clear_token == "1" else (ntfy_token.strip() or old["ntfy_token"]))
    sset(s, "notif_hook_url", "" if clear_hook == "1" else (hook_url or old["hook_url"]))
    sset(s, "notif_lang", lang if lang in i18n.LOCALES else "en")
    for k, v, lo, hi in (("offline_min", offline_min, 1, 120), ("inet_min", inet_min, 1, 120)):
        sset(s, "notif_" + k, str(min(hi, max(lo, int(v)))) if v.isdigit() else str(old[k]))
    for k, v in (("offline", r_offline), ("inet", r_inet), ("backup", r_backup), ("ban", r_ban)):
        sset(s, "notif_r_" + k, "1" if v == "1" else "0")
    log(s, "powiadomienia", "włączone" if on == "1" else "wyłączone")  # bez adresów i tokenów w dzienniku
    s.commit()
    _NOTIF_NEXT.clear()
    _NOTIF_FAILS.clear()
    return settings_view(request, s, tr("msg.nf_saved"), True)


@app.post("/settings/notify/test", dependencies=[Depends(admin)])
def settings_notify_test(request: Request, s: Session = Depends(db)):
    cfg = notif_cfg(s)
    errs = notify.dispatch(cfg, notif_event(cfg, "test", "info", "test"), force=True)
    return settings_view(request, s, tr("msg.nf_test_ok") if not errs else tr("msg.nf_test_err") + " " + "; ".join(errs), not errs)


@app.post("/settings/autoban", dependencies=[Depends(admin)])
def settings_autoban(request: Request, on: str = Form(""), n: str = Form("5"), minutes: str = Form("10"), hours: str = Form("1"),
                     s: Session = Depends(db)):
    cfg = autoban_cfg(s)
    n = int(n) if n.isdigit() else cfg["n"]
    minutes = int(minutes) if minutes.isdigit() else cfg["min"]
    hours = int(hours) if hours.isdigit() and int(hours) in AUTOBAN_HOURS else 1
    sset(s, "autoban_on", "1" if on == "1" else "0")
    sset(s, "autoban_n", str(min(50, max(3, n))))
    sset(s, "autoban_min", str(min(120, max(1, minutes))))
    sset(s, "autoban_h", str(hours))
    log(s, "auto-ban", ("włączony" if on == "1" else "wyłączony") + ": %d prób / %d min, ban na %d h" % (
        min(50, max(3, n)), min(120, max(1, minutes)), hours))
    s.commit()
    _AB_HITS.clear()
    return settings_view(request, s, tr("msg.ab_saved"), True)


@app.post("/settings/backup-now", dependencies=[Depends(admin)])
def backup_now(request: Request, s: Session = Depends(db)):
    try:
        open(os.path.join(BACKUP_DIR, ".now"), "w").close()
    except OSError as e:
        return settings_view(request, s, tr("msg.bk_fail", err=e), False)
    log(s, "kopia bazy", "zlecona ręcznie")
    s.commit()
    return settings_view(request, s, tr("msg.bk_ok"), True)


@app.post("/settings/backup-limit", dependencies=[Depends(admin)])
def settings_backup_limit(request: Request, mode: str = Form("none"), gb: str = Form(""), s: Session = Depends(db)):
    if mode != "limit":
        sset(s, "backup_limit_mb", "")
        log(s, "limit kopii", "bez limitu")
        s.commit()
        return settings_view(request, s, tr("msg.bk_limit_none"), True)
    mb = backuplib.parse_limit_gb(gb)
    if mb is None:
        return settings_view(request, s, tr("msg.bk_limit_bad"), False)
    newest = backups_info().get("newest_b", 0)
    if mb * 1024 * 1024 < newest:
        return settings_view(request, s, tr("msg.bk_limit_small", size=bytes_h(newest)), False)
    sset(s, "backup_limit_mb", str(mb))
    log(s, "limit kopii", "%d MB" % mb)
    s.commit()
    removed = enforce_backup_limit(s)
    msg = tr("msg.bk_limit_saved", limit=bytes_h(mb * 1024 * 1024))
    if removed:
        msg += " " + tr("msg.bk_limit_removed", n=len(removed))
    return settings_view(request, s, msg, True)


@app.get("/backups/{name}", dependencies=[Depends(admin)])
def backup_download(name: str, s: Session = Depends(db)):
    p = os.path.join(BACKUP_DIR, name)
    if not BACKUP_RE.match(name) or not os.path.isfile(p):
        raise HTTPException(404)
    log(s, "pobrano kopię", name)
    s.commit()
    return FileResponse(p, filename=name, media_type="application/octet-stream")


@app.post("/backups/{name}/delete", dependencies=[Depends(admin)])
def backup_delete(request: Request, name: str, s: Session = Depends(db)):
    p = os.path.join(BACKUP_DIR, name)
    if BACKUP_RE.match(name) and os.path.isfile(p):
        os.remove(p)
        log(s, "usunięto kopię", name)
        s.commit()
    return RedirectResponse("/settings#backup", 303)


def _save_router_thresholds(request, form):
    """Zapisuje własne progi routerów z formularza (pola nr_<id> i off_<id>, puste = automatycznie, nie mniej niż 1 s)."""
    with Session(engine) as s:
        s.info["who"] = request.state.user.username
        thr, bad = {}, False
        for r in ordered_routers(s):
            item = {}
            for key, field in (("nr", "nr_%d" % r.id), ("off", "off_%d" % r.id)):
                raw = str(form.get(field, "")).strip().replace(",", ".")
                if not raw:
                    continue
                try:
                    v = float(raw)
                except ValueError:
                    bad = True
                    continue
                if v < 1:
                    bad = True
                    continue
                item[key] = round(v, 2)
            if item:
                thr[str(r.id)] = item
        if bad:
            return settings_view(request, s, tr("msg.off_routers_bad"), False)
        sset(s, "router_thr", json.dumps(thr))
        log(s, "progi routerów", "własne progi: %d routerów" % len(thr))
        s.commit()
        _THR.clear()
        _THR.update(router_thresholds(s))
        return settings_view(request, s, tr("msg.off_routers_ok"), True)


@app.post("/settings/offline/routers", dependencies=[Depends(admin)])
async def settings_offline_routers(request: Request):
    form = dict(await request.form())
    return await run_in_threadpool(_save_router_thresholds, request, form)


@app.post("/settings/offline", dependencies=[Depends(admin)])
def settings_offline(request: Request, mult: str = Form("1.5"), s: Session = Depends(db)):
    try:
        v = float(mult.strip().replace(",", "."))
    except ValueError:
        return settings_view(request, s, tr("msg.off_bad"), False)
    if not 1.0 <= v <= 100000:
        return settings_view(request, s, tr("msg.off_bad"), False)
    txt = ("%.2f" % v).rstrip("0").rstrip(".")
    sset(s, "offline_mult", txt)
    log(s, "próg offline", "mnożnik %s" % txt)
    s.commit()
    _OFFLINE_MULT[0] = v
    return settings_view(request, s, tr("msg.off_ok", x=txt.replace(".", ",")), True)


@app.post("/settings/interval", dependencies=[Depends(admin)])
def settings_interval(request: Request, every: int = Form(60), s: Session = Depends(db)):
    if every not in INTERVALS:
        return settings_view(request, s, tr("msg.iv_bad"), False)
    sset(s, "interval", str(every))
    log(s, "interwał", "%d s" % every)
    s.commit()
    return settings_view(request, s, tr("msg.iv_ok", n=every), True)


@app.get("/settings", dependencies=[Depends(admin)])
def settings_page(request: Request, s: Session = Depends(db)):
    return settings_view(request, s)


@app.post("/settings", dependencies=[Depends(admin)])
def settings_save(request: Request, domain: str = Form(""), email: str = Form(""), s: Session = Depends(db)):
    domain, email = domain.strip().lower(), email.strip()
    if domain and not DOMAIN_RE.match(domain):
        return settings_view(request, s, tr("msg.dom_bad"), False)
    if email and not EMAIL_RE.match(email):
        return settings_view(request, s, tr("msg.mail_bad"), False)
    try:
        r = httpx.post(CADDY + "/load", content=caddyfile(domain, email).encode(),
                       headers={"Content-Type": "text/caddyfile"}, timeout=15)
    except Exception as e:
        return settings_view(request, s, tr("msg.caddy_conn", err=e), False)
    if r.status_code != 200:
        return settings_view(request, s, tr("msg.caddy_rej", err=r.text[:300]), False)
    sset(s, "domain", domain)
    sset(s, "email", email)
    log(s, "ustawienia", "domena=%s" % (domain or "brak"))
    s.commit()
    msg = tr("msg.https_on") if domain else tr("msg.https_off")
    return settings_view(request, s, msg, True)
