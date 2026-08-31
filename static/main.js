const signinScreen = document.getElementById("signin-screen");
const appShell = document.getElementById("app-shell");
const accountChip = document.getElementById("account-chip");
const signoutBtn = document.getElementById("signout-btn");

const tbody = document.getElementById("queue-body");
const digestBody = document.getElementById("digest-body");
const resumeIndicator = document.getElementById("resume-indicator");
const schedulerStatus = document.getElementById("scheduler-status");
const runNowBtn = document.getElementById("run-now-btn");
const refreshBtn = document.getElementById("refresh-btn");
const previewModal = document.getElementById("preview-modal");
const previewSubjectInput = document.getElementById("preview-subject-input");
const previewBodyInput = document.getElementById("preview-body-input");
const previewStatus = document.getElementById("preview-status");
const sentHistoryList = document.getElementById("sent-history-list");
const archiveToggleBtn = document.getElementById("archive-toggle-btn");
let currentPreview = { id: null, template: null };
let showingArchive = false;

// Mirrors lifecycle.py's transition table, for enabling only valid "Advance"
// options client-side - the server (lifecycle.apply_transition) is still the
// single place transitions are actually validated (ARC-0001 invariant 1).
const ADVANCE_EVENTS = {
  sent: [
    ["hr_reply", "HR replied"],
    ["schedule_interview", "Schedule interview"],
    ["reject", "Mark rejected"],
    ["offer", "Mark offer"],
  ],
  awaiting_hr_reply: [
    ["schedule_interview", "Schedule interview"],
    ["reject", "Mark rejected"],
    ["offer", "Mark offer"],
  ],
  interview_scheduled: [
    ["schedule_interview", "Next round"],
    ["reject", "Mark rejected"],
    ["offer", "Mark offer"],
  ],
};

document.getElementById("preview-close").addEventListener("click", () => {
  previewModal.classList.add("hidden");
});
document.getElementById("preview-finalize").addEventListener("click", finalizeCurrentPreview);
document.getElementById("preview-regenerate").addEventListener("click", () => {
  if (!confirm("Discard current edits and regenerate from the template?")) return;
  renderFromTemplate(currentPreview.id, currentPreview.template);
});

async function loadResume() {
  const res = await fetch("/api/resume");
  const data = await res.json();
  resumeIndicator.textContent = data.resume_filename
    ? `Resume: ${data.resume_filename}`
    : "Resume: none found in resumes/";
}

async function loadQueue() {
  // No status param => server defaults to ACTIONABLE_STATUSES (every
  // non-terminal row, ARC-0003 invariant 1) unless the Archived toggle is on.
  const url = showingArchive ? "/api/queue?status=offer,rejected,skipped" : "/api/queue";
  const res = await fetch(url);
  const rows = await res.json();
  renderRows(rows);
}

async function loadSchedulerStatus() {
  const res = await fetch("/api/scheduler/status");
  const data = await res.json();
  if (!data.last_run_at) {
    schedulerStatus.textContent = "Scheduler: no runs yet";
    return;
  }
  const when = new Date(data.last_run_at).toLocaleString();
  const parts = [`Last run: ${when} (${data.last_run_status})`];
  if (data.last_run_status === "success") {
    parts.push(`${data.processed_count ?? 0} added / ${data.messages_found ?? 0} found`);
  } else if (data.last_run_error) {
    parts.push(`error: ${data.last_run_error}`);
  }
  schedulerStatus.textContent = parts.join(" — ");
  schedulerStatus.title = `Next expected run: ${new Date(data.next_expected_run_utc).toLocaleString()}`;
}

async function runEmailCheckNow() {
  runNowBtn.disabled = true;
  runNowBtn.textContent = "Running...";
  try {
    const res = await fetch("/api/scheduler/run-now", { method: "POST" });
    const data = await res.json();
    if (!res.ok || data.status === "failed") {
      alert(`Run failed: ${data.error || "unknown error"}`);
    } else {
      alert(`Done — found ${data.messages_found}, added ${data.rows_inserted} new candidate(s).`);
    }
  } catch (e) {
    alert(`Run failed: ${e}`);
  } finally {
    runNowBtn.disabled = false;
    runNowBtn.textContent = "Run Email Check Now";
    loadSchedulerStatus();
    loadQueue();
    loadDigests();
  }
}

