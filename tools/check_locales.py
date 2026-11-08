#!/usr/bin/env python3
"""Checks the translation files in app/locales against the English reference (en.json).

Errors (exit code 1): invalid JSON, keys that do not exist in en.json, placeholders ({name}, %s, %d)
that differ from the English text, a missing "_name".
Warnings: keys that are not translated yet (the app falls back to English for them).

Usage: python tools/check_locales.py
"""
import json
import re
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "app" / "locales"
REF = "en"


PLURAL = re.compile(r"^(.+)\.(one|few|many|other)$")


def base(key):
    m = PLURAL.match(key)
    return m.group(1) if m else key


def placeholders(text):
    return sorted(re.findall(r"\{\w+\}", text)), re.findall(r"%[sd]", text)


def main():
    files = {f.stem: f for f in sorted(DIR.glob("*.json"))}
    if REF not in files:
        print("missing %s.json" % REF)
        return 1
    data, errors, warnings = {}, [], []
    for code, f in files.items():
        try:
            data[code] = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            errors.append("%s.json: invalid JSON: %s" % (code, e))
    if errors:
        print("\n".join(errors))
        return 1
    ref = data[REF]
    ref_bases = {base(k) for k in ref}
    for code, d in data.items():
        if code == REF:
            continue
        if not d.get("_name"):
            errors.append("%s.json: missing \"_name\"" % code)
        for k, v in d.items():
            if k not in ref and not (PLURAL.match(k) and base(k) in ref_bases):
                errors.append("%s.json: unknown key %r (not in %s.json)" % (code, k, REF))
            elif not isinstance(v, str):
                errors.append("%s.json: value of %r is not a string" % (code, k))
            elif k in ref and placeholders(v) != placeholders(ref[k]):
                errors.append("%s.json: placeholders differ in %r: %s vs %s" % (code, k, placeholders(v), placeholders(ref[k])))
        have = {base(k) for k in d}
        missing = sorted({base(k) for k in ref if not k.startswith("_")} - have)
        if missing:
            warnings.append("%s.json: %d key(s) not translated yet (falls back to English), e.g. %s" % (code, len(missing), ", ".join(missing[:5])))
    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("ERROR:", e)
    print("%d language file(s) checked, %d error(s), %d warning(s)" % (len(data), len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
