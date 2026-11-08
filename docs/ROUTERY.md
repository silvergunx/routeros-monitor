# Routery MikroTik

## Podłączenie routera

1. W panelu: **Routery → Dodaj router**. Podaj nazwę i zaznacz **router brzegowy**, jeśli ten router ma bezpośrednie wyjście do internetu
   (tylko on mierzy jakość internetu i prędkość łącza; pozostałe routery mierzą tylko połączenie do swojej bramy).
2. Na stronie routera skopiuj komendę konfiguracyjną. Wygląda tak:
   ```
   /tool fetch url="http://ADRES_SERWERA/api/setup.rsc?t=TOKEN&every=60" dst-path=app-setup.rsc; :delay 1s; /import app-setup.rsc
   ```
3. Wklej ją w terminalu RouterOS (WinBox → New Terminal albo SSH). Na końcu skrypt wypisze, które moduły włączył.

`TOKEN` jest unikalny dla każdego routera i działa jak hasło: kto go zna, może wysyłać dane w imieniu routera
i pobierać whitelistę. Nie publikuj go. Jeśli wyciekł, usuń router w panelu i dodaj go ponownie (dostanie nowy token).

Komendę wklejasz ponownie po zmianie interwału odczytu, adresu serwera (np. po włączeniu HTTPS) albo gdy opis wersji o tym mówi.
Skrypt najpierw usuwa swoje stare elementy, więc ponowne wklejenie jest bezpieczne.

## Co instaluje komenda

Wszystkie elementy mają nazwy zaczynające się od `app-`, dzięki czemu łatwo je znaleźć i usunąć.

| Element | Nazwa | Zadanie |
|---|---|---|
| skrypt + harmonogram | `app-monitor` / `app-mon` | parametry systemu i interfejsów co interwał (domyślnie 60 s) |
| skrypty + harmonogram | `app-inventory` (`app-inv-dhcp`, `app-inv-wifi`, `app-inv-wireless`, `app-inv-vpn`, `app-inv-sys`) / `app-inv` | klienci DHCP, Wi-Fi, VPN, informacje o systemie co minutę |
| skrypt + harmonogram | `app-whitelist` / `app-wl` | pobranie whitelisty co 5 min (tylko gdy moduł włączony) |
| skrypt + harmonogram | `app-blacklist` / `app-bl` | pobranie blacklisty co 5 min (tylko gdy moduł włączony) |
| skrypt + harmonogram | `app-speed` / `app-spd` | test prędkości na routerze (router brzegowy, gdy serwer aplikacji nie stoi w jego sieci) |
| skrypt | `app-live` | tryb ustawiania Wi-Fi na żywo, uruchamiany tylko na żądanie z panelu |
| sondy Netwatch | komentarz `app-nw:` | brama, a na routerze brzegowym: DNS 1.1.1.1, 8.8.8.8, 9.9.9.9, test DNS i HTTP |
| akcja i reguły logowania | `appsyslog` | wysyłanie logów (critical, error, warning, info bez fetch) na serwer, UDP `SYSLOG_PORT` |
| lista adresów | `whitelist`, komentarz `wl:` | wpisy whitelisty; inne wpisy na tej liście nie są ruszane |
| lista adresów | `blacklist`, komentarz `bl:` | wpisy blacklisty; inne wpisy na tej liście nie są ruszane |

Skrypty, które nie mają sensu na danym urządzeniu (Wi-Fi bez interfejsów Wi-Fi, DHCP bez serwera DHCP), nie są instalowane.

## Whitelista w firewallu

Aplikacja tylko wypełnia listę adresów `whitelist`. Regułę, która z niej korzysta, dodajesz sam, np.:
```
/ip firewall filter add chain=input src-address-list=whitelist action=accept comment="dostep z whitelisty" place-before=0
```
Zanim dodasz regułę blokującą resztę, sprawdź, że Twój adres jest na liście, żeby nie odciąć sobie dostępu.

## Blacklista w firewallu

Aplikacja tylko wypełnia listę adresów `blacklist`; sama niczego nie blokuje. Regułę blokującą dodajesz raz na każdym routerze
(tabela raw działa przed śledzeniem połączeń, więc mało obciąża procesor):
```
/ip firewall raw add chain=prerouting src-address-list=blacklist action=drop comment="app-blacklist"
```
O kolejności decydują reguły firewalla. Jeśli adresy z whitelisty nigdy nie mają być blokowane, dodaj dla nich regułę `accept`
przed regułą z blacklisty. Aplikacja nie pozwoli zbanować Twojego aktualnego adresu, adresu serwera aplikacji, monitorowanych
routerów ani sieci szerszych niż /8, ale pilnuje tylko adresów, które zna: reguły na routerze sprawdzaj ostrożnie.
Usunięcie konfiguracji z routera (strona routera → Konfiguracja) usuwa też wpisy `bl:` i regułę `app-blacklist`.

## Router poza siecią lokalną

Routery łączą się z serwerem same, więc router w innej lokalizacji musi widzieć adres serwera: przez VPN (np. WireGuard)
albo przez domenę z HTTPS. Bez tego dane nie dotrą.

## Usunięcie z routera

```
/system scheduler remove [find name~"^app-"]
/system script remove [find name~"^app-"]
/tool netwatch remove [find comment~"^app-nw:"]
:do {/system logging remove [find action=appsyslog]} on-error={}
:do {/system logging action remove [find name=appsyslog]} on-error={}
/ip firewall address-list remove [find comment~"^wl:"]
/file remove [find name~"^app-"]
```
Pierwsze dwie linie zatrzymują wysyłanie danych i usuwają skrypty, trzecia usuwa sondy, czwarta i piąta logowanie na serwer,
szósta wpisy whitelisty dodane przez aplikację, siódma pobrane pliki.

## Najczęstsze problemy

- **Brak danych po wklejeniu komendy:** sprawdź z routera `/tool fetch url="http://ADRES_SERWERA/" output=none`.
  Jeśli nie działa, router nie widzi serwera (firewall, routing, zły adres).
- **Logi nie przychodzą:** port UDP `SYSLOG_PORT` musi być otwarty na serwerze. Logi są przypisywane do routera po adresie IP;
  przy NAT ustaw adres ręcznie w zakładce Konfiguracja routera.
- **Test prędkości z serwera niedostępny:** wybierz w **Ustawienia → Test prędkości** router, w którego sieci stoi serwer aplikacji.
  Sprawdź `docker compose exec app speedtest --version`.
