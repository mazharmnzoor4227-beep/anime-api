"""anime-api: shared helpers + source registry.

See README.md and anime-api-work/INTERFACE.md for the full contract.
"""

from anime_api.sources import get_source, list_sources

__all__ = ["get_source", "list_sources"]
