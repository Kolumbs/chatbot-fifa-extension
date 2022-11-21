"""Testcases on FIFA Betting Game"""
import time
import unittest
from unittest.mock import MagicMock, call

from chatbot import Package, Conversation, Message

from chatbot_fifa_extension import FIFAGame, fifa


class GroupWinners(unittest.TestCase):
    """Testcase for getting group winners"""

    def test(self):
        """win by points"""
        # Qatar 0
        # Ecuador 3
        # Senegal 6
        # Nethers 9
        results = {
            'Qatar and Ecuador': [0, 2],
            'Senegal and Netherlands': [0, 2],
            'Qatar and Senegal': [0, 2],
            'Netherlands and Ecuador': [2, 0],
            'Netherlands and Qatar': [2, 0],
            'Ecuador and Senegal': [0, 2]
        }
        team1, team2 = fifa.get_group_winners(results)
        self.assertEqual("Netherlands", team1)
        self.assertEqual("Senegal", team2)

    def test_by_goal_diff(self):
        """win by total goal diff"""
        results = {
            'Qatar and Ecuador': [0, 2],
            'Senegal and Netherlands': [0, 1],
            'Qatar and Senegal': [0, 2],
            'Netherlands and Ecuador': [0, 2],
            'Netherlands and Qatar': [2, 0],
            'Ecuador and Senegal': [0, 2]
        }
        team1, team2 = fifa.get_group_winners(results)
        self.assertEqual("Senegal", team1)
        self.assertEqual("Ecuador", team2)

    def test_by_goals(self):
        """win by total goals"""
        results = {
            'Qatar and Ecuador': [0, 2],
            'Senegal and Netherlands': [2, 4],
            'Qatar and Senegal': [0, 2],
            'Netherlands and Ecuador': [1, 3],
            'Netherlands and Qatar': [2, 0],
            'Ecuador and Senegal': [0, 2]
        }
        team1, team2 = fifa.get_group_winners(results)
        self.assertEqual("Netherlands", team1)
        self.assertEqual("Senegal", team2)

    def test_by_points_subgroup(self):
        """win by total points in subgroup"""
        results = {
            'Qatar and Ecuador': [0, 2],
            'Senegal and Netherlands': [2, 4],
            'Qatar and Senegal': [0, 2],
            'Netherlands and Ecuador': [0, 2],
            'Netherlands and Qatar': [2, 0],
            'Ecuador and Senegal': [0, 2]
        }
        team1, team2 = fifa.get_group_winners(results)
        self.assertEqual("Netherlands", team1)
        self.assertEqual("Senegal", team2)


class Abstract(unittest.TestCase):
    """Abstract testcase for FIFA extension tests"""

    def setUp(self):
        self.game = FIFAGame(conf={"database_path": "tests/tmp", "administrator": "yunk"})
        self.callback = MagicMock()
        self.build_new_pack()

    def tearDown(self):
        self.callback.reset_mock()
        self.cancel_all_bets()

    def assert_answer(self, ask, *respond, reset=True):
        """assert that bot responds to ask"""
        self.make_call(ask)
        self.callback.assert_has_calls([call(i) for i in respond])
        if reset:
            self.callback.reset_mock()

    def make_call(self, ask):
        """makes a call"""
        self.pack.message.text = ask
        self.game.consume(self.pack)

    def register(self, name="Richard", contest="family", new=False):
        """helper function to register player in contest"""
        self.assert_answer("Hello", "What is your contest code?")
        self.assert_answer(contest, "OK. Now please state your name!")
        if new:
            msg = f"Nice to meet you {name}"
        else:
            msg = f"Welcome back {name}"
        self.assert_answer(
            name,
            msg,
            unittest.mock.ANY
        )

    def build_new_pack(self):
        """builds new package for exchange between chatbot"""
        self.pack = Package(Message(""), Conversation(), self.callback)

    def cancel_all_bets(self):
        """cleans out all previous bets"""
        nothing = call('Nothing to cancel. Enter first bet')
        canceling = call('OK. Canceled previous bet')
        no_contest = call('Such contest does not exist. Try again')
        timeout = 3 + time.time()
        while True:
            self.make_call("cancel")
            response = self.callback.call_args_list[0]
            self.callback.reset_mock()
            self.assertIn(response, [nothing, canceling, no_contest])
            if response in [nothing, no_contest]:
                break
            if timeout < time.time():
                raise RuntimeError("Timeout reached.")


