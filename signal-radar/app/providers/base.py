"""Provider interface for LinkedIn data.

Signal Radar never logs into LinkedIn itself. A provider wraps a data source
(a demo generator, Apify actors, or any vendor API) and returns normalized
posts and engagers.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Person:
    profile_url: str
    name: str
    headline: str = ""
    title: str = ""
    company: str = ""
    company_domain: str = ""
    company_size: int | None = None
    industry: str = ""
    location: str = ""


@dataclass
class Engagement:
    person: Person
    kind: str  # "reaction" | "comment"
    reaction_type: str = ""
    comment_text: str = ""


@dataclass
class Post:
    external_id: str
    url: str
    text: str
    author_name: str = ""
    author_headline: str = ""
    author_url: str = ""
    posted_at: str | None = None
    reaction_count: int = 0
    comment_count: int = 0
    engagements: list[Engagement] = field(default_factory=list)


class LinkedInProvider(Protocol):
    name: str

    def search_posts(self, keywords: list[str], limit: int = 20) -> list[Post]:
        """Recent public posts that mention any of the keywords."""

    def profile_posts(self, url: str, limit: int = 10) -> list[Post]:
        """Recent posts by a person or company page."""

    def engagements(self, post: Post, limit: int = 100) -> list[Engagement]:
        """People who reacted to or commented on a post."""
