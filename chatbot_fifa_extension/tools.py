"""Framework-neutral FIFA World Cup betting capability.

The operations are exposed as a list of :class:`ToolSpec` descriptors. Each
descriptor carries a name, a human/LLM-readable description, a pydantic model
describing its parameters (the single source of truth for the schema), and a
plain handler ``(FifaContext, params) -> str``.

The tournament is data-driven: an administrator registers the groups and their
teams, and the group-stage fixtures are derived from them. No tournament data
is hard-coded, and no LLM/agent SDK is imported here.

Administrative tools are gated by ``admin_secret`` (validated inside the
handler, so the gate does not rely on the calling LLM).
"""

from dataclasses import dataclass
from typing import Callable

import pydantic

from . import fifa, memories
from .context import FifaContext


# --------------------------------------------------------------------------- #
# Parameter schemas (pydantic = schema source of truth + validation)
# --------------------------------------------------------------------------- #
class NoArgs(pydantic.BaseModel):
    """No parameters."""


class AdminAuth(pydantic.BaseModel):
    """Base for administrative operations requiring the admin secret."""

    admin_secret: str = pydantic.Field(
        description="The admin secret that authorizes tournament management."
    )


class RegisterGroup(AdminAuth):
    """Register (or overwrite) a group and the teams competing in it."""

    group: str = pydantic.Field(description="Group label, for example 'A'.")
    teams: list[str] = pydantic.Field(
        description="The teams competing in this group."
    )


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
        description="Name of the player placing the prediction."
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
    """A framework-neutral description of one operation."""

    name: str
    description: str
    params: type[pydantic.BaseModel]
    handler: Callable[[FifaContext, pydantic.BaseModel], str]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _require_admin(ctx: FifaContext, token: str):
    """Return an error string if the admin secret is missing/wrong, else None."""
    if not ctx.admin_secret:
        return "Admin features are not configured on this bot."
    if token != ctx.admin_secret:
        return "Not authorized: the admin secret is incorrect."
    return None


def _group_fixtures(ctx: FifaContext):
    """Return the ordered group-stage fixtures derived from registered groups."""
    groups = list(ctx.store.get("group"))
    return fifa.generate_group_fixtures(groups)


def _next_unbet(player):
    """Return the next match the player has not predicted yet, or ''. """
    for game, result in player.bets:
        if not result:
            return game
    return ""


# --------------------------------------------------------------------------- #
# Administrative handlers (gated by admin_secret)
# --------------------------------------------------------------------------- #
def authenticate_admin(ctx: FifaContext, args: AdminAuth) -> str:
    """Check whether the provided admin secret is correct."""
    err = _require_admin(ctx, args.admin_secret)
    if err:
        return err
    return "Verified: the admin secret is correct - you may set up the tournament."


def register_group(ctx: FifaContext, args: RegisterGroup) -> str:
    """Register or overwrite a group and its teams."""
    err = _require_admin(ctx, args.admin_secret)
    if err:
        return err
    name = args.group.strip().upper()
    teams = [t.strip() for t in args.teams if t.strip()]
    ctx.store.put(memories.Group(name=name, teams=teams))
    return f"Registered group {name}: {', '.join(teams)}."


def list_groups(ctx: FifaContext, _args: NoArgs) -> str:
    """List the registered groups and their teams."""
    groups = sorted(ctx.store.get("group"), key=lambda g: g.name)
    if not groups:
        return "No groups are registered yet."
    return "\n".join(f"Group {g.name}: {', '.join(g.teams)}" for g in groups)


def clear_tournament(ctx: FifaContext, args: AdminAuth) -> str:
    """Delete all registered groups (use to redo the tournament setup)."""
    err = _require_admin(ctx, args.admin_secret)
    if err:
        return err
    groups = list(ctx.store.get("group"))
    for group in groups:
        ctx.store.delete(group)
    return f"Cleared {len(groups)} group(s)."


