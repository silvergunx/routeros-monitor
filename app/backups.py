"""Limit rozmiaru kopii zapasowych: wybór kopii do usunięcia (czysta logika, bez zależności)."""


def plan_prune(files, max_bytes):
    """Które kopie usunąć, żeby łączny rozmiar nie przekraczał `max_bytes`.

    files     - [(nazwa, rozmiar_w_bajtach, czas_modyfikacji)], dowolna kolejność
    max_bytes - limit; None albo <= 0 = bez limitu
    Usuwa od najstarszej. NAJNOWSZA kopia zostaje zawsze, nawet gdy sama jest większa niż limit.
    Zwraca listę nazw do usunięcia (od najstarszej).
    """
    if not max_bytes or max_bytes <= 0 or len(files) < 2:
        return []
    ordered = sorted(files, key=lambda f: (f[2], f[0]))      # od najstarszej
    total = sum(f[1] for f in ordered)
    out = []
    for name, size, _ in ordered[:-1]:                        # najnowszej nie ruszamy
        if total <= max_bytes:
            break
        out.append(name)
        total -= size
    return out


def parse_limit_gb(text):
    """'2', '2,5', '0.5' -> limit w MB (int) albo None, gdy wartość jest niepoprawna. Zakres 0,1 GB .. 100000 GB."""
    try:
        gb = float(str(text).strip().replace(",", "."))
    except ValueError:
        return None
    if not (0.1 <= gb <= 100000) or gb != gb:
        return None
    return int(round(gb * 1024))
