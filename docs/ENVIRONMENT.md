# Environment variables

Copy [`.env.example`](../.env.example) to `.env` for local development. On Vercel, set the same keys in **Project → Settings → Environment Variables**.

## Required for production

| Variable | Example | Notes |
|----------|---------|-------|
| `SECRET_KEY` | long random string | Flask session signing |
| `ADMIN_TOKEN` | long random string | UI login + `X-Admin-Token` API auth |
| `USE_MOCK_DB` | `false` | Must be false on Vercel (mock DB does not persist) |
| `FIREBASE_CREDENTIALS_JSON` | `{...}` | Full service-account JSON (minified is fine) |
| `FIREBASE_PROJECT_ID` | `my-project` | Firebase project id |
| `TWILIO_ACCOUNT_SID` | `ACxxxx` | Twilio console |
| `TWILIO_AUTH_TOKEN` | secret | Twilio console |
| `TWILIO_WHATSAPP_FROM` | `whatsapp:+14155238886` | Sandbox or approved sender |
| `APP_BASE_URL` | `https://your-app.vercel.app` | Used for Twilio signature validation |

## Optional

| Variable | Default | Notes |
|----------|---------|-------|
| `FIREBASE_CREDENTIALS_PATH` | _(empty)_ | Local file path alternative to JSON env |
| `TWILIO_WEBHOOK_VALIDATE` | `false` | Set `true` after webhook URL is stable |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, … |
| `TIMEZONE` | `Asia/Jerusalem` | Week boundaries |
| `NURSES_PER_SHIFT` | `2` | Default staffing target |
| `SHIFTS_PER_DAY` | `3` | Informational (shifts are fixed: בוקר/ערב/לילה) |
| `USE_MOCK_DB` | `true` locally | In-memory store for demos/tests |

## Local demo (no Firebase / Twilio)

```bash
cp .env.example .env
# leave USE_MOCK_DB=true and Twilio empty
python wsgi.py
```

Outbound WhatsApp messages are mocked to the application log.

## API authentication

```http
X-Admin-Token: <ADMIN_TOKEN>
```

Browser UI stores the same token in an `admin_token` cookie after `/login`.
