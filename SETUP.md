# Setup

## 1. Install dependencies

```bash
pip install -r requirements.txt
```

## 2. Create Gmail API OAuth credentials

1. Go to https://console.cloud.google.com/ and create a new project (or reuse one).
2. In **APIs & Services > Library**, search for "Gmail API" and click **Enable**.
3. In **APIs & Services > OAuth consent screen**:
   - User type: **External** (unless you have a Workspace account, then Internal works too).
   - Fill in app name, your email as support/contact.
   - Under **Test users**, add your own Gmail address. This keeps the app in "Testing" mode, which avoids Google's verification review — fine for a personal single-user tool.
4. In **APIs & Services > Credentials**, click **Create Credentials > OAuth client ID**.
   - Application type: **Desktop app**.
   - Download the resulting JSON and save it in `P:\job\emailing_agent\secret\` (any filename starting with `client_secret` works — the app auto-detects it).

## 3. First run — consent

The first time you run `fetch_job.py` or `app.py`, a browser window will open asking you to log in and approve access (read + send scopes only). After approving, a `token.json` file is created and will be silently refreshed on future runs — you won't need to log in again unless you delete `token.json` or revoke access.

## 4. Run the daily fetch manually (first test)

```bash
python fetch_job.py
```

This searches Gmail for Naukri emails, parses them, and populates `queue.db`. It never sends anything.

## 5. Run the review UI

```bash
uvicorn app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 in a browser. Review each row, edit the HR email if needed, pick a template, preview it, and click **Approve & Send** when ready.

## 6. Schedule the daily fetch (Windows Task Scheduler)

1. Open Task Scheduler > **Create Basic Task**.
2. Name: `Naukri Job Triage Fetch`. Trigger: **Daily**, pick a time (e.g. 8:00 AM).
3. Action: **Start a program**.
   - Program/script: path to your `python.exe` (e.g. `C:\Python312\python.exe` or your venv's python).
   - Arguments: `fetch_job.py`
   - Start in: `P:\job\emailing_agent`
4. Finish. The task will run once daily, silently populating the queue.

## 7. (Optional) Auto-start the review UI at logon

If you'd rather not run `uvicorn` manually each time:

1. Task Scheduler > **Create Task**.
2. Trigger: **At log on**.
3. Action: Program = path to `python.exe`, Arguments = `-m uvicorn app:app --host 127.0.0.1 --port 8000`, Start in = `P:\job\emailing_agent`.
4. The UI will then always be available at http://127.0.0.1:8000 once you're logged in.

## Notes

- The `secret/` folder (client secret + `token.json`), `queue.db`, `tracker.xlsx`, and `state.json` are all gitignored — never commit them.
- The daily fetch defaults to a 5-day lookback window if `state.json` doesn't exist yet (first run).
- Edit `templates/reply_to_naukri.txt` and `templates/cold_outreach.txt` to replace the `[PLACEHOLDER: ...]` lines with your own wording. The first line of each file (`Subject: ...`) is used as the email subject.
- Before trusting this against real HR contacts, send one test email to an address you control to confirm the resume attachment and threaded-reply-to-a-different-recipient behavior work as expected in your Gmail account.
