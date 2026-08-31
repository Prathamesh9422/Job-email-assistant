const baseUrlInput = document.getElementById("base-url");
const tokenInput = document.getElementById("api-token");
const statusEl = document.getElementById("status");

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = kind || "";
}

function normalizeBaseUrl(url) {
  return url.trim().replace(/\/+$/, "");
}

async function load() {
  const { apiBaseUrl, apiToken } = await chrome.storage.local.get(["apiBaseUrl", "apiToken"]);
  if (apiBaseUrl) baseUrlInput.value = apiBaseUrl;
  if (apiToken) tokenInput.value = apiToken;
}

document.getElementById("save-btn").addEventListener("click", async () => {
  const baseUrl = normalizeBaseUrl(baseUrlInput.value);
  const token = tokenInput.value.trim();

  if (!baseUrl || !/^https?:\/\/.+/.test(baseUrl)) {
    setStatus("Enter a valid http(s) base URL.", "error");
    return;
  }
  if (!token) {
    setStatus("Paste your API token.", "error");
    return;
  }

  // MV3 extensions must hold host permission for any origin they fetch() -
  // the base URL is user-supplied (dev vs. production), so it's requested
  // here at save time rather than pre-declared in the manifest.
  const granted = await chrome.permissions.request({ origins: [`${baseUrl}/*`] });
  if (!granted) {
    setStatus("Permission for that URL was denied - the extension can't sync without it.", "error");
    return;
  }

  await chrome.storage.local.set({ apiBaseUrl: baseUrl, apiToken: token });
  setStatus("Saved.", "success");
});

load();
