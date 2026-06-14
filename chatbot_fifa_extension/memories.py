"""Permanent memory objects."""
import dataclasses


@dataclasses.dataclass()
class Group:
    """A tournament group and the teams competing in it.

    Registered by the administrator; used for standings/scoring. Match fixtures
    come from the loaded schedule (see Match), not derived from groups.
    """
    name: str = dataclasses.field(default=None, metadata={"key": True})
    teams: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass()
class Match:
    """A scheduled tournament match.

    number is the schedule order/id. kickoff is an ISO-8601 UTC timestamp;
    predictions for a match lock once kickoff has passed (admins excepted).
    home_goals/away_goals hold the actual result once known (None until played).
    """
    number: int = dataclasses.field(default=0, metadata={"key": True})
    stage: str = "group"
    home: str = ""
    away: str = ""
    kickoff: str = ""  # ISO-8601 UTC, e.g. "2026-06-11T19:00:00+00:00"
    result: list = dataclasses.field(default_factory=list)  # [] until played, then [h, a]


@dataclasses.dataclass()
class Player:
    """A player and their per-match score predictions.

    name is the display name (key). talker links the player to a browser/session
    identity (from the conversation); betting actions resolve the player by
    talker, so the player never has to re-state their name. An admin can repoint
    talker if the player loses their session (cleared cookies).
    predictions maps str(match number) -> [home_goals, away_goals].
    """
    name: str = dataclasses.field(default=None, metadata={"key": True})
    talker: str = ""  # legacy single-session field (kept so old links still match)
    talkers: list = dataclasses.field(default_factory=list)  # linked session ids
    predictions: dict = dataclasses.field(default_factory=dict)
