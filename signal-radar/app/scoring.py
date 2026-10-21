"""Intent scoring: how likely is this person to be in-market right now?

Uses Claude when ANTHROPIC_API_KEY is set; otherwise (or on any API failure)
falls back to a transparent keyword heuristic so the pipeline never stalls.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

HIGH_INTENT = [
    r"looking for", r"recommend", r"alternative", r"any(one)? (use|using|tried)", r"pricing",
    r"how much", r"demo", r"\bdm\b", r"evaluat", r"switch(ed|ing)? (from|away)", r"vendor",
    r"integrat", r"in-house", r"struggl", r"need (a|an|to)", r"budget", r"rfp",
]
NEGATIVE = [r"\bhate\b", r"terrible", r"scam", r"waste", r"awful"]
POSITIVE = [r"great", r"love", r"agree", r"congrats", r"spot on", r"thanks", r"👏", r"🔥"]


class IntentAssessment(BaseModel):
    intent_score: int = Field(ge=0, le=100, description="0 = no buying intent, 100 = actively buying")
    sentiment: Literal["positive", "neutral", "negative"]
    buying_stage: Literal["unaware", "problem_aware", "solution_aware", "evaluating", "ready_to_buy"]
    reason: str = Field(description="One sentence citing the evidence")
    suggested_opener: str = Field(description="A short, specific first message referencing their activity")


def _hits(patterns: list[str], text: str) -> int:
    return sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))


def _recency_factor(iso: str | None) -> float:
    if not iso:
        return 1.0
    try:
        age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).days
    except ValueError:
        return 1.0
    return 1.0 if age_days <= 3 else 0.85 if age_days <= 14 else 0.6


def heuristic_score(lead: dict, signals: list[dict]) -> IntentAssessment:
    # Engagement volume can only lift a lead so far; what they actually say drives the score.
    comments = [s["comment_text"] for s in signals if s["kind"] == "comment" and s["comment_text"]]
    volume = sum((12 if s["kind"] == "comment" else 5) * _recency_factor(s.get("created_at"))
                 for s in signals)
    competitor = 8 if any(s.get("is_competitor") for s in signals) else 0
    joined = " ".join(comments)
    intent_hits = _hits(HIGH_INTENT, joined)
    score = min(100, round(min(volume, 30) + competitor + min(intent_hits * 22, 62)))

    neg, pos = _hits(NEGATIVE, joined), _hits(POSITIVE, joined)
    sentiment = "negative" if neg > pos else "positive" if pos > 0 else "neutral"
    stage = ("evaluating" if intent_hits >= 2 else "solution_aware" if intent_hits == 1
             else "problem_aware" if comments else "unaware")

    first_name = (lead.get("name") or "there").split()[0]
    if comments:
        reason = f"Commented: \"{comments[0][:120]}\""
        opener = (f"Hi {first_name}, saw your comment on that post about this. "
                  "Happy to share what's working for teams like yours. Worth a quick chat?")
    else:
        kinds = {s.get("reaction_type") or "reaction" for s in signals}
        reason = f"Reacted ({', '.join(sorted(kinds))}) to {len(signals)} relevant post(s)"
        opener = (f"Hi {first_name}, noticed you've been following the conversation on this topic. "
                  "Curious how your team is handling it today?")
    return IntentAssessment(intent_score=score, sentiment=sentiment, buying_stage=stage,
                            reason=reason, suggested_opener=opener)


SYSTEM_PROMPT = """You qualify B2B sales leads from public LinkedIn engagement.
You get one person, our offer, and the posts they engaged with (reaction or comment).
Judge how likely they are to be in-market for the offer right now.

Calibration:
- A lone like on a generic post is weak (10-30).
- A comment asking for tools, pricing, alternatives, or describing the exact pain is strong (60-90).
- Engaging with a competitor's post about their product is a meaningful signal.
- Repeated engagement across several relevant posts raises intent.
- Be skeptical: congratulations and generic praise are not buying intent.

The suggested opener must reference their actual activity, be under 45 words,
sound human, and never claim we saw anything private."""


class Scorer:
    def __init__(self, api_key: str, model: str):
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else None

    @property
    def mode(self) -> str:
        return "claude" if self.client else "heuristic"

    def score(self, lead: dict, signals: list[dict], offer: dict) -> tuple[IntentAssessment, str]:
        if self.client is None:
            return heuristic_score(lead, signals), "heuristic"
        try:
            return self._score_with_claude(lead, signals, offer), "claude"
        except Exception as exc:  # scoring must never break ingestion
            log.warning("Claude scoring failed for %s, using heuristic: %s", lead.get("name"), exc)
            return heuristic_score(lead, signals), "heuristic"

    def _score_with_claude(self, lead: dict, signals: list[dict], offer: dict) -> IntentAssessment:
        lines = []
        for s in signals[:10]:
            source = "competitor post" if s.get("is_competitor") else f"{s.get('monitor_kind', '')} monitor"
            action = f"commented: \"{s['comment_text']}\"" if s["kind"] == "comment" else \
                f"reacted ({s.get('reaction_type') or 'like'})"
            lines.append(f"- [{source}] Post by {s.get('author_name') or 'unknown'}: "
                         f"\"{(s.get('post_text') or '')[:400]}\"\n  They {action}")
        prompt = (
            f"OUR OFFER\nProduct: {offer.get('product') or 'not specified'}\n"
            f"Value prop: {offer.get('value_prop') or 'not specified'}\n"
            f"Competitors: {', '.join(offer.get('competitors') or []) or 'not specified'}\n\n"
            f"PERSON\nName: {lead.get('name')}\nHeadline: {lead.get('headline')}\n"
            f"Company: {lead.get('company')} ({lead.get('company_size') or '?'} employees, "
            f"{lead.get('industry') or 'unknown industry'})\nLocation: {lead.get('location')}\n\n"
            f"ENGAGEMENT\n" + "\n".join(lines)
        )
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=2048,
            output_config={"effort": "low"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_format=IntentAssessment,
        )
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise RuntimeError(f"no structured output (stop_reason={response.stop_reason})")
        return response.parsed_output
