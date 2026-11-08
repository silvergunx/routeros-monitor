"""Zabezpieczenie blacklisty przed odcięciem sobie dostępu (czysta logika, bez zależności od reszty aplikacji)."""
import ipaddress

MIN_PREFIX = 8  # najszersza dozwolona sieć IPv4 (/8)


def check_ban(entry, my_ips, host=""):
    """Czy wolno dodać `entry` (adres IPv4, sieć CIDR albo domenę) do blacklisty?

    my_ips - adresy, których nie wolno zablokować (Twój aktualny adres, serwer aplikacji, monitorowane routery),
    host   - nazwa domeny, pod którą działa panel.
    Zwraca "" (można) albo kod: "bad" (adres specjalny), "broad" (za szeroka sieć), "self" (obejmuje chroniony adres).
    """
    entry = (entry or "").strip().lower()
    try:
        net = ipaddress.ip_network(entry, strict=False)
    except ValueError:
        # domena: nie może być nazwą panelu
        return "self" if host and entry == host.strip().lower().rstrip(".") else ""
    if net.version != 4:
        return "bad"
    if net.is_loopback or net.is_unspecified or net.is_multicast or net.is_reserved:
        return "bad"
    if net.prefixlen < MIN_PREFIX:
        return "broad"
    for a in my_ips:
        try:
            if a and ipaddress.ip_address(str(a).split("%")[0]) in net:
                return "self"
        except ValueError:
            continue
    return ""