class AdminMode(Abstract):
    """Testcase on entering admin mode"""

    def tearDown(self):
        pass

    def register_admin(self):
        """register to admin mode"""
        self.make_call("Hello")
        self.make_call("Burgy")
        self.make_call("admin mode")
        self.make_call("yunk")
        self.callback.reset_mock()

    def test(self):
        """should be possible to enter admin mode"""
        self.make_call("Hello")
        self.make_call("Burgy")
        self.assert_answer("admin mode", "Please identify yourself")
        self.assert_answer("yunkr", 'You are not identified. Please identify')
        self.assert_answer("yunk", "You are identified. Commands available")

    def test_add_player(self):
        """should be possible to add players to contest"""
        self.register_admin()
        self.assert_answer("add players to contest", "State name of contest")
        self.assert_answer("Burgy", "State name of the player to add")
        self.assert_answer("Richard", "OK. Added")
        self.assert_answer("Richard", "OK. Added")

    def test_get_results(self):
        """should be possible to get results of players bets for next game"""
        self.register_admin()
        self.assert_answer("predictions", "For which contest?")
        self.assert_answer("Burgy", "Richard missing bets")


class NextGame(AdminMode):
    """Testcase on next game command"""

    def setUp(self):
        """add new contest with two players"""
        Abstract.setUp(self)
        self.make_call("greet")
        self.callback.reset_mock()
        self.make_call("Burgy")
        no_contest = call('Such contest does not exist. Try again')
        if self.callback.call_args_list[0] == no_contest:
            self.make_call("create contest")
            self.assert_answer("Burgy", "Now please state your name!")
        self.make_call("Burg 1")
        self.build_new_pack()
        self.make_call("greet")
        self.make_call("Burgy")
        self.make_call("Burg 2")
        self.build_new_pack()
        self.make_call("greet")
        self.make_call("Burgy")
        self.callback.reset_mock()

    def test(self):
        """should be possible to get result predictions of next game"""
        self.register_admin()
        self.assert_answer("predictions", "For which contest?")
        self.assert_answer("Burgy", "Richard missing bets")


class Play(Abstract):
    """Testcase on starting to play FIFA Betting Game"""

    def test(self):
        """should be possible to call start of the game"""
        self.assert_answer("Hello", "What is your contest code?")
        self.assert_answer("help", "If you want to create new contest call create contest")
        self.assert_answer("create contest", "Please state the name of the contest")
        self.assert_answer("family", "Now please state your name!")
        self.assert_answer(
            "Richard",
            "Welcome back Richard",
            "What will be result between Qatar and Ecuador?",
        )
        self.assertFalse(self.game.is_complete())

    def test_restart(self):
        """betting should restart from where it was left off"""
        previous_bet = "What will be result between Qatar and Ecuador?"
        self.register("Richard")
        self.assert_answer("0:2", "What will be result between England and Iran?")
        self.assert_answer(
            "cancel",
            "OK. Canceled previous bet",
            previous_bet,
        )
        self.assert_answer("0:2", "What will be result between England and Iran?")
        self.build_new_pack()
        self.register()
        self.assert_answer("0:2", "What will be result between Senegal and Netherlands?")


