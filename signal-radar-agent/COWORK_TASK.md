# Cowork scheduled task: Signal Radar Autopilot

Create one scheduled task in Claude Cowork on the Mac mini and paste the prompt below.

**Schedule:** weekdays, 3 times a day at irregular minutes, for example **09:37, 13:12 and 16:48** (Europe/Madrid). Signal Radar also refuses outreach outside the working hours set in Settings → Autopilot, so a mis-timed run does nothing.

**Before the first run:** follow `README.md` in this folder (install the helper, save the token, connect Claude in Chrome, sign in to LinkedIn in that Chrome).

---

## Prompt to paste

```
Run one Signal Radar Autopilot session.

Follow the playbook at ~/signal-radar-agent/PLAYBOOK.md exactly. Read it fully before doing anything.
Use my own Chrome (Claude in Chrome), where I'm signed in to LinkedIn. Talk to Signal Radar only through:
  python3 ~/signal-radar-agent/sr.py <command>

Non-negotiable:
- Start with `sr.py config`. If it says not allowed or paused, end the session and stop.
- Stay within max_page_views_per_session and wait between actions as the playbook says.
- Contact only the people `sr.py next` returns, with exactly the text it returns.
- Never like, comment, accept or withdraw invitations, post, or change settings.
- On any LinkedIn warning, captcha, limit notice or login prompt: report it with
  `sr.py session end --warning "<exact text>"` and stop immediately.

End with a short summary: signals found, actions sent or skipped, replies, warnings.
```
