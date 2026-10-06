# Anar backend

REST API of the Anar Android app (client: `deviran01/super-app-android`) and the admin
dashboard that manages it. It serves the catalog (every service, category and logo) and each
store's update policy. Python 3.11, FastAPI and uvicorn in Docker; the contract is
[CONFIG_SPEC.md](https://github.com/deviran01/super-app-android/blob/main/docs/CONFIG_SPEC.md).

| Endpoint | Returns |
|---|---|
| `GET /api/v1/config` | The catalog (`data/catalog.json`) plus `assetsBaseUrl`, the absolute base for its image paths. |
| `GET /api/v1/app/version` | The update policy for the caller's store: `minimumSupportedVersion` (hard update), `latestVersion` (soft update), `forceUpdate`, `updateUrl` (that store's page), messages, and `update` (`REQUIRED` / `OPTIONAL` / `NONE`) when `appVersion` is sent. |
| `POST /api/v1/events` | Anonymous daily usage totals from the app ([statistics](#usage-statistics)); `204`. |
| `GET /api/v1/feedback/challenge`, `POST /api/v1/feedback` | A one-time proof-of-work challenge, then a user's anonymous [feedback](#feedback) message; `202`. |
| `GET /logos/…`, `GET /icons/…` | Images, cached for 7 days. |
| `GET /health` | Liveness for Docker. |
| `/admin/` | The [admin dashboard](#admin-dashboard) (sign-in required). |

The config and version endpoints take `platform=android`, `channel` (`bazaar` / `myket` / `direct`) and
`appVersion` (the app's versionCode), answer with an `ETag` and `Cache-Control: no-cache`, and
return `304` when `If-None-Match` still matches. The app sends nothing else — no user, session
or device data.

```text
app/main.py                 routes, ETag/304, image caching, security headers
app/content.py              loads data/ (reloaded when the files change), checks, QA scenarios
app/stats.py                usage statistics: API-call counts and app reports (SQLite, data/stats/)
app/feedback.py             feedback messages, their spam and abuse checks (SQLite, data/feedback/)
app/admin/                  dashboard: API (routes.py), validation (schema.py), draft/publish/
                            history (store.py), accounts and sessions (auth.py), images, UI (static/)
app/cli.py                  admin accounts from the command line
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

## Admin dashboard

**https://superapp.2z2.ir/admin/** — everything the app shows, without editing JSON:

- **Services**: add, edit, remove, switch on/off, drag to reorder within a category; logo by
  upload (resized to the app's 256 px square) or straight from the service's Cafe Bazaar
  listing; names and descriptions in Persian and English; maintenance message; every web
  behavior the app supports (domains, permissions, popups, cache, keep-alive, user agent…).
- **Categories**: order, title, color, icon (any glyph image, converted to a tintable icon).
- **Compare groups**, **Settings** (feature flags, payment domains, links) and **Releases**
  (soft/hard update versions and the store page, per store).
- **Draft → Publish**: edits collect in a draft; *Publish* validates it with the app's own
  rules and makes it live (users get it on their next launch). *Discard* drops the draft.
- **History**: every published version, who published it and why; any one can be restored
  into the draft. **Admins**: add or remove accounts, change your password.
- **Statistics**: daily active users, installs, API calls, app and service opens, how
  services are opened (home, search, favorites…), categories, searches with no results,
  update prompts and clicks, page-load errors per service, stores and app versions — for 7,
  30 or 90 days, per store.
- **Feedback**: messages users send from the app, newest first, in Inbox, Archived and Spam;
  mark read, archive, move to spam or back, delete. The sidebar shows the unread count.

Security: scrypt-hashed passwords; signed, `HttpOnly`, `Secure`, `SameSite=Strict` session
cookies (12 h) that sign-out and password changes revoke; a required request header against
cross-site requests; 15-minute lockout after 5 wrong passwords; a strict Content Security
Policy; nothing cached (`no-store`) or indexed. Two admins editing at once can't overwrite
each other: a save based on an older draft is refused.

**The server owns `data/` now.** The first deploy seeds it from this repository; after that,
changes are made and published in the dashboard, and `deploy/deploy.sh` never overwrites
them. `deploy/pull.sh` copies the live catalog, release rules and uploaded images back here
so git keeps a history.

First admin (or a forgotten password), on the server:

```bash
cd /srv/superapp
sudo docker compose exec api python -m app.cli create-admin <username> --generate   # prints a password
sudo docker compose exec api python -m app.cli set-password <username> --generate
```

## Usage statistics

Two sources, one table of daily counters (`data/stats/stats.db`, SQLite, kept 400 days):

- **API calls**, counted by the server for `config`, `version`, `events` and `feedback`: day (Iran time),
  endpoint, result (`2xx` / `304` / `4xx` / `5xx`), channel and app version. No IP address
  or other request data is stored.
- **App reports** (`POST /api/v1/events`): the app counts events on the device and sends
  daily totals at launch and when it goes to the background (at most every 15 minutes).
  There is no user or device identifier: daily active users and installs are counters each
  install sends at most once a day / once ever. Users can turn reports off in the app
  (Settings → Privacy). Format and event list: the app's
  [CONFIG_SPEC.md](https://github.com/deviran01/super-app-android/blob/main/docs/CONFIG_SPEC.md#post-apiv1events--usage-totals).

Reports can't be authenticated (the app has no identity), so treat the numbers as
estimates. The server keeps only known events, catalog ids and channels, merges each report
per day and counter before capping it (one install adds at most one active day), accepts days
from the last week, stores the app version only for users and installs, and buckets unknown
versions as "other". Forged reports can nudge numbers, but can't add text, and the rows they
can create are bounded (catalog ids × fixed values × 4 channels per day). Counts are buffered
in memory and written by a background thread every 10 seconds, and before every dashboard
read.

## Feedback

Users send short messages from the app (Settings → Send feedback): a kind (problem, idea,
other) and 10–1000 characters of text. Like everything else the app sends, it's anonymous:
stored with the store channel, versionCode and Android API level only — no account, device,
address or contact (`data/feedback/feedback.db`, SQLite, kept a year). The app tells users not
to write passwords or personal details. Turn it off with the `feedback` feature flag
(dashboard → Settings): the app hides it and the API refuses it.

Abuse and spam, without identifying anyone (`app/feedback.py`):

- **Proof of work.** `GET /api/v1/feedback/challenge` returns a challenge signed by the server
  (valid 10 minutes, usable once) and a difficulty; the app finds a nonce for which
  SHA-256(`<challenge>:<nonce>`) starts with that many zero bits (18 by default, about a
  second on a phone; up to 21 when many messages arrive) and posts it with the message. A
  script pays that for every message.
- **Limits.** Per address, in memory only: 6 messages in 10 minutes, 20 an hour (behind the
  CDN the address is the CDN edge's, which many users share). Overall: 200 an hour, 1000 a
  day. Past them: `429` with `Retry-After`.
- **Content.** Control and bidi-override characters are removed and whitespace tidied before
  the length check. Messages with many links or handles, a character repeated 20 times, or
  hardly any letters go to Spam instead of the inbox; the same text again (ignoring case,
  punctuation, digits and Arabic/Persian letter forms) within a week only counts as a repeat
  of the first copy. The sender gets `202` either way.
- **Storage.** At most 20,000 messages: the oldest spam, archived and read ones make room;
  new ones are refused (`429`) only when everything left is unread.

Answers: `202` taken; `400` invalid (length, kind, fields); `403` turned off; `409` the
challenge is wrong, expired or used (get a new one); `413` over 8 KB; `429` rate-limited.
The challenge key comes from `SUPERAPP_FEEDBACK_SECRET`, or is generated once into
`data/feedback/secret`.

## Releases: soft and hard updates per store

Use the dashboard's **Releases** page (it edits `data/release.json`). `default` applies to every build; a store under
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
.venv/bin/python -m app.cli create-admin you                    # once, for the dashboard
SUPERAPP_DEV=1 SUPERAPP_SCENARIOS=lab SUPERAPP_DOCS=1 .venv/bin/uvicorn app.main:app --port 8080 --reload
adb reverse tcp:8080 tcp:8080          # let the device reach it
.venv/bin/pytest                       # tests
```

or with Docker: `SUPERAPP_PORT=8080 SUPERAPP_DEV=1 SUPERAPP_SCENARIOS=lab docker compose up --build`.
`SUPERAPP_DEV=1` allows the dashboard's session cookie over plain `http://` (local only);
`SUPERAPP_DOCS=1` serves interactive API docs at `/docs` (off in production). Running locally
edits this checkout's `data/` like production edits the server's.

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
| Content | `/srv/superapp/data`, `/srv/superapp/public` | written by the dashboard (owned by uid 10001); `data/admin/` holds accounts, the draft and history; `data/stats/` the usage statistics, `data/feedback/` feedback messages |
| Host nginx site | `/etc/nginx/sites-available/superapp.2z2.ir.conf` | copy of `deploy/host-nginx/superapp.2z2.ir.conf`; the API is GET/HEAD only except `POST /api/v1/events` (64 KB) and `POST /api/v1/feedback` (8 KB); `/admin` takes edits (256 KB) and image uploads (6 MB); `X-Forwarded-For` is set by nginx, never passed through |
| TLS | Let's Encrypt via webroot `/var/www/letsencrypt` | renews with the host's certbot timer; its own hook reloads nginx |
| CDN | ArvanCloud proxies the domain | Arvan terminates TLS for users and reaches the origin over HTTPS. It honors `Cache-Control`: API responses are never cached at the edge (`no-cache` + ETag → 304s), images are (7 days) |

### Deploy

```bash
echo 'DEPLOY_HOST=user@server' > deploy/.env   # once; git-ignored (this repository is public)
deploy/deploy.sh
```

It uploads the code and the repository's images (never deleting uploaded ones), seeds `data/`
on the first deploy only, builds the image on your machine (`linux/amd64`; Docker needed —
PyPI is slow or blocked from the server) and loads it there, then waits until the container
is healthy. `DEPLOY_BUILD=server deploy/deploy.sh` builds on the server instead. Content changes go through the dashboard, not deploys.

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
