"""Deterministic demo data so the whole product works without any API keys."""

import hashlib
import random
from datetime import datetime, timedelta, timezone

from .base import Engagement, Person, Post

FIRST = ["Sofia", "Liam", "Amara", "Noah", "Elena", "Marcus", "Priya", "Lucas", "Hana", "Diego",
         "Chloe", "Omar", "Ines", "Tom", "Yuki", "Jonas", "Maya", "Rafael", "Zoe", "Arjun",
         "Clara", "Mateo", "Leah", "Felix", "Nadia", "Hugo", "Aisha", "Pablo", "Emma", "Karim"]
LAST = ["Martin", "Garcia", "Okafor", "Schmidt", "Rossi", "Dubois", "Patel", "Kim", "Nguyen",
        "Silva", "Novak", "Haddad", "Fischer", "Lopez", "Tanaka", "Berg", "Moreau", "Costa"]
COMPANIES = [
    ("Northwind Analytics", "northwind.io", 120, "Software", "Berlin, Germany"),
    ("Brightpath Logistics", "brightpath.com", 850, "Logistics", "Rotterdam, Netherlands"),
    ("Helio Health", "heliohealth.co", 45, "Healthcare", "Boston, United States"),
    ("Quanta Retail", "quantaretail.com", 2300, "Retail", "Madrid, Spain"),
    ("Stackforge", "stackforge.dev", 30, "Software", "London, United Kingdom"),
    ("Verda Energy", "verda.energy", 400, "Energy", "Lisbon, Portugal"),
    ("Lumen Fintech", "lumenpay.com", 210, "Financial Services", "Paris, France"),
    ("Orbit HR", "orbithr.com", 75, "Software", "Austin, United States"),
    ("Cobalt Manufacturing", "cobaltmfg.com", 5200, "Manufacturing", "Munich, Germany"),
    ("Pinecrest Agency", "pinecrest.agency", 12, "Marketing", "Barcelona, Spain"),
    ("Atlas Cloud", "atlascloud.io", 640, "Software", "Dublin, Ireland"),
    ("Mosaic Education", "mosaic.edu", 90, "Education", "Toronto, Canada"),
]
TITLES = ["CEO & Co-founder", "Founder", "VP of Sales", "Head of Growth", "Director of Marketing",
          "Revenue Operations Manager", "Sales Development Representative", "Account Executive",
          "CTO", "Head of Partnerships", "Marketing Manager", "Chief Revenue Officer",
          "Business Development Manager", "Product Manager", "Software Engineer",
          "Talent Acquisition Recruiter", "Growth Marketing Intern", "COO"]
REACTIONS = ["like", "like", "like", "celebrate", "insightful", "support", "love"]
COMMENTS = [
    "Great points, thanks for sharing!",
    "We're actually looking for a tool that does exactly this. What do you use?",
    "Anyone have recommendations for {kw}? Evaluating options this quarter.",
    "How does pricing work for this? Our team is around 20 people.",
    "We switched away from our current vendor last month, the onboarding was painful.",
    "Totally agree, this is underrated.",
    "Interesting, would love a demo. DM me.",
    "This is spot on 👏",
    "We tried building this in-house and it was a nightmare. Curious about alternatives.",
    "Congrats on the launch!",
    "Is there an integration with HubSpot?",
    "Saving this for later.",
]
POST_TEMPLATES = [
    "Hot take: most teams are doing {kw} completely wrong. Here's what we learned after 2 years...",
    "We just hit a milestone thanks to {kw}. Thread on what worked and what didn't 🧵",
    "Is anyone else struggling with {kw}? We've tried three tools and none of them stuck.",
    "5 lessons on {kw} from scaling our team from 5 to 50 people.",
    "Excited to announce our new approach to {kw}. Would love feedback from the community!",
]


def _rng(*parts: str) -> random.Random:
    seed = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return random.Random(int(seed[:16], 16))


def _people() -> list[Person]:
    rng = _rng("people")
    people = []
    for i in range(400):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        company, domain, size, industry, location = rng.choice(COMPANIES)
        title = rng.choice(TITLES)
        slug = f"{first}-{last}-{i}".lower()
        people.append(Person(
            profile_url=f"https://www.linkedin.com/in/{slug}",
            name=f"{first} {last}",
            headline=f"{title} at {company}",
            title=title,
            company=company,
            company_domain=domain,
            company_size=size,
            industry=industry,
            location=location,
        ))
    return people


PEOPLE = _people()


class MockProvider:
    name = "mock"

    def _make_posts(self, seed: str, topic: str, limit: int) -> list[Post]:
        # Seed by day so repeated runs on the same day are idempotent,
        # while a new day brings fresh posts.
        day = datetime.now(timezone.utc).date().isoformat()
        rng = _rng(seed, day)
        posts = []
        for i in range(min(limit, rng.randint(3, 6))):
            author = rng.choice(PEOPLE)
            ext = hashlib.md5(f"{seed}{day}{i}".encode()).hexdigest()[:12]
            posted = datetime.now(timezone.utc) - timedelta(hours=rng.randint(1, 72))
            posts.append(Post(
                external_id=ext,
                url=f"https://www.linkedin.com/feed/update/urn:li:activity:{int(ext, 16)}",
                text=rng.choice(POST_TEMPLATES).format(kw=topic),
                author_name=author.name,
                author_headline=author.headline,
                author_url=author.profile_url,
                posted_at=posted.replace(microsecond=0).isoformat(),
                reaction_count=rng.randint(15, 400),
                comment_count=rng.randint(2, 60),
            ))
        return posts

    def search_posts(self, keywords: list[str], limit: int = 20) -> list[Post]:
        posts: list[Post] = []
        for kw in keywords:
            posts.extend(self._make_posts(f"kw:{kw.lower()}", kw, limit))
        return posts[:limit]

    def profile_posts(self, url: str, limit: int = 10) -> list[Post]:
        topic = url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ") or "our product"
        return self._make_posts(f"profile:{url}", topic, limit)

    def engagements(self, post: Post, limit: int = 100) -> list[Engagement]:
        rng = _rng("eng", post.external_id)
        crowd = rng.sample(PEOPLE, k=min(limit, rng.randint(6, 18)))
        out = []
        for person in crowd:
            if rng.random() < 0.35:
                out.append(Engagement(person=person, kind="comment",
                                      comment_text=rng.choice(COMMENTS).format(kw="a tool like this")))
            else:
                out.append(Engagement(person=person, kind="reaction",
                                      reaction_type=rng.choice(REACTIONS)))
        return out
