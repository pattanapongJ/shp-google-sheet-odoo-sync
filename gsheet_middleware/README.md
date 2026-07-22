# Odoo ⇄ Google Sheet Tax-Invoice Middleware

FastAPI service that reads tax-invoice requests from a Google Form / Sheet and
serves them to Odoo, already filtered to the last 7 days and normalized to the
field names Odoo expects.

```
Google Form ──▶ Google Sheet ──▶ [this middleware] ──▶ Odoo cron (GET /records)
```

The middleware is **read-only**: it never writes to Odoo or the sheet. All the
accounting (cancel invoice → re-issue → reconcile) happens inside the Odoo
module `tax_invoice_gsheet_sync`.

## Endpoints

| Method | Path        | Auth            | Description                                   |
|--------|-------------|-----------------|-----------------------------------------------|
| GET    | `/health`   | none            | Liveness check.                               |
| GET    | `/records`  | `X-API-Key`     | 7-day-filtered, normalized sheet records.     |

`GET /records` response:

```json
{
  "count": 1,
  "max_age_days": 7,
  "generated_at": "2026-07-17T02:00:00Z",
  "records": [
    {
      "timestamp": "2026-07-15T09:12:00Z",
      "order_reference": "PO-2026-0042",
      "order_date": "2026-07-10",
      "amount": 1284.50,
      "customer_name": "Mr. Somchai Jaidee",
      "address": "123 Sukhumvit Rd, Bangkok",
      "tax_id": "0105561000000",
      "phone": "0812345678",
      "email": "somchai@example.com"
    }
  ]
}
```

`customer_name` is `title + name + surname` joined (Odoo's
`tax_inv_customer_name` is a single field).

## Google setup (service account)

1. In Google Cloud Console create a project and **enable the Google Sheets API**.
2. Create a **Service Account**, then create a **JSON key** for it. Download it.
3. Open your response spreadsheet → **Share** → add the service account's
   `client_email` (from the JSON) with **Viewer** access.
4. Copy the spreadsheet ID from the URL:
   `https://docs.google.com/spreadsheets/d/`**`<SPREADSHEET_ID>`**`/edit`.

## Configure

```bash
cp .env.example .env
# edit .env:
#   API_KEY            -> a long random string (also set it in Odoo settings)
#   GOOGLE_SA_KEY_FILE -> path to the downloaded service-account JSON
#   COLUMN_MAP         -> map YOUR header row text to the normalized fields
```

**Config split.** The spreadsheet id, sheet range, max record age and timezone
are **managed in Odoo** (Sales → Settings → Tax Invoice GSheet Sync) and sent to
`/records` as query params, so an admin never has to touch this host. The
`.env` values for `SPREADSHEET_ID / SHEET_RANGE / MAX_AGE_DAYS / SHEET_TIMEZONE`
are only fallbacks used when a request omits them (e.g. a manual `curl`).
`API_KEY`, `GOOGLE_SA_KEY_FILE` and `COLUMN_MAP` stay here.

`/records` query params (all optional, override env): `spreadsheet_id`,
`sheet_range`, `max_age_days`, `timezone`.

**`COLUMN_MAP` is the important one.** The keys are the exact header texts in
row 1 of the sheet (they may be Thai); the values are fixed normalized names:
`timestamp, order_reference, order_date, amount, title, name, surname, address,
tax_id, phone, email`. Any header not in the map is ignored.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Verify:

```bash
curl -s localhost:8000/health
curl -s -H "X-API-Key: <your key>" localhost:8000/records | python3 -m json.tool
```

For production run behind a reverse proxy (systemd + `uvicorn --workers 2`, or
`gunicorn -k uvicorn.workers.UvicornWorker`). If Odoo and the middleware are on
different hosts, expose it over HTTPS.
