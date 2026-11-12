"""SentientMilk: a local brain server that apps think with. Apps import only the client side."""

from .client import BrainClient, connect, default_home
from .config import DEFAULT_BASE_URL, DEFAULT_MODEL
from .exceptions import BrainError

__version__ = "0.15.0"
__all__ = ["DEFAULT_BASE_URL", "DEFAULT_MODEL", "BrainClient", "BrainError", "connect", "default_home"]
