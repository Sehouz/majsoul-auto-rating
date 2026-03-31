"""
Local Majsoul client package vendored for majsoul-auto-rating.
"""

from __future__ import annotations

from importlib import import_module

__version__ = "0.1.0"

__all__ = [
    "MajsoulClient",
    "MajsoulError",
    "ConnectionError",
    "AuthenticationError",
    "TimeoutError",
    "MessageError",
    "parse_wrapper",
    "to_dict",
    "is_wrapper",
    "auto_parse_bytes",
    "auto_parse_message_fields",
]


def __getattr__(name: str):
    if name == "MajsoulClient":
        return import_module(".client", __name__).MajsoulClient

    if name in {
        "MajsoulError",
        "ConnectionError",
        "AuthenticationError",
        "TimeoutError",
        "MessageError",
    }:
        return getattr(import_module(".exceptions", __name__), name)

    if name in {
        "parse_wrapper",
        "to_dict",
        "is_wrapper",
        "auto_parse_bytes",
        "auto_parse_message_fields",
    }:
        return getattr(import_module(".utils", __name__), name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
