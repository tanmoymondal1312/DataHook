# DataHook — Agent Context

Single-file context for an AI agent working on **either side** of DataHook
(the Django REST backend, or the Android/Jetpack-Compose frontend that consumes
it). It is the source of truth for the API contract, auth, push, and gotchas.

---

## 1. What DataHook is

A no-code **API / form-endpoint builder**. A logged-in developer creates an
"endpoint", defines typed **attributes** (fields), and gets a public **ingest
URL + secret API key**. Any website/app `POST`s JSON (or an HTML form) to that
URL; the submission is validated against the schema, stored, and the endpoint
owner receives a **Firebase (FCM) push notification**. Owners browse, search,
export, and get per-endpoint stats.

Two audiences of the API:
- **Owner/admin API** (`/api/…`) — JWT-authenticated; used by the Android app.
- **Public ingest** (`/ingest/{slug}/`) — API-key-authenticated; used by the
  developer's external sites/apps.

---

## 2. Environments

| | Base URL |
|---|---|
| **Production** (live) | `https://datahook.mediaghor.com` |
| Local dev | `http://localhost:8000` |

- Prod is behind **Cloudflare** (TLS at the edge + nginx Cloudflare-origin cert)
  → nginx → gunicorn `127.0.0.1:9100`. Server path `/home/tanmoy/apps/datahook`.
- **Test account:** `demo@datahook.dev` / `demo12345` (owns endpoint `id=1`,
  "Contact Form"). ⚠️ These are public/demo creds — fine for testing, not for
  real data.

---

## 3. Auth (JWT — simplejwt)

- Header on every `/api/` call: `Authorization: Bearer <access>`
- Access token lifetime **60 min**; refresh **14 days**.
- Login field is **email** (no username). User object: `{id, email, name, date_joined}`.

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/auth/register/` | `{email, name, password}` | `201 {user, access, refresh}` |
| POST | `/api/auth/login/` | `{email, password}` | `200 {user, access, refresh}` |
| POST | `/api/auth/google/` | `{id_token}` | `200`/`201 {user, created, access, refresh}` |
| POST | `/api/auth/refresh/` | `{refresh}` | `200 {access}` |
| GET | `/api/auth/me/` | — | `200 {id, email, name, date_joined}` |
| DELETE | `/api/auth/me/` | — | `204` — **permanently deletes the account** |

`password` min length 8. Duplicate email → `400`. Bad credentials → `400`.

**Google sign-in** (`/api/auth/google/`): the Android app obtains a Google ID
token via Credential Manager using the project's **Web** client ID, and the
server verifies it against `GOOGLE_WEB_CLIENT_ID` (google-auth). Accounts are
matched on the *verified* email, so Google and password login share **one**
account — an existing password user signing in with Google keeps their password.
New accounts are created with an unusable password (`201`, `created: true`);
existing ones return `200`, `created: false`. A blank `name` is backfilled from
Google, but a name the user already set is never overwritten. Rejected with
`400`: bad/expired token, untrusted issuer, unverified email, disabled account,
or `GOOGLE_WEB_CLIENT_ID` unset (feature off — password login unaffected).

---

## 4. Data model & field types

- **Endpoint**: `name`, auto `slug` (`name`+random), secret `api_key` (40 chars),
  `description`, `notify_on_submit` (bool, default true), `notify_title`
  (custom push title, max 100 chars, blank = default), `ingest_url`.
- **Attribute** (per endpoint): `label`, `key`, `type`, `required`, `order`,
  `show_in_notification` (bool, default false — drives the push body).
  - `key` = strict slug: `^[a-z_][a-z0-9_]*$` (lowercase/digits/underscore, no
    spaces), **unique per endpoint**. This is the JSON key developers POST.
  - `type` ∈ `text | email | number | phone | date | boolean | image`.
  - `image` holds a **URL** (not a file); it can drive the notification
    picture and the app-wide data-header image.
  - Display flags: `show_in_notification`, `show_as_subtitle`,
    `show_as_data_header`. The last two are **exclusive per endpoint** —
    setting one clears it on the endpoint's other attributes (enforced in
    `Attribute.save()`).
- **Submission**: `data` (JSON object of key→value), `source_ip`, `created_at`.
  Serialized with `header_image` — the resolved URL of the endpoint's
  `show_as_data_header` image attribute for that payload, or `""`.
- **Device**: `fcm_token` (unique), `platform` (default `android`) — per user.

**Type validation rules (ingest):** `email` valid email · `phone` digits/`+`/`-`/
space · `number` int/float · `date` ISO `YYYY-MM-DD` · `boolean`
`true/false/1/0` · `text` any string · `image` must match
`^https?://\S+$` (http/https only — FCM and Coil will not fetch `data:`).

