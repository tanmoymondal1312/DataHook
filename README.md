# DataHook

A Django REST backend that lets developers spin up their own **typed API /
form-ingest endpoints** — no code required. Create an endpoint, define its
attributes (typed fields), and share the ingest URL + secret API key. Any
website or app can `POST` JSON (or a plain HTML form) to it; submissions are
stored and validated, and the owner gets a Firebase push notification.

This backend powers an Android (Jetpack Compose) client and implements the exact
API contract that client depends on.

---

## Stack

- Python 3.12 · Django 5.1 · Django REST Framework
- `djangorestframework-simplejwt` — JWT auth (access + refresh)
- Custom **email-login** user model (no username)
- SQLite for dev, Postgres-compatible for production
- `firebase-admin` — FCM push (service-account JSON via env)
- `django-cors-headers` — permissive for public ingest, restrictable for the app
- Deploy target: gunicorn + systemd + nginx on `datahook.mediaghor.com`

---

## Quick start (local)

```bash
# 1. Create + activate a virtualenv
python3.12 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env          # then edit SECRET_KEY etc. (defaults work for dev)

# 4. Migrate the database
python manage.py migrate

# 5. Seed a demo user + endpoint (prints credentials, ingest URL, API key)
python manage.py seed_demo

# 6. (optional) create an admin superuser for /admin/
python manage.py createsuperuser

# 7. Run
python manage.py runserver
```

The API is now at `http://localhost:8000/`.

### Try the full flow in 30 seconds

```bash
# seed_demo prints these — substitute your slug + api key:
curl -X POST "http://localhost:8000/ingest/contact-form-XXXXXX/" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <api_key>" \
  -d '{"name":"Ada","email":"ada@example.com"}'
# -> {"success": true, "id": 2}
```

Then log in and read it back:

```bash
ACCESS=$(curl -s -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@datahook.dev","password":"demo12345"}' | python -c "import sys,json;print(json.load(sys.stdin)['access'])")

curl http://localhost:8000/api/endpoints/1/submissions/ -H "Authorization: Bearer $ACCESS"
```

---

## Configuration (`.env`)

All settings are environment-driven — see [.env.example](.env.example). Key vars:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django secret. **Change in production.** |
| `DEBUG` | `True`/`False`. |
| `ALLOWED_HOSTS` | Comma-separated hostnames. |
| `BASE_URL` | Public origin used to build ingest URLs + snippets (no trailing slash). |
| `FIREBASE_CREDENTIALS` | Absolute path to the Firebase service-account JSON. Blank ⇒ push disabled (rest of API still works). |
| `CORS_ALLOWED_ORIGINS` | Origins allowed for the admin API. |
| `CORS_INGEST_ALLOW_ALL` | Allow all origins for `/ingest/` (so plain HTML forms work). |
| `INGEST_THROTTLE_RATE` / `AUTH_THROTTLE_RATE` | DRF rate limits, e.g. `60/minute`. |
| `POSTGRES_DB`, `POSTGRES_USER`, … | Set `POSTGRES_DB` to switch from SQLite to Postgres. |

---

## API contract

All `/api/` admin routes require `Authorization: Bearer <access>`.
The `/ingest/{slug}/` route is public and authenticated by the `X-API-Key` header.

### Auth & devices

| Method | Path | Body | Result |
|---|---|---|---|
| POST | `/api/auth/register/` | `{email, name, password}` | `201 {user, access, refresh}` |
| POST | `/api/auth/login/` | `{email, password}` | `200 {user, access, refresh}` |
| POST | `/api/auth/refresh/` | `{refresh}` | `200 {access}` |
| GET  | `/api/auth/me/` | — | `200 user` |
| POST | `/api/devices/` | `{fcm_token}` | `200` (upsert device) |
| DELETE | `/api/devices/` | `{fcm_token}` | `204` |

### Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/api/endpoints/` | list with `submission_count`, `attribute_count` |
| POST | `/api/endpoints/` | `{name, description?}` → `201` full detail |
| GET | `/api/endpoints/{id}/` | detail + `attributes[]` + `ingest_url` + `api_key` + `snippets{}` |
| PATCH | `/api/endpoints/{id}/` | `{name?, description?, notify_on_submit?}` |
| DELETE | `/api/endpoints/{id}/` | `204` |
| POST | `/api/endpoints/{id}/rotate-key/` | `200 {api_key}` |

