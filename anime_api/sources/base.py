"""Base class every anime source subclasses.

Contract: anime-api-work/INTERFACE.md. Return shapes are JSON-serializable
dicts/lists only — no objects. Every public method catches its own per-item
errors so one bad card never kills a list.
"""

from anime_api.http import resolve_domain


class Source:
    id = ""           # e.g. "animeworld" (URL-safe, used in ?source=)
    name = ""         # display name, e.g. "Anime World India"
    language = ""     # "hindi" | "english"
    domain_key = ""   # Firebase key, e.g. "animeworldindia" ("" if none)
    default_url = ""  # static fallback host

    @property
    def base_url(self):
        """Live host, resolved via the Firebase domain map (cached 5 min)."""
        return resolve_domain(self.domain_key, self.default_url)

    def search(self, query, page=1):
        """search(query, page=1) -> list of item dicts (see INTERFACE.md)."""
        raise NotImplementedError

    def home(self, section, page=1):
        """home(section, page=1) -> list of item dicts.

        section in {"trending", "popular", "latest"}.
        """
        raise NotImplementedError

    def details(self, item_id):
        """details(item_id) -> details dict (see INTERFACE.md)."""
        raise NotImplementedError

    def streams(self, episode_data):
        """streams(episode_data) -> {"streams": [...], "subtitles": [...]}."""
        raise NotImplementedError
