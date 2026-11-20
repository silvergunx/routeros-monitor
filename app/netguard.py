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


_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def is_local_addr(ip):
    """True dla adresu z sieci prywatnej, lokalnej (link-local), pętli zwrotnej i CGNAT (100.64.0.0/10, np. tunele VPN dostawców)."""
    try:
        a = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_private or a.is_loopback or a.is_link_local or (a.version == 4 and a in _CGNAT)


def target_allowed(host, private_only=True, resolver=None):
    """Czy serwer panelu może samodzielnie połączyć się z urządzeniem `host` (sondy, SNMP). Przy private_only wszystkie adresy,
    na które host się rozwiązuje, muszą być lokalne; nierozwiązywalna nazwa jest odrzucana. Zwraca (True/False, powód)."""
    host = (host or "").strip()
    if not host:
        return False, "empty"
    if not private_only:
        return True, ""
    import socket
    try:
        infos = (resolver or socket.getaddrinfo)(host, None)
    except OSError:
        return False, "unresolved"
    ips = {i[4][0] for i in infos}
    if not ips:
        return False, "unresolved"
    if all(is_local_addr(x) for x in ips):
        return True, ""
    return False, "public address"
