"""ICP fit scoring: how closely does this person match who we sell to?"""

import re

SENIORITY_RULES = [
    ("c_level", r"\b(ceo|cto|cfo|coo|cmo|cro|cpo|chief|founder|co-founder|owner|president)\b"),
    ("vp", r"\b(vp|vice president|svp|evp)\b"),
    ("director", r"\b(director|head of)\b"),
    ("manager", r"\b(manager|lead|principal)\b"),
    ("entry", r"\b(intern|student|trainee|junior|assistant)\b"),
]
SENIORITY_LABELS = {
    "c_level": "C-level / Founder", "vp": "VP", "director": "Director / Head",
    "manager": "Manager / Lead", "ic": "Individual contributor", "entry": "Entry level",
}

WEIGHTS = {"title": 35, "seniority": 20, "company_size": 20, "industry": 15, "location": 10}


def infer_seniority(title: str) -> str:
    t = title.lower()
    for level, pattern in SENIORITY_RULES:
        if re.search(pattern, t):
            return level
    return "ic" if t else ""


def _contains_any(text: str, needles: list[str]) -> bool:
    text = text.lower()
    return any(n.strip().lower() in text for n in needles if n.strip())


def icp_fit(lead: dict, icp: dict) -> tuple[int, list[str]]:
    """Returns (score 0-100, reasons). Criteria left empty count as a match."""
    title = f"{lead.get('title', '')} {lead.get('headline', '')}"
    if _contains_any(title, icp.get("titles_exclude") or []):
        return 0, ["Title matches an excluded keyword"]

    score, reasons = 0, []

    titles = icp.get("titles_include") or []
    if not titles or _contains_any(title, titles):
        score += WEIGHTS["title"]
        if titles:
            reasons.append("Title matches ICP")

    seniorities = icp.get("seniorities") or []
    if not seniorities or lead.get("seniority") in seniorities:
        score += WEIGHTS["seniority"]
        if seniorities:
            reasons.append(f"Seniority: {SENIORITY_LABELS.get(lead.get('seniority'), 'unknown')}")

    size = lead.get("company_size")
    lo, hi = icp.get("company_size_min"), icp.get("company_size_max")
    if lo is None and hi is None:
        score += WEIGHTS["company_size"]
    elif size is not None and (lo is None or size >= lo) and (hi is None or size <= hi):
        score += WEIGHTS["company_size"]
        reasons.append(f"Company size {size} in range")

    industries = icp.get("industries") or []
    if not industries or _contains_any(lead.get("industry", ""), industries):
        score += WEIGHTS["industry"]
        if industries:
            reasons.append(f"Industry: {lead.get('industry')}")

    locations = icp.get("locations") or []
    if not locations or _contains_any(lead.get("location", ""), locations):
        score += WEIGHTS["location"]
        if locations:
            reasons.append(f"Location: {lead.get('location')}")

    return score, reasons