runNowBtn.addEventListener("click", runEmailCheckNow);

async function loadDigests() {
  const res = await fetch("/api/queue?status=digest");
  const rows = await res.json();
  renderDigests(rows);
}

function renderDigests(rows) {
  digestBody.innerHTML = "";
  if (rows.length === 0) {
    digestBody.innerHTML = `<tr><td colspan="4">No digest emails right now.</td></tr>`;
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");

    const tdSubject = document.createElement("td");
    tdSubject.dataset.label = "Subject";
    tdSubject.textContent = row.subject || "(no subject)";

    const tdReceived = document.createElement("td");
    tdReceived.dataset.label = "Received";
    tdReceived.textContent = row.received_at ? new Date(row.received_at).toLocaleString() : "";

    const tdLinks = document.createElement("td");
    tdLinks.dataset.label = "Job links";
    const links = row.digest_job_links || [];
    if (links.length === 0) {
      tdLinks.textContent = "(no job links found)";
    } else {
      links.forEach((url, i) => {
        const a = document.createElement("a");
        a.href = url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = `Job ${i + 1}`;
        tdLinks.appendChild(a);
        if (i < links.length - 1) tdLinks.appendChild(document.createTextNode(" | "));
      });
    }

    const tdActions = document.createElement("td");
    tdActions.dataset.label = "Actions";
    const dismissBtn = document.createElement("button");
    dismissBtn.textContent = "Dismiss";
    dismissBtn.addEventListener("click", () => dismissDigest(row.id));
    tdActions.appendChild(dismissBtn);

    tr.append(tdSubject, tdReceived, tdLinks, tdActions);
    digestBody.appendChild(tr);
  }
}

async function dismissDigest(id) {
  await fetch(`/api/queue/${id}/skip`, { method: "POST" });
  loadDigests();
}

function renderRows(rows) {
  tbody.innerHTML = "";
  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8">No candidates right now.</td></tr>`;
    return;
  }
  for (const row of rows) {
    tbody.appendChild(renderRow(row));
  }
}

function renderRow(row) {
  const tr = document.createElement("tr");
  tr.dataset.id = row.id;

  const tdReceived = document.createElement("td");
  tdReceived.dataset.label = "Received";
  tdReceived.textContent = row.received_at ? new Date(row.received_at).toLocaleString() : "";

  const tdCompany = document.createElement("td");
  tdCompany.dataset.label = "Company";
  const companyInput = document.createElement("input");
  companyInput.type = "text";
  companyInput.value = row.company || "";
  companyInput.placeholder = "Company name";
  companyInput.addEventListener("change", () => patchRow(row.id, { company: companyInput.value }));
  tdCompany.appendChild(companyInput);

  const tdRole = document.createElement("td");
  tdRole.dataset.label = "Role";
  tdRole.textContent = row.role || "(unknown)";

  const tdHr = document.createElement("td");
  tdHr.dataset.label = "HR Email";
  const hrInput = document.createElement("input");
  hrInput.type = "text";
  hrInput.value = row.hr_email || "";
  hrInput.placeholder = "hr@company.com";
  hrInput.addEventListener("change", () => patchRow(row.id, { hr_email: hrInput.value }));
  tdHr.appendChild(hrInput);

  const tdSource = document.createElement("td");
  tdSource.dataset.label = "Source / Confidence";
  tdSource.textContent = `${row.hr_email_source} / ${row.hr_email_confidence}`;

  const tdTemplate = document.createElement("td");
  tdTemplate.dataset.label = "Template";
  const select = document.createElement("select");
  for (const [value, label] of [
    ["reply_to_naukri", "Reply to Naukri"],
    ["cold_outreach", "Cold outreach"],
    ["cover_letter", "Cover letter"],
  ]) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    if (row.template_used === value) opt.selected = true;
    select.appendChild(opt);
  }
  select.addEventListener("change", () => patchRow(row.id, { template_used: select.value }));
  tdTemplate.appendChild(select);

  const tdStatus = document.createElement("td");
  tdStatus.dataset.label = "Status";
  const pill = document.createElement("span");
  pill.className = `status-pill status-${row.status}`;
  pill.textContent = row.status;
  tdStatus.appendChild(pill);
  if (row.error_message) {
    const err = document.createElement("div");
    err.style.color = "#DC2626";
    err.style.fontSize = "0.75rem";
    err.textContent = row.error_message;
    tdStatus.appendChild(err);
  }
  tdStatus.appendChild(buildTimeline(row));

  const advanceOptions = ADVANCE_EVENTS[row.status];
  if (advanceOptions) {
    const advanceRow = document.createElement("div");
    advanceRow.className = "advance-row";
    const select = document.createElement("select");
    for (const [event, label] of advanceOptions) {
      const opt = document.createElement("option");
      opt.value = event;
      opt.textContent = label;
      select.appendChild(opt);
    }
    const advanceBtn = document.createElement("button");
    advanceBtn.textContent = "Record";
    advanceBtn.addEventListener("click", () => advanceRowLifecycle(row.id, select.value));
    advanceRow.append(select, advanceBtn);
    tdStatus.appendChild(advanceRow);
  }

  const tdActions = document.createElement("td");
  tdActions.dataset.label = "Actions";
  tdActions.className = "actions";

  const scrapeBtn = document.createElement("button");
  scrapeBtn.textContent = "Scrape";
  scrapeBtn.addEventListener("click", () => scrapeRow(row.id));
  tdActions.appendChild(scrapeBtn);

  const previewBtn = document.createElement("button");
  previewBtn.textContent = "Preview";
  previewBtn.addEventListener("click", () => previewRow(row.id, select.value));
  tdActions.appendChild(previewBtn);

  const sendBtn = document.createElement("button");
  sendBtn.textContent = "Approve & Send";
  sendBtn.className = "primary";
  sendBtn.addEventListener("click", () => sendRow(row.id));
  tdActions.appendChild(sendBtn);

  const skipBtn = document.createElement("button");
  skipBtn.textContent = "Skip";
  skipBtn.addEventListener("click", () => skipRow(row.id));
  tdActions.appendChild(skipBtn);

  tr.append(tdReceived, tdCompany, tdRole, tdHr, tdSource, tdTemplate, tdStatus, tdActions);
  return tr;
}