### Attributes (nested)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/endpoints/{id}/attributes/` | list |
| POST | `/api/endpoints/{id}/attributes/` | `{label, key, type, required, order?}` |
| PATCH | `/api/endpoints/{id}/attributes/{aid}/` | update |
| DELETE | `/api/endpoints/{id}/attributes/{aid}/` | `204` |

- `type` ∈ `text | email | number | phone | date | boolean`
- `key` must be a **strict slug**: lowercase letters/digits/underscore, no
  spaces, starting with a letter/underscore — and unique per endpoint
  (`400` otherwise).

### Submissions (nested)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/endpoints/{id}/submissions/?search=&page=` | paginated, page size 20. `search` = case-insensitive contains across the JSON payload. |
| DELETE | `/api/endpoints/{id}/submissions/{sid}/` | `204` |
| GET | `/api/endpoints/{id}/export/?format=csv\|json` | file download; columns = attribute keys + `created_at` |

### Public ingest

```
POST /ingest/{slug}/
Header: X-API-Key: <endpoint.api_key>
Content-Type: application/json | application/x-www-form-urlencoded | multipart/form-data
```

Strict validation against the endpoint's attributes:

- every `required` attribute must be present and non-empty
- every provided key must match a defined attribute (unknown keys rejected)
- each value must validate for its type
  (`email`, `phone`, `number`, `date` = `YYYY-MM-DD`, `boolean` = `true/false/1/0`, `text`)

On failure: `400 {"errors": {key: message}}`.
On success: the submission is stored (with source IP), an FCM push is sent to all
of the owner's devices (if `notify_on_submit`), and the response is
`201 {"success": true, "id": <id>}`.

Errors follow a consistent envelope: `{"detail": "...", "errors": {...}}`.

---

## Auto-generated snippets

`GET /api/endpoints/{id}/` includes a `snippets` object with three ready-to-copy
strings built from the endpoint's ingest URL, API key and attribute keys:

- **`js_fetch`** — a `fetch()` POST with the JSON body + headers
- **`curl`** — the equivalent `curl` command
- **`html_form`** — a ready `<form>` posting to the ingest URL (works because
  ingest accepts form-urlencoded)

> The HTML form intentionally does **not** embed the API key (forms are
> client-visible). Post it through a small proxy that adds the `X-API-Key`
> header, or use the JS/curl snippets for authenticated calls.

---

## FCM push

Set `FIREBASE_CREDENTIALS` to your service-account JSON path. On a new
submission DataHook sends:

- **title**: `New submission · {endpoint.name}`
- **body**: first two field values
- **data**: `{endpoint_id, submission_id, type: "submission"}`

Tokens FCM reports as unregistered are pruned automatically. If credentials are
absent or invalid, push degrades to a no-op — the API keeps working.

---

## Production deployment (`datahook.mediaghor.com`)

Files live in [deploy/](deploy/).

```bash
# On the server, project at /srv/datahook with venv + .env in place:
python manage.py migrate
python manage.py collectstatic --noinput

# gunicorn via systemd (binds 127.0.0.1:9100)
sudo cp deploy/datahook.service /etc/systemd/system/datahook.service
sudo systemctl daemon-reload
sudo systemctl enable --now datahook

# nginx reverse proxy on the subdomain
sudo cp deploy/nginx-datahook.conf /etc/nginx/sites-available/datahook
sudo ln -s /etc/nginx/sites-available/datahook /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# TLS
sudo certbot --nginx -d datahook.mediaghor.com
```

Set `BASE_URL=https://datahook.mediaghor.com` and `DEBUG=False` in the server's
`.env`. nginx forwards `X-Forwarded-For` so submissions record the real client
IP.

---

## Project layout

```
config/          Django project (settings, urls, wsgi/asgi, exception handler)
accounts/        Custom User + manager, Device, auth/device API
endpoints/       Endpoint / Attribute / Submission models, admin API,
                 public ingest, validators, snippets, FCM, seed command
deploy/          systemd unit + nginx server block
```

---

## Notes

- Rate limiting: `/ingest/` and the auth endpoints are throttled per client IP
  (configurable via `.env`).
- Ownership isolation: users only ever see/modify their own endpoints,
  attributes and submissions (`404` otherwise).
- Postgres: everything uses portable ORM constructs (the submission search casts
  the JSON column to text via `Cast`, which works on both SQLite and Postgres).
# DataHook
