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
- Faster and safer application start: database migrations are executed only when something actually has to change (they used to run on every
  start and waited for a running backup to finish, which could delay the start by minutes), and the one-off data fixes no longer scan the whole
  `metrics` table on every start. Waiting for a table lock is limited to 15 s per attempt.
- `IFACE_RETENTION_DAYS` (default **7**): per-interface traffic samples, the largest table in the database, are now kept for fewer days than
  the other measurements (`RETENTION_DAYS`). **Older interface samples are deleted** (in the background, in chunks, so routers are not blocked); the
  interface charts for ranges longer than this show less history. The daily WAN transfer statistics are not affected.
- Backups no longer contain the chart history by default (`BACKUP_INCLUDE_METRICS=1` restores the old behaviour); logs, the change log, users, routers,
  settings and IP lists are always included. Backups become much smaller.
- **Backup size limit** (Settings → Database backups): optionally cap the total size of the stored backups (for small SD cards or disks). The oldest
  backups are removed first and the newest one is always kept; checked every 5 minutes and when the limit is saved. Also shows the free disk space and
  warns when it is low. The default is no limit. The limit cannot be set below the size of the newest backup.
- The list of compared LibreSpeed servers is collapsed by default; only the chosen server is shown.
- **Blacklist** (ban list) next to the whitelist: the same entries (IP, network or domain, reason, optional expiry, all routers or one,
  import/export, enable/disable), a separate router script `app-blacklist` (**Routers**: paste the configuration command again) and a
  ready-to-paste firewall rule. The application refuses to ban your own address, the application server, a monitored router,
  loopback/multicast addresses and networks broader than /8. The module can be switched off in Settings.

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
