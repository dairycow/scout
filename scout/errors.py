"""Errors: one user-facing exception type for the whole project."""


class ScoutError(Exception):
    """Fatal, user-facing error (bad config, API error, etc.)."""
