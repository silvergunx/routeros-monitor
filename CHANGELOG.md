# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/),
versions follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`, with `-beta.N` for test releases.

Notes marked **Routers** mean the configuration command has to be pasted again on the routers.

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
