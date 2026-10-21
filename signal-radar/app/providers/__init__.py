from ..config import Settings
from .apify import ApifyProvider
from .base import Engagement, LinkedInProvider, Person, Post
from .mock import MockProvider

__all__ = ["Engagement", "LinkedInProvider", "Person", "Post", "get_provider"]


def get_provider(settings: Settings) -> LinkedInProvider:
    if settings.linkedin_provider == "apify":
        return ApifyProvider(
            token=settings.apify_token,
            post_search_actor=settings.apify_post_search_actor,
            profile_posts_actor=settings.apify_profile_posts_actor,
            reactions_actor=settings.apify_post_reactions_actor,
            comments_actor=settings.apify_post_comments_actor,
        )
    return MockProvider()