const TERMINAL_STATUSES = new Set(["offer", "rejected", "skipped"]);

// Variable-length lifecycle timeline (ARC-0003 "Lifecycle Progress UI"): one
// entry per event actually recorded on the row, not a fixed N-step indicator.
// Note: only the most recent interview round's timestamp is stored, so this
// shows the current round, not a full per-round history (interview_round is
// a counter, per ARC-0001 invariant 3, not a row per round).
function buildTimeline(row) {
  const list = document.createElement("ol");
  list.className = "lifecycle-timeline";

  const entries = [{ label: "Applied", at: row.received_at, done: true }];
  if (row.sent_at) entries.push({ label: "Sent", at: row.sent_at, done: true });
  if (row.hr_reply_at) entries.push({ label: "HR replied", at: row.hr_reply_at, done: true });
  if (row.interview_scheduled_at) {
    entries.push({
      label: `Interview — Round ${row.interview_round || 1}`,
      at: row.interview_scheduled_at,
      done: true,
    });
  }
  if (TERMINAL_STATUSES.has(row.status) && row.status !== "skipped") {
    entries.push({ label: row.status === "offer" ? "Offer" : "Rejected", at: row.decided_at, done: true });
  } else if (row.sent_at) {
    entries.push({ label: "Outcome", at: null, done: false });
  }

  for (const entry of entries) {
    const li = document.createElement("li");
    li.className = entry.done ? "done" : "pending";
    const text = entry.at ? `${entry.label} — ${new Date(entry.at).toLocaleDateString()}` : entry.label;
    li.textContent = text;
    list.appendChild(li);
  }
  return list;
}

async function advanceRowLifecycle(id, event) {
  const res = await fetch(`/api/queue/${id}/advance`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Could not record that update");
    return;
  }
  loadQueue();
}

