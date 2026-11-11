# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/),
versions follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`, with `-beta.N` for test releases.

Notes marked **Routers** mean the configuration command has to be pasted again on the routers.

## [Unreleased]

## [1.5.0] - 2026-11-11

### Added
- **Devices without DHCP in the Devices list**: a device with a fixed IP address (or a network without a DHCP server) used to be missing, because only DHCP leases were read. The `app-inv-dhcp` router script now also sends the ARP table entries that have no DHCP lease (address, MAC, interface, state). They get the same online/idle/offline status as the others and show as "no DHCP" with the vendor from the MAC address and, if you set one, your own name (✎). An IP address in ARP without a real MAC address (empty or all zeros) is not hidden: it shows as a highlighted "unknown device" without a vendor, so you can notice that something tries to talk to an address nobody answers for. Entries from the WAN interface (the provider's gateway and neighbours) are ignored, and failed or incomplete ARP entries are skipped. An ARP entry expires a few minutes after the last traffic, so a silent device disappears sooner than a DHCP lease would. **Routers**: paste the configuration command again on every router (the script version is now 3, so routers show "script outdated" until then).
- **Panel ports in `.env`**: `HTTP_PORT` and `HTTPS_PORT` (defaults 80 and 443) set the ports on the server in `docker-compose.yml`, so another service using 80 or 443 no longer forces editing the compose file, which `git pull` would overwrite. Existing installations are unaffected. An automatic Let's Encrypt certificate still needs 80 and 443 reachable from the internet.
- **Device vendor from the MAC address and your own device names** (suggested on the forum). The Devices and Wi-Fi tabs show the vendor under the name (also when a host name exists), taken from the public IEEE registry that your own server downloads (Settings → General, about 4 MB, refreshed every 30 days, button "Download now"; `OUI_DOWNLOAD=0` turns the automatic download off). Devices with a random, private MAC address (phones) are marked as such. Admins can give any device their own name with the ✎ button; the name is stored per MAC address and applies on all routers. The log analysis shows the name and vendor next to MAC addresses, and when the same device keeps dropping on authentication it adds a hint that it most likely has a wrong Wi-Fi password saved. No router script change, no need to paste the command again.

## [1.4.0] - 2026-11-11

### Added
- Documentation chapter [docs/NTFY.md](docs/NTFY.md) (Polish) about notifications through your own ntfy server: how it works, tested versions and minimum requirements (with a 10 % margin), installation, accounts with the least privileges, setting up the monitor and the phone (Android, iPhone), access from outside the home network and troubleshooting.
- **"Update in progress" instead of "offline" during a RouterOS update**: a new small router script `app-upgrade` (separate from `app-monitor`, runs every 5 s) reads the stored state of the RouterOS package update (`/system package update`, without checking for updates on the network) and sends it to the server only when it changes. A state showing download progress (`Downloaded 94% (…)`, `Downloading`, `Installing`) means the router is about to restart. For the next 15 minutes such a router that goes silent gets a blue **"update in progress"** status (with "last seen …") instead of the red offline one, and instead of the "no connection" alert you get one information notification ("RouterOS update: router is restarting, to version …"). When the router returns with a different RouterOS version you get one notification "RouterOS updated: version changed from A to B" (this also works without the script state, e.g. for a restart you did not announce, and for a downgrade); the channel in brackets, e.g. "(stable)", is not part of the version. If the router does not return within 15 minutes the usual "no connection" alert comes back, so a failed update is never hidden. Without the script state nothing changes: a normal outage is a normal alert. The log analysis describes `router rebooted … /upgrade` and a changed update channel in plain language. The latest state is written to the application log (`router update status: …`) and shown in "Report a problem". **Routers**: paste the configuration command again on every router (the script version is now 2, so routers show "script outdated" until then).
- **Notifications (ntfy and webhook)**, off by default (Settings → Notifications). The application server sends one message per event (at most 30 per hour) when a router sends no data for longer than a set time (and when it is back), when the internet is down on an edge router (and when it is back), when a backup fails or is too old, and, grouped at most every 10 minutes, when the auto-ban blocked addresses. ntfy messages use the JSON API (optional access token), webhooks get a JSON object with the event, title, message, router name and time. The text contains no IP addresses, tokens or passwords, but it does contain router names; a public ntfy.sh topic can be read by anyone who knows its name, so use a long topic or your own server. The webhook address and token are stored in the database and never shown again. A "Send a test notification" button uses the saved settings. Notifications work even when a router is down, because they are sent by the application server.
- **Application log in the "Report a problem" page**: the tail of the application log (warnings, errors including stack traces of server errors, and printed messages) is added to the report with tokens, IP and MAC addresses, e-mails and router, user and domain names removed automatically. The filter is best-effort, so the text can be reviewed and edited before copying. The log buffer lives in memory and is cleared on restart; access logs are not included.

### Changed
- **Router tokens are masked in the container log**: the access lines of the application (`POST /api/metrics?t=…`) now show `t=***` instead of the token, which lets anyone send data in the name of a router, so logs can be shared more safely. Log lines written before the update still contain tokens until the container is recreated (`docker compose up -d --force-recreate app` starts a fresh log).
- A clock correction by MikroTik Cloud (`cloud change time A => B`) of up to 15 minutes is now stored as information instead of critical: RouterOS marks it `critical`, but after a restart it is normal (the router starts with the last saved time), and critical entries cannot be muted and count as unread errors. A larger jump stays critical. Entries already stored are not changed.
- **Router status "no response" and faster offline detection**: a router that is late with a measurement by its usual interval + 1/5 of the interval + 1 s (5 s: 7 s, 10 s: 13 s, 60 s: 73 s) gets a yellow **"no response"** status; it becomes red **"offline"** after that time multiplied by a multiplier (default 1.5, from 1, set in Settings → General; 5 s: 10.5 s, 60 s: 109.5 s), instead of a fixed 180 s. The usual interval is measured from each router's latest measurements (until at least three are known the interval from Settings is used and the automatic offline threshold is at least 90 s), so it also stays correct when the script on a router was not pasted again after changing the interval. **Every router can have its own thresholds** in seconds (Settings → General, empty = automatic) with no upper limit, because routers can be strong or weak; the only lower bounds are "no response" not earlier than the measured interval + 1 s and "offline" not earlier than "no response" + 1 s (the table shows the value in effect). Very short thresholds can make the status flicker. The "no connection" notification keeps its own threshold.
- **Settings are split into tabs** like the router page: General (HTTPS, monitoring interval, router order), Security (whitelist, blacklist and auto-ban), Notifications and logs, Speed test and Backups. Links such as `/settings#backup` open the right tab, the last tab is remembered, and the result message of a save is shown above the tabs.
- The mute button (🔇) is no longer shown on login-failure entries and other entries that can never be muted.
- `README.pl.md` links the Polish changelog.

