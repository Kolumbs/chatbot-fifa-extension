"""Testcases on FIFA Betting Game"""
import unittest
from unittest.mock import MagicMock

from zoozl.chat.api import Package

from chatbot_fifa_extension import FIFAGame


class Play(unittest.TestCase):
    """Testcase on starting to play FIFA Betting Game"""

    def setUp(self):
        self.game = FIFAGame(conf="nothing")

    def test(self):
        """should be possible to call start of the game"""
        callback = MagicMock()
        pack = Package("test", "test", callback)
        self.game.consume(pack)
        callback.assert_called()
        self.assertTrue(self.game.is_complete())
