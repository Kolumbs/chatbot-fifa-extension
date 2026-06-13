"""Framework-neutral FIFA World Cup betting capability.

Operations are exposed as a list of :class:`ToolSpec` descriptors (name,
description, a pydantic params model, and a ``(FifaContext, params) -> str``
handler). No LLM/agent SDK is imported here.

The tournament is data-driven:
  * an administrator registers the groups and their teams, and loads the
    match schedule (dated fixtures);
  * players predict the next match that has not kicked off yet - predictions
    lock once a match starts;
  * the administrator may override any player's prediction for any match at
    any time, including after kickoff.

Administrative tools are gated by ``admin_secret`` (validated inside the
handler, so the gate does not rely on the calling LLM).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from typing import Callable

import pydantic

from . import memories
from .context import FifaContext


SCHEDULE_FILE = os.path.join(
    os.path.dirname(__file__), "data", "wc2026_group_schedule.json"
)


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


class AdminSetPrediction(AdminAuth):
    """Admin override of a player's prediction for a specific match."""

    player_name: str = pydantic.Field(description="The player whose pick to set.")
    home: str = pydantic.Field(description="Home team of the match (as scheduled).")
    away: str = pydantic.Field(description="Away team of the match (as scheduled).")
    home_score: int = pydantic.Field(ge=0, description="Predicted home goals.")
    away_score: int = pydantic.Field(ge=0, description="Predicted away goals.")


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
        ge=0, description="Predicted goals for the home (first) team."
    )
    away_score: int = pydantic.Field(
        ge=0, description="Predicted goals for the away (second) team."
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
# Time / schedule helpers
# --------------------------------------------------------------------------- #
def _now():
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def _kickoff(match):
    """Parse a match kickoff into an aware datetime, or None if unparseable."""
    try:
        moment = datetime.fromisoformat(match.kickoff)
    except (ValueError, TypeError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _has_started(match):
    """True if the match has kicked off (predictions locked for players)."""
    moment = _kickoff(match)
    return moment is not None and _now() >= moment


def _ordered_matches(ctx):
    """All matches sorted by kickoff then number (unscheduled sort last)."""
    far_future = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(
        ctx.store.get("match"),
        key=lambda m: (_kickoff(m) or far_future, m.number),
    )


def _label(match):
    """Human-readable match label."""
    return f"{match.home} vs {match.away}"


def _describe(match):
    """Label plus kickoff time."""
    return f"{_label(match)} (kickoff {match.kickoff})"


def _next_open_match(ctx, player):
    """Next match in schedule order that is unstarted and not yet predicted."""
    for match in _ordered_matches(ctx):
        if str(match.number) in player.predictions:
            continue
        if _has_started(match):
            continue
        return match
    return None


def _find_match(ctx, home, away):
    """Find a match by home and away team names (case-insensitive)."""
    home, away = home.strip().lower(), away.strip().lower()
    for match in ctx.store.get("match"):
        if match.home.lower() == home and match.away.lower() == away:
            return match
    return None


# --------------------------------------------------------------------------- #
# Admin: auth + setup
# --------------------------------------------------------------------------- #
def _require_admin(ctx, token):
    """Return an error string if the admin secret is missing/wrong, else None."""
    if not ctx.admin_secret:
        return "Admin features are not configured on this bot."
    if token != ctx.admin_secret:
        return "Not authorized: the admin secret is incorrect."
    return None


def authenticate_admin(ctx: FifaContext, args: AdminAuth) -> str:
    """Check whether the provided admin secret is correct."""
    err = _require_admin(ctx, args.admin_secret)
    if err:
        return err
    return "Verified: the admin secret is correct - you may manage the tournament."


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


def load_schedule(ctx: FifaContext, args: AdminAuth) -> str:
    """Load the bundled match schedule, replacing any existing matches."""
    err = _require_admin(ctx, args.admin_secret)
    if err:
        return err
    try:
        with open(SCHEDULE_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        return f"Could not read the bundled schedule: {exc}"
    for match in list(ctx.store.get("match")):
        ctx.store.delete(match)
    for entry in data:
        ctx.store.put(
            memories.Match(
                number=int(entry["number"]),
                stage=entry.get("stage", "group"),
                home=entry["home"],
                away=entry["away"],
                kickoff=entry["kickoff"],
            )
        )
    if not data:
        return "The bundled schedule is empty."
    first = min(e["kickoff"] for e in data)
    last = max(e["kickoff"] for e in data)
    return f"Loaded {len(data)} matches (from {first} to {last})."


def clear_tournament(ctx: FifaContext, args: AdminAuth) -> str:
    """Delete all registered groups and matches (use to redo setup)."""
    err = _require_admin(ctx, args.admin_secret)
    if err:
        return err
    groups = list(ctx.store.get("group"))
    matches = list(ctx.store.get("match"))
    for group in groups:
        ctx.store.delete(group)
    for match in matches:
        ctx.store.delete(match)
    return f"Cleared {len(groups)} group(s) and {len(matches)} match(es)."


def admin_set_prediction(ctx: FifaContext, args: AdminSetPrediction) -> str:
    """Override a player's prediction for a match (ignores the kickoff lock)."""
    err = _require_admin(ctx, args.admin_secret)
    if err:
        return err
    player = ctx.store.get.player(name=args.player_name)
    if not player:
        return f"No player named '{args.player_name}'."
    match = _find_match(ctx, args.home, args.away)
    if not match:
        return f"No match '{args.home} vs {args.away}' in the schedule."
    player.predictions[str(match.number)] = [args.home_score, args.away_score]
    ctx.store.put(player)
    return (
        f"Set {args.player_name}'s prediction for {_label(match)} to "
        f"{args.home_score}:{args.away_score}."
    )


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
    """Register (or re-join) a player in a contest."""
    contest = ctx.store.get.contest(code=args.contest_code)
    if not contest:
        return (
            f"Contest '{args.contest_code}' does not exist. "
            "Create it first with find_or_create_contest."
        )
    if not list(ctx.store.get("match")):
        return (
            "The match schedule isn't loaded yet. An admin needs to load the "
            "schedule first."
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
    verb = "Registered" if created else "Welcome back,"
    nxt = _next_open_match(ctx, player)
    if nxt:
        return (
            f"{verb} {args.name} in contest '{args.contest_code}'. "
            f"Next match to predict: {_describe(nxt)}."
        )
    return (
        f"{verb} {args.name} in contest '{args.contest_code}'. "
        "There are no upcoming matches to predict right now."
    )


def get_next_match(ctx: FifaContext, args: PlayerRef) -> str:
    """Return the next match awaiting the player's prediction, if any."""
    player = ctx.store.get.player(name=args.player_name)
    if not player:
        return f"No player named '{args.player_name}'. Register first."
    nxt = _next_open_match(ctx, player)
    if nxt:
        return f"Next match awaiting {args.player_name}'s prediction: {_describe(nxt)}."
    return f"{args.player_name} has no upcoming matches to predict right now."


def place_bet(ctx: FifaContext, args: PlaceBet) -> str:
    """Record the player's predicted score for their next upcoming match."""
    player = ctx.store.get.player(name=args.player_name)
    if not player:
        return f"No player named '{args.player_name}'. Register first."
    match = _next_open_match(ctx, player)
    if not match:
        return (
            f"{args.player_name} has no upcoming matches to predict right now."
        )
    player.predictions[str(match.number)] = [args.home_score, args.away_score]
    ctx.store.put(player)
    nxt = _next_open_match(ctx, player)
    tail = f" Next match: {_describe(nxt)}." if nxt else " That was the last open match."
    return (
        f"Recorded {args.player_name}'s prediction for {_label(match)}: "
        f"{args.home_score}:{args.away_score}.{tail}"
    )


def cancel_last_bet(ctx: FifaContext, args: PlayerRef) -> str:
    """Cancel the player's latest still-open prediction so it can be re-entered."""
    player = ctx.store.get.player(name=args.player_name)
    if not player:
        return f"No player named '{args.player_name}'. Register first."
    for match in reversed(_ordered_matches(ctx)):
        if str(match.number) in player.predictions and not _has_started(match):
            del player.predictions[str(match.number)]
            ctx.store.put(player)
            return (
                f"Canceled {args.player_name}'s prediction for {_label(match)}. "
                "You can predict it again."
            )
    return f"{args.player_name} has no open predictions to cancel."


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
        "load_schedule",
        "ADMIN: load the official match schedule (dated fixtures), replacing "
        "any existing matches (requires the admin secret).",
        AdminAuth,
        load_schedule,
    ),
    ToolSpec(
        "clear_tournament",
        "ADMIN: delete all registered groups and matches to redo setup "
        "(requires the admin secret).",
        AdminAuth,
        clear_tournament,
    ),
    ToolSpec(
        "admin_set_prediction",
        "ADMIN: set or override any player's prediction for a specific match, "
        "even after kickoff (requires the admin secret).",
        AdminSetPrediction,
        admin_set_prediction,
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
        "Get the next match awaiting a prediction from the given player.",
        PlayerRef,
        get_next_match,
    ),
    ToolSpec(
        "place_bet",
        "Record a player's predicted score for their next upcoming match. "
        "Refused once that match has kicked off.",
        PlaceBet,
        place_bet,
    ),
    ToolSpec(
        "cancel_last_bet",
        "Cancel a player's latest still-open prediction so it can be entered again.",
        PlayerRef,
        cancel_last_bet,
    ),
]


def get_toolspecs() -> list[ToolSpec]:
    """Return the list of available tool descriptors."""
    return list(TOOLSPECS)
