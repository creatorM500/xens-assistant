from .registry import register
from ..core.tier_config import tier_config


@register(
    name="sync_tier_config",
    description="Sync tier/model configuration from a URL. Downloads and saves to ~/.ainslup/tier_config.json",
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to fetch tier config JSON from (e.g. a GitHub gist raw URL)",
            },
        },
        "required": ["url"],
    },
    tier="free",
)
def sync_tier_config(url: str) -> str:
    return tier_config.load_from_url(url)