### Fixed
- The right part of the top menu (user, theme, language, log out) is aligned to the right again on wide screens and when the menu wraps; it was pushed to the left by a spacer element that shared a class name with the settings tabs. The mobile menu is unchanged.
- Notifications could arrive minutes late, because all background work shared one loop in which a heavy task (cleaning old data, WAN statistics, backups) delayed everything after it. **Background tasks are now independent**: each has its own schedule and never waits for the others or overlaps itself (log ingestion every 2 s, notifications every 15 s, speed test check, client statistics, cache refresh), and the heavy database tasks (WAN statistics, cleaning interface samples and logs, backup size limit) go one at a time through a separate queue so they cannot pile onto the database or hold up the light tasks. The database connection pool was enlarged (10 + 10) for this. Tasks that take longer than 10 s are written to the application log (`slow background task`, visible in "Report a problem").
- **Offline alerts no longer wait for a long warm-up after a restart**: for 5 minutes after the application started no router was judged offline, so an alert for a router switched off shortly after an update could come minutes late. Now only a router that has not reported since the start waits for a short warm-up (about two intervals); a router that has already sent a measurement is judged immediately. A failed send no longer suspends all notifications for 5 minutes: only that event is retried (after 15, 30, 60, 120 s) and the others go on. Every sent notification and every failed attempt is written to the application log, the ntfy timeout is 10 s, and "Report a problem" has a new Notifications section (state, rules, last check, errors, retries).

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
