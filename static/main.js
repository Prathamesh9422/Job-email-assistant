const tbody = document.getElementById("queue-body");
const digestBody = document.getElementById("digest-body");
const resumeIndicator = document.getElementById("resume-indicator");
const refreshBtn = document.getElementById("refresh-btn");
const previewModal = document.getElementById("preview-modal");
const previewSubject = document.getElementById("preview-subject");
const previewBody = document.getElementById("preview-body");
document.getElementById("preview-close").addEventListener("click", () => {
  previewModal.classList.add("hidden");
});

async function loadResume() {
  const res = await fetch("/api/resume");
  const data = await res.json();
  resumeIndicator.textContent = data.resume_filename
    ? `Resume: ${data.resume_filename}`
    : "Resume: none found in resumes/";
}

async function loadQueue() {
  const res = await fetch("/api/queue?status=needs_info,ready,failed");
  const rows = await res.json();
  renderRows(rows);
}

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
    tdSubject.textContent = row.subject || "(no subject)";

    const tdReceived = document.createElement("td");
    tdReceived.textContent = row.received_at ? new Date(row.received_at).toLocaleString() : "";

    const tdLinks = document.createElement("td");
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
    tbody.innerHTML = `<tr><td colspan="7">No candidates right now.</td></tr>`;
    return;
  }
  for (const row of rows) {
    tbody.appendChild(renderRow(row));
  }
}

function renderRow(row) {
  const tr = document.createElement("tr");
  tr.dataset.id = row.id;

  const tdCompany = document.createElement("td");
  tdCompany.textContent = row.company || "(unknown)";

  const tdRole = document.createElement("td");
  tdRole.textContent = row.role || "(unknown)";

  const tdHr = document.createElement("td");
  const hrInput = document.createElement("input");
  hrInput.type = "text";
  hrInput.value = row.hr_email || "";
  hrInput.placeholder = "hr@company.com";
  hrInput.addEventListener("change", () => patchRow(row.id, { hr_email: hrInput.value }));
  tdHr.appendChild(hrInput);

  const tdSource = document.createElement("td");
  tdSource.textContent = `${row.hr_email_source} / ${row.hr_email_confidence}`;

  const tdTemplate = document.createElement("td");
  const select = document.createElement("select");
  for (const [value, label] of [
    ["reply_to_naukri", "Reply to Naukri"],
    ["cold_outreach", "Cold outreach"],
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
  const pill = document.createElement("span");
  pill.className = `status-pill status-${row.status}`;
  pill.textContent = row.status;
  tdStatus.appendChild(pill);
  if (row.error_message) {
    const err = document.createElement("div");
    err.style.color = "#a02622";
    err.style.fontSize = "0.75rem";
    err.textContent = row.error_message;
    tdStatus.appendChild(err);
  }

  const tdActions = document.createElement("td");
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

  tr.append(tdCompany, tdRole, tdHr, tdSource, tdTemplate, tdStatus, tdActions);
  return tr;
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

async function previewRow(id, template) {
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
  previewSubject.textContent = data.subject;
  previewBody.textContent = data.body;
  previewModal.classList.remove("hidden");
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
});

loadResume();
loadQueue();
loadDigests();
