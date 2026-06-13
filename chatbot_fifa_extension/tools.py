"""Framework-neutral FIFA World Cup betting capability.

The betting operations are exposed as a list of :class:`ToolSpec` descriptors.
Each descriptor carries a name, a human/LLM-readable description, a pydantic
model describing its parameters (the single source of truth for the schema),
and a plain handler ``(FifaContext, params) -> str``.

No LLM/agent SDK is imported here. A front-end (the OpenAI Agents SDK adapter
in the host, or a future MCP/REST binding) iterates :data:`TOOLSPECS` and binds
each descriptor to its own tool format.
"""

from dataclasses import dataclass
from typing import Callable

import pydantic

from . import fifa, memories
from .context import FifaContext
from .exceptions import DrawNotAllowed


# --------------------------------------------------------------------------- #
# Parameter schemas (pydantic = schema source of truth + validation)
# --------------------------------------------------------------------------- #
class ContestRef(pydantic.BaseModel):
    """Reference to a contest by its code."""

    code: str = pydantic.Field(description="Short code identifying the contest.")


class RegisterPlayer(pydantic.BaseModel):
    """Join a contest under a player name."""

    contest_code: str = pydantic.Field(description="Code of the contest to join.")
    name: str = pydantic.Field(
        description="Display name the player will be known by."
    )


class PlayerRef(pydantic.BaseModel):
    """Reference to a player by name."""

    player_name: str = pydantic.Field(description="Name of the player.")


class PlaceBet(pydantic.BaseModel):
    """Predicted score for the match currently awaiting the player's bet."""

    player_name: str = pydantic.Field(
        description="Name of the player placing the bet."
    )
    home_score: int = pydantic.Field(
        ge=0, description="Predicted goals for the first team in the match."
    )
    away_score: int = pydantic.Field(
        ge=0, description="Predicted goals for the second team in the match."
    )


# --------------------------------------------------------------------------- #
# Tool descriptor
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ToolSpec:
    """A framework-neutral description of one betting operation."""

    name: str
    description: str
    params: type[pydantic.BaseModel]
    handler: Callable[[FifaContext, pydantic.BaseModel], str]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _admin_bets(ctx: FifaContext):
    """Return the administrator's bets (actual results), or an empty list.

    The administrator's bets drive knockout-stage progression and scoring. They
    are not required for group-stage betting, which is pre-seeded per player.
    """
    admin = ctx.store.get.player(name=ctx.administrator)
    return admin.bets if admin else []


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
def find_or_create_contest(ctx: FifaContext, args: ContestRef) -> str:
    """Find a contest by code, creating it if it does not exist."""
    contest = ctx.store.get.contest(code=args.code)
    if contest:
        count = len(contest.players)
        return f"Contest '{args.code}' already exists with {count} player(s)."
    ctx.store.put(memories.Contest(code=args.code))
    return f"Created new contest '{args.code}'."


def register_player(ctx: FifaContext, args: RegisterPlayer) -> str:
    """Register (or re-join) a player in a contest and seed their bet card."""
    contest = ctx.store.get.contest(code=args.contest_code)
    if not contest:
        return (
            f"Contest '{args.contest_code}' does not exist. "
            "Create it first with find_or_create_contest."
        )
    player = ctx.store.get.player(name=args.name)
    created = False
    if not player:
        player = memories.Player(name=args.name)
        ctx.store.put(player)
        created = True
    if args.name not in contest.players:
        contest.players.append(args.name)
        ctx.store.put(contest)
    cup = fifa.WorldCup(player, _admin_bets(ctx))
    cup.load_next_bet()
    ctx.store.put(player)
    verb = "Registered" if created else "Welcome back,"
    if player.next_bet:
        return (
            f"{verb} {args.name} in contest '{args.contest_code}'. "
            f"Next match to bet on: {player.next_bet}."
        )
    return (
        f"{verb} {args.name} in contest '{args.contest_code}'. "
        "No match is awaiting a bet right now."
    )


def get_next_match(ctx: FifaContext, args: PlayerRef) -> str:
    """Return the next match awaiting the player's bet, if any."""
    player = ctx.store.get.player(name=args.player_name)
    if not player:
        return f"No player named '{args.player_name}'. Register first."
    cup = fifa.WorldCup(player, _admin_bets(ctx))
    cup.load_next_bet()
    ctx.store.put(player)
    if player.next_bet:
        return f"Next match awaiting {args.player_name}'s bet: {player.next_bet}."
    return f"{args.player_name} has no match awaiting a bet right now."


def place_bet(ctx: FifaContext, args: PlaceBet) -> str:
    """Record the player's predicted score for the match awaiting a bet."""
    player = ctx.store.get.player(name=args.player_name)
    if not player:
        return f"No player named '{args.player_name}'. Register first."
    cup = fifa.WorldCup(player, _admin_bets(ctx))
    cup.load_next_bet()
    match = player.next_bet
    if not match:
        return f"{args.player_name} has no match awaiting a bet right now."
    try:
        cup.add_bet([args.home_score, args.away_score])
    except DrawNotAllowed:
        return (
            f"Draws are not allowed in the knockout stage for match {match}. "
            "Please give a decisive score."
        )
    cup.load_next_bet()
    ctx.store.put(player)
    if player.next_bet:
        nxt = f" Next match: {player.next_bet}."
    else:
        nxt = " That was the last match awaiting a bet."
    return (
        f"Recorded {args.player_name}'s bet on {match}: "
        f"{args.home_score}:{args.away_score}.{nxt}"
    )


def cancel_last_bet(ctx: FifaContext, args: PlayerRef) -> str:
    """Cancel the player's most recent bet so it can be re-entered."""
    player = ctx.store.get.player(name=args.player_name)
    if not player:
        return f"No player named '{args.player_name}'. Register first."
    cup = fifa.WorldCup(player, _admin_bets(ctx))
    canceled = cup.cancel_previous_bet()
    cup.load_next_bet()
    ctx.store.put(player)
    if canceled:
        return (
            f"Canceled {args.player_name}'s last bet on {canceled}. "
            f"Next match: {player.next_bet or 'none'}."
        )
    return f"{args.player_name} has no bets to cancel."


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
TOOLSPECS: list[ToolSpec] = [
    ToolSpec(
        "find_or_create_contest",
        "Find a betting contest by its code, creating it if it does not exist.",
        ContestRef,
        find_or_create_contest,
    ),
    ToolSpec(
        "register_player",
        "Register a player (by name) in a contest so they can place bets.",
        RegisterPlayer,
        register_player,
    ),
    ToolSpec(
        "get_next_match",
        "Get the next match that is awaiting a bet from the given player.",
        PlayerRef,
        get_next_match,
    ),
    ToolSpec(
        "place_bet",
        "Record a player's predicted score for the match awaiting their bet.",
        PlaceBet,
        place_bet,
    ),
    ToolSpec(
        "cancel_last_bet",
        "Cancel a player's most recent bet so it can be entered again.",
        PlayerRef,
        cancel_last_bet,
    ),
]


def get_toolspecs() -> list[ToolSpec]:
    """Return the list of available betting tool descriptors."""
    return list(TOOLSPECS)
