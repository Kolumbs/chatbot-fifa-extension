"""Permanent memory objects"""
import dataclasses


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