class Full(Abstract):
    """Test full betting scenario"""

    def tearDown(self):
        pass

    def test(self):
        """one full cycle of bets"""
        common = "What will be result between "
        player = str(time.time())
        self.register(player, new=True)
        bets = (
            ("2:0", "England and Iran"),
            ("2:2", "Senegal and Netherlands"),
            ("0:2", "United States and Wales"),
            ("0:2", "Argentina and Saudi Arabia"),
            ("2:2", "Denmark and Tunisia"),
            ("2:0", "Mexico and Poland"),
            ("0:2", "France and Australia"),
            ("2:0", "Morocco and Croatia"),
            ("0:2", "Germany and Japan"),
            ("0:2", "Spain and Costa Rica"),
            ("2:0", "Belgium and Canada"),
            ("2:0", "Switzerland and Cameroon"),
            ("0:2", "Uruguay and Korea Republic"),
            ("0:2", "Portugal and Ghana"),
            ("0:2", "Brazil and Serbia"),
            ("2:1", "Wales and Iran"),
            ("0:2", "Qatar and Senegal"),
            ("2:0", "Netherlands and Ecuador"),
            ("0:2", "England and United States"),
            ("5:0", "Tunisia and Australia"),
            ("0:2", "Poland and Saudi Arabia"),
            ("0:2", "France and Denmark"),
            ("2:2", "Argentina and Mexico"),
            ("5:0", "Japan and Costa Rica"),
            ("0:2", "Belgium and Morocco"),
            ("0:2", "Croatia and Canada"),
            ("0:2", "Spain and Germany"),
            ("1:1", "Cameroon and Serbia"),
            ("0:2", "Korea Republic and Ghana"),
            ("1:1", "Brazil and Switzerland"),
            ("2:0", "Portugal and Uruguay"),
            ("2:0", "Netherlands and Qatar"),
            ("0:2", "Ecuador and Senegal"),
            ("5:0", "Wales and England"),
            ("0:2", "Iran and United States"),
            ("2:0", "Australia and Denmark"),
            ("0:1", "Tunisia and France"),
            ("0:2", "Poland and Argentina"),
            ("0:2", "Saudi Arabia and Mexico"),
            ("2:0", "Croatia and Belgium"),
            ("0:2", "Canada and Morocco"),
            ("2:0", "Japan and Spain"),
            ("0:2", "Costa Rica and Germany"),
            ("0:2", "Ghana and Uruguay"),
            ("1:2", "Korea Republic and Portugal"),
            ("0:2", "Serbia and Switzerland"),
            ("0:2", "Cameroon and Brazil"),
            ("0:2", "Qatar and Iran"), # Round 16 49
            ("0:2", "Argentina and Denmark"), # 50
            ("cancel", "Qatar and Iran"), # Try cancelling in middle of group16
            ("0:2", "Argentina and Denmark"), # 50
            ("0:2", "France and Saudi Arabia"), # 51
            ("0:2", "England and Ecuador"), # 52
            ("0:2", "Spain and Canada"), # 53
            ("1:1", "DRAW"), # Disallow draws
            ("0:2", "Brazil and Ghana"), # 54
            ("0:2", "Belgium and Germany"), # 55
            ("0:2", "Portugal and Serbia"), # 56
            ("1:2", "Canada and Ghana"), # Quarter-finals 57
            ("0:2", "Iran and Denmark"), # 58
            ("0:2", "Germany and Serbia"), # 59
            ("0:2", "Saudi Arabia and Ecuador"), # 60
            ("0:2", "Ghana and Denmark"), # Semi-finals
            ("0:2", "Serbia and Ecuador"),
            ("0:2", "Ghana and Serbia"),
            ("0:2", "Denmark and Ecuador"),
            ("2:0", "CHAMP"),
        )
        for score, game in bets:
            with self.subTest(score=score, game=game):
                if game == "DRAW":
                    msg = "Draw in knockout stage is not allowed"
                elif game == "CHAMP":
                    msg = "Congrats Denmark is your World Cup 2022 Champion!"
                else:
                    msg = common + game + "?"
                if score == "cancel":
                    self.assert_answer(score, "OK. Canceled previous bet", msg)
                else:
                    self.assert_answer(score, msg)
