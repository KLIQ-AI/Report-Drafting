"use strict";

const appUrl = document.getElementById("appUrl");
const token = document.getElementById("token");
const saved = document.getElementById("saved");

chrome.storage.local.get(["appUrl", "token"]).then((s) => {
  appUrl.value = s.appUrl || "https://kliq-signal-radar.lovable.app";
  token.value = s.token || "";
});

document.getElementById("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = new URL(appUrl.value.trim());
  if (url.protocol !== "https:") {
    saved.textContent = "The URL must start with https://";
    return;
  }
  // *.lovable.app is allowed by the manifest; any other domain needs a one-time permission.
  if (!/\.lovable\.app$/i.test(url.hostname)) {
    const granted = await chrome.permissions.request({ origins: [`${url.origin}/*`] });
    if (!granted) {
      saved.textContent = "Permission to contact that domain was refused.";
      return;
    }
  }
  await chrome.storage.local.set({ appUrl: url.origin, token: token.value.trim() });
  saved.textContent = "Saved.";
});
