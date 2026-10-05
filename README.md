# Daricheh backend

REST API of the Daricheh Android app (client: `deviran01/super-app-android`). It serves the
catalog (every service, category and logo) and each store's update policy. Python 3.11,
FastAPI and uvicorn in Docker; the contract is
[CONFIG_SPEC.md](https://github.com/deviran01/super-app-android/blob/main/docs/CONFIG_SPEC.md).

| Endpoint | Returns |
|---|---|
| `GET /api/v1/config` | The catalog (`data/catalog.json`) plus `assetsBaseUrl`, the absolute base for its image paths. |
| `GET /api/v1/app/version` | The update policy for the caller's store: `minimumSupportedVersion` (hard update), `latestVersion` (soft update), `forceUpdate`, `updateUrl` (that store's page), messages, and `update` (`REQUIRED` / `OPTIONAL` / `NONE`) when `appVersion` is sent. |
| `GET /logos/…`, `GET /icons/…` | Images, cached for 7 days. |
| `GET /health` | Liveness for Docker. |

Both API endpoints take `platform=android`, `channel` (`bazaar` / `myket` / `direct`) and
`appVersion` (the app's versionCode), answer with an `ETag` and `Cache-Control: no-cache`, and
return `304` when `If-None-Match` still matches. The app sends nothing else — no user, session
or device data.

```text
app/main.py                 routes, ETag/304, image caching
app/content.py              loads data/ (reloaded when the files change), checks, QA scenarios
data/catalog.json           the catalog (12 categories, 29 services, compare groups)
data/release.json           update rules: defaults + per-store overrides and store links
public/logos/<id>.png       service logos (official app icons, 256 px); missing ones fall back to monograms
public/icons/categories/    duotone category glyphs, alpha only (tinted by the app)
public/lab/                 QA test pages (local only, with the lab scenario)
scenarios/*.json            QA overlays
schema/                     JSON Schemas of data/catalog.json and data/release.json
tests/                      API tests (pytest)
tools/                      catalog builder, asset fetcher
compose.yaml, Dockerfile    the service (production and local)
deploy/                     deploy.sh and the host nginx site
```

## Releases: soft and hard updates per store

Edit `data/release.json` and deploy. `default` applies to every build; a store under
`channels` overrides any field. Each store's `updateUrl` is its listing:

```json
{
  "default": { "minimumSupportedVersion": 1, "latestVersion": 1, "forceUpdate": false, "message": {…}, "optionalMessage": {…} },
  "channels": {
    "bazaar": { "updateUrl": "https://cafebazaar.ir/app/io.celin.super.app", "minimumSupportedVersion": 1, "latestVersion": 1 },
    "myket":  { "updateUrl": "https://myket.ir/app/io.celin.super.app", "minimumSupportedVersion": 1, "latestVersion": 1 }
  }
}
```

- Soft update: raise a store's `latestVersion` once that store has approved the release.
- Hard update: raise a store's `minimumSupportedVersion` — **only after the release is live
  in that store**, or its users are sent to a page without the update.
- The app checks this on every launch and every return to the foreground (a cheap `304`
  when nothing changed). Playbook:
  [RELEASING.md](https://github.com/deviran01/super-app-android/blob/main/docs/RELEASING.md).

## Run locally

The app's debug and QA builds call `http://127.0.0.1:8080/` (through `adb reverse`).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
SUPERAPP_SCENARIOS=lab SUPERAPP_DOCS=1 .venv/bin/uvicorn app.main:app --port 8080 --reload
adb reverse tcp:8080 tcp:8080          # let the device reach it
.venv/bin/pytest                       # tests
```

or with Docker: `SUPERAPP_PORT=8080 SUPERAPP_SCENARIOS=lab docker compose up --build`.
`SUPERAPP_DOCS=1` serves interactive API docs at `/docs` (off in production).

## QA scenarios

`SUPERAPP_SCENARIOS` takes a comma-separated list:

| Name | Effect |
|---|---|
| `lab` | Adds a "QA lab" category with local test pages (debug/QA builds only; release rejects `http:`). |
| `optional-update` | `latestVersion: 9999` in every store → update banner (soft). |
| `force-update` | `minimumSupportedVersion: 9999` in every store → blocking update screen (hard). |
| `bazaar-ahead` | Only Bazaar's `latestVersion` moves → Bazaar builds see the banner, Myket builds don't. |
| `maintenance` | Tapsi under maintenance. |
| `disabled` | Digikala disabled remotely. |
| `down` | Every API endpoint answers 503. |
| `invalid` | Truncated catalog JSON (the app must keep its cached copy). |

A scenario may merge-patch the catalog (`"features": {…}`), add entries (`appendCategories`,
`appendServices`), patch services by id (`patchServices`), merge-patch the release rules
(`"release": {…}`), replace the catalog body (`raw`) or force a status (`status`).

## Editing the catalog

`tools/build_sample_config.py` holds the catalog as readable tables and writes
`data/catalog.json` and `data/release.json`. Edit and re-run it, or edit the JSON directly.
Image paths are relative to the site root (`logos/snapp.png`). Validate:

```bash
pip install jsonschema   # once
python3 -c "import json,jsonschema; [jsonschema.validate(json.load(open(f'data/{n}.json')), json.load(open(f'schema/{n}.schema.json'))) for n in ('catalog','release')]"
```

The API refuses unusable files (it keeps serving the previous ones), and the app validates
every response again. The app repository keeps a snapshot of `data/catalog.json` as a test
fixture (`core/data/src/test/resources/config.json`); refresh it when the catalog's shape changes.

`tools/fetch_assets.py` (needs `pip install pillow resvg-py`) downloads each service's
official Android app icon from its Cafe Bazaar or Myket listing, falling back to the site's
own icon, and normalizes it to an opaque full-bleed square. Category glyphs are Solar Bold
Duotone icons rendered to alpha-only PNGs.

## Production: superapp.2z2.ir

Live at **https://superapp.2z2.ir/api/v1/config** and
**https://superapp.2z2.ir/api/v1/app/version**, on a shared Docker host, isolated from
everything else on it:

| Piece | Where | Notes |
|---|---|---|
| Container `superapp-api` | `/srv/superapp` (compose project `superapp`) | `python:3.11-slim`, uvicorn as an unprivileged user, loopback `127.0.0.1:8120` only, read-only root FS, all capabilities dropped, 192 MB / 0.5 CPU / 64 PID cap |
| Content | `/srv/superapp/data`, `/srv/superapp/public` | mounted read-only; replaced by `deploy.sh`, picked up without a restart |
| Host nginx site | `/etc/nginx/sites-available/superapp.2z2.ir.conf` | copy of `deploy/host-nginx/superapp.2z2.ir.conf`; GET/HEAD only |
| TLS | Let's Encrypt via webroot `/var/www/letsencrypt` | renews with the host's certbot timer; its own hook reloads nginx |
| CDN | ArvanCloud proxies the domain | Arvan terminates TLS for users and reaches the origin over HTTPS. It honors `Cache-Control`: API responses are never cached at the edge (`no-cache` + ETag → 304s), images are (7 days) |

### Deploy

```bash
echo 'DEPLOY_HOST=user@server' > deploy/.env   # once; git-ignored (this repository is public)
deploy/deploy.sh
```

It checks `data/` with the API's own rules, uploads the code, then images, then `data/` last
(a client never gets a catalog whose images aren't there yet), removes images no longer
used, rebuilds the image when the code changed (content-only deploys need no restart), and
waits until the container is healthy.

### One-time host setup (already done; for a rebuild)

1. `deploy/deploy.sh` (creates `/srv/superapp`, builds and starts the container).
2. Copy `deploy/host-nginx/superapp.2z2.ir.conf` to `/etc/nginx/sites-available/`, pointing
   `ssl_certificate*` at any existing (e.g. self-signed catch-all) certificate for now;
   symlink it into `sites-enabled`; `nginx -t && systemctl reload nginx`.
3. `certbot certonly --webroot -w /var/www/letsencrypt -d superapp.2z2.ir --deploy-hook "systemctl reload nginx"`,
   restore the Let's Encrypt paths in the site, `nginx -t && systemctl reload nginx`.

## Third-party assets

- `public/icons/categories/` are rendered from the **Solar** icon set by 480 Design,
  licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (attribution required).
- `public/logos/` are the services' own app icons; they are trademarks of their owners and
  are used to identify the services. Replace them with partner-approved logos for production
  agreements.
