# Powiadomienia przez ntfy

Monitor potrafi wysyłać powiadomienia o zdarzeniach (router przestał nadawać, aktualizacja RouterOS, brak internetu, błąd kopii zapasowej,
automatyczny ban) do serwera [ntfy](https://ntfy.sh) i/lub na dowolny adres webhook. Ten rozdział opisuje, jak postawić własny serwer ntfy,
połączyć go z monitorem i telefonem oraz czego się spodziewać.

## Jak to działa

```
monitor ──(HTTP, JSON)──► serwer ntfy ──► telefon z aplikacją ntfy
                              └─ iPhone: sygnał „jest nowa wiadomość" przez ntfy.sh ─► push Apple ─► aplikacja pobiera treść z Twojego serwera
```

- Powiadomienia wysyła **serwer monitora**, więc działają także wtedy, gdy router jest wyłączony. Nie zadziałają, gdy padnie sam serwer monitora
  (lub serwer ntfy).
- Własny serwer ntfy oznacza, że temat i treść wiadomości zostają u Ciebie. Na iPhonie dla natychmiastowych powiadomień przez ntfy.sh idzie
  tylko sygnał, że przyszła wiadomość (patrz [iPhone](#iphone)).
- Treść wiadomości zawiera nazwę routera, ale **nie zawiera adresów IP, tokenów ani haseł**.

## Wymagania i minima

### Co zostało przetestowane

| Element | Przetestowana konfiguracja |
|---|---|
| RouterOS | **7.24.6** (kanał long-term) oraz 7.25 i 7.25.1; wersja 7 (wersji 6 nie wspieramy) |
| Serwer ntfy | ntfy **2.37.2**, instalacja natywna (pakiet `.deb`) na 32-bitowym Linuksie z systemd |
| Komputer z serwerem ntfy | jeden rdzeń ARMv6 ok. 1 GHz, **512 MB RAM**, karta pamięci, Wi-Fi 2,4 GHz |
| Telefon | iPhone z aplikacją ntfy (Android nie był testowany w tym projekcie) |
| Dostęp spoza domu | VPN (WireGuard) do sieci z serwerem ntfy |

### Minima (z zapasem 10 %)

Zasada: minimum = zmierzone lub policzone zapotrzebowanie **plus 10 % zapasu**. Tam, gdzie nie mamy pomiaru, minimum to najmniejsza
konfiguracja, na której to przetestowano; nie schodź poniżej niej.

| Wymaganie | Minimum | Skąd ta wartość |
|---|---|---|
| RouterOS | **7.24.6 lub nowszy** | najniższa przetestowana wersja; starszych wersji 7 nie sprawdzaliśmy |
| ntfy | **2.37.2 lub nowszy** | przetestowana wersja |
| Komputer z serwerem ntfy: CPU | 1 rdzeń ARMv6 ok. 1 GHz lub mocniejszy (ARMv7, ARM64, x86-64) | najsłabsza przetestowana konfiguracja |
| Komputer z serwerem ntfy: RAM | **512 MB** | najmniejsza przetestowana ilość; pomiar zajętości ntfy: zobacz [Jak sprawdzić zapas](#jak-sprawdzic-zapas) |
| Miejsce na dane ntfy | **4 MB** ponad system (pamięć podręczna i konta) | obliczenie poniżej |
| Sieć | monitor widzi serwer ntfy po HTTP; serwer ntfy ma dostęp wychodzący do `ntfy.sh` (tylko dla iPhone'a) | konstrukcja rozwiązania |
| Telefon | aplikacja ntfy; w sieci domowej lub przez VPN, żeby pobrać treść z serwera | konstrukcja rozwiązania |

**Obliczenie miejsca na dane.** Monitor wysyła najwyżej **30 wiadomości na godzinę** (twardy limit), a ntfy domyślnie trzyma wiadomości **12 godzin**
(`cache-duration`). Wiadomość ma najwyżej **4 KB** (domyślny limit ntfy). Daje to 30 × 12 × 4 KB ≈ 1,4 MB. Przyjmujemy dwukrotny narzut bazy
SQLite (założenie, nie pomiar), co daje ok. 2,8 MB, plus 10 % zapasu ≈ 3,1 MB, czyli **4 MB** po zaokrągleniu w górę. Konta i tokeny zajmują
poniżej 1 MB (założenie, nie pomiar), a to mieści się w zaokrągleniu. Załączniki nie są używane.

<a id="jak-sprawdzic-zapas"></a>
**Jak sprawdzić zapas na własnym sprzęcie.** Zmierz zajętość pamięci przez usługę i dodaj 10 %:

```bash
systemctl status ntfy | grep -i memory
```

```bash
ps -o rss,vsz,cmd -C ntfy
```

Do tego wolna pamięć po uruchomieniu systemu (`free -m`) musi wynosić co najmniej 1,1 × zajętość ntfy. Jeśli tak jest, masz wymagane 10 % zapasu.

## Zdarzenia i czas reakcji

| Zdarzenie | Kiedy | Priorytet w ntfy |
|---|---|---|
| Router przestał nadawać | po czasie z ustawień (domyślnie 5 min, najmniej 1 min) plus do 15 s sprawdzania | krytyczny (5) |
| Router wrócił | do 15 s od jego pierwszego pomiaru po powrocie; w wiadomości jest czas przerwy | informacja (3) |
| Aktualizacja RouterOS: router się restartuje | gdy router po pobraniu aktualizacji zamilknie (zamiast alertu „brak łączności”) | informacja (3) |
| RouterOS zaktualizowany (zmiana wersji) | gdy router wróci z inną wersją; pokazuje „z A na B” | informacja (3) |
| Brak internetu na routerze brzegowym i powrót | po czasie z ustawień (domyślnie 3 min) | krytyczny (5) / informacja (3) |
| Błąd kopii zapasowej lub brak świeżej kopii i powrót do normy | przy zmianie stanu | ostrzeżenie (4) / informacja (3) |
| Auto-ban zablokował adresy | zbiorczo, najwyżej co 10 min | ostrzeżenie (4) |

Zasady wysyłania: **jedno powiadomienie na zmianę stanu** (bez powtarzania), **najwyżej 30 na godzinę**. Nieudana wysyłka jest ponawiana tylko dla
tego zdarzenia po 15, 30, 60 i 120 s i nie wstrzymuje pozostałych. Tuż po restarcie monitora router, który jeszcze się nie zgłosił, czeka krótką
rozgrzewkę (ok. dwa interwały), a router, który już przysłał pomiar, jest oceniany od razu.

## Instalacja serwera ntfy (Linux)

Wybierz pakiet zgodny z architekturą (`uname -m`). Polecenia pochodzą z [dokumentacji ntfy](https://docs.ntfy.sh/install/); sprawdź tam aktualną
wersję.

**amd64, armv7 (armhf), arm64: repozytorium apt** (przykład dla armhf; dla innych zmień `arch=`):

```bash
sudo mkdir -p /etc/apt/keyrings
sudo curl -L -o /etc/apt/keyrings/ntfy.gpg https://archive.ntfy.sh/apt/keyring.gpg
sudo apt install apt-transport-https
echo "deb [arch=armhf signed-by=/etc/apt/keyrings/ntfy.gpg] https://archive.ntfy.sh/apt stable main" | sudo tee /etc/apt/sources.list.d/ntfy.list
sudo apt update
sudo apt install ntfy
```

**armv6: ręczne pobranie pakietu.** Repozytorium apt nie ma armv6, a pakiet armv7 się na nim nie uruchomi. Pobierz `ntfy_WERSJA_linux_armv6.deb`
ze [strony wydań](https://github.com/binwiederhier/ntfy/releases), a potem:

```bash
sudo dpkg -i ntfy_WERSJA_linux_armv6.deb
```

**Docker:** obraz `binwiederhier/ntfy`, polecenie `serve`; konfigurację zamontuj w `/etc/ntfy`, a dane w `/var/cache/ntfy`.

### Konfiguracja

W pliku `/etc/ntfy/server.yml` ustaw (adres serwera zamień na swój):

```yaml
base-url: "http://ADRES-SERWERA"
auth-file: "/var/lib/ntfy/user.db"
auth-default-access: "deny-all"
```

`deny-all` oznacza, że bez konta nikt niczego nie odczyta ani nie wyśle, nawet znając nazwę tematu. Uruchom usługę:

```bash
sudo systemctl enable ntfy && sudo systemctl restart ntfy
```

Sprawdź, czy działa: `sudo systemctl status ntfy` (stan `active (running)`).

### Konta i uprawnienia (najmniejsze uprawnienia)

Zamiast jednego konta administratora w telefonie i w monitorze utwórz trzy:

```bash
sudo ntfy user add --role=admin ADMIN          # tylko do zarządzania, nigdzie go nie wpisuj
sudo ntfy user add telefon                      # telefon: tylko odczyt
sudo ntfy access telefon TEMAT read-only
sudo ntfy user add monitor-wysylka              # monitor: tylko zapis
sudo ntfy access monitor-wysylka TEMAT write-only
sudo ntfy token add monitor-wysylka             # wypisze token (tk_...) dla monitora
```

Składnię `ntfy access` sprawdź przez `ntfy access --help` w swojej wersji. Jako `TEMAT` wybierz **długą, trudną do odgadnięcia nazwę**
(litery, cyfry, `-` i `_`; do 64 znaków). Token wpisujesz **tylko w monitorze**, a w telefonie logujesz się nazwą i hasłem konta `telefon`.
Przy publicznym serwerze `ntfy.sh` temat jest jedyną ochroną: każdy, kto zna jego nazwę, czyta wiadomości.

## Konfiguracja monitora

**Ustawienia → Powiadomienia i logi → Powiadomienia:**

1. Wpisz adres serwera ntfy (`http://ADRES-SERWERA`), temat i token konta `monitor-wysylka`. Adres webhooka (opcjonalnie) i token są zapisywane w bazie
   i nie są później pokazywane.
2. Zaznacz reguły (router przestał nadawać i po ilu minutach, brak internetu, kopia, auto-ban) oraz język powiadomień.
3. Zapisz, a potem kliknij **Wyślij testowe powiadomienie**. Test używa zapisanych ustawień i pomija limit godzinowy.
4. Zaznacz **Włącz powiadomienia** i zapisz. Sam przycisk testu wysyła zawsze, także przy wyłączonym module.

**Webhook** dostaje obiekt JSON z polami: `app`, `version`, `kind`, `severity`, `title`, `message`, `router`, `time`. Nadaje się np. do automatyzacji
domowej.

## Telefon

W aplikacji ntfy dodaj własny serwer (adres jak wyżej, konto `telefon` i jego hasło) i zasubskrybuj temat.

### Android

Własny serwer nie korzysta z Firebase. Wiadomości dochodzą przez stałe połączenie aplikacji (usługa w tle z trwałym powiadomieniem, w
dokumentacji ntfy „instant delivery"). Jeśli powiadomienia przychodzą dopiero po otwarciu aplikacji, sprawdź, czy ta usługa działa
(przełącznik „Subscription Service") i czy system nie ogranicza aplikacji w tle (oszczędzanie baterii, dodatkowe blokady producenta telefonu).

### iPhone

iOS nie pozwala aplikacji trzymać stałego połączenia, więc własny serwer potrzebuje w `server.yml` jednej linii (jest w dokumentacji ntfy jako
potrzebna dla powiadomień push na iOS):

```yaml
upstream-base-url: "https://ntfy.sh"
```

Po zmianie zrestartuj usługę (`sudo systemctl restart ntfy`) i dodaj subskrypcję na nowo. Telefon musi mieć dostęp do Twojego serwera (sieć
domowa lub VPN), żeby pobrać treść wiadomości; bez tego może pokazać tylko ogólny komunikat.

**Pułapka:** tryb Skupienia (np. **Sen**) wycisza banery. Wiadomość jest wtedy na liście w aplikacji, ale nie wyskakuje. Dodaj aplikację ntfy do
dozwolonych w ustawieniach trybu Skupienia.

### Dostęp spoza domu

Najprościej i najbezpieczniej: **ntfy zostaje w sieci lokalnej**, a telefon łączy się z domem przez **VPN** (np. WireGuard). Dla samego ntfy wystarczy
wąski tunel: w konfiguracji klienta ustaw `AllowedIPs` tylko na adres serwera ntfy (a nie `0.0.0.0/0`), żeby internet z telefonu nie szedł przez
tunel. Na routerze ogranicz ten tunel regułą firewalla do adresu serwera ntfy i jego portu.

Jeśli mimo to wystawiasz ntfy do internetu: **tylko po HTTPS** z prawdziwym certyfikatem (certyfikat dotyczy nazwy hosta, nie portu), z
`auth-default-access: "deny-all"`, kontami z ograniczonymi uprawnieniami i `behind-proxy: true`, gdy stoi za serwerem pośredniczącym. Zwykłe
HTTP przez internet ujawnia token i treść wiadomości.

## Rozwiązywanie problemów

| Objaw | Przyczyna i co zrobić |
|---|---|
| Strona ntfy w przeglądarce: „Powiadomienia nie są obsługiwane … tylko przez HTTPS" | To ograniczenie przeglądarki (powiadomienia systemowe tylko przez HTTPS), nie błąd serwera. Używaj aplikacji w telefonie; powiadomienia z monitora i tak dochodzą. |
| Test w monitorze: `HTTP 403` lub `HTTP 401` | Konto lub token nie ma prawa zapisu do tematu, albo wpisano zły temat lub token. Sprawdź `sudo ntfy access`. |
| Test w monitorze: `timed out` lub `connection refused` | Zły adres lub port, firewall, serwer ntfy nie działa. Monitor czeka na odpowiedź do 10 s. |
| Wiadomość jest na liście w aplikacji, ale nie ma banera (iPhone) | Tryb Skupienia (np. Sen), wyłączone powiadomienia aplikacji lub brak `upstream-base-url`. |
| Alert przychodzi dopiero po kilku minutach | Sprawdź w monitorze **Zgłoś problem → Notifications** (stan, ostatni błąd, oczekujące ponowienia) i **Application log** (wiersze `notify:`). Alert przychodzi po progu z ustawień (domyślnie 5 min) plus do 15 s. |
| iPhone pokazuje tylko ogólny komunikat | Telefon nie ma dostępu do serwera ntfy w chwili otrzymania sygnału (brak VPN lub sieci domowej). |

## Aktualizacja i kopia serwera ntfy

- Aktualizacja: `sudo apt update && sudo apt upgrade` (repozytorium apt) albo ponowna instalacja nowszego pakietu `.deb`.
- Kopia: plik użytkowników i tokenów (`/var/lib/ntfy/user.db`, ścieżka z `auth-file`). Pamięć podręczna wiadomości nie wymaga kopii.
