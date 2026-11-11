# Third-party components

RouterOS Monitor itself is released under the [MIT](LICENSE) licence. The Docker image contains or downloads the following
third-party software, which keeps its own licence.

## LibreSpeed CLI (bundled in the image)

- Program: `librespeed-cli` 1.0.14, a command-line client for [LibreSpeed](https://librespeed.org) speed tests.
- Licence: **GNU Lesser General Public License v3.0** (LGPL-3.0). The licence text is shipped in the image at
  `/usr/share/doc/librespeed-cli/LICENSE`.
- Source code: <https://github.com/librespeed/speedtest-cli> (release `v1.0.14`).
- The binary is downloaded unmodified from the project's official GitHub release while the image is built and verified against a pinned
  SHA-256 checksum (see `app/Dockerfile`). RouterOS Monitor only runs it as a separate program and does not link against it.
- It is run without `--share`, so no results are uploaded to LibreSpeed. It contacts `librespeed.org` to fetch the server list and
  then the chosen public test server.

## Speedtest CLI by Ookla (not bundled)

Not part of this repository and **not included in the ready-made images**. When you build the image yourself
(`docker compose up -d --build`), it is downloaded from Ookla and is subject to Ookla's licence and privacy policy
(personal, non-commercial use). You can use the LibreSpeed or Cloudflare engine instead.

## IEEE OUI registry (not bundled)

Device vendors are shown based on the public IEEE MA-L registry (`https://standards-oui.ieee.org/oui/oui.csv`). It is **not part of this
repository or the images**: your own server downloads it (about 4 MB, at most once every 30 days, or with the button in Settings) and
keeps it in its database. MAC addresses are looked up locally and never sent anywhere. Set `OUI_DOWNLOAD=0` to turn the automatic
download off. The registry data belongs to the IEEE.

## Python and other packages

The packages listed in `app/requirements.txt` are installed from PyPI under their own licences. The charts use
[Chart.js](https://www.chartjs.org/) (MIT), loaded from the jsDelivr CDN in the browser. The database, Caddy and the base images
come from their official Docker images.
