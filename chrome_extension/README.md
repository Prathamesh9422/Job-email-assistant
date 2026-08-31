# Naukri Applied-Jobs Sync (Chrome extension)

Scrapes your Naukri "Applied Jobs" history page and syncs new applications
into the job-triage dashboard (ARC-0004), for HR-contact enrichment.

## Install (unpacked, for now - not published to the Chrome Web Store)

1. `chrome://extensions` → enable **Developer mode** (top right).
2. **Load unpacked** → select this `chrome_extension/` folder.

## Set up

1. Open the dashboard, sign in, and click **Generate extension token** in
   the "Chrome extension" panel. Copy the token shown - it's shown once.
2. Click the extension's icon → **Options** (or right-click the icon →
   Options).
3. Enter your dashboard's base URL (e.g. `https://your-app.up.railway.app`,
   or `http://127.0.0.1:8000` for local dev) and paste the token. **Save**.
   Chrome will ask you to approve access to that URL - approve it, or the
   extension can't reach your API.

## Use

1. Go to `https://www.naukri.com/myapply/historypage` and let the page load.
2. Click the extension icon → **Scrape & Sync applied jobs**.
3. It scrolls the list to load every application, then posts them to your
   dashboard. New ones land as `needs_info` rows ready for enrichment;
   ones already synced (same company + role + applied date) are skipped,
   never duplicated or overwritten.

Regenerating the token on the dashboard invalidates the old one immediately
- update Options with the new one.
