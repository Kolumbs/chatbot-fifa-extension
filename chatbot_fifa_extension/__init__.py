"""Package allows to extend a chatbot with FIFA World Cup results prediction game"""
from chatbot import Interface, Message

import membank

from chatbot_fifa_extension import fifa, memories
from .exceptions import *


def is_valid_result(result, callback):
    """Validates that result is input correctly"""
    if len(result) != 2:
        callback("Result must be two numbers with ':'(colon) in between")
        callback("If you want to cancel previous result, ask cancel")
        return False
    for i in result[0]:
        if not i.isdigit():
            callback(f"First result must be a number, was {result[0]}")
            return False
    for i in result[1]:
        if not i.isdigit():
            callback(f"Second result must be a number, was {result[1]}")
            return False
    return True


class FIFAGame(Interface):
    """Allows to make predictions for World Cup results"""
    aliases = {"play fifa", "play world cup"}

    def __init__(self, conf):
        Interface.__init__(self, conf)
        if "database_path" not in conf:
            raise RuntimeError("FIFAGame requires a database path")
        url = f'sqlite://{conf["database_path"]}/db'
        self.mem = membank.LoadMemory(url)
        self._is_complete = False

    def consume(self, package):
        if "contest" not in package.conversation.data:
            package.callback("What is your contest code?")
            package.conversation.data["contest"] = None
        elif not package.conversation.data["contest"]:
            if "create contest" in package.message.text:
                package.conversation.data["create contest"] = True
                package.callback("Please state the name of the contest")
            else:
                self.check_contest(package)
        elif "player" not in package.conversation.data:
            self.add_player(package)
        else:
            self.get_bets(package)
            self.mem.put(package.conversation.data["player"])

    def check_contest(self, package):
        """try to find contest otherwise suggest to create one"""
        if "create contest" in package.conversation.data:
            self.create_contest(package)
        else:
            contest = self.mem.get.contest(code=package.message.text)
            if contest:
                package.conversation.data["contest"] = contest
                package.callback("OK. Now please state your name!")
            else:
                package.callback("Such contest does not exist. Try again")
                package.callback("If you want to create new contest call create contest")

    def create_contest(self, package):
        """creates new contest"""
        code = package.message.text
        contest = self.mem.get.contest(code=code)
        if not contest:
            contest = memories.Contest(package.message.text)
            self.mem.put(contest)
            package.callback("OK. New contest created")
        else:
            package.callback("Such contest already exists!")
        package.conversation.data["contest"] = contest
        package.callback("Now please state your name!")

    def add_player(self, package):
        """creates or restores to existing player"""
        player = self.mem.get.player(name=package.message.text)
        if player and player.name not in package.conversation.data["contest"].players:
            package.conversation.data["contest"].players.append(player.name)
            package.callback(f"Welcome back {player.name}")
        else:
            player = memories.Player(name=package.message.text)
            self.mem.put(player)
            package.conversation.data["contest"].players.append(player.name)
            package.callback(f"Nice to meet you {player.name}")
        package.conversation.data["player"] = player
        player.next_bet = ""
        self.get_bets(package)
        self.mem.put(player)

    def get_bets(self, package):
        """get all bet scores from the player"""
        bet = fifa.WorldCup(package.conversation.data["player"])
        if not bet.player.next_bet:
            bet.load_next_bet()
            if bet.player.next_bet:
                bet_call = "What will be result between " + bet.player.next_bet + "?"
                package.callback(bet_call)
            else:
                champ = fifa.get_knock_win(bet.player.bets[-1])
                package.callback(f"Congrats {champ} is your World Cup 2022 Champion!")
                package.callback("Your bets are finalised! Good luck!!!")
                self._is_complete = True
        else:
            if "cancel" in package.message.text:
                self.cancel_bet(bet, package)
            else:
                result = package.message.text.split(":", maxsplit=2)
                if is_valid_result(result, package.callback):
                    try:
                        bet.add_bet(result)
                        self.get_bets(package)
                    except DrawNotAllowed:
                        package.callback("Draw in knockout stage is not allowed")

    def is_complete(self):
        return self._is_complete

    def cancel_bet(self, bet, package):
        """cancel previous bet"""
        previous = bet.cancel_previous_bet()
        if previous:
            package.callback("OK. Canceled previous bet")
            self.get_bets(package)
        else:
            package.callback("Nothing to cancel. Enter first bet")
