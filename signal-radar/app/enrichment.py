"""Contact enrichment. Swap MockEnricher for a vendor (Lusha, Apollo, Hunter...)
by implementing `enrich(lead) -> dict` with keys email / email_status."""

import re
import unicodedata
from typing import Protocol


class Enricher(Protocol):
    name: str

    def enrich(self, lead: dict) -> dict: ...


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


class MockEnricher:
    """Guesses first.last@domain. Marked 'guessed' so nobody mistakes it for verified."""

    name = "mock"

    def enrich(self, lead: dict) -> dict:
        domain = lead.get("company_domain")
        parts = [re.sub(r"[^a-z]", "", p) for p in _ascii(lead.get("name", "")).split()]
        parts = [p for p in parts if p]
        if not domain or len(parts) < 2:
            return {"email": "", "email_status": "not_found"}
        return {"email": f"{parts[0]}.{parts[-1]}@{domain}", "email_status": "guessed"}


class NoEnricher:
    name = "none"

    def enrich(self, lead: dict) -> dict:
        return {}


def get_enricher(name: str) -> Enricher:
    return MockEnricher() if name == "mock" else NoEnricher()
