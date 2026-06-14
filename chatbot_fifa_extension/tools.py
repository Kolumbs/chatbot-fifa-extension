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

from . import fifa, memories
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


class SetResult(AdminAuth):
    """Admin entry of a match's actual final score."""

    home: str = pydantic.Field(description="Home team of the match (as scheduled).")
    away: str = pydantic.Field(description="Away team of the match (as scheduled).")
    home_score: int = pydantic.Field(ge=0, description="Actual home goals.")
    away_score: int = pydantic.Field(ge=0, description="Actual away goals.")


class RegisterPlayer(pydantic.BaseModel):
    """Register under a player name."""

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


class UpdatePrediction(pydantic.BaseModel):
    """Correct a player's prediction for a specific (not-yet-started) match."""

    player_name: str = pydantic.Field(description="Name of the player.")
    home: str = pydantic.Field(description="Home team of the match to fix.")
    away: str = pydantic.Field(description="Away team of the match to fix.")
    home_score: int = pydantic.Field(ge=0, description="Corrected home goals.")
    away_score: int = pydantic.Field(ge=0, description="Corrected away goals.")


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
    preds = player.predictions or {}
    for match in _ordered_matches(ctx):
        if str(match.number) in preds:
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


def _ensure_predictions(player):
    """Return predictions as a dict, coercing legacy/None records in place."""
    if not isinstance(player.predictions, dict):
        player.predictions = {}
    return player.predictions


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
    _ensure_predictions(player)[str(match.number)] = [args.home_score, args.away_score]
    ctx.store.put(player)
    return (
        f"Set {args.player_name}'s prediction for {_label(match)} to "
        f"{args.home_score}:{args.away_score}."
    )


def set_result(ctx: FifaContext, args: SetResult) -> str:
    """Record the actual final score of a match."""
    err = _require_admin(ctx, args.admin_secret)
    if err:
        return err
    match = _find_match(ctx, args.home, args.away)
    if not match:
        return f"No match '{args.home} vs {args.away}' in the schedule."
    match.result = [args.home_score, args.away_score]
    ctx.store.put(match)
    return (
        f"Recorded result for {_label(match)}: "
        f"{args.home_score}:{args.away_score}."
    )


# --------------------------------------------------------------------------- #
# Lookup handlers (read-only; let the bot report real state, not guess)
# --------------------------------------------------------------------------- #
def list_players(ctx: FifaContext, _args: NoArgs) -> str:
    """List every registered player and how many predictions each has made."""
    players = sorted(ctx.store.get("player"), key=lambda p: p.name)
    if not players:
        return "No players are registered yet."
    lines = []
    for player in players:
        preds = player.predictions if isinstance(player.predictions, dict) else {}
        lines.append(f"{player.name}: {len(preds)} prediction(s)")
    return "\n".join(lines)


def get_predictions(ctx: FifaContext, args: PlayerRef) -> str:
    """List all of a player's saved predictions."""
    player = ctx.store.get.player(name=args.player_name)
    if not player:
        return f"No player named '{args.player_name}'."
    preds = player.predictions if isinstance(player.predictions, dict) else {}
    if not preds:
        return f"{args.player_name} has no predictions yet."
    by_number = {str(m.number): m for m in ctx.store.get("match")}
    lines = []
    for number in sorted(preds, key=lambda x: int(x)):
        match = by_number.get(number)
        label = _label(match) if match else f"match {number}"
        home, away = preds[number]
        lines.append(f"{label}: {home}:{away}")
    return f"{args.player_name}'s predictions:\n" + "\n".join(lines)


