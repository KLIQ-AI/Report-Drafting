"""Apify-backed provider.

Apify hosts many community LinkedIn actors (post search, profile posts, post
reactions, post comments). Their input and output shapes differ, so actor IDs
are configured via env vars and outputs are normalized tolerantly below. If you
pick an actor with unusual field names, extend the `_pick` key lists.
"""

import httpx

from .base import Engagement, Person, Post

API = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"


def _pick(item: dict, *keys: str, default=""):
    for key in keys:
        cur = item
        for part in key.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur not in (None, ""):
            return cur
    return default


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class ApifyProvider:
    name = "apify"

    def __init__(self, token: str, post_search_actor: str, profile_posts_actor: str,
                 reactions_actor: str, comments_actor: str, timeout: float = 300):
        if not token:
            raise ValueError("APIFY_TOKEN is required for the apify provider")
        self.token = token
        self.post_search_actor = post_search_actor
        self.profile_posts_actor = profile_posts_actor
        self.reactions_actor = reactions_actor
        self.comments_actor = comments_actor
        self.client = httpx.Client(timeout=timeout)

    def _run(self, actor: str, payload: dict) -> list[dict]:
        if not actor:
            raise ValueError("Apify actor ID not configured for this operation")
        resp = self.client.post(API.format(actor=actor.replace("/", "~")),
                                params={"token": self.token}, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []

    def _to_post(self, item: dict) -> Post:
        url = _pick(item, "url", "postUrl", "post_url", "link")
        return Post(
            external_id=str(_pick(item, "urn", "id", "postId", "activityId", default=url)),
            url=url,
            text=_pick(item, "text", "content", "postText", "commentary"),
            author_name=_pick(item, "author.name", "authorName", "author.fullName", "authorFullName"),
            author_headline=_pick(item, "author.headline", "authorHeadline", "author.occupation"),
            author_url=_pick(item, "author.url", "authorProfileUrl", "author.profileUrl", "authorUrl"),
            posted_at=_pick(item, "postedAt", "postedAtISO", "date", "postedDate", default=None),
            reaction_count=_int(_pick(item, "numLikes", "reactionCount", "likes", "stats.total_reactions")),
            comment_count=_int(_pick(item, "numComments", "commentCount", "comments", "stats.comments")),
        )

    def _to_person(self, item: dict) -> Person:
        headline = _pick(item, "headline", "occupation", "actor.headline", "author.headline",
                         "reactor.headline")
        title, company = headline, ""
        if " at " in headline:
            title, company = headline.split(" at ", 1)
        return Person(
            profile_url=_pick(item, "profileUrl", "profile_url", "url", "actor.url",
                              "author.profileUrl", "reactor.profile_url", "linkedinUrl"),
            name=_pick(item, "name", "fullName", "actor.name", "author.name", "reactor.name"),
            headline=headline,
            title=_pick(item, "title", "jobTitle", default=title.strip()),
            company=_pick(item, "company", "companyName", default=company.strip()),
            location=_pick(item, "location", "geo"),
        )

    def search_posts(self, keywords: list[str], limit: int = 20) -> list[Post]:
        items = self._run(self.post_search_actor, {
            "searchQueries": keywords, "keywords": keywords,
            "maxPosts": limit, "limit": limit, "sortBy": "date_posted",
        })
        return [self._to_post(i) for i in items][:limit]

    def profile_posts(self, url: str, limit: int = 10) -> list[Post]:
        items = self._run(self.profile_posts_actor, {
            "profileUrls": [url], "urls": [url], "username": url,
            "maxPosts": limit, "limit": limit,
        })
        return [self._to_post(i) for i in items][:limit]

    def engagements(self, post: Post, limit: int = 100) -> list[Engagement]:
        out: list[Engagement] = []
        if self.reactions_actor:
            for item in self._run(self.reactions_actor, {"postUrls": [post.url], "post_urls": [post.url],
                                                         "limit": limit}):
                person = self._to_person(item)
                if person.profile_url:
                    out.append(Engagement(person=person, kind="reaction",
                                          reaction_type=str(_pick(item, "reactionType", "reaction_type",
                                                                  default="like")).lower()))
        if self.comments_actor:
            for item in self._run(self.comments_actor, {"postIds": [post.url], "postUrls": [post.url],
                                                        "limit": limit}):
                person = self._to_person(item)
                if person.profile_url:
                    out.append(Engagement(person=person, kind="comment",
                                          comment_text=_pick(item, "text", "comment", "commentary")))
        return out[: limit * 2]