---

## 5. Admin API reference (JWT)

Users only ever see/modify **their own** resources (`404` otherwise).

### Devices (FCM registration)
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/devices/` | `{fcm_token, platform?}` | `200 {id, fcm_token, platform}` (upsert) |
| DELETE | `/api/devices/` | `{fcm_token}` | `204` |

### Endpoints
| Method | Path | Body / Notes |
|---|---|---|
| GET | `/api/endpoints/` | plain array; items include `submission_count`, `attribute_count`, `ingest_url` |
| POST | `/api/endpoints/` | `{name, description?}` → `201` full detail |
| GET | `/api/endpoints/{id}/` | detail: `{…, api_key, ingest_url, attributes[], snippets{}, submission_count, attribute_count}` |
| PATCH | `/api/endpoints/{id}/` | `{name?, description?, notify_on_submit?, notify_title?}` |
| DELETE | `/api/endpoints/{id}/` | `204` |
| POST | `/api/endpoints/{id}/rotate-key/` | `200 {api_key}` (regenerates) |
| POST | `/api/endpoints/{id}/logo/` | **multipart**, field `logo` → `200` full detail |
| DELETE | `/api/endpoints/{id}/logo/` | `200` full detail (logo cleared) |

**Endpoint list item shape:** `{id, name, slug, description, notify_on_submit,
notify_title, ingest_url, submission_count, attribute_count, created_at}`.

### Attributes (nested)
| Method | Path | Body |
|---|---|---|
| GET | `/api/endpoints/{id}/attributes/` | plain array |
| POST | `/api/endpoints/{id}/attributes/` | `{label, key, type, required, order?, show_in_notification?}` → `201`; invalid/dup key → `400` |
| PATCH | `/api/endpoints/{id}/attributes/{aid}/` | partial |
| DELETE | `/api/endpoints/{id}/attributes/{aid}/` | `204` |

**Attribute shape:** `{id, label, key, type, required, order,
show_in_notification, show_as_subtitle, show_as_data_header}`.

### Submissions (nested)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/endpoints/{id}/submissions/?search=&page=` | paginated, page size 20. `search` = case-insensitive contains across the JSON payload. Item: `{id, data, source_ip, created_at}` |
| DELETE | `/api/endpoints/{id}/submissions/{sid}/` | `204` |
| GET | `/api/endpoints/{id}/export/?format=csv\|json` | file download; columns = attribute keys + `created_at` |

### Aggregate feed & stats
| Method | Path | Notes |
|---|---|---|
| GET | `/api/submissions/?search=&page=` | **all** submissions across the user's endpoints, newest first, paginated (20/page). Item: `{id, endpoint_id, endpoint_name, data, created_at}` |
| GET | `/api/endpoints/{id}/stats/` | owner-only. `{total, today, last_7_days, daily:[{date:"YYYY-MM-DD", count:int}, …30 days]}`. `daily` is zero-filled (no gaps), oldest→newest, last entry = today. |

**Pagination shape** (submissions + aggregate only): `{count, next, previous, results:[…]}`.
Endpoints and attributes are **not** paginated (plain arrays).

---

## 6. Public ingest (the shared API)

```
POST /ingest/{slug}/
Header:  X-API-Key: <endpoint.api_key>
Content-Type: application/json | application/x-www-form-urlencoded | multipart/form-data
Body: { "<attr_key>": <value>, ... }
```

Rules (strict):
- Missing/wrong `X-API-Key` → **401** `{detail}`.
- Unknown slug → **404** `{detail}`.
- Every `required` attribute must be present & non-empty; every provided key
  must be a defined attribute; each value must pass its type check.
- On any validation failure → **400** `{"errors": {key: message}}`.
- On success → **201** `{"success": true, "id": <submission_id>}`, stores the
  submission (with source IP) and fires FCM if `notify_on_submit`.

Ingest allows **all origins** (CORS) so plain HTML forms and any app can post.

---

## 7. FCM push (Firebase project `webhook-001`)

