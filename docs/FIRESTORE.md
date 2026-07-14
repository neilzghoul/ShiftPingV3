# Firestore Schema

ShiftPing stores five top-level collections in Firebase Firestore.

## Collections

### `employees/{employeeId}`

| Field      | Type    | Description                          |
|------------|---------|--------------------------------------|
| id         | string  | Document ID (UUID)                   |
| name       | string  | Full name (Hebrew)                   |
| gender     | string  | `male` or `female`                   |
| phone      | string  | E.164 phone (`+972...`)              |
| active     | bool    | Included in scheduling if true       |
| notes      | string  | Optional admin notes                 |
| createdAt  | string  | ISO timestamp                        |
| updatedAt  | string  | ISO timestamp                        |

### `preferences/{employeeId}_{weekId}`

| Field      | Type    | Description                                      |
|------------|---------|--------------------------------------------------|
| id         | string  | `{employeeId}_{weekId}`                          |
| employeeId | string  | FK to employees                                  |
| weekId     | string  | e.g. `2026-W29`                                  |
| grid       | map     | `{ "ראשון": { "בוקר": "WANT"\|"CAN"\|"NO"\|null, ... }, ... }` |
| submitted  | bool    | Nurse finished preference collection             |
| createdAt  | string  | ISO timestamp                                    |
| updatedAt  | string  | ISO timestamp                                    |

### `schedules/{weekId}`

| Field         | Type    | Description                                         |
|---------------|---------|-----------------------------------------------------|
| id / weekId   | string  | e.g. `2026-W29`                                     |
| grid          | map     | `{ "ראשון": { "בוקר": ["empId", ...], ... }, ... }` |
| status        | string  | `draft` or `published`                              |
| published     | bool    | Mirror of published state                           |
| notes         | string  | Optional                                            |
| generationLog | array   | Human-readable generation notes                     |
| createdAt     | string  | ISO timestamp                                       |
| updatedAt     | string  | ISO timestamp                                       |

### `conversations/{phone}`

| Field   | Type   | Description                                      |
|---------|--------|--------------------------------------------------|
| id      | string | E.164 phone                                      |
| phone   | string | Same as id                                       |
| state   | string | `idle` or `collecting_prefs`                     |
| context | map    | e.g. `{ "weekId": "2026-W29" }`                  |

### `priority_history/{nurseId}_{week}`

| Field                   | Type   | Description                                              |
|-------------------------|--------|----------------------------------------------------------|
| id                      | string | `{nurse_id}_{week}`                                      |
| nurse_id                | string | FK to employees                                          |
| week                    | string | e.g. `2026-W30`                                          |
| preferences_satisfied   | int    | Count of WANT slots fulfilled in that week's schedule (0–3) |
| priority_score          | int    | `0→100`, `1→80`, `2→60`, `3→40`                          |
| nurse_name              | string | Denormalized display name                                |
| createdAt / updatedAt   | string | ISO timestamps                                           |

Scores from prior weeks are applied when generating the next schedule (higher = stronger pull onto WANT slots).

### `shift_swaps/{id}`

| Field               | Type   | Description |
|---------------------|--------|-------------|
| requester_nurse_id  | string | Who initiated |
| proposed_nurse_id   | string | Counterparty |
| week                | string | Week id |
| original_shift      | map    | `{day, shift}` of requester |
| requested_shift     | map    | `{day, shift}` of proposed |
| status              | string | `pending_requester_approval` (awaiting proposed) → `pending_chief_approval` → `approved` / `rejected` |
| history             | array  | Status change trail |
| created_at / updated_at | string | ISO |

### `swap_audit/{id}`

Append-only audit events: `swap_id`, `action`, `actor_id`, `detail`, `at`.

## Setup steps

1. Create a Firebase project at https://console.firebase.google.com
2. Enable **Firestore** (production or test mode; lock down rules for production)
3. Project settings → Service accounts → Generate new private key
4. Save the JSON locally as `firebase-credentials.json` (do not commit)
5. Set in `.env`:
   ```
   USE_MOCK_DB=false
   FIREBASE_CREDENTIALS_PATH=./firebase-credentials.json
   FIREBASE_PROJECT_ID=your-project-id
   ```
6. On Vercel, paste the entire service-account JSON into `FIREBASE_CREDENTIALS_JSON`
   and set `USE_MOCK_DB=false`

## Security rules (starter)

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      // Server-only access via Admin SDK – deny all client access
      allow read, write: if false;
    }
  }
}
```

No client SDK is used; the Flask backend uses the Admin SDK exclusively.
