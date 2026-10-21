"""Runtime configuration, read from environment variables."""

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    db_path: str
    run_interval_minutes: int
    linkedin_provider: str
    apify_token: str
    apify_post_search_actor: str
    apify_profile_posts_actor: str
    apify_post_reactions_actor: str
    apify_post_comments_actor: str
    enrichment_provider: str
    anthropic_api_key: str
    scoring_model: str


def load_settings() -> Settings:
    return Settings(
        db_path=_env("SIGNAL_RADAR_DB", "signal_radar.db"),
        run_interval_minutes=int(_env("RUN_INTERVAL_MINUTES", "360") or 0),
        linkedin_provider=_env("LINKEDIN_PROVIDER", "mock").lower(),
        apify_token=_env("APIFY_TOKEN"),
        apify_post_search_actor=_env("APIFY_POST_SEARCH_ACTOR"),
        apify_profile_posts_actor=_env("APIFY_PROFILE_POSTS_ACTOR"),
        apify_post_reactions_actor=_env("APIFY_POST_REACTIONS_ACTOR"),
        apify_post_comments_actor=_env("APIFY_POST_COMMENTS_ACTOR"),
        enrichment_provider=_env("ENRICHMENT_PROVIDER", "mock").lower(),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        scoring_model=_env("SCORING_MODEL", "claude-opus-5-5"),
    )