On a new submission to an endpoint with `notify_on_submit=true`, the backend
sends (via `messaging.send()`, FCM HTTP v1) to **every device token** of the
endpoint owner. Messages are **data-only** (no `notification` block): with one,
the system builds the tray notification itself whenever the app is backgrounded
and silently drops the subtitle and large icon. Data-only means the app's
handler always runs, so the notification looks identical foreground or
background; `priority=high` keeps delivery prompt.

`fcm.build_notification(endpoint, submission)` returns
`{title, body, subtitle, image_url, logo_url}`:

- **title** — `endpoint.notify_title` when set, else `New submission · {name}`.
- **body** — the **values** of the attributes flagged `show_in_notification`,
  in attribute order, joined by ` · `. **Labels are not shown** — they are the
  owner's internal field names and only crowd the notification. Keys the caller
  omitted or sent empty are skipped; booleans render as `Yes`/`No`; truncated
  to 240 chars with an ellipsis. When no attribute is selected (or nothing
  usable was submitted) the body falls back to `New submission received` — which
  is exactly the pre-feature behaviour, so existing endpoints are unaffected.
  **Image attributes never appear in the body** — a raw URL reads as noise.
- **subtitle** — the bare value (no `Label:` prefix) of the `show_as_subtitle`
  attribute, truncated to 40 chars. `""` when unset.
- **image_url** — the URL from an `image` attribute flagged
  `show_in_notification`; the client renders it as the big picture.
- **logo_url** — the endpoint's uploaded logo (absolute URL); the client renders
  it as the notification's **large icon**.

> ⚠️ The **small status-bar icon cannot come from the server** — Android
> requires a local drawable and renders it as a flat silhouette. An uploaded
> logo can therefore only ever be the large icon.
- **data** (all values are strings):
  ```json
  {
    "type": "submission",
    "endpoint_id": "<id>",
    "endpoint_name": "<name>",
    "submission_id": "<id>",
    "submission_json": "{\"id\":.., \"data\":{...}, \"created_at\":\"..\"}",
    "title": "…", "body": "…", "subtitle": "…",
    "image_url": "…", "logo_url": "…"
  }
  ```

`submission_json` embeds the whole record, so **tapping the notification opens
that exact submission with no extra API call** — parse `data.submission_json`
into `{id, data, created_at}`.

Invalid/`UNREGISTERED` tokens are auto-pruned from the DB. If the payload ever
exceeds FCM's ~4 KB limit, that send is logged as a failure (the token is **not**
pruned).

**Android app responsibilities:**
1. Get the FCM registration token (`FirebaseMessaging.getInstance().token`) and
   `POST /api/devices/ {fcm_token}` after login / on token refresh.
2. On logout or token invalidation, `DELETE /api/devices/ {fcm_token}`.
3. Handle taps: read `data.submission_json` → navigate to that submission.
   (A `notification` block is included, so backgrounded apps get a tray
   notification automatically; data arrives in the launch intent extras on tap.)

---

## 8. Error envelope

All error responses share a consistent shape:
```json
{ "detail": "human message", "errors": { "field": ["msg"] } }
```
`errors` is present for field/validation errors (and ingest uses `{"errors": {...}}`).
Status codes: `400` validation · `401` unauthenticated/bad key · `403` forbidden
· `404` not found/not owned · `429` throttled.

---

## 9. Auto-generated snippets

`GET /api/endpoints/{id}/` returns `snippets: {js_fetch, curl, html_form}` —
ready-to-copy integration code built from the endpoint's ingest URL, API key and
attribute keys. Good for a "How to integrate" screen in the app.

---

## 10. Gotchas (read before debugging)

- **Cloudflare bot filter:** requests with a bare/bot `User-Agent` (e.g. Python's
  default `Python-urllib/3.x`) get **`403` Cloudflare error 1010** and never
  reach the app. Browsers, Android OkHttp, and `curl` pass fine. Server-to-server
  callers must send a normal `User-Agent` header.
- **Pagination scope:** only `/submissions/` (nested + aggregate) are paginated.
  Endpoints/attributes are plain JSON arrays.
- **Times are UTC** (`TIME_ZONE=UTC` on the server) — `today`/`daily` in stats
  are UTC days.
- **CORS:** `/api/` is restricted to configured origins; `/ingest/` is open to all.
- **Ingest ≠ admin:** `/ingest/` uses `X-API-Key` (no JWT); `/api/` uses JWT (no key).

---

