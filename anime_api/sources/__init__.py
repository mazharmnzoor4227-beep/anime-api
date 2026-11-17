"""Source registry.

Discovers every ``anime_api/sources/<id>.py`` module at import time and
registers any ``Source`` subclass it defines (keyed by ``Source.id``).
Modules that fail to import (e.g. a source whose optional dependency is
missing) are skipped, never fatal — the rest of the API keeps working.
"""

import importlib
import pkgutil

from anime_api.sources.base import Source

_SOURCES = {}


def _discover():
    import anime_api.sources as _pkg

    for info in pkgutil.iter_modules(_pkg.__path__):
        if info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(
                "anime_api.sources." + info.name
            )
        except Exception:
            continue
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, Source)
                and obj is not Source
                and obj.id
            ):
                _SOURCES[obj.id] = obj


_discover()


def list_sources():
    """Return instantiated sources, sorted by id."""
    return [_SOURCES[sid]() for sid in sorted(_SOURCES)]


def get_source(source_id):
    """Return an instantiated source, or None if unknown."""
    cls = _SOURCES.get(source_id)
    return cls() if cls else None


def source_ids():
    return sorted(_SOURCES)
