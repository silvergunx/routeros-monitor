# Dziennik zmian

Polska wersja [CHANGELOG.md](CHANGELOG.md), który jest wersją źródłową (z niego powstają notatki wydań na GitHubie).
Tu opisane są wszystkie istotne zmiany. Format wzorowany na [Keep a Changelog](https://keepachangelog.com/),
wersje według [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`, z dopiskiem `-beta.N` dla wydań testowych.

Uwagi oznaczone **Routery** oznaczają, że trzeba ponownie wkleić komendę konfiguracyjną na routerach.

## [Unreleased]

## [1.3.0] - 2026-11-10
### Dodano
- **Wskaźnik nieaktualnego skryptu routera**: router podaje teraz wersję swojego skryptu przy każdym pomiarze. Gdy skrypt na routerze jest starszy niż ten, którego oczekuje aplikacja, administrator widzi plakietkę „skrypt na routerze nieaktualny” na liście routerów i na stronie routera, a strona „Zgłoś problem” też to pokazuje. **Routery**: wklej jeszcze raz komendę konfiguracyjną na każdym routerze (skrypty ze starszych wersji nie wysyłają wersji, więc do tego czasu są pokazywane jako nieaktualne). Od tej chwili panel sam powie, kiedy nowa wersja wymaga ponownego wklejenia.
- **Automatyczny ban (jak fail2ban)**, domyślnie wyłączony (Ustawienia → Blacklista). Gdy publiczny adres wywoła N nieudanych logowań (domyślnie 5) w ciągu M minut (domyślnie 10), trafia na blacklistę wszystkich routerów na ograniczony czas (domyślnie **1 h**, do wyboru 1/6/24/72 h), a ban wygasa sam. **Możesz sam się zablokować**: strona ustawień pokazuje wyraźne ostrzeżenie i prosi o potwierdzenie przy włączaniu. Aplikacja nie banuje adresów z whitelisty, serwera aplikacji, monitorowanych routerów ani adresów, z których w ostatnich 24 godzinach korzystano z panelu, ale nie zna Twoich innych adresów (dodaj je do whitelisty). Ban działa dopiero wtedy, gdy na routerach jest wklejona reguła blokująca ze strony blacklisty. Każdy ban jest zapisany w blackliście i w dzienniku zmian; maksymalnie 500 automatycznych wpisów naraz.
- **Wyciszanie hałaśliwych komunikatów logu**: administrator ma przycisk 🔇 przy ostrzeżeniach i informacjach w logach routera (zakładka Logi). Przestaje on zapisywać nowe wpisy tego routera pasujące do tego samego wzorca (liczby, adresy IP i adresy MAC są pomijane), co zmniejsza tabelę logów i bazę. Błędów, komunikatów krytycznych ani prób logowania nie da się wyciszyć. Wpisy pasujące do wyciszonego wzorca mają na liście stały znacznik 🔕, a jedno kliknięcie włącza je z powrotem; wyciszone wzorce są też wypisane w Ustawieniach (maksymalnie 100). Przy wyciszeniu wzorca stare pasujące ostrzeżenia i informacje tego routera są **usuwane** (po potwierdzeniu, nie da się tego cofnąć); zostaje najnowszy, ze znacznikiem 🔕.
- **Zgłoś problem** (administratorzy, link w stopce, strona `/report`): pokazuje dane diagnostyczne do zgłoszenia błędu i pozwala je skopiować albo otworzyć formularz błędu na GitHubie z wypełnionymi polami. Obejmuje środowisko (wersja, kanał obrazu, platforma, system, strefa czasowa, pamięć, czas działania), bazę (rozmiar i liczba wierszy największych tabel, retencja, interwał monitoringu), routery (jako „Router 1, 2…”: model, RouterOS i firmware, stan, ostatni kontakt, liczba wpisów logu w ostatniej godzinie, odrzucone źródła syslog), kopie zapasowe (liczba, rozmiar, wiek, ostatni błąd, limit, wolne miejsce) oraz funkcje (moduły, liczba wpisów na listach, status sprawdzania aktualizacji, silnik testu prędkości i ostatni wynik). Aplikacja niczego nie wysyła sama, a dane nie zawierają haseł, tokenów, adresów IP, nazw routerów ani użytkowników ani treści logów.

## [1.2.0] - 2026-11-08
### Dodano
- **Przycisk „Banuj” w analizie logów**: nieudane logowania z adresów publicznych mają przy każdym adresie przycisk „Banuj” (administratorzy, gdy moduł blacklisty jest włączony). Po potwierdzeniu dodaje adres do blacklisty wszystkich routerów bez terminu wygaśnięcia, z tymi samymi zabezpieczeniami co strona blacklisty (własny adres, serwer aplikacji, monitorowane routery). Zbanowane już adresy są oznaczone.
- Reguła firewalla blacklisty jest teraz ograniczona do interfejsów WAN (`in-interface-list=WAN`), usuwa swoją starszą kopię przy ponownym wklejeniu i jest też pokazana w analizie logów pod nieudanymi logowaniami, obok przycisków „Banuj”. **Routery**: wklej nową regułę ponownie, jeśli używasz starej (dopasowuje wszystkie interfejsy).

### Naprawiono
- „Zatwierdź” w logach routera obejmuje teraz także ostrzeżenia: przycisk liczy błędy i ostrzeżenia razem i działa, gdy są same ostrzeżenia (wcześniej zostawał nieaktywny, więc licznik ostrzeżeń na liście routerów nie dawał się wyzerować).
- Komentarze wpisów whitelisty i blacklisty z polskimi (spoza ASCII) literami były zniekształcone na liście adresów na routerze (RouterOS nie radzi sobie z nimi we wklejonym skrypcie). Teraz w skrypcie wysyłanym do routera są zamieniane na zwykłe ASCII (panel dalej pokazuje oryginalny tekst). Wpisy już utworzone ze zniekształconym komentarzem nie są zmieniane na routerze przez synchronizację: usuń je raz komendą `/ip firewall address-list remove [find comment~"^bl:"]` (lub `wl:`), a następna synchronizacja (do 5 min) odtworzy je poprawnie.
- Strona routera pokazywała „RouterOS {'v': ...} dostępny” zamiast wersji RouterOS: powiadomienie o aktualizacji aplikacji w menu przesłaniało zmienną aktualizacji RouterOS.

## [1.1.0] - 2026-11-08

### Dodano
- Silnik testu prędkości **LibreSpeed** (otwarte oprogramowanie, LGPL-3.0, [librespeed.org](https://librespeed.org)) wbudowany w obraz Dockera. Jest domyślnym silnikiem, gdy nie ma Speedtest by Ookla, więc użytkownicy gotowego obrazu dostają pełny test prędkości bez budowania czegokolwiek.
  Do LibreSpeed nie jest wysyłane nic poza samym ruchem testowym. Silnik i serwer wybierasz w Ustawieniach → Test prędkości.
  Domyślnie sam wybiera najlepszy serwer: porównuje 8 najbliższych krótkim testem pobierania, zapamiętuje najszybszy i powtarza sprawdzenie co 7 dni (przycisk „Znajdź najlepszy serwer teraz” w Ustawieniach). Używa 8 równoległych połączeń. Na szybkich łączach wynik pobierania może być wyraźnie niższy niż w Ookla (zależy od serwera społecznościowego), więc Ookla pozostaje zalecanym silnikiem, gdy budujesz obraz samodzielnie.
- `THIRD_PARTY.md` z licencjami wbudowanych składników.
- Zrzuty ekranu w README, zrobione z fikcyjnych danych demo (`tools/demo_data.py`, `tools/demo_server.py`, `tools/screenshots.py`).
- Poprawione teksty, które zostawały po polsku w angielskim interfejsie (rola CAPsMAN i funkcje routera, informacje o handshake VPN, komunikaty błędów testu prędkości, przykład importu).
- Szybszy i bezpieczniejszy start aplikacji: migracje bazy wykonują się tylko wtedy, gdy coś naprawdę trzeba zmienić (wcześniej działały przy każdym starcie i czekały na trwającą kopię zapasową, co mogło opóźnić start o minuty), a jednorazowe poprawki danych nie skanują już całej tabeli `metrics` przy każdym starcie. Oczekiwanie na blokadę tabeli jest ograniczone do 15 s na próbę.
- `IFACE_RETENTION_DAYS` (domyślnie **7**): próbki ruchu poszczególnych interfejsów, największa tabela w bazie, są teraz trzymane krócej niż pozostałe pomiary (`RETENTION_DAYS`). **Starsze próbki interfejsów są usuwane** (w tle, porcjami, żeby nie blokować routerów); wykresy interfejsów dla dłuższych zakresów pokazują mniej historii. Dzienne statystyki transferu WAN nie są dotknięte.
- **Zmienione pliki poza obrazem: `backup.sh`** (użytkownicy gotowego obrazu muszą pobrać go ponownie, patrz README, i zrestartować kontener `backup`: `docker compose restart backup`).
- Kopie zapasowe domyślnie nie zawierają już historii wykresów (`BACKUP_INCLUDE_METRICS=1` przywraca dawne zachowanie); logi, dziennik zmian, użytkownicy, routery, ustawienia i listy IP są zawsze w kopii. Kopie robią się dużo mniejsze.
- **Limit rozmiaru kopii zapasowych** (Ustawienia → Kopie zapasowe bazy): opcjonalnie ogranicza łączny rozmiar przechowywanych kopii (dla małych kart SD lub dysków). Najpierw usuwane są najstarsze kopie, a najnowsza zawsze zostaje; sprawdzane co 5 minut i przy zapisie limitu. Pokazuje też wolne miejsce na dysku i ostrzega, gdy jest go mało. Domyślnie brak limitu. Limitu nie da się ustawić poniżej rozmiaru najnowszej kopii.
- Lista porównywanych serwerów LibreSpeed jest domyślnie zwinięta; widać tylko wybrany serwer.
- **Blacklista** (lista banów) obok whitelisty: te same wpisy (IP, sieć lub domena, powód, opcjonalne wygaśnięcie, wszystkie routery lub jeden, import/eksport, włączanie/wyłączanie), osobny skrypt routera `app-blacklist` (**Routery**: wklej komendę konfiguracyjną ponownie) i gotowa do wklejenia reguła firewalla. Aplikacja odmawia zbanowania własnego adresu, serwera aplikacji, monitorowanego routera, adresów loopback/multicast i sieci szerszych niż /8. Moduł można wyłączyć w Ustawieniach.

## [1.0.0] - 2026-11-08

Pierwsza publiczna wersja.

### Dodano
- Monitoring routerów: CPU, RAM, temperatura, interfejsy i ruch WAN, klienci DHCP, klienci Wi-Fi (wifi-qcom / CAPsMAN / wireless), tunele VPN.
- Jakość łącza: sondy Netwatch, lista przerw, nocny test prędkości (Speedtest by Ookla z zapasowym Cloudflare).
- Logi routerów przez syslog z analizą „po ludzku” typowych komunikatów RouterOS.
- Centralna whitelista adresów IP pobierana przez routery.
- Tryb ustawiania i analizy Wi-Fi na żywo.
- Użytkownicy z rolami, dziennik zmian, automatyczne kopie zapasowe bazy, HTTPS jednym kliknięciem (Caddy).
- Interfejs po polsku i angielsku z przełącznikiem języka opartym na ciasteczku; kolejne języki można dodać plikiem JSON ([docs/TRANSLATING.md](docs/TRANSLATING.md)).
- Zwijana sekcja „Przerwy w internecie” na zakładce jakości łącza.
- README po angielsku, `SECURITY.md`, `CONTRIBUTING.md`.
- Gotowe wieloarchitekturowe obrazy Dockera (amd64, arm64) w GitHub Container Registry, z kanałami `stable` i `beta` (`APP_CHANNEL` w `.env`); `docker-compose.yml` obsługuje zarówno `docker compose pull`, jak i budowanie z kodu.
  Publiczne obrazy nie zawierają Speedtest CLI od Ookla.
- GitHub Actions: publikowanie obrazów, wydania GitHub z tagów, sprawdzanie plików tłumaczeń.
- `tools/check_locales.py` sprawdza pliki tłumaczeń; `tests/test_version.py` testuje obsługę wersji.
- Wersja aplikacji w stopce strony i plakietka dla administratorów, gdy na GitHubie jest nowsze wydanie (`UPDATE_CHECK=0` ją wyłącza).