## 11. Quick start (verified live)

```bash
BASE=https://datahook.mediaghor.com

# 1) login
ACCESS=$(curl -s -X POST $BASE/api/auth/login/ -H "Content-Type: application/json" \
  -d '{"email":"demo@datahook.dev","password":"demo12345"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access'])")

# 2) read endpoint detail (slug + api_key + snippets)
curl -s $BASE/api/endpoints/1/ -H "Authorization: Bearer $ACCESS"

# 3) public ingest (substitute slug + key from step 2)
curl -X POST "$BASE/ingest/<slug>/" \
  -H "Content-Type: application/json" -H "X-API-Key: <api_key>" \
  -d '{"name":"Ada","email":"ada@example.com"}'      # -> {"success":true,"id":..}

# 4) aggregate feed + stats
curl -s "$BASE/api/submissions/?page=1" -H "Authorization: Bearer $ACCESS"
curl -s "$BASE/api/endpoints/1/stats/"  -H "Authorization: Bearer $ACCESS"
```

---

## 12. Backend layout & ops (for a backend agent)

```
config/      settings (.env-driven), urls, exceptions (error envelope),
             middleware (ingest CORS), legal.py (public /privacy/ page)
accounts/    custom email User + manager, Device, auth/device API
endpoints/   Endpoint/Attribute/Submission models, admin API, public ingest,
             validators, snippets, fcm.py, seed_demo command, tests.py (22 tests)
accounts/    …also GoogleAuthSerializer/View (Google ID-token sign-in), tests.py (11 tests)
deploy/      systemd unit + nginx server block
```

- Stack: Python 3.12, Django 5.1, DRF, simplejwt, firebase-admin, django-cors-headers.
- Config via `.env` (see `.env.example`): `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`,
  `BASE_URL`, `FIREBASE_CREDENTIALS` (path to service-account JSON, kept out of git),
  `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, throttle rates,
  `GOOGLE_WEB_CLIENT_ID` (OAuth **Web** client ID, `client_type: 3` in the
  Android app's `google-services.json`), `MEDIA_ROOT`, `LOGO_MAX_BYTES`.
- **Media:** logos live under `MEDIA_ROOT/endpoint-logos/` and are served by
  nginx at `/media/` (see `deploy/nginx-datahook.conf`). Needs Pillow.
  Back this directory up alongside the database.
  `/media/` sends **`Cache-Control: no-store`** deliberately: Cloudflare
  overrides an origin `max-age` with its own Browser Cache TTL (4h), which left
  a *deleted* logo fetchable from the edge long after it was gone from disk.
  `no-store` is honoured (`cf-cache-status: BYPASS`), so deletion is immediate
  everywhere. Don't "optimise" this back to `expires`.
- Run tests: `./venv/bin/python manage.py test` (84 tests).
- **Public legal page:** `GET /privacy/` (no auth) renders
  `templates/legal/privacy.html`. This exact URL is registered in the Play
  Console, so it must never require auth or 404. Contact address and date come
  from `PRIVACY_CONTACT_EMAIL` / `PRIVACY_POLICY_UPDATED`.
  Every `mailto:` on it is wrapped in `<!--email_off-->` — Cloudflare's email
  obfuscation otherwise rewrites the address into a JS-only placeholder that
  reads "[email protected]" to a reviewer. A test enforces this.
- **Account deletion:** `DELETE /api/auth/me/` erases the user and cascades to
  their endpoints, attributes, submissions and devices. Uploaded logos are
  deleted from disk **first** — a `FileField` leaves its file behind when the
  row goes, which would orphan a publicly-readable image under `/media/`.
  Reachable in the app from Settings → Delete account (type-to-confirm).
  This exists because Google Play requires an in-app deletion path. Throttling is
  auto-disabled under `manage.py test` (`settings.TESTING`) — the rate-limit
  counters are cache-backed and would otherwise leak between test cases.
- **Prod deploy of a change:** `scp` the file(s) to `/home/tanmoy/apps/datahook/…`
  then `sudo systemctl restart datahook`. (nginx already proxies; TLS via
  Cloudflare origin cert — no certbot.)
- Rate-limited: `/ingest/` and auth endpoints are throttled per IP.

> ⚠️ **Repo drift:** the live server + local working copy run ahead of the
> GitHub repo (`github.com/tanmoymondal1312/DataHook`). Commit & push the local
> repo before relying on `git pull` on the server.
