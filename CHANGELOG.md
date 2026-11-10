# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/),
versions follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`, with `-beta.N` for test releases.

Notes marked **Routers** mean the configuration command has to be pasted again on the routers.

## [Unreleased]

Work in progress on `develop` (version 1.4.0).

### Added
- **Application log in the "Report a problem" page**: the tail of the application log (warnings, errors including stack traces of server errors, and printed messages) is added to the report with tokens, IP and MAC addresses, e-mails and router, user and domain names removed automatically. The filter is best-effort, so the text can be reviewed and edited before copying. The log buffer lives in memory and is cleared on restart; access logs are not included.

### Changed
- The mute button (🔇) is no longer shown on login-failure entries and other entries that can never be muted.
- `README.pl.md` links the Polish changelog.

## [1.3.0] - 2026-11-10
### Added
- **Outdated router script indicator**: the router now reports the version of its script with every measurement. When the script on a router is older than the one the application expects, administrators see a badge "router script outdated" on the router list and on the router page, and the "Report a problem" page lists it. **Routers**: paste the configuration command once more on every router (the scripts of earlier versions send no version, so they are shown as outdated until then). From then on the panel tells you whenever a new version needs a re-paste.
- **Automatic ban (like fail2ban)**, off by default (Settings → Blacklist). When a public address causes N failed logins (default 5) within M minutes (default 10), it is added to the blacklist for all routers for a limited time (default **1 h**, choices 1/6/24/72 h) and the ban expires on its own. **You can lock yourself out**: the settings page shows a clear warning and asks for confirmation when you enable it. It never bans whitelisted addresses, the application server, monitored routers or addresses that accessed the panel in the last 24 hours, but it does not know your other addresses (add them to the whitelist). A ban only takes effect when the blocking rule from the blacklist page is pasted on the routers. Each ban is recorded in the blacklist and the change log; at most 500 automatic entries at once.
- **Mute noisy log messages**: administrators get a 🔇 button on warning and information entries in the router logs (Logs tab). It stops storing new entries of that router that match the same pattern (numbers, addresses and MAC addresses are ignored), which keeps the log table and the database smaller. Errors, critical messages and login attempts can never be muted. Entries that match a muted pattern keep a 🔕 marker in the list, and one click unmutes them again; muted patterns are also listed in Settings (at most 100). When you mute a pattern, the old matching warning and information entries of that router are **deleted** (after a confirmation, this cannot be undone); the newest one stays, with the 🔕 marker.
- **Report a problem** (administrators, link in the footer, page `/report`): shows diagnostic data for a bug report and lets you copy it or open the GitHub bug form with the fields filled in. It covers the environment (version, image channel, platform, OS, time zone, memory, uptime), the database (size and row counts of the largest tables, retention settings, monitoring interval), routers (as "Router 1, 2...": model, RouterOS and firmware, state, last contact, number of log entries in the last hour, rejected syslog sources), backups (count, size, age, last error, limit, free space) and features (modules, number of list entries, update check status, speed test engine and last result). The application sends nothing by itself, and the data contains no passwords, tokens, IP addresses, router or user names or log contents.

## [1.2.0] - 2026-11-08
### Added
- **Ban button in the log analysis**: failed logins from public addresses show a "Ban" button next to each address (administrators, when the blacklist module is on). It adds the address to the blacklist for all routers without expiry, after a confirmation, using the same protections as the blacklist page (own address, application server, monitored routers). Already banned addresses are marked.
- The blacklist firewall rule is now limited to the WAN interfaces (`in-interface-list=WAN`), removes its older copy when pasted again, and is also shown in the log analysis under the failed logins, next to the Ban buttons. **Routers**: paste the new rule again if you already use the old one (it matches all interfaces).

### Fixed
- "Acknowledge" in the router logs now also covers warnings: the button counts errors and warnings together and works when there are only warnings (it used to stay disabled, so the warning counter on the router list could not be reset).
- Whitelist and blacklist comments with Polish (non-ASCII) letters were garbled in the address list on the router (RouterOS does not handle them in a pasted script). They are now converted to plain ASCII in the script sent to the router (the panel still shows the original text). Entries already created with a garbled comment are not changed on the router by the sync: remove them once with `/ip firewall address-list remove [find comment~"^bl:"]` (or `wl:`) and the next sync (up to 5 min) recreates them.
- The router page showed "RouterOS {'v': ...} available" instead of the RouterOS version: the application update notice in the menu shadowed the RouterOS update variable.

## [1.1.0] - 2026-11-08

### Added
- **LibreSpeed** speed test engine (open source, LGPL-3.0, [librespeed.org](https://librespeed.org)) bundled in the Docker image. It is the default
  engine when Speedtest by Ookla is not installed, so users of the ready-made image get a full speed test without building anything.
  Nothing is sent to LibreSpeed besides the test traffic itself. Choose the engine and server in Settings → Speed test.
  By default it picks the best server itself: it compares the 8 nearest servers with a short download test, remembers the fastest
  and repeats the check every 7 days (button "Find the best server now" in Settings). It uses 8 parallel connections. On fast links its download result can be well below Ookla's (it depends on the community server), so Ookla stays the
  recommended engine when you build the image yourself.
- `THIRD_PARTY.md` with the licences of bundled components.
- Screenshots in the README, taken from fictional demo data (`tools/demo_data.py`, `tools/demo_server.py`, `tools/screenshots.py`).
- Fixed texts that stayed in Polish in the English interface (CAPsMAN role and router features, VPN handshake info, speed-test error messages, import example).
- Faster and safer application start: database migrations are executed only when something actually has to change (they used to run on every
  start and waited for a running backup to finish, which could delay the start by minutes), and the one-off data fixes no longer scan the whole
  `metrics` table on every start. Waiting for a table lock is limited to 15 s per attempt.
- `IFACE_RETENTION_DAYS` (default **7**): per-interface traffic samples, the largest table in the database, are now kept for fewer days than
  the other measurements (`RETENTION_DAYS`). **Older interface samples are deleted** (in the background, in chunks, so routers are not blocked); the
  interface charts for ranges longer than this show less history. The daily WAN transfer statistics are not affected.
- **Changed files outside the image: `backup.sh`** (users of the ready-made image must download it again, see the README, and restart the `backup`
  container: `docker compose restart backup`).
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
