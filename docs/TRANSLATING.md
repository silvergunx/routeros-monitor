# Translating RouterOS Monitor / Tłumaczenia

The interface is available in **Polish** and **English**. Adding another language needs no code changes.

Interfejs jest dostępny po polsku i angielsku. Dodanie kolejnego języka nie wymaga zmian w kodzie.

## How to add a language

1. Copy `app/locales/en.json` to `app/locales/<code>.json` (e.g. `de.json`, `cs.json`, `uk.json`).
2. Set `"_name"` to the language name written in that language (it is shown in the language switcher).
3. Translate the **values**. Do not change the keys.
4. Optional: add a flag as `app/locales/<code>.svg` (a small SVG, ratio about 3:2). Without it the switcher shows just the code.
5. Rebuild the container: `docker compose up -d --build`. The new language appears in the menu and on the login page.

The language is chosen per browser: a cookie set by the switcher, otherwise the browser's `Accept-Language`, otherwise English.
Missing keys fall back to English, so a partial translation works.

## Rules for the translation files

- Keep placeholders exactly as they are: `{name}`, `{n}`, `{hour}`... and in keys starting with `an.` also `%s` / `%d` **in the same order** as in the original.
- Keys ending with `.html` may contain simple HTML (`<b>`, `<code>`). Keep the tags.
- Keep text in `` `backticks` `` (RouterOS commands) unchanged.
- Plurals: keys such as `rt.errors.one` / `.few` / `.many` / `.other`. English only needs `one` and `other`. If your language has other plural rules, add a function to `PLURAL` in `app/i18n.py`.
- Key groups: `nav.*`, `login.*`, `account.*`, `users.*`, `wl.*`, `rt.*` (router list), `rp.*` (router page), `lv.*` (Wi-Fi mode), `set.*` (settings), `msg.*` / `err.*` (messages), `an.NNN` (log analysis: explanations of RouterOS log messages).

## What is not translated

- The change log (audit log) entries are stored in the database in Polish (e.g. `logowanie`).
- Raw RouterOS log messages and router/interface names come from the routers.
- Server console output (`docker compose logs`).
- Dates and numbers follow the browser's locale.

## Checking your work

Run `python tools/check_locales.py`: it reports unknown keys, changed placeholders and untranslated keys (CI runs it too).

Open the panel with your language selected and click through every tab. A quick sanity check: search the file for keys whose value is still the English text.
