# Signal Radar Autopilot (Mac mini + Claude Cowork)

A Cowork agent on your Mac mini browses **your own** LinkedIn 2–3 times per working day, at human volume. It:

- registers your own signals in Signal Radar: comments and reactions on your posts, profile viewers, accepted invitations, replies, mentions;
- sends the outreach that Signal Radar has drafted and scheduled.

Signal Radar is the system of record and the rulebook: caps, working hours, who gets contacted, wording, sequencing, stop-on-reply and pause. The agent only follows instructions.

| File | What it is |
|---|---|
| `sr.py` | Command-line helper the agent uses to talk to Signal Radar. Python standard library only. |
| `PLAYBOOK.md` | Step-by-step procedure the agent follows each session. |
| `COWORK_TASK.md` | Schedule and prompt for the Cowork scheduled task. |

## One-time setup (about 10 minutes)

1. **Copy this folder to the Mac mini** as `~/signal-radar-agent/`. Check Python works:
   ```bash
   python3 ~/signal-radar-agent/sr.py --help
   ```
2. **Create an agent token.** In Signal Radar, open **Settings → Chrome extension → Generate token**, choose scope **Cowork agent**, and copy the token.
3. **Store the token on the Mac mini.** It's never put in the agent's prompt:
   ```bash
   mkdir -p ~/.signal-radar && chmod 700 ~/.signal-radar
   cat > ~/.signal-radar/agent.json <<'EOF'
   { "app_url": "https://kliq-signal-radar.lovable.app", "token": "PASTE_TOKEN_HERE" }
   EOF
   chmod 600 ~/.signal-radar/agent.json
   python3 ~/signal-radar-agent/sr.py config   # should print your autopilot settings
   ```
4. **Set up Chrome on the Mac mini.** Sign in to LinkedIn, install and connect **Claude in Chrome**, and keep Chrome open. Set the Mac mini never to sleep: *System Settings → Energy → Prevent automatic sleeping*.
5. **Configure Autopilot in Signal Radar.** Under **Settings → Autopilot**, set your name and role (used in messages), check the caps, then turn **Enable autopilot** on. Start with **mode: approve** for the first few days to check the drafts, then switch to **auto**.
6. **Create the scheduled task in Cowork** using `COWORK_TASK.md`.

## Safety switches

- **Pause all** (Settings → Autopilot) stops outreach immediately. The agent checks it at the start of every session, and `outreach/next` returns nothing while paused.
- **Automatic pause:** any LinkedIn warning, or 3 failed actions in a row, pauses autopilot and posts to Slack.
- **Caps are enforced by Signal Radar, not by the agent.** Defaults: 10 connection requests a day / 60 a week, and 15 messages a day.
- **Stop outreach to one person:** use **Stop outreach** on the lead, or **Do not contact**.
- **When someone replies,** all automation for them stops, and you get a Slack message.

## Be aware

Automating your own LinkedIn account goes against LinkedIn's user agreement, even at human volume. The setup keeps volume low and stops on the first warning, but the risk to the account isn't zero. Keep the caps conservative.
