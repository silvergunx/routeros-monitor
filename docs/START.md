# Pierwsze 5 minut

Ten przewodnik jest dla kogoś, kto nie zna RouterOS i chce zobaczyć, jak wygląda jego sieć. Nie musisz niczego rozumieć na starcie: panel tłumaczy pojęcia w dymkach (ikona ⓘ), a wszystko, co robi na routerze, możesz w każdej chwili usunąć jedną komendą.

## Co będzie potrzebne

- komputer, który działa cały czas i ma Dockera (może to być mały komputer jednopłytkowy, NAS albo serwer wirtualny),
- router MikroTik z RouterOS 7,
- przeglądarka na dowolnym urządzeniu w tej samej sieci.

## Krok po kroku

1. **Zainstaluj panel.** Skopiuj plik z ustawieniami, wpisz własne hasła i uruchom (pełne komendy są w [README](../README.pl.md#instalacja)). Panel nie wystartuje z przykładowymi hasłami, żeby nikt nie został z domyślnym.
2. **Zaloguj się** w przeglądarce pod adresem serwera, danymi z pliku z ustawieniami.
3. **Dodaj router.** W panelu: **Routery → Dodaj router**. Na stronie routera zobaczysz gotową komendę. Skopiuj ją.
4. **Wklej komendę w terminalu routera** (Winbox → New Terminal albo SSH). Nie podajesz nigdzie hasła do routera: router sam wysyła dane do panelu. Po kilkudziesięciu sekundach pojawią się pierwsze dane.
5. **Zobacz, co masz.** Otwórz stronę routera. Zakładki pokazują kolejno: **Porty** (które gniazda działają i z jaką prędkością), **Wykresy** (obciążenie i ruch), **Urządzenia** (kto jest w sieci), **Wi-Fi** (jakość połączenia każdego urządzenia), **VPN** i **Logi** (zdarzenia z routera tłumaczone na zwykły język).

## Co zrobić potem (kiedy chcesz)

- **Mapa sieci.** W Ustawieniach włącz moduł **Topologia** i wklej komendę ponownie na routerach. Zobaczysz rysunek: Internet, routery, access pointy, urządzenia kablowe i Wi-Fi oraz połączenia VPN.
- **Powiadomienia na telefon.** Jeśli chcesz wiedzieć, że router przestał odpowiadać albo wypadł internet, ustaw powiadomienia (patrz [docs/NTFY.md](NTFY.md)).
- **Nazwy urządzeń.** Kliknij ✎ przy urządzeniu i nadaj mu nazwę. Będzie widoczna wszędzie w panelu.
- **Blokowanie adresów.** Whitelista i blacklista są opcjonalne i ich włączenie wymaga Twojej decyzji. Panel nigdy sam nie zmienia firewalla.

## Czego panel nie robi

- Nie zna haseł do Twoich routerów i nie loguje się na nie.
- Nie zmienia firewalla ani innych ustawień routera. Skrypty tylko czytają informacje i wysyłają je do panelu.
- Niczego nie wysyła poza Twoją sieć (żadnej telemetrii). Opcjonalnie sprawdza, czy jest nowa wersja, i można to wyłączyć.

## Jeśli coś nie działa

- Router nie pojawia się w panelu: sprawdź, czy router widzi serwer (adres w komendzie musi być osiągalny z routera) i czy komenda wkleiła się w całości.
- Wszystko, co panel zainstalował na routerze, ma nazwę zaczynającą się od `app-`. Usunięcie opisano w [docs/ROUTERY.md](ROUTERY.md).
- W razie pytań lub błędów: przycisk „Zgłoś problem” w stopce panelu przygotowuje opis bez haseł i tokenów, który możesz wkleić w zgłoszeniu na GitHubie.

## Dymki i tryby: Uczę się i Pro

Obok trudniejszych pojęć (CAPsMAN, VLAN, klasa sprzętu, legenda mapy) jest ikona **ⓘ**. Kliknięcie pokazuje krótkie wyjaśnienie. Na początku masz tryb **Uczę się** (podpowiedzi włączone). Gdy znasz już pojęcia, przełącz się na tryb **Pro**: ikony znikają. Przełącznik jest w każdej podpowiedzi (także w pierwszej) oraz na stronie konta.
