# Daricheh backend

Backend of the Daricheh Android app (client: `deviran01/super-app-android`). It is one JSON
document — every service, category, logo and the update policy — served as a static file
today and by a REST backend later (same URL, same document; contract:
[CONFIG_SPEC.md](https://github.com/deviran01/super-app-android/blob/main/docs/CONFIG_SPEC.md)). This repository holds that document, its images, a tiny
standard-library dev server, the production deployment and the tools around them.

```text
public/                     exactly what a static host serves:
public/config.json          the config (12 categories, 29 services, compare groups, per-store versions)
public/logos/<id>.png       service logos (official app icons, 256 px); missing ones fall back to monograms
public/icons/categories/    duotone category glyphs, alpha only (tinted by the app)
public/lab/                 QA test pages (served with --scenario lab)
schema/config.schema.json   JSON Schema of the document
scenarios/*.json            QA overlays applied on top of the sample
server.py                   dev server (ETag/304 like a CDN, QA scenarios)
tools/                      catalog builder, asset fetcher, static exporter
deploy/                     production: compose file, container + host nginx configs, deploy.sh
dist/                       export_static.py output (git-ignored)
```

## Run locally

Python 3 only, no packages. Clone this repository next to the app's (`../super-app-backend`
from the app checkout); debug and QA builds of the app read `http://127.0.0.1:8080/config.json`.

```bash
python3 server.py                                   # :8080, sample config
python3 server.py --scenario lab                    # + "Daricheh Lab" test pages
python3 server.py --scenario force-update --scenario maintenance
adb reverse tcp:8080 tcp:8080                       # let the device reach it
```

## Scenarios

| Name | Effect |
|---|---|
| `lab` | Adds a "QA lab" category with local test pages (debug/QA builds only; release rejects `http:`). |
| `optional-update` | `latestVersion: 9999` in every store → update banner (soft). |
| `force-update` | `minimumSupportedVersion: 9999` in every store → blocking update screen (hard). |
| `bazaar-ahead` | Only the Bazaar rule moves to 9999 → Bazaar builds see the banner, Myket builds don't. |
| `maintenance` | Tapsi under maintenance. |
| `disabled` | Digikala disabled remotely. |
| `down` | Config endpoint answers 503. |
| `invalid` | Truncated JSON (the app must keep its cached config). |

A scenario file may merge-patch the document (`"app": {…}`), add entries
(`appendCategories`, `appendServices`), patch services by id (`patchServices`), replace the
body (`raw`) or force a status (`status`).

## Editing the catalog

`tools/build_sample_config.py` holds the catalog as readable tables and writes
`public/config.json`. Edit and re-run it, or edit the JSON directly. Image paths are relative
(`logos/snapp.png`), so the folder works at any URL. Validate:

```bash
pip install jsonschema   # once
python3 -c "import json,jsonschema; jsonschema.validate(json.load(open('public/config.json')), json.load(open('schema/config.schema.json')))"
```

The app's own validator is the source of truth. The app repository keeps a snapshot of this
document as a test fixture (`core/data/src/test/resources/config.json`) that must stay valid
with no warnings: copy `public/config.json` there when the document's shape changes.

`tools/fetch_assets.py` (needs `pip install pillow resvg-py`) downloads each service's
official Android app icon from its Cafe Bazaar or Myket listing (package names are listed in
the script), falling back to the site's own icon (web manifest, apple-touch-icon, icon links),
and normalizes it to an opaque full-bleed square. Category glyphs are Solar Bold Duotone
icons rendered to alpha-only PNGs. Sources unreachable from your network are skipped.

## Production: superapp.2z2.ir

Live at **https://superapp.2z2.ir/config.json** (release builds read it), on a shared Docker
host, isolated from everything else on it:

| Piece | Where | Notes |
|---|---|---|
| Container `superapp-config` | `/srv/superapp/compose.yaml` (project `superapp`) | unprivileged nginx, loopback `127.0.0.1:8120` only, read-only root FS, all capabilities dropped, 64 MB / 0.5 CPU / 64 PID cap |
| Content | `/srv/superapp/public/` | bind-mounted read-only; replaced by `deploy.sh` without a restart |
| Host nginx site | `/etc/nginx/sites-available/superapp.2z2.ir.conf` | copy of `deploy/host-nginx/superapp.2z2.ir.conf`; GET/HEAD only |
| TLS | Let's Encrypt via webroot `/var/www/letsencrypt` | renews with the host's certbot timer; its own hook reloads nginx |
| CDN | ArvanCloud proxies the domain | Arvan terminates TLS for users and reaches the origin over HTTPS. It honors the origin's `Cache-Control`: `config.json` is never cached at the edge (`no-cache` + ETag → 304s), images are (7 days) |

### Publish a change

Edit `public/config.json` (or `tools/build_sample_config.py` and re-run it), then:

```bash
echo 'DEPLOY_HOST=user@server' > deploy/.env   # once; git-ignored (this repository is public)
deploy/deploy.sh
```

It exports and checks the folder, uploads images first and `config.json` last (a client
never sees a document whose images aren't there yet), removes images no longer referenced,
and makes sure the container is up and healthy. Users get the change on their next launch.
For version rules (soft/hard updates per store) follow [RELEASING.md](https://github.com/deviran01/super-app-android/blob/main/docs/RELEASING.md).

### One-time host setup (already done; for a rebuild)

1. `deploy.sh` (creates `/srv/superapp` and starts the container).
2. Copy `deploy/host-nginx/superapp.2z2.ir.conf` to `/etc/nginx/sites-available/`, pointing
   `ssl_certificate*` at any existing (e.g. self-signed catch-all) certificate for now;
   symlink it into `sites-enabled`; `nginx -t && systemctl reload nginx`.
3. `certbot certonly --webroot -w /var/www/letsencrypt -d superapp.2z2.ir --deploy-hook "systemctl reload nginx"`,
   restore the Let's Encrypt paths in the site, `nginx -t && systemctl reload nginx`.

### Later: a REST backend

Run it as the `superapp` compose service on `127.0.0.1:8120` answering `GET /config.json`
with the same document; nothing else changes (host nginx, TLS, apps in the field). It may
use the `appVersion`, `channel` and `platform` query parameters to tailor the document.
Never require or log user identifiers — the app sends none.

### Any other static host

`python3 tools/export_static.py` builds the same folder for any HTTPS host: serve
`config.json` with an `ETag` and `Cache-Control: no-cache`, images with long caching, and
give a changed image a new file name.

## Third-party assets

- `public/icons/categories/` are rendered from the **Solar** icon set by 480 Design,
  licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (attribution required).
- `public/logos/` are the services' own app icons; they are trademarks of their owners and
  are used to identify the services. Replace them with partner-approved logos for production
  agreements.
