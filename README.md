# RouterOS Monitor

Panel WWW do monitorowania routerów **MikroTik RouterOS 7** oraz centralne źródło **whitelisty adresów IP**,
którą routery pobierają same. Całość działa w Dockerze (`docker compose`), bez instalowania czegokolwiek na serwerze poza Dockerem.

Interfejs jest po polsku, działa w trybie jasnym i ciemnym oraz na telefonie.

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
- **test prędkości Speedtest by Ookla** (ten sam co speedtest.net) wbudowany w kontener, z wyborem serwera testowego,
  jitterem, utratą pakietów i linkiem do wyniku; zapasowo test Cloudflare; codziennie w nocy i na żądanie

**Logi**
- odbiór logów z routerów przez syslog (UDP), kolorowanie wg ważności, potwierdzanie, eksport z zakresem dat
- tłumaczenie typowych komunikatów RouterOS na zrozumiały opis po polsku i zakładka analizy z poradami

**Whitelista**
- adresy IP, sieci i domeny w bazie aplikacji; routery pobierają listę skryptem do `/ip firewall address-list`
- import i eksport, włączanie/wyłączanie wpisów; cały moduł można wyłączyć w Ustawieniach

**Pozostałe**
- tryb ustawiania / analizy Wi-Fi na żywo (odczyt co 2 s) do szukania najlepszego miejsca dla punktu dostępowego
- użytkownicy z rolami (administrator / podgląd), dziennik zmian
- automatyczne kopie zapasowe bazy z pobieraniem i usuwaniem w panelu
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
4. Uruchom:
   ```
   docker compose up -d --build
   ```
5. Otwórz `http://ADRES_SERWERA/` i zaloguj się danymi z `.env`.
6. Dodaj router (**Routery → Dodaj router**), skopiuj komendę ze strony routera i wklej ją w terminalu RouterOS.
   Po kilkudziesięciu sekundach pojawią się pierwsze dane.
7. Opcjonalnie HTTPS: **Ustawienia → HTTPS**, podaj domenę wskazującą na serwer (porty 80 i 443 muszą być dostępne z internetu).

Szczegóły konfiguracji routerów: [docs/ROUTERY.md](docs/ROUTERY.md).

## Aktualizacja

```
cd routeros-monitor
touch backups/.now        # kopia bazy przed aktualizacją (po kilkunastu sekundach pojawi się w backups/)
git pull
docker compose up -d --build
docker compose logs app --tail 30
```
Baza danych jest w wolumenie Dockera `dbdata`, a `.env` i `backups/` nie są częścią repozytorium, więc aktualizacja ich nie nadpisuje.
Nowe kolumny w bazie aplikacja dodaje sama przy starcie.
**Nie używaj `docker compose down -v`**, bo przełącznik `-v` usuwa wolumen z bazą.

Jeśli zmiana dotyczy skryptów na routerach, w opisie wersji będzie informacja, że trzeba ponownie wkleić komendę konfiguracyjną.

## Konfiguracja (`.env`)

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `DB_PASSWORD` | – | hasło bazy PostgreSQL (ustawiane tylko przy pierwszym starcie bazy) |
| `ADMIN_USER` / `ADMIN_PASSWORD` | `admin` / – | pierwsze konto administratora |
| `SECRET_KEY` | – | klucz sesji, min. 16 znaków (`openssl rand -hex 32`) |
| `RETENTION_DAYS` | `30` | ile dni trzymać pomiary |
| `SYSLOG_PORT` | `514` | port UDP na serwerze dla logów z routerów |
| `LOG_RETENTION_DAYS` | `14` | ile dni trzymać logi |
| `TZ` | `Europe/Warsaw` | strefa czasu |
| `BACKUP_HOUR` / `BACKUP_KEEP_DAYS` | `3` / `14` | godzina kopii zapasowej i czas jej przechowywania |
| `SPEEDTEST_TIME` | `03:30:00` | godzina nocnego testu prędkości |
| `SPEEDTEST_STREAMS` | `6` | liczba połączeń w zapasowym teście Cloudflare |

Nie używaj znaku `$` w wartościach (Compose traktuje go jako zmienną).
Pozostałe ustawienia (interwał odczytu, test prędkości, whitelista, kolejność routerów, HTTPS) są w panelu w zakładce **Ustawienia**.

## Kopie zapasowe

Kontener `backup` robi kopię codziennie o `BACKUP_HOUR` do katalogu `./backups`. Kopię na żądanie, pobieranie i usuwanie
znajdziesz w **Ustawienia → Kopie zapasowe bazy**.

Przywracanie (nadpisuje obecne dane):
```
docker compose stop app
docker compose exec -T db pg_restore -U monitor -d monitor --clean --if-exists < backups/NAZWA_PLIKU.dump
docker compose start app
```
Przeniesienie na nowy serwer: zainstaluj aplikację, skopiuj swój `.env` i plik kopii, uruchom i wykonaj przywracanie.

## Diagnostyka

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

Bezpieczeństwo: [docs/BEZPIECZENSTWO.md](docs/BEZPIECZENSTWO.md).

## Języki

Interfejs działa po polsku i angielsku (przełącznik PL / EN w menu i na ekranie logowania, wybór zapamiętuje ciasteczko). Kolejne języki dodaje się samym plikiem JSON, bez zmian w kodzie: [docs/TRANSLATING.md](docs/TRANSLATING.md).

## Licencja

Kod projektu: [MIT](LICENSE).

Podczas budowy obrazu pobierany jest program **Speedtest CLI firmy Ookla**, który nie jest częścią tego repozytorium
i ma własną licencję (użytek osobisty, niekomercyjny). Aplikacja uruchamia go z akceptacją licencji i polityki prywatności Ookla.
Jeśli tego nie chcesz, wybierz w Ustawieniach silnik Cloudflare.

Projekt nie jest powiązany z MikroTik, Ookla ani Cloudflare. Nazwy należą do ich właścicieli.
