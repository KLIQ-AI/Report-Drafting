"""Where qualified leads go: any webhook (Clay, n8n, Make, Zapier, HeyReach, your CRM) and Slack."""

import httpx

LEAD_FIELDS = ["id", "name", "headline", "title", "company", "company_domain", "company_size",
               "industry", "location", "seniority", "profile_url", "email", "email_status",
               "icp_fit", "intent_score", "sentiment", "buying_stage", "intent_reason",
               "suggested_opener", "status", "first_seen", "last_seen"]


def lead_payload(lead: dict, signals: list[dict]) -> dict:
    return {
        "event": "lead.qualified",
        "lead": {k: lead.get(k) for k in LEAD_FIELDS},
        "signals": [
            {"kind": s["kind"], "reaction_type": s.get("reaction_type"),
             "comment_text": s.get("comment_text"), "post_url": s.get("post_url"),
             "post_text": (s.get("post_text") or "")[:500], "monitor": s.get("monitor_name")}
            for s in signals
        ],
    }


def slack_payload(lead: dict, signals: list[dict]) -> dict:
    top = next((s for s in signals if s["kind"] == "comment"), signals[0] if signals else None)
    activity = ""
    if top:
        activity = (f"💬 _\"{top['comment_text'][:200]}\"_" if top["kind"] == "comment"
                    else f"👍 Reacted to a post from *{top.get('monitor_name', 'a monitor')}*")
        if top.get("post_url"):
            activity += f" · <{top['post_url']}|view post>"
    text = (f"🎯 *<{lead['profile_url']}|{lead['name']}>* · {lead.get('headline', '')}\n"
            f"Intent *{lead['intent_score']}* · ICP fit *{lead['icp_fit']}* · {lead.get('buying_stage', '')}\n"
            f"{lead.get('intent_reason', '')}\n{activity}")
    return {"text": text}


def post_json(url: str, payload: dict, client: httpx.Client | None = None) -> tuple[bool, str]:
    try:
        c = client or httpx.Client(timeout=15)
        r = c.post(url, json=payload)
        return r.is_success, f"HTTP {r.status_code}"
    except httpx.HTTPError as exc:
        return False, str(exc)
