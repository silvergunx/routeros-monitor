# Contributing

Thank you for your interest! Bug reports, ideas, translations and pull requests are welcome.

## Reporting a problem or suggesting something

Open an issue and include: the application version (file `VERSION`), the RouterOS version of the router involved,
what you expected and what happened, and the relevant lines of `docker compose logs app`.
Remove passwords, tokens and public IP addresses from anything you paste.
For security problems see [SECURITY.md](SECURITY.md) instead.

## Branches and releases

| Branch | Purpose |
|---|---|
| `main` | stable code; every stable release (`v1.2.0`) is tagged here |
| `develop` | work in progress and test releases (`v1.3.0-beta.1`) |

Open pull requests against **`develop`**. Maintainers merge `develop` into `main` and tag a release when it has been tested.
Update [CHANGELOG.md](CHANGELOG.md) in your pull request.

Releasing (maintainers):
1. Set the version in `VERSION` and add a section `## [x.y.z] - date` to `CHANGELOG.md`.
2. Test a beta first: tag `vX.Y.Z-beta.1` on `develop`. GitHub Actions publishes the image `:beta` and a pre-release.
3. When it is good, merge `develop` into `main` and tag `vX.Y.Z`. Actions publishes `:X.Y.Z` and `:stable` and creates the Release
   (the tag must match `VERSION`).

## Translations

The easiest way to help: add a language. No code changes are needed, see [docs/TRANSLATING.md](docs/TRANSLATING.md).

## Running it locally

```
git clone https://github.com/silvergunx/routeros-monitor.git
cd routeros-monitor
git checkout develop
cp .env.example .env      # set DB_PASSWORD, ADMIN_PASSWORD, SECRET_KEY
docker compose up -d --build
```

The panel is then at `http://localhost/`. After changing Python or template files rebuild with `docker compose up -d --build`.

## Code guidelines

- Keep changes small and focused; one topic per pull request.
- Every text shown to the user goes through the translation files (`app/locales/*.json`), never hard-coded in templates or Python.
  Provide at least the English and Polish text.
- Run `python tools/check_locales.py` after touching `app/locales/*.json`.
- Do not add new dependencies without a good reason; the project is intentionally small.
- Do not commit secrets, `.env` files, backups or real router data.
