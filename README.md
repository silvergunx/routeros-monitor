# RouterOS Monitor

**English** · [Polski](README.pl.md)

A web panel for monitoring **MikroTik RouterOS 7** routers and a central source of an **IP whitelist and blacklist** that the routers
fetch on their own. Everything runs in Docker (`docker compose`); nothing but Docker has to be installed on the server.

The interface is available in Polish and English, works in light and dark mode and on phones.

**Contents:** [Features](#features) · [Requirements](#requirements) · [Installation](#installation) · [Updating](#updating) · [Configuration](#configuration-env) · [Backups](#backups) · [Troubleshooting](#troubleshooting) · [Languages](#languages) · [Documentation](#documentation) · [License](#license)

## Features

**Router monitoring**
- CPU, RAM, disk, temperature, uptime, RouterOS and firmware version, notice about an available update
- interfaces and traffic (including the WAN link), interface groups, history charts
- DHCP clients with device names and online state
- Wi-Fi clients (wifi-qcom / CAPsMAN and the older wireless package) with signal, SNR, speed and a connection quality rating
- VPN tunnels (WireGuard and others)

**Link quality**
- Netwatch probes: latency, jitter and packet loss to the gateway and, on the edge router, also DNS, HTTP and internet availability in %
- list of outages with their type (no internet / DNS not working / HTTP not working)
- a speed test run by the application server with a choice of engine and test server: **LibreSpeed** (open source, built into the image),
  **Speedtest by Ookla** (the same test as speedtest.net; available when you build the image yourself) and Cloudflare as a fallback;
  download, upload, ping and jitter; every night and on demand

**Logs**
- receiving router logs over syslog (UDP), colouring by severity, acknowledging, export with a date range
- translation of common RouterOS messages into plain language and an analysis tab with advice

**Whitelist and blacklist**
- IP addresses, networks and domains stored in the application; routers fetch the lists with scripts into `/ip firewall address-list`
  (lists `whitelist` and `blacklist`), for all routers or for one
- blacklist (ban list): optional expiry for temporary bans, protection against banning yourself, the application server or a monitored router,
  and a ready-to-paste firewall drop rule (the application itself never changes the firewall)
- import and export, enabling/disabling entries; each module can be switched off in Settings

**Other**
- live Wi-Fi setup / analysis mode (readings every 2 s) for finding the best place for an access point
- users with roles (administrator / view only), change log
- automatic database backups with download and delete in the panel, and an optional size limit for the stored backups
- HTTPS in one click: enter a domain in Settings and a Let's Encrypt certificate is issued automatically (Caddy)

## Requirements

- a Linux server (tested on Ubuntu 26.04 LTS) with Docker and the Compose plugin
- MikroTik routers running **RouterOS 7** (tested on 7.24) that can reach the application server on the network
- server ports: TCP 80 and 443 (panel), UDP 514 (router logs)

## Installation

1. Install Docker:
   ```
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker $USER
   ```
   Log out and in again so the `docker` group takes effect.
2. Get the project:
   ```
   git clone https://github.com/silvergunx/routeros-monitor.git
   cd routeros-monitor
   ```
3. Prepare the configuration:
   ```
   cp .env.example .env
   openssl rand -hex 32
   nano .env
   ```
   Set your own `DB_PASSWORD` and `ADMIN_PASSWORD`, and paste the output of `openssl rand -hex 32` as `SECRET_KEY`.
   The application will not start with the example passwords.
4. Start it (pick one):
   ```
   docker compose pull && docker compose up -d      # ready-made image (fast)
   docker compose up -d --build                     # or build it from the source
   ```
5. Open `http://SERVER_ADDRESS/` and log in with the data from `.env`.
6. Add a router (**Routers → Add router**), copy the command from the router page and paste it into the RouterOS terminal.
   The first data appears after a few dozen seconds.
7. Optional HTTPS: **Settings → HTTPS**, enter a domain that points to the server (ports 80 and 443 must be reachable from the internet).

Router configuration details: [docs/ROUTERY.md](docs/ROUTERY.md) (Polish).

## Updating

Releases are listed on the [Releases page](https://github.com/silvergunx/routeros-monitor/releases) and in [CHANGELOG.md](CHANGELOG.md).
Take a database backup first, then update in the way you prefer:

```
cd routeros-monitor
touch backups/.now        # database backup before the update (the file appears in backups/ after a few seconds)
```

**Option A: ready-made image** (no building on the server)
```
docker compose pull
docker compose up -d
```

Option A only updates the **application image**. The files next to `docker-compose.yml` (`docker-compose.yml`, `backup.sh`, `Caddyfile`) are
not part of the image. When the release notes say that one of them changed, download it again (`develop` below is the beta branch; use `main` for `stable`):
```
cd routeros-monitor
curl -fsSL https://raw.githubusercontent.com/silvergunx/routeros-monitor/main/backup.sh -o backup.sh
curl -fsSL https://raw.githubusercontent.com/silvergunx/routeros-monitor/main/docker-compose.yml -o docker-compose.yml
docker compose up -d
```
(Keep your own `.env`; new variables have defaults.) With option B `git pull` refreshes these files for you.

**Option B: build from the source**
```
git pull
docker compose up -d --build
```

Then check the log: `docker compose logs app --tail 30`.

**Channels.** `stable` (default) is the tested release. For test versions set `APP_CHANNEL=beta` in `.env` (option A) or use
`git checkout develop` (option B). Test versions may contain bugs, so do not use them on a router you cannot reach.
To pin an exact version use `APP_CHANNEL=1.0.0`.

The database lives in the Docker volume `dbdata`, and `.env` and `backups/` are not part of the repository, so an update does not overwrite them.
The application adds new database columns on its own at startup.
**Do not use `docker compose down -v`**: the `-v` switch deletes the volume with the database.

If a change affects the scripts on the routers, the release notes will say that the configuration command has to be pasted again.

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `UPDATE_CHECK` | `1` | set to `0` to stop the panel from asking GitHub for new releases (see below) |
| `APP_CHANNEL` | `stable` | image channel: `stable`, `beta` or an exact version such as `1.0.0` |
| `DB_PASSWORD` | – | PostgreSQL password (applied only when the database is first created) |
| `ADMIN_USER` / `ADMIN_PASSWORD` | `admin` / – | the first administrator account |
| `SECRET_KEY` | – | session key, at least 16 characters (`openssl rand -hex 32`) |
| `RETENTION_DAYS` | `30` | how many days to keep measurements (CPU, RAM, link quality, ...) |
| `IFACE_RETENTION_DAYS` | `7` | how many days to keep per-interface traffic samples (the largest table); older samples are removed in the background |
| `SYSLOG_PORT` | `514` | UDP port on the server for router logs |
| `LOG_RETENTION_DAYS` | `14` | how many days to keep logs |
| `TZ` | `Europe/Warsaw` | time zone |
| `BACKUP_HOUR` / `BACKUP_KEEP_DAYS` | `3` / `14` | backup hour and how long backups are kept |
| `BACKUP_INCLUDE_METRICS` | `0` | `1` also puts the chart history (measurements) into the backups; by default they are small and hold logs, the change log, users, routers and IP lists, but no chart history |
| `SPEEDTEST_TIME` | `03:30:00` | time of the nightly speed test |
| `SPEEDTEST_STREAMS` | `6` | number of connections in the fallback Cloudflare test |

**Update notice.** The panel (administrators only) shows a badge when a newer release exists on GitHub. The server asks the public
GitHub API (`api.github.com`) at most every 6 hours, in the background, and sends nothing but its IP address and the application version
in the User-Agent. Test versions (`-beta`) also see test releases. Disable it with `UPDATE_CHECK=0`. The panel never updates itself.

Do not use the `$` character in values (Compose treats it as a variable).
The other settings (polling interval, speed test, whitelist, router order, HTTPS) are in the panel under **Settings**.

## Backups

The `backup` container makes a backup every day at `BACKUP_HOUR` into the `./backups` directory. On-demand backups, download and
delete are in **Settings → Database backups**.

By default the backups contain everything except the chart history (per-interface traffic, CPU/RAM measurements and client counts): logs, the change log,
users, routers, settings and IP lists are included. After a restore the charts start empty. Set `BACKUP_INCLUDE_METRICS=1` to include the history
(the backups are then much larger).

Restoring (overwrites the current data):
```
docker compose stop app
docker compose exec -T db pg_restore -U monitor -d monitor --clean --if-exists < backups/FILE_NAME.dump
docker compose start app
```
Moving to a new server: install the application, copy your `.env` and the backup file, start it and run the restore.

## Troubleshooting

Database size: `docker compose exec db psql -U monitor -d monitor -c "SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 8;"`.
The per-interface table is usually the largest; lower `IFACE_RETENTION_DAYS` to shrink it. Removing old rows frees space for new ones but does not shrink the files
on disk; to give the space back run (it locks the table for a moment and needs free space for a copy) `docker compose exec db psql -U monitor -d monitor -c "VACUUM FULL iface_metrics;"`.

```
docker compose ps
docker compose logs -f app caddy
docker compose exec app speedtest --version
```

## Architecture

| Service | Image | Role |
|---|---|---|
| `app` | Python 3.12, FastAPI | panel, API for routers, syslog receiver, speed tests |
| `db` | PostgreSQL 16 | data |
| `backup` | PostgreSQL 16 | `pg_dump` backups |
| `caddy` | Caddy 2 | reverse proxy and HTTPS certificates |

The routers send data to the application themselves (`/tool fetch`), so the application needs no login or password for the routers.

Security: [SECURITY.md](SECURITY.md) and [docs/BEZPIECZENSTWO.md](docs/BEZPIECZENSTWO.md) (Polish).

## Languages

The interface is available in Polish and English (PL / EN switcher in the menu and on the login screen; the choice is remembered in a cookie).
More languages are added with a single JSON file and no code changes: [docs/TRANSLATING.md](docs/TRANSLATING.md).

## Documentation

| Document | What is in it |
|---|---|
| [Releases](https://github.com/silvergunx/routeros-monitor/releases) and [CHANGELOG.md](CHANGELOG.md) | what changed in each version, and what has to be done on the routers or the server after an update |
| [docs/ROUTERY.md](docs/ROUTERY.md) (Polish) | what the configuration command installs on a router, firewall rules for the whitelist and the blacklist, routers outside the local network |
| [docs/BEZPIECZENSTWO.md](docs/BEZPIECZENSTWO.md) (Polish) and [SECURITY.md](SECURITY.md) | hardening notes and how to report a vulnerability |
| [docs/TRANSLATING.md](docs/TRANSLATING.md) | how to add a language |
| [CONTRIBUTING.md](CONTRIBUTING.md) | branches (`main` stable, `develop` beta), tests, how to release |
| [THIRD_PARTY.md](THIRD_PARTY.md) | licences of bundled components (LibreSpeed CLI) and of the optional Ookla program |

Questions and bug reports: [GitHub Issues](https://github.com/silvergunx/routeros-monitor/issues).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

Project code: [MIT](LICENSE).

The image bundles **LibreSpeed CLI** (LGPL-3.0, unmodified) for the speed test; see [THIRD_PARTY.md](THIRD_PARTY.md) for the licences of bundled components.
It runs without sharing results, so nothing but the test traffic goes to the public LibreSpeed servers.

When you build the image yourself (`docker compose up -d --build`), **Ookla's Speedtest CLI** is also downloaded. It is not part of this repository
and has its own licence (personal, non-commercial use); the application runs it accepting Ookla's licence and privacy policy.
The ready-made images do **not** include it (Settings then shows how to build with it). You can always choose the LibreSpeed or Cloudflare engine instead.

This project is not affiliated with MikroTik, Ookla or Cloudflare. The names belong to their owners.
