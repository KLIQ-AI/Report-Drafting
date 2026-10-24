# Signal Radar Capture (Chrome extension)

Sends the LinkedIn page you are looking at to your Signal Radar workspace:

- **Who viewed your profile** (`linkedin.com/analytics/profile-views/`): every viewer on screen, both named people and anonymous ones ("Someone at Unilever").
- **A person's profile** (`linkedin.com/in/...`): adds that person as a lead.

Signal Radar then matches each person with your existing leads, scores them against your ICP, and queues deep screening. Anonymous viewers are kept as company-level signals.

## How it behaves (and why)

- **Nothing runs until you click the icon.** The extension uses Chrome's `activeTab` permission, so it can only read a LinkedIn tab at the moment you click it. It has no permanent access to linkedin.com and injects nothing into LinkedIn pages on its own.
- **It reads only what's already on your screen.** No page visits, scrolling, clicking or requests to LinkedIn on your behalf. To send more viewers, scroll down first so LinkedIn loads them.
- **The data goes only to your own Signal Radar app**, authenticated with a token you create there.

## Install (about 2 minutes)

1. Download this folder (`signal-radar-extension/`) from the repo, or clone the repo.
2. In Chrome, open `chrome://extensions`, switch on **Developer mode** (top right), click **Load unpacked**, and select the `signal-radar-extension` folder.
3. Pin the extension (puzzle icon → pin "Signal Radar Capture").
4. In Signal Radar, go to **Settings → Chrome extension → Generate token** and copy the token. It's shown only once.
5. Right-click the extension icon → **Options**. Enter your app URL (default `https://kliq-signal-radar.lovable.app`) and paste the token, then Save.

## Use

1. On LinkedIn, open **Who viewed your profile** (or any person's profile).
2. Scroll down to load the viewers you want to send.
3. Click the extension icon, check the preview, and click **Send**.

## Develop

```bash
npm install
npm test   # parser tests against simulated LinkedIn markup (jsdom)
```

`collect.js` holds the page reader. It must stay self-contained: Chrome serializes the function when injecting it, and a test checks this. LinkedIn changes its markup often. If names stop being parsed, the app still receives the page text (`page_text`) and extracts viewers from it server-side, so captures keep working while you update the selectors.
