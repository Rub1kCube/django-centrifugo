from __future__ import annotations

import importlib.metadata


__all__ = ["__title__", "__version__"]

_metadata = importlib.metadata.metadata("django-centrifugo")

__title__ = _metadata["Name"]
"""Name of the project."""
__version__ = _metadata["Version"]
"""Version of the project."""