async function patchRow(id, fields) {
  await fetch(`/api/queue/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  loadQueue();
}

async function scrapeRow(id) {
  const res = await fetch(`/api/queue/${id}/scrape`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Scrape failed");
    return;
  }
  if (data.candidates.length === 0) {
    alert("No candidate emails found on the company site.");
  } else {
    alert(`Found: ${data.candidates.join(", ")}\nFilled in the first result — review before sending.`);
  }
  loadQueue();
}

async function loadSentHistory(id) {
  const res = await fetch(`/api/queue/${id}/sent-records`);
  const records = await res.json();
  sentHistoryList.innerHTML = "";
  if (!res.ok || records.length === 0) {
    sentHistoryList.innerHTML = "<li>Nothing sent for this candidate yet.</li>";
    return;
  }
  for (const rec of records) {
    const li = document.createElement("li");
    const when = new Date(rec.sent_at).toLocaleString();
    li.innerHTML = `<strong>${when}</strong><br>${escapeHtml(rec.subject)}`;
    li.title = rec.body;
    sentHistoryList.appendChild(li);
  }
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s || "";
  return div.innerHTML;
}

async function previewRow(id, template) {
  currentPreview = { id, template };
  previewStatus.textContent = "";
  previewModal.classList.remove("hidden");
  loadSentHistory(id);

  const finalRes = await fetch(`/api/queue/${id}/final`);
  const finalData = await finalRes.json();
  if (finalData.body) {
    previewSubjectInput.value = finalData.subject || "";
    previewBodyInput.value = finalData.body;
    previewStatus.textContent = "Showing your previously finalized version.";
    return;
  }

  await renderFromTemplate(id, template);
}

async function renderFromTemplate(id, template) {
  const res = await fetch(`/api/queue/${id}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Preview failed");
    return;
  }
  previewSubjectInput.value = data.subject;
  previewBodyInput.value = data.body;
  previewStatus.textContent = "";
}

async function finalizeCurrentPreview() {
  if (!currentPreview.id) return;
  const res = await fetch(`/api/queue/${currentPreview.id}/finalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      subject: previewSubjectInput.value,
      body: previewBodyInput.value,
    }),
  });
  if (!res.ok) {
    const data = await res.json();
    alert(data.detail || "Finalize failed");
    return;
  }
  previewStatus.textContent = "Finalized — this exact text will be used when you Approve & Send.";
}

async function sendRow(id) {
  if (!confirm("Send this email now? This action is final.")) return;
  const res = await fetch(`/api/queue/${id}/send`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Send failed");
    loadQueue();
    return;
  }
  loadQueue();
}

async function skipRow(id) {
  if (!confirm("Skip this candidate?")) return;
  await fetch(`/api/queue/${id}/skip`, { method: "POST" });
  loadQueue();
}

refreshBtn.addEventListener("click", () => {
  loadQueue();
  loadDigests();
  loadSchedulerStatus();
});

archiveToggleBtn.addEventListener("click", () => {
  showingArchive = !showingArchive;
  archiveToggleBtn.textContent = showingArchive ? "Show actionable" : "Show archived";
  loadQueue();
});

signoutBtn.addEventListener("click", async () => {
  await fetch("/auth/logout", { method: "POST" });
  window.location.reload();
});

const generateTokenBtn = document.getElementById("generate-token-btn");
const tokenDisplay = document.getElementById("token-display");
const tokenValueInput = document.getElementById("token-value");
const copyTokenBtn = document.getElementById("copy-token-btn");

generateTokenBtn.addEventListener("click", async () => {
  if (
    tokenDisplay.classList.contains("hidden") ||
    confirm("Regenerating replaces your current token - the old one stops working immediately. Continue?")
  ) {
    const res = await fetch("/api/settings/api-token", { method: "POST" });
    const data = await res.json();
    tokenValueInput.value = data.token;
    tokenDisplay.classList.remove("hidden");
  }
});

copyTokenBtn.addEventListener("click", async () => {
  await navigator.clipboard.writeText(tokenValueInput.value);
  copyTokenBtn.textContent = "Copied!";
  setTimeout(() => (copyTokenBtn.textContent = "Copy"), 1500);
});

async function checkAuthAndInit() {
  const res = await fetch("/api/me");
  if (res.status === 401) {
    signinScreen.classList.remove("hidden");
    appShell.classList.add("hidden");
    return;
  }
  const me = await res.json();
  accountChip.textContent = `Signed in as ${me.email}`;
  signinScreen.classList.add("hidden");
  appShell.classList.remove("hidden");

  loadResume();
  loadQueue();
  loadDigests();
  loadSchedulerStatus();
}

checkAuthAndInit();
