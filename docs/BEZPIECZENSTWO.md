# Bezpieczeństwo

- **Sekrety tylko w `.env`.** Plik jest w `.gitignore` i nigdy nie trafia do repozytorium. Aplikacja nie wystartuje
  z przykładowymi hasłami ani z `SECRET_KEY` krótszym niż 16 znaków.
- **Hasła użytkowników** są przechowywane jako skróty z solą, nie jawnym tekstem.
- **Role:** administrator może zmieniać ustawienia, routery i whitelistę; konto podglądu tylko przegląda.
- **Token routera** w adresie komendy konfiguracyjnej działa jak hasło. Bez HTTPS przechodzi przez sieć jawnym tekstem,
  dlatego przy routerach łączących się przez internet włącz HTTPS (Ustawienia → HTTPS) albo użyj VPN.
- **Panel w internecie:** najlepiej udostępniaj go tylko w sieci lokalnej lub przez VPN. Jeśli musi być publiczny, włącz HTTPS
  i używaj silnych haseł.
- **Panel administracyjny Caddy** (port 2019) działa tylko w wewnętrznej sieci Dockera i nie jest wystawiony na zewnątrz.
- **Syslog (UDP 514)** nie ma uwierzytelniania; ogranicz port w firewallu serwera do adresów routerów, np.:
  ```
  sudo ufw allow from 192.168.88.0/24 to any port 514 proto udp
  ```
- **Kopie zapasowe** w `./backups` zawierają całą bazę (w tym skróty haseł i tokeny routerów). Nie udostępniaj ich.
- **Zasoby zewnętrzne:** wykresy korzystają z biblioteki Chart.js z CDN jsDelivr, sprawdzanie aktualizacji RouterOS łączy się
  z `upgrade.mikrotik.com`, test prędkości z serwerami Ookla lub Cloudflare.

Znalazłeś problem z bezpieczeństwem? Zgłoś go w zakładce Issues bez publikowania szczegółów pozwalających go wykorzystać.
