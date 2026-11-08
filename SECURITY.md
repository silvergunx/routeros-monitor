# Security Policy

## Supported versions

Security fixes are released for the latest stable version (the newest release without a `-beta` suffix).
Please update before reporting a problem.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private reporting: open the repository's **Security** tab and choose **Report a vulnerability**.
Describe what you found, how to reproduce it and which version you tested. You will get an answer as soon as possible
and the fix will be released together with a note in [CHANGELOG.md](CHANGELOG.md).

## Hardening notes

See [docs/BEZPIECZENSTWO.md](docs/BEZPIECZENSTWO.md) (Polish). The main points:

- Secrets live only in `.env`, which is never committed. The application refuses to start with the example passwords.
- The router token in the configuration command works like a password; use HTTPS (Settings → HTTPS) or a VPN for routers that connect over the internet.
- Prefer exposing the panel only on the local network or through a VPN.
- Syslog (UDP 514) has no authentication; restrict the port in the server firewall to your routers.
- Backups in `./backups` contain the whole database (password hashes and router tokens). Do not share them.