def standings(ctx: FifaContext, _args: NoArgs) -> str:
    """Score all registered players against entered results and rank them.

    Scoring (the original scheme): 6 points for an exact score, 3 for the
    correct outcome; on a match nobody predicted exactly, the closest correct
    prediction (by goal difference) earns +2, or +1 each if several tie.
    """
    players = list(ctx.store.get("player"))
    if not players:
        return "No players are registered yet."
    scores = {p.name: 0 for p in players}
    played = [m for m in _ordered_matches(ctx) if m.result]
    if not played:
        return "No match results have been entered yet."
    for match in played:
        perfect = False
        closest = []
        closest_diff = None
        for player in players:
            preds = player.predictions if isinstance(player.predictions, dict) else {}
            prediction = preds.get(str(match.number))
            if not prediction:
                continue
            correct, diff = fifa.get_score_bet(match.result, prediction)
            if correct and diff == 0:
                perfect = True
                scores[player.name] += 6
            elif correct:
                scores[player.name] += 3
                if closest_diff is None or diff < closest_diff:
                    closest, closest_diff = [player.name], diff
                elif diff == closest_diff:
                    closest.append(player.name)
        if not perfect and closest:
            bonus = 2 if len(closest) == 1 else 1
            for name in closest:
                scores[name] += bonus
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    lines = [f"{i + 1}. {name} - {pts} pts" for i, (name, pts) in enumerate(ranked)]
    return (
        f"Standings (after {len(played)} played match(es)):\n"
        + "\n".join(lines)
    )


def next_match_needing_result(ctx: FifaContext, _args: NoArgs) -> str:
    """Return the next already-kicked-off match that has no result entered."""
    for match in _ordered_matches(ctx):
        if _has_started(match) and not match.result:
            return f"Next match needing a result: {_describe(match)}."
    return "Every match that has kicked off already has a result entered."


# --------------------------------------------------------------------------- #
# Player handlers
# --------------------------------------------------------------------------- #
def register_player(ctx: FifaContext, args: RegisterPlayer) -> str:
    """Register (or welcome back) a player by name."""
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
    verb = "Registered" if created else "Welcome back,"
    nxt = _next_open_match(ctx, player)
    if nxt:
        return f"{verb} {args.name}. Next match to predict: {_describe(nxt)}."
    return f"{verb} {args.name}. There are no upcoming matches to predict right now."


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
    _ensure_predictions(player)[str(match.number)] = [args.home_score, args.away_score]
    ctx.store.put(player)
    nxt = _next_open_match(ctx, player)
    tail = f" Next match: {_describe(nxt)}." if nxt else " That was the last open match."
    return (
        f"Recorded {args.player_name}'s prediction for {_label(match)}: "
        f"{args.home_score}:{args.away_score}.{tail}"
    )


def update_prediction(ctx: FifaContext, args: UpdatePrediction) -> str:
    """Correct a player's prediction for a specific match that hasn't started."""
    player = ctx.store.get.player(name=args.player_name)
    if not player:
        return f"No player named '{args.player_name}'. Register first."
    match = _find_match(ctx, args.home, args.away)
    if not match:
        return f"No match '{args.home} vs {args.away}' in the schedule."
    if _has_started(match):
        return (
            f"{_label(match)} has already kicked off, so its prediction is "
            "locked. Only Juris can change it now."
        )
    _ensure_predictions(player)[str(match.number)] = [args.home_score, args.away_score]
    ctx.store.put(player)
    return (
        f"Updated {args.player_name}'s prediction for {_label(match)} to "
        f"{args.home_score}:{args.away_score}."
    )


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
    ToolSpec(
        "set_result",
        "ADMIN: record the actual final score of a match once it has been "
        "played (requires the admin secret).",
        SetResult,
        set_result,
    ),
    # lookups (read-only) - use these to report real state instead of guessing
    ToolSpec(
        "list_players",
        "List every registered player and how many predictions each has made.",
        NoArgs,
        list_players,
    ),
    ToolSpec(
        "get_predictions",
        "List all of a player's saved predictions (their match picks).",
        PlayerRef,
        get_predictions,
    ),
    ToolSpec(
        "standings",
        "Show the scoreboard, scoring all players' predictions against the "
        "entered match results.",
        NoArgs,
        standings,
    ),
    ToolSpec(
        "next_match_needing_result",
        "Get the next already-played match that still needs its actual result "
        "entered. Use this when recording results - NOT get_next_match, which is "
        "for players' predictions.",
        NoArgs,
        next_match_needing_result,
    ),
    # player
    ToolSpec(
        "register_player",
        "Register a player by name so they can place predictions.",
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
        "update_prediction",
        "Correct a player's prediction for a specific match (by team names) that "
        "has not kicked off yet.",
        UpdatePrediction,
        update_prediction,
    ),
]


def get_toolspecs() -> list[ToolSpec]:
    """Return the list of available tool descriptors."""
    return list(TOOLSPECS)
