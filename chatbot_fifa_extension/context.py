"""Framework-neutral execution context for the FIFA betting tools.

This module deliberately depends only on the persistence layer (membank). It
must never import an LLM/agent SDK so that the betting capability can be bound
to any front-end (OpenAI Agents SDK, MCP, REST, ...).
"""

from dataclasses import dataclass

import membank


@dataclass
class FifaContext:
    """Holds the persistence store and config the betting tools operate on.

    :param store: membank store holding Contest and Player records.
    :param administrator: name of the administrator player whose bets carry the
        actual match results (used to advance knockout stages and to score).
    """

    store: membank.LoadMemory
    administrator: str


def build_context(conf: dict) -> FifaContext:
    """Build a :class:`FifaContext` from a configuration mapping.

    :param conf: mapping with ``database_path`` and ``administrator`` keys,
        matching the existing ``[chatbot_fifa_extension]`` config section. The
        sqlite url scheme is kept identical to previous releases so existing
        data keeps working.
    """
    if "database_path" not in conf or "administrator" not in conf:
        raise RuntimeError(
            "FIFA tools require 'database_path' and 'administrator' in config"
        )
    store = membank.LoadMemory(f"sqlite://{conf['database_path']}/db")
    return FifaContext(store=store, administrator=conf["administrator"])
