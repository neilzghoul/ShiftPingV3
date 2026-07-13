# ShiftPing

Nurse shift scheduling over WhatsApp — Hebrew UI, preference collection (רוצה / יכול-ה / לא), automatic weekly roster generation, RTL paper-style viewer, and admin editing.

**Stack:** Python · Flask · Firebase Firestore · Twilio WhatsApp · Vercel

---

## Features

1. **Employee management** — add / edit / delete nurses (name, gender, phone)
2. **WhatsApp preferences** — WANT / CAN / NO (`רוצה` / `יכול`·`יכולה` / `לא`)
3. **Hebrew + gender-aware** messaging and RTL admin UI
4. **Auto schedule generation** — no double shifts, no night→morning, respect `NO`, fairness balancing
5. **Paper-format schedule viewer** (days as columns, shifts as rows)
6. **Admin editor** — multi-select assignments per cell
7. **Publish** — personal WhatsApp messages to every active nurse

---

## Quick start (local, mock DB)

```bash
cd ShiftPingV3
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# ADMIN_TOKEN in .env is used for login / API

python wsgi.py
# → http://localhost:5000
```

1. Open http://localhost:5000/login and enter `ADMIN_TOKEN` (default from `.env.example`: `change-me-admin-token`)
2. On the dashboard, click **טען נתוני דוגמה**
3. Click **צור סידור אוטומטי**, then open **סידור** / **עריכה**

Or seed from the CLI:

```bash
python scripts/seed.py
```

---

## Environment variables

See [`.env.example`](.env.example) for the full list.

| Variable | Purpose |
|----------|---------|
| `ADMIN_TOKEN` | Login cookie + `X-Admin-Token` header for APIs |
| `USE_MOCK_DB` | `true` = in-memory (local); `false` = Firestore |
| `FIREBASE_CREDENTIALS_JSON` / `_PATH` | Service account for Firestore |
| `TWILIO_ACCOUNT_SID` / `AUTH_TOKEN` / `WHATSAPP_FROM` | WhatsApp send + webhook |
| `APP_BASE_URL` | Public URL (needed for Twilio signature validation) |
| `NURSES_PER_SHIFT` | Default slots per shift (default `2`) |

Without Twilio credentials, outbound messages are **logged and mocked** (safe for local demos).

---

## Firebase setup

Full schema and security rules: [`docs/FIRESTORE.md`](docs/FIRESTORE.md).

Environment variable reference: [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md).

Summary:

1. Create a Firebase project and enable Firestore
2. Generate a service account key
3. Set `USE_MOCK_DB=false` and credentials in `.env` or Vercel env vars

---

## Twilio WhatsApp

1. Create a Twilio account and enable WhatsApp (Sandbox is fine for testing)
2. Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`
3. Point the WhatsApp sandbox “When a message comes in” webhook to:

   `https://<your-domain>/webhook/whatsapp` (HTTP POST)

4. Nurses must be registered as employees with the same phone number they use on WhatsApp
5. From the dashboard: **בקש העדפות ב-WhatsApp**

### Nurse message examples

```
ראשון בוקר רוצה
שני ערב יכולה
שלישי לילה לא
סטטוס
סיים
עזרה
סידור
```

Replies are gender-aware (`יכול` / `יכולה`, greetings).

---

## API overview

All mutating `/api/*` routes (except health + WhatsApp webhook) require header:

`X-Admin-Token: <ADMIN_TOKEN>`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET/POST/PUT/DELETE | `/api/employees` | CRUD |
| GET/PUT | `/api/preferences`, `/api/preferences/<id>` | Preference grids |
| POST | `/api/preferences/request` | Broadcast WhatsApp preference request |
| GET/POST | `/api/schedules`, `/api/schedules/generate` | Read / generate |
| PUT/PATCH | `/api/schedules/<week>` | Save or patch assignment |
| POST | `/api/schedules/<week>/publish` | Publish + WhatsApp |
| POST | `/api/seed` | Load sample nurses |
| POST | `/webhook/whatsapp` | Twilio inbound |

---

## Scheduling logic

For each day (Sun→Sat) and shift (בוקר → ערב → לילה):

- Skip anyone who marked **NO**
- Skip anyone already assigned that day
- Skip **night → next morning** (rest rule)
- Prefer **WANT** over **CAN** over unanswered
- Prefer nurses with fewer shifts so far (fairness)
- Second pass fills understaffed cells without violating hard constraints

Admin edits can create soft warnings (shown in the UI); publish still works.

---

## Deploy to Vercel

```bash
npm i -g vercel   # if needed
vercel
```

Configure environment variables in the Vercel project (especially `USE_MOCK_DB=false`, Firebase JSON, Twilio, `ADMIN_TOKEN`, `APP_BASE_URL`, `SECRET_KEY`).

[`vercel.json`](vercel.json) routes all traffic to the Flask app in [`api/index.py`](api/index.py).

> **Note:** In-memory mock DB does **not** persist across serverless invocations. Use Firestore in production.

---

## Tests

```bash
python tests/test_core.py
```

---

## Project layout

```
api/index.py          # Vercel entry
app/
  config.py
  routes/             # HTTP + pages
  services/           # DB, employees, prefs, scheduler, WhatsApp
  utils/              # Hebrew, dates, auth, logging
templates/            # RTL Hebrew UI
static/
docs/FIRESTORE.md
scripts/seed.py
```

---

## License

MIT
