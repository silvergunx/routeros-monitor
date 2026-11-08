"""Testy limitu rozmiaru kopii. Uruchom: python tests/test_backups.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from backups import plan_prune, parse_limit_gb

MB = 1024 * 1024
F = [("a.dump", 100 * MB, 1), ("b.dump", 100 * MB, 2), ("c.dump", 100 * MB, 3), ("d.dump", 100 * MB, 4)]   # a najstarsza, d najnowsza

# --- bez limitu / mieści się
assert plan_prune(F, None) == [] and plan_prune(F, 0) == [] and plan_prune(F, -5) == []
assert plan_prune(F, 400 * MB) == [] and plan_prune(F, 10_000 * MB) == []
# --- usuwa od najstarszej, dokładnie tyle ile trzeba
assert plan_prune(F, 399 * MB) == ["a.dump"]
assert plan_prune(F, 300 * MB) == ["a.dump"]
assert plan_prune(F, 299 * MB) == ["a.dump", "b.dump"]
assert plan_prune(F, 100 * MB) == ["a.dump", "b.dump", "c.dump"]
# --- najnowsza zostaje zawsze, nawet większa niż limit
assert plan_prune(F, 1) == ["a.dump", "b.dump", "c.dump"]
assert plan_prune([("x.dump", 900 * MB, 5)], 10 * MB) == [] and plan_prune([], 10 * MB) == []
# --- kolejność wejściowa nie ma znaczenia; różne rozmiary
shuffled = [F[2], F[0], F[3], F[1]]
assert plan_prune(shuffled, 150 * MB) == ["a.dump", "b.dump", "c.dump"]
mixed = [("old.dump", 500 * MB, 1), ("mid.dump", 50 * MB, 2), ("new.dump", 60 * MB, 3)]
assert plan_prune(mixed, 120 * MB) == ["old.dump"]
# --- równe czasy: deterministycznie wg nazwy
same = [("b.dump", MB, 7), ("a.dump", MB, 7), ("c.dump", MB, 7)]
assert plan_prune(same, MB) == ["a.dump", "b.dump"]

# --- parsowanie limitu (GB -> MB)
assert parse_limit_gb("2") == 2048 and parse_limit_gb("2,5") == 2560 and parse_limit_gb(" 0.5 ") == 512
assert parse_limit_gb("0,1") == 102 and parse_limit_gb("100000") == 100000 * 1024
for bad in ("", "abc", "0", "-1", "0.05", "100001", "nan", "inf", None):
    assert parse_limit_gb(bad) is None, bad
print("test_backups: OK")
