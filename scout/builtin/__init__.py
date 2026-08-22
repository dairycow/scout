"""Internal plugins sharing PluginApi with user plugins.

Manifest order is normative: config seeds defaults; session subscribes
before display so projections are current for later subscribers.
"""

MANIFEST = [
    "config", "session", "providers", "tools",
    "skills", "prompt", "display", "commands",
]
