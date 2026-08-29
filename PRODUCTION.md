# Production deployment (Railway)

This app runs as two Railway services sharing one Postgres database:

- **Web service** — the dashboard (`app.py`), always on.
- **Cron service** — the daily Gmail check (`fetch_job.py`), runs once a day and exits.

Neither service ever sends email automatically. Sending only happens when you click
**Approve & Send** in the dashboard.

## 1. Gmail OAuth — get a production-safe refresh token

Your OAuth consent screen is currently in **Testing** status. Google expires
refresh tokens issued under Testing after **7 days, regardless of use** — this
would silently break the daily cron job about a week after deployment.

1. In [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services
   → OAuth consent screen** → **Publish App** → confirm **In production**.
   - This app only serves you (restricted scopes, single user) — Google does not
     require a verification review to publish and use it yourself. You'll just see
     an "unverified app" click-through warning on future consent screens, which is
     safe to accept for your own app.
2. The 7-day expiry is fixed at the moment a token is *issued* — publishing doesn't
   retroactively fix an already-issued token. Redo the local consent once more:
   ```bash
   del secret\token.json
   python fetch_job.py
   ```
   Approve in the browser. This mints a fresh refresh token issued under
   Production status (no expiry).
3. Open `secret\client_secret*.json` and the new `secret\token.json`. You need three values:
   - `client_id` and `client_secret` — from the client_secret file.
   - `refresh_token` — from `token.json`.

   These three values become Railway environment variables in step 4 — **never commit
   either file to GitHub** (both are already gitignored).

## 2. Push the code

```bash
git add -A
git commit -m "Add Railway/Postgres production support"
git push origin main
```

## 3. Railway: create the Postgres database

In your Railway project: **New → Database → Add PostgreSQL**. Railway provisions it
and exposes a `DATABASE_URL` you'll reference from both services below.

## 4. Railway: create the web (dashboard) service

**New → GitHub Repo** → select `Prathamesh9422/Job-email-assistant`.

- **Settings → Deploy → Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
  (Railway also reads the committed `Procfile`, but setting it explicitly avoids ambiguity.)
- **Settings → Volumes → New Volume** → mount path `/data`.
- **Variables**:
  | Variable | Value |
  |---|---|
  | `DATABASE_URL` | reference the Postgres service's `DATABASE_URL` |
  | `GOOGLE_CLIENT_ID` | from step 1 |
  | `GOOGLE_CLIENT_SECRET` | from step 1 |
  | `GOOGLE_REFRESH_TOKEN` | from step 1 |
  | `DATA_DIR` | `/data` |

  `PORT` is injected automatically — don't set it.
- Deploy. Once live, note the public URL Railway assigns (Settings → Networking →
  Generate Domain if one isn't already there).

## 5. Railway: create the cron service

**New → GitHub Repo** → same repo again (a second, independent service).

- **Settings → Deploy → Start Command**: `python fetch_job.py`
- **Settings → Cron Schedule**: `30 14 * * *` (UTC — this is 8:00 PM India time)
- **No volume** — this service never touches `tracker.xlsx` or the resume.
- **Variables**:
  | Variable | Value |
  |---|---|
  | `DATABASE_URL` | same Postgres reference as the web service |
  | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REFRESH_TOKEN` | same values as the web service |

Railway runs this service's start command once per schedule tick, then the process
exits — it is not an always-on service. `fetch_job.py` has no code path that calls
Gmail's send API, so it structurally cannot send email regardless of configuration.

## 6. One-time: upload your resume

The resume PDF is intentionally excluded from git. After the web service is deployed
with its Volume attached, you need to get a resume file onto `/data/resumes/` once.
Railway doesn't have a general file browser for Volumes, so the simplest path is the
[Railway CLI](https://docs.railway.app/guides/cli):

```bash
railway link          # select this project/service
railway run bash
# now inside the running container's shell:
mkdir -p /data/resumes
# from another terminal on your machine:
railway ssh -- 'cat > /data/resumes/resume.pdf' < path\to\your\resume.pdf
```

(Exact upload mechanics may vary by Railway CLI version — if this doesn't work
directly, ask for the current recommended way to copy a file onto a Railway Volume.)

## 7. Verify

- `GET https://<your-web-service>.up.railway.app/api/health` → `{"ok": true}`
- Dashboard loads and the queue table renders (reading from Postgres now, not local SQLite).
- Click **Run Email Check Now** in the dashboard — confirm it completes and
  `GET /api/scheduler/status` shows a `success` entry with a real timestamp.
- Manually trigger the cron service once from Railway ("Run now") and confirm the
  same thing happens on that path.
- Re-run either path a second time and confirm no `queue` row is duplicated for the
  same Gmail message (`gmail_message_id` is unique — this is enforced at the database level).
- Send one real test email from the deployed dashboard to an address you control,
  to confirm the resume attaches correctly from the Volume.

## Notes

- Local development is unaffected by any of this — without `DATABASE_URL` set,
  `db.py` defaults to the same local `queue.db` SQLite file as before; without
  `GOOGLE_CLIENT_ID`/`SECRET`/`REFRESH_TOKEN` set, `gmail_client.py` falls back to
  the local `secret/` file + browser consent flow exactly as before.
- The Windows Task Scheduler entry (SETUP.md) can be left running as a local-dev
  convenience, disabled, or removed — it's independent of the Railway Cron job and
  has no effect on production once Railway is live.
