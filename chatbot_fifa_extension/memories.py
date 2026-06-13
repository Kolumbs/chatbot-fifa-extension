"""Permanent memory objects"""
import dataclasses


@dataclasses.dataclass()
class Group:
    """A tournament group and the teams competing in it.

    Registered by the administrator; the group-stage fixtures are derived from
    the registered groups (see fifa.generate_group_fixtures).
    """
    name: str = dataclasses.field(default=None, metadata={"key": True})
    teams: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass()
class Contest:
    """Unique contest that contains participant list"""
    code: str = dataclasses.field(default=None, metadata={"key": True})
    players: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass()
class Player:
    """Information about player and it's bets"""
    name: str = dataclasses.field(default=None, metadata={"key": True})
    bets: list = dataclasses.field(default_factory=list)
    next_bet: str = ""