# --------------------------------------------------------------------------- #
# Player handlers
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
    fixtures = _group_fixtures(ctx)
    if not fixtures:
        return (
            "The tournament isn't set up yet - no groups have been registered. "
            "An admin needs to register the groups and teams first."
        )
    player = ctx.store.get.player(name=args.name)
    created = False
    if not player:
        player = memories.Player(name=args.name)
        created = True
    if not player.bets:
        player.bets = [[fixture, 0] for fixture in fixtures]
    ctx.store.put(player)
    if args.name not in contest.players:
        contest.players.append(args.name)
        ctx.store.put(contest)
    verb = "Registered" if created else "Welcome back,"
    nxt = _next_unbet(player)
    if nxt:
        return (
            f"{verb} {args.name} in contest '{args.contest_code}'. "
            f"Next match to predict: {nxt}."
        )
    return (
        f"{verb} {args.name} in contest '{args.contest_code}'. "
        "You have predicted every match."
    )


def get_next_match(ctx: FifaContext, args: PlayerRef) -> str:
    """Return the next match awaiting the player's prediction, if any."""
    player = ctx.store.get.player(name=args.player_name)
    if not player:
        return f"No player named '{args.player_name}'. Register first."
    nxt = _next_unbet(player)
    if nxt:
        return f"Next match awaiting {args.player_name}'s prediction: {nxt}."
    return f"{args.player_name} has predicted every match."


def place_bet(ctx: FifaContext, args: PlaceBet) -> str:
    """Record the player's predicted score for the match awaiting a prediction."""
    player = ctx.store.get.player(name=args.player_name)
    if not player:
        return f"No player named '{args.player_name}'. Register first."
    match = ""
    for bet in player.bets:
        if not bet[1]:
            match = bet[0]
            bet[1] = [args.home_score, args.away_score]
            break
    if not match:
        return f"{args.player_name} has no match awaiting a prediction."
    ctx.store.put(player)
    nxt = _next_unbet(player)
    tail = f" Next match: {nxt}." if nxt else " That was the last match."
    return (
        f"Recorded {args.player_name}'s prediction for {match}: "
        f"{args.home_score}:{args.away_score}.{tail}"
    )


def cancel_last_bet(ctx: FifaContext, args: PlayerRef) -> str:
    """Cancel the player's most recent prediction so it can be re-entered."""
    player = ctx.store.get.player(name=args.player_name)
    if not player:
        return f"No player named '{args.player_name}'. Register first."
    canceled = fifa.remove_previous_bet(player.bets)
    ctx.store.put(player)
    if canceled:
        return (
            f"Canceled {args.player_name}'s prediction for {canceled}. "
            "You can predict it again."
        )
    return f"{args.player_name} has no predictions to cancel."


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
TOOLSPECS: list[ToolSpec] = [
    # administrative
    ToolSpec(
        "authenticate_admin",
        "Check whether an admin secret is correct. Call this whenever someone "
        "offers the admin secret, and let the result decide - do not judge the "
        "secret yourself.",
        AdminAuth,
        authenticate_admin,
    ),
    ToolSpec(
        "register_group",
        "ADMIN: register or overwrite a group and the teams in it "
        "(requires the admin secret).",
        RegisterGroup,
        register_group,
    ),
    ToolSpec(
        "list_groups",
        "List the registered tournament groups and their teams.",
        NoArgs,
        list_groups,
    ),
    ToolSpec(
        "clear_tournament",
        "ADMIN: delete all registered groups to redo setup "
        "(requires the admin secret).",
        AdminAuth,
        clear_tournament,
    ),
    # player
    ToolSpec(
        "find_or_create_contest",
        "Find a betting contest by its code, creating it if it does not exist.",
        ContestRef,
        find_or_create_contest,
    ),
    ToolSpec(
        "register_player",
        "Register a player (by name) in a contest so they can place predictions.",
        RegisterPlayer,
        register_player,
    ),
    ToolSpec(
        "get_next_match",
        "Get the next match that is awaiting a prediction from the given player.",
        PlayerRef,
        get_next_match,
    ),
    ToolSpec(
        "place_bet",
        "Record a player's predicted score for the match awaiting their prediction.",
        PlaceBet,
        place_bet,
    ),
    ToolSpec(
        "cancel_last_bet",
        "Cancel a player's most recent prediction so it can be entered again.",
        PlayerRef,
        cancel_last_bet,
    ),
]


def get_toolspecs() -> list[ToolSpec]:
    """Return the list of available tool descriptors."""
    return list(TOOLSPECS)
