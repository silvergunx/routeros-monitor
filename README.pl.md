# RouterOS Monitor

[English](README.md) · **Polski**

Panel WWW do monitorowania routerów **MikroTik RouterOS 7** oraz centralne źródło **whitelisty adresów IP**,
którą routery pobierają same. Całość działa w Dockerze (`docker compose`), bez instalowania czegokolwiek na serwerze poza Dockerem.

Interfejs jest dostępny po polsku i angielsku, działa w trybie jasnym i ciemnym oraz na telefonie.

**Spis treści:** [Co potrafi](#co-potrafi) · [Wymagania](#wymagania) · [Instalacja](#instalacja) · [Aktualizacja](#aktualizacja) · [Konfiguracja](#konfiguracja-env) · [Kopie zapasowe](#kopie-zapasowe) · [Diagnostyka](#diagnostyka) · [Języki](#języki) · [Dokumentacja](#dokumentacja) · [Licencja](#licencja)

## Co potrafi

**Monitoring routerów**
- CPU, RAM, dysk, temperatura, uptime, wersja RouterOS i firmware, informacja o dostępnej aktualizacji
- interfejsy i ruch (także łącze WAN), grupy interfejsów, wykresy historii
- klienci DHCP z nazwami urządzeń i stanem online
- klienci Wi-Fi (wifi-qcom / CAPsMAN i starszy wireless) z sygnałem, SNR, prędkością i oceną jakości połączenia
- tunele VPN (WireGuard i inne)

**Jakość łącza**
- sondy Netwatch: opóźnienie, jitter i utrata pakietów do bramy, a na routerze brzegowym także DNS, HTTP i dostępność internetu w %
- lista przerw z typem (brak internetu / nie działa DNS / nie działa HTTP)
- test prędkości wykonywany przez serwer aplikacji, z wyborem silnika i serwera testowego: **LibreSpeed** (otwartoźródłowy, wbudowany w obraz),
  **Speedtest by Ookla** (ten sam co speedtest.net; dostępny po własnej budowie obrazu) i zapasowo Cloudflare;
  pobieranie, wysyłanie, ping i jitter; codziennie w nocy i na żądanie

**Logi**
- odbiór logów z routerów przez syslog (UDP), kolorowanie wg ważności, potwierdzanie, eksport z zakresem dat
- tłumaczenie typowych komunikatów RouterOS na zrozumiały opis po polsku i zakładka analizy z poradami

**Whitelista i blacklista**
- adresy IP, sieci i domeny w bazie aplikacji; routery pobierają listy skryptami do `/ip firewall address-list`
  (listy `whitelist` i `blacklist`), dla wszystkich routerów albo jednego
- blacklista (banowanie): opcjonalny termin ważności dla banów czasowych, ochrona przed zbanowaniem siebie, serwera aplikacji
  i monitorowanego routera oraz gotowa reguła firewalla do wklejenia (sama aplikacja nigdy nie zmienia firewalla)
- import i eksport, włączanie/wyłączanie wpisów; każdy moduł można wyłączyć w Ustawieniach

**Pozostałe**
- tryb ustawiania / analizy Wi-Fi na żywo (odczyt co 2 s) do szukania najlepszego miejsca dla punktu dostępowego
- użytkownicy z rolami (administrator / podgląd), dziennik zmian
- automatyczne kopie zapasowe bazy z pobieraniem i usuwaniem w panelu oraz opcjonalnym limitem rozmiaru przechowywanych kopii
- HTTPS jednym kliknięciem: podajesz domenę w Ustawieniach, certyfikat Let's Encrypt wystawia się sam (Caddy)

## Wymagania

- serwer z Linuksem (testowane na Ubuntu 26.04 LTS) i Dockerem z wtyczką Compose
- routery MikroTik z **RouterOS 7** (testowane na 7.24), które widzą serwer aplikacji w sieci
- porty na serwerze: TCP 80 i 443 (panel), UDP 514 (logi z routerów)

## Instalacja

1. Zainstaluj Dockera:
   ```
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker $USER
   ```
   Wyloguj się i zaloguj ponownie, żeby grupa `docker` zaczęła działać.
2. Pobierz projekt:
   ```
   git clone https://github.com/silvergunx/routeros-monitor.git
   cd routeros-monitor
   ```
3. Przygotuj konfigurację:
   ```
   cp .env.example .env
   openssl rand -hex 32
   nano .env
   ```
   Ustaw własne `DB_PASSWORD` i `ADMIN_PASSWORD`, a jako `SECRET_KEY` wklej wynik `openssl rand -hex 32`.
   Aplikacja nie wystartuje z przykładowymi hasłami.
4. Uruchom (jedna z dwóch dróg):
   ```
   docker compose pull && docker compose up -d      # gotowy obraz (szybko)
   docker compose up -d --build                     # albo budowa z kodu
   ```
5. Otwórz `http://ADRES_SERWERA/` i zaloguj się danymi z `.env`.
6. Dodaj router (**Routery → Dodaj router**), skopiuj komendę ze strony routera i wklej ją w terminalu RouterOS.
   Po kilkudziesięciu sekundach pojawią się pierwsze dane.
7. Opcjonalnie HTTPS: **Ustawienia → HTTPS**, podaj domenę wskazującą na serwer (porty 80 i 443 muszą być dostępne z internetu).

Szczegóły konfiguracji routerów: [docs/ROUTERY.md](docs/ROUTERY.md).

## Aktualizacja

Wydania są na [stronie Releases](https://github.com/silvergunx/routeros-monitor/releases) i w [CHANGELOG.md](CHANGELOG.md).
Najpierw zrób kopię bazy, potem zaktualizuj wybraną drogą:

```
cd routeros-monitor
touch backups/.now        # kopia bazy przed aktualizacją (po kilkunastu sekundach pojawi się w backups/)
```

**Droga A: gotowy obraz** (bez budowania na serwerze)
```
docker compose pull
docker compose up -d
```

Droga A aktualizuje tylko **obraz aplikacji**. Pliki obok `docker-compose.yml` (`docker-compose.yml`, `backup.sh`, `Caddyfile`) nie są częścią obrazu.
Gdy notatki wydania mówią, że któryś się zmienił, pobierz go ponownie (poniżej `main` dla wersji `stable`; dla beta użyj `develop`):
```
cd routeros-monitor
curl -fsSL https://raw.githubusercontent.com/silvergunx/routeros-monitor/main/backup.sh -o backup.sh
curl -fsSL https://raw.githubusercontent.com/silvergunx/routeros-monitor/main/docker-compose.yml -o docker-compose.yml
docker compose up -d
```
(Własny `.env` zostaje; nowe zmienne mają wartości domyślne.) W drodze B `git pull` odświeża te pliki za Ciebie.

**Droga B: budowa z kodu**
```
git pull
docker compose up -d --build
```

Potem sprawdź logi: `docker compose logs app --tail 30`.

**Kanały.** `stable` (domyślny) to przetestowane wydanie. Wersje testowe: ustaw `APP_CHANNEL=beta` w `.env` (droga A) albo
`git checkout develop` (droga B). Wersje testowe mogą zawierać błędy, więc nie używaj ich na routerze, do którego nie masz dostępu.
Konkretną wersję przypniesz przez `APP_CHANNEL=1.0.0`.

Baza danych jest w wolumenie Dockera `dbdata`, a `.env` i `backups/` nie są częścią repozytorium, więc aktualizacja ich nie nadpisuje.
Nowe kolumny w bazie aplikacja dodaje sama przy starcie.
**Nie używaj `docker compose down -v`**, bo przełącznik `-v` usuwa wolumen z bazą.

Jeśli zmiana dotyczy skryptów na routerach, w opisie wersji będzie informacja, że trzeba ponownie wkleić komendę konfiguracyjną.

## Konfiguracja (`.env`)

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `UPDATE_CHECK` | `1` | `0` wyłącza sprawdzanie nowych wydań na GitHubie (patrz niżej) |
| `APP_CHANNEL` | `stable` | kanał obrazu: `stable`, `beta` albo konkretna wersja, np. `1.0.0` |
| `DB_PASSWORD` | – | hasło bazy PostgreSQL (ustawiane tylko przy pierwszym starcie bazy) |
| `ADMIN_USER` / `ADMIN_PASSWORD` | `admin` / – | pierwsze konto administratora |
| `SECRET_KEY` | – | klucz sesji, min. 16 znaków (`openssl rand -hex 32`) |
| `RETENTION_DAYS` | `30` | ile dni trzymać pomiary (CPU, RAM, jakość łącza itd.) |
| `IFACE_RETENTION_DAYS` | `7` | ile dni trzymać próbki ruchu interfejsów (największa tabela); starsze są usuwane w tle |
| `SYSLOG_PORT` | `514` | port UDP na serwerze dla logów z routerów |
| `LOG_RETENTION_DAYS` | `14` | ile dni trzymać logi |
| `TZ` | `Europe/Warsaw` | strefa czasu |
| `BACKUP_HOUR` / `BACKUP_KEEP_DAYS` | `3` / `14` | godzina kopii zapasowej i czas jej przechowywania |
| `BACKUP_INCLUDE_METRICS` | `0` | `1` dołącza do kopii także historię wykresów (pomiary); domyślnie kopie są małe i zawierają logi, dziennik zmian, użytkowników, routery i listy IP, ale bez historii wykresów |
| `SPEEDTEST_TIME` | `03:30:00` | godzina nocnego testu prędkości |
| `SPEEDTEST_STREAMS` | `6` | liczba połączeń w zapasowym teście Cloudflare |

**Powiadomienie o aktualizacji.** Panel (tylko administratorowi) pokazuje znaczek, gdy na GitHubie jest nowsze wydanie. Serwer pyta publiczne
API GitHuba (`api.github.com`) najwyżej co 6 godzin, w tle, i nie wysyła nic poza adresem IP i wersją aplikacji w nagłówku User-Agent.
Wersje testowe (`-beta`) widzą też wydania testowe. Wyłączysz to przez `UPDATE_CHECK=0`. Panel nigdy sam się nie aktualizuje.

Nie używaj znaku `$` w wartościach (Compose traktuje go jako zmienną).
Pozostałe ustawienia (interwał odczytu, test prędkości, whitelista, kolejność routerów, HTTPS) są w panelu w zakładce **Ustawienia**.

## Kopie zapasowe

Kontener `backup` robi kopię codziennie o `BACKUP_HOUR` do katalogu `./backups`. Kopię na żądanie, pobieranie i usuwanie
znajdziesz w **Ustawienia → Kopie zapasowe bazy**.

Domyślnie kopie zawierają wszystko oprócz historii wykresów (ruch interfejsów, pomiary CPU/RAM i liczba klientów): logi, dziennik zmian,
użytkownicy, routery, ustawienia i listy IP są w kopii. Po przywróceniu wykresy zaczynają od zera. `BACKUP_INCLUDE_METRICS=1` dołącza historię
(kopie są wtedy znacznie większe).

Przywracanie (nadpisuje obecne dane):
```
docker compose stop app
docker compose exec -T db pg_restore -U monitor -d monitor --clean --if-exists < backups/NAZWA_PLIKU.dump
docker compose start app
```
Przeniesienie na nowy serwer: zainstaluj aplikację, skopiuj swój `.env` i plik kopii, uruchom i wykonaj przywracanie.

## Diagnostyka

Rozmiar bazy: `docker compose exec db psql -U monitor -d monitor -c "SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 8;"`.
Zwykle największa jest tabela interfejsów; zmniejsz `IFACE_RETENTION_DAYS`, aby ją odchudzić. Usunięcie starych wierszy zwalnia miejsce na nowe, ale nie zmniejsza plików
na dysku; aby oddać miejsce systemowi, uruchom (na chwilę blokuje tabelę i potrzebuje wolnego miejsca na kopię) `docker compose exec db psql -U monitor -d monitor -c "VACUUM FULL iface_metrics;"`.

```
docker compose ps
docker compose logs -f app caddy
docker compose exec app speedtest --version
```

## Budowa

| Usługa | Obraz | Zadanie |
|---|---|---|
| `app` | Python 3.12, FastAPI | panel, API dla routerów, odbiór syslog, testy prędkości |
| `db` | PostgreSQL 16 | dane |
| `backup` | PostgreSQL 16 | kopie `pg_dump` |
| `caddy` | Caddy 2 | reverse proxy i certyfikaty HTTPS |

Routery same wysyłają dane do aplikacji (`/tool fetch`), więc aplikacja nie potrzebuje loginu ani hasła do routerów.

Bezpieczeństwo: [docs/BEZPIECZENSTWO.md](docs/BEZPIECZENSTWO.md) oraz [SECURITY.md](SECURITY.md) (zgłaszanie błędów).

## Języki

Interfejs działa po polsku i angielsku (przełącznik PL / EN w menu i na ekranie logowania, wybór zapamiętuje ciasteczko). Kolejne języki dodaje się samym plikiem JSON, bez zmian w kodzie: [docs/TRANSLATING.md](docs/TRANSLATING.md).

## Dokumentacja

| Dokument | Co zawiera |
|---|---|
| [Releases](https://github.com/silvergunx/routeros-monitor/releases) i [CHANGELOG.md](CHANGELOG.md) | co zmieniło się w każdej wersji i co trzeba zrobić na routerach lub serwerze po aktualizacji |
| [docs/ROUTERY.md](docs/ROUTERY.md) | co instaluje komenda konfiguracyjna na routerze, reguły firewalla dla whitelisty i blacklisty, routery poza siecią lokalną |
| [docs/BEZPIECZENSTWO.md](docs/BEZPIECZENSTWO.md) i [SECURITY.md](SECURITY.md) | zalecenia bezpieczeństwa i zgłaszanie błędów bezpieczeństwa |
| [docs/TRANSLATING.md](docs/TRANSLATING.md) | jak dodać język |
| [CONTRIBUTING.md](CONTRIBUTING.md) | gałęzie (`main` stabilna, `develop` beta), testy, wydawanie wersji |
| [THIRD_PARTY.md](THIRD_PARTY.md) | licencje dołączonych składników (LibreSpeed CLI) i opcjonalnego programu Ookla |

Pytania i zgłoszenia błędów: [GitHub Issues](https://github.com/silvergunx/routeros-monitor/issues).

## Licencja

Kod projektu: [MIT](LICENSE).

Obraz zawiera **LibreSpeed CLI** (LGPL-3.0, bez zmian) do testu prędkości; licencje dołączonych składników są w [THIRD_PARTY.md](THIRD_PARTY.md).
Działa bez udostępniania wyników, więc do publicznych serwerów LibreSpeed trafia tylko ruch testowy.

Przy własnej budowie obrazu (`docker compose up -d --build`) pobierany jest dodatkowo program **Speedtest CLI firmy Ookla**, który nie jest częścią
tego repozytorium i ma własną licencję (użytek osobisty, niekomercyjny); aplikacja uruchamia go z akceptacją licencji i polityki prywatności Ookla.
Gotowe obrazy go **nie zawierają** (w Ustawieniach jest wtedy podpowiedź, jak zbudować obraz z Ooklą). Zawsze możesz wybrać silnik LibreSpeed lub Cloudflare.

Projekt nie jest powiązany z MikroTik, Ookla ani Cloudflare. Nazwy należą do ich właścicieli.
