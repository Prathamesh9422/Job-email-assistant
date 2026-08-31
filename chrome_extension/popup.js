const notConfiguredEl = document.getElementById("not-configured");
const wrongPageEl = document.getElementById("wrong-page");
const mainEl = document.getElementById("main");
const statusEl = document.getElementById("status");
const errorsEl = document.getElementById("errors");
const syncBtn = document.getElementById("sync-btn");

document.getElementById("open-options-btn").addEventListener("click", () => chrome.runtime.openOptionsPage());
document.getElementById("options-link").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = kind || "";
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function init() {
  const { apiBaseUrl, apiToken } = await chrome.storage.local.get(["apiBaseUrl", "apiToken"]);
  if (!apiBaseUrl || !apiToken) {
    notConfiguredEl.style.display = "block";
    return;
  }

  const tab = await getActiveTab();
  if (!tab?.url?.includes("naukri.com/myapply/historypage")) {
    wrongPageEl.style.display = "block";
    return;
  }

  mainEl.style.display = "block";
}

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "SCRAPE_PROGRESS") {
    setStatus(`Loading applied jobs... (${message.loadedCount} rows loaded so far)`);
  }
});

syncBtn.addEventListener("click", async () => {
  syncBtn.disabled = true;
  errorsEl.textContent = "";
  setStatus("Scraping this page...");

  try {
    const { apiBaseUrl, apiToken } = await chrome.storage.local.get(["apiBaseUrl", "apiToken"]);
    const tab = await getActiveTab();

    const response = await chrome.tabs.sendMessage(tab.id, { type: "SCRAPE_APPLIED_JOBS" });
    if (!response?.ok) {
      throw new Error(response?.error || "Scrape failed - try reloading the Naukri tab.");
    }
    const jobs = response.jobs;
    if (jobs.length === 0) {
      setStatus("No applied jobs found on this page.", "error");
      return;
    }

    setStatus(`Found ${jobs.length} applied job(s). Syncing...`);

    const payload = {
      jobs: jobs.map((j) => ({
        company: j.company,
        role: j.role,
        applied_date: j.applied_date,
        job_link: j.job_link,
      })),
    };

    const res = await fetch(`${apiBaseUrl}/api/queue/ingest-scraped`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiToken}`,
      },
      body: JSON.stringify(payload),
    });

    if (res.status === 401) {
      throw new Error("Token rejected - regenerate it from the dashboard and update Options.");
    }
    if (!res.ok) {
      throw new Error(`Server error (${res.status})`);
    }

    const result = await res.json();
    setStatus(
      `Synced: ${result.inserted} new, ${result.skipped} already synced or invalid (of ${result.received} scraped).`,
      "success"
    );
    if (result.errors?.length) {
      errorsEl.textContent = "Skipped rows:\n" + result.errors.join("\n");
    }
  } catch (err) {
    setStatus(String(err.message || err), "error");
  } finally {
    syncBtn.disabled = false;
  }
});

init();
