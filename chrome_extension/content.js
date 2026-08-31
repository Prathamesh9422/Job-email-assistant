// Runs on naukri.com. Scrapes the "Applied on the go" application-history
// list (myapply/historypage) when asked, and hands raw rows back to the
// popup - it does not call the API itself (that needs the stored token +
// base URL, which live in extension storage, not accessible/needed here).

const CONTAINER_SELECTOR = ".jdTuplesContainer";
const NOISE_LINES = new Set(["Prep for this interview", "Mock", "Q&A"]);
const RATING_RE = /^\d\.\d$/;
// The trailing relative-date phrase inside a status line like
// "Application sent 4 days ago" - matches what browser_ingest.py's
// resolve_applied_date() understands (today/yesterday/N days ago/N week(s) ago).
const RELATIVE_DATE_RE = /(today|yesterday|\d+\s+days?\s+ago|\d+\s+weeks?\s+ago)\s*$/i;

function extractRelativeDate(statusLine) {
  if (!statusLine) return null;
  const match = statusLine.match(RELATIVE_DATE_RE);
  return match ? match[1].replace(/\s+/g, " ").trim() : null;
}

function extractJobLink(cardEl) {
  const anchor = cardEl.querySelector("a[href]");
  return anchor ? anchor.href : null;
}

function parseCard(cardEl) {
  const rawLines = cardEl.innerText.split("\n").map((s) => s.trim()).filter(Boolean);
  const lines = rawLines.filter((l) => !NOISE_LINES.has(l));
  if (lines.length < 2) return null;

  let i = 0;
  const title = lines[i++];
  const company = lines[i++];
  if (lines[i] && RATING_RE.test(lines[i])) {
    i += 2; // skip rating + "N Reviews"
  }
  const statusLine = lines[i++] || "";

  return {
    role: title,
    company,
    applied_date: extractRelativeDate(statusLine),
    job_link: extractJobLink(cardEl),
    _raw_status: statusLine, // kept for the popup to show "why skipped" on unparseable dates
  };
}

async function waitFor(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// The applied-jobs list lazy-loads more cards as the container scrolls, the
// same way the visible page does for a human - there is no "load all"
// endpoint, so we drive the same scroll-triggered fetches the UI itself uses.
async function loadAllCards(container, onProgress) {
  let stableRounds = 0;
  const maxRounds = 60; // ~60 * 500ms = 30s ceiling, well past any real applied-jobs list
  for (let round = 0; round < maxRounds && stableRounds < 3; round++) {
    const before = container.children.length;
    container.scrollTop = container.scrollHeight;
    await waitFor(500);
    const after = container.children.length;
    if (onProgress) onProgress(after);
    stableRounds = after > before ? 0 : stableRounds + 1;
  }
}

async function scrapeAppliedJobs(onProgress) {
  const container = document.querySelector(CONTAINER_SELECTOR);
  if (!container) {
    throw new Error(
      "Couldn't find the applied-jobs list on this page. Make sure you're on " +
        "naukri.com/myapply/historypage and it has finished loading."
    );
  }

  await loadAllCards(container, onProgress);

  const jobs = Array.from(container.children)
    .map(parseCard)
    .filter((job) => job && job.company && job.role);

  return jobs;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "SCRAPE_APPLIED_JOBS") return undefined;

  scrapeAppliedJobs((loadedCount) => {
    chrome.runtime.sendMessage({ type: "SCRAPE_PROGRESS", loadedCount }).catch(() => {});
  })
    .then((jobs) => sendResponse({ ok: true, jobs }))
    .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));

  return true; // keep the message channel open for the async response above
});
