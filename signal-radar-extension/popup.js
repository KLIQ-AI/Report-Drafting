"use strict";

const $ = (id) => document.getElementById(id);
const VERSION = chrome.runtime.getManifest().version;

function show(id, on = true) { $(id).hidden = !on; }
function setStatus(text) { $("status").textContent = text; }

async function getSettings() {
  const { appUrl = "", token = "" } = await chrome.storage.local.get(["appUrl", "token"]);
  return { appUrl: appUrl.replace(/\/+$/, ""), token };
}

function renderPreview(items) {
  const ul = $("preview");
  ul.replaceChildren(...items.slice(0, 6).map((it) => {
    const li = document.createElement("li");
    const b = document.createElement("b");
    b.textContent = it.anonymous ? "Anonymous viewer" : it.name || "(no name)";
    const span = document.createElement("span");
    span.textContent = it.anonymous ? it.anonymous_hint || "" : it.headline || "";
    li.append(b, span);
    return li;
  }));
  if (items.length > 6) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = `+ ${items.length - 6} more`;
    ul.append(li);
  }
  show("preview", items.length > 0);
}

async function main() {
  $("open-options").addEventListener("click", (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); });

  const settings = await getSettings();
  if (!settings.appUrl || !settings.token) {
    setStatus("Connect the extension to your Signal Radar workspace first.");
    $("send").textContent = "Open settings";
    $("send").onclick = () => chrome.runtime.openOptionsPage();
    show("send");
    return;
  }

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/^https:\/\/([a-z]+\.)?linkedin\.com\//i.test(tab.url || "")) {
    setStatus("Open your LinkedIn profile viewers page, or a person's profile, then click again.");
    return;
  }

  let capture;
  try {
    const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: collectLinkedInPage });
    capture = result;
  } catch (err) {
    setStatus(`Couldn't read this page: ${err.message}`);
    return;
  }

  if (!capture || capture.type === "unsupported") {
    setStatus("This page isn't supported. Use “Who viewed your profile” or a person's profile page.");
    return;
  }

  const people = capture.items.filter((i) => !i.anonymous).length;
  const anon = capture.items.length - people;
  if (capture.type === "profile_views") {
    setStatus(`Profile viewers on screen: ${people} people, ${anon} anonymous.`);
    $("hint").textContent = "Only what's loaded on screen is sent. Scroll down first to load more viewers.";
    show("hint");
    $("send").textContent = `Send ${capture.items.length || ""} viewers`.replace("  ", " ");
  } else {
    setStatus("Profile on screen:");
    $("send").textContent = "Add to Signal Radar";
  }
  renderPreview(capture.items);
  if (!capture.items.length && !capture.page_text) {
    setStatus("Nothing to send: no viewers found on screen.");
    return;
  }
  show("send");

  $("send").onclick = async () => {
    $("send").disabled = true;
    $("send").textContent = "Sending…";
    try {
      const res = await fetch(`${settings.appUrl}/api/public/ingest/linkedin`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${settings.token}` },
        body: JSON.stringify({ ...capture, captured_at: new Date().toISOString(), extension_version: VERSION }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || body.ok === false) throw new Error(body.error || `HTTP ${res.status}`);
      $("result").textContent = capture.type === "profile"
        ? (body.new_leads ? "Added as a new lead." : "Updated the existing lead.")
        : `Sent ${body.received ?? capture.items.length}: ${body.new_leads ?? 0} new leads, ${body.matched_existing ?? 0} already known, ${body.anonymous ?? anon} anonymous.`;
      $("result").className = "result ok";
      show("send", false);
    } catch (err) {
      $("result").textContent = `Failed: ${err.message}`;
      $("result").className = "result err";
      $("send").disabled = false;
      $("send").textContent = "Try again";
    }
    show("result");
  };
}

main();
