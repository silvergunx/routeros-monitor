# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/),
versions follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`, with `-beta.N` for test releases.

Notes marked **Routers** mean the configuration command has to be pasted again on the routers.

## [Unreleased]

Work in progress on `develop` (version 1.1.0).

### Added
- **LibreSpeed** speed test engine (open source, LGPL-3.0, [librespeed.org](https://librespeed.org)) bundled in the Docker image. It is the default
  engine when Speedtest by Ookla is not installed, so users of the ready-made image get a full speed test without building anything.
  Nothing is sent to LibreSpeed besides the test traffic itself. Choose the engine and server in Settings → Speed test.
  By default it picks the best server itself: it compares the 8 nearest servers with a short download test, remembers the fastest
  and repeats the check every 7 days (button "Find the best server now" in Settings). It uses 8 parallel connections. On fast links its download result can be well below Ookla's (it depends on the community server), so Ookla stays the
  recommended engine when you build the image yourself.
- `THIRD_PARTY.md` with the licences of bundled components.

## [1.0.0] - 2026-11-08

First public version.

### Added
- Router monitoring: CPU, RAM, temperature, interfaces and WAN traffic, DHCP clients, Wi-Fi clients (wifi-qcom / CAPsMAN / wireless), VPN tunnels.
- Link quality: Netwatch probes, outage list, nightly speed test (Speedtest by Ookla with a Cloudflare fallback).
- Router logs over syslog with a plain-language analysis of common RouterOS messages.
- Central IP whitelist fetched by the routers.
- Live Wi-Fi setup / analysis mode.
- Users with roles, change log, automatic database backups, one-click HTTPS (Caddy).
- Interface in Polish and English with a cookie-based language switcher; more languages can be added with a JSON file ([docs/TRANSLATING.md](docs/TRANSLATING.md)).
- Collapsible "Internet outages" section on the link quality tab.
- English README, `SECURITY.md`, `CONTRIBUTING.md`.
- Ready-made multi-arch Docker images (amd64, arm64) on GitHub Container Registry, with `stable` and `beta` channels
  (`APP_CHANNEL` in `.env`); `docker-compose.yml` supports both `docker compose pull` and building from source.
  The public images do not include Ookla's Speedtest CLI.
- GitHub Actions: image publishing, GitHub Releases from tags, checks for translation files.
- `tools/check_locales.py` validates translation files; `tests/test_version.py` tests version handling.
- Application version in the page footer and a badge for administrators when a newer release is available on GitHub (`UPDATE_CHECK=0` disables it).
