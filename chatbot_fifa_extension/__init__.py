"""Package allows to extend a chatbot with FIFA World Cup results prediction game"""

from zoozl.chatbot import Interface

import membank

from . import fifa, memories
from .exceptions import DrawNotAllowed


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

    def load(self, root):
        """Load database."""
        my_conf = root.conf["chatbot_fifa_extension"]
        if "database_path" not in my_conf or "administrator" not in my_conf:
            msg = "FIFAGame requires a database path and administrator in config"
            raise RuntimeError(msg)
        url = f'sqlite://{my_conf["database_path"]}/db'
        self.mem = membank.LoadMemory(url)
        self._is_complete = False
        self.conf = my_conf

    def consume(self, context, package):
        if package.last_message.text == "admin mode":
            package.conversation.data["admin mode"] = {}
            package.callback("Please identify yourself")
        elif "admin mode" in package.conversation.data:
            self.do_admin(package)
        elif "contest" not in package.conversation.data:
            package.callback("What is your contest code?")
            package.conversation.data["contest"] = None
        elif not package.conversation.data["contest"]:
            if "create contest" in package.last_message.text:
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
            contest = self.mem.get.contest(code=package.last_message.text)
            if contest:
                package.conversation.data["contest"] = contest
                package.callback("OK. Now please state your name!")
            else:
                package.callback("Such contest does not exist. Try again")
                package.callback(
                    "If you want to create new contest call create contest"
                )

    def create_contest(self, package):
        """creates new contest"""
        code = package.last_message.text
        contest = self.mem.get.contest(code=code)
        if not contest:
            contest = memories.Contest(package.last_message.text)
            self.mem.put(contest)
            package.callback("OK. New contest created")
        else:
            package.callback("Such contest already exists!")
        package.conversation.data["contest"] = contest
        package.callback("Now please state your name!")

    def add_player(self, package):
        """creates or restores to existing player"""
        player = self.mem.get.player(name=package.last_message.text)
        if not player:
            player = memories.Player(name=package.last_message.text)
            self.mem.put(player)
            package.conversation.data["contest"].players.append(player.name)
            self.mem.put(package.conversation.data["contest"])
            package.callback(f"Nice to meet you {player.name}")
        else:
            if player.name not in package.conversation.data["contest"].players:
                package.conversation.data["contest"].players.append(player.name)
                self.mem.put(package.conversation.data["contest"])
            package.callback(f"Welcome back {player.name}")
        package.conversation.data["player"] = player
        player.next_bet = ""
        self.get_bets(package)
        self.mem.put(player)

    # pylint: disable=too-many-branches
    def get_bets(self, package):
        """get all bet scores from the player"""
        admin = self.mem.get.player(name=self.conf["administrator"])
        bet = fifa.WorldCup(package.conversation.data["player"], admin.bets)
        if not bet.player.next_bet:
            if self.conf["administrator"] == package.conversation.data["player"].name:
                bet.load_next_admin_bet()
            else:
                bet.load_next_bet()
            if bet.player.next_bet:
                bet_call = "What will be result between " + bet.player.next_bet + "?"
                package.callback(bet_call)
            else:
                complete = fifa.bets_complete(admin.bets)
                if complete < 48:
                    package.callback("Please wait while group stage ends")
                elif complete < 56:
                    package.callback("Please wait while round 16 ends")
                elif complete < 60:
                    package.callback("Please wait while quarter finals end")
                elif complete < 62:
                    package.callback("Please wait while semi finals end")
                else:
                    champ = fifa.get_knock_win(bet.player.bets[-1])
                    package.callback(
                        f"Congrats {champ} is your World Cup 2022 Champion!"
                    )
                    package.callback("Your bets are finalised! Good luck!!!")
                    self._is_complete = True
        else:
            if "cancel" in package.last_message.text:
                self.cancel_bet(bet, package)
            else:
                result = package.last_message.text.split(":", maxsplit=2)
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

    def do_admin(self, package):
        """admin mode handling"""
        admin_conf = package.conversation.data["admin mode"]
        if not admin_conf:
            if package.last_message.text == self.conf["administrator"]:
                package.callback("You are identified. Commands available")
                admin_conf["command"] = ""
                admin_conf["data"] = {}
            else:
                package.callback("You are not identified. Please identify")
        else:
            if package.last_message.text == "add players to contest":
                admin_conf["command"] = "add_player_to_contest"
            if package.last_message.text == "predictions":
                admin_conf["command"] = "predictions"
            if package.last_message.text == "results":
                admin_conf["command"] = "results"
            if "command" in admin_conf and admin_conf["command"]:
                executor = getattr(self, admin_conf["command"])
                executor(package)
            else:
                package.callback("State your admin command")

    def add_player_to_contest(self, package):
        """add player name to contest"""
        data = package.conversation.data["admin mode"]["data"]
        if "done" == package.last_message.text:
            package.callback("OK.")
            package.conversation.data["admin mode"] = {}
        elif "contest" not in data:
            package.callback("State name of contest")
            data["contest"] = ""
        elif not data["contest"]:
            data["contest"] = package.last_message.text
            contest = self.mem.get.contest(code=package.last_message.text)
            if not contest:
                package.callback(f"Contest {package.last_message.text} not found")
            else:
                data["contest"] = contest
                package.callback("Contest is {data['contest'].code}")
                package.callback("State name of the player to add")
        else:
            player = self.mem.get.player(name=package.last_message.text)
            if not player:
                package.callback("Player {package.last_message.text} does not exist")
            else:
                name = player.name
                if name not in data["contest"].players:
                    data["contest"].players.append(name)
                    self.mem.put(data["contest"])
                package.callback("OK. Added")

    def predictions(self, package):
        """return predictions of all players within contest"""
        data = package.conversation.data["admin mode"]["data"]
        if "contest" not in data:
            package.callback("For which contest?")
            data["contest"] = ""
        elif not data["contest"]:
            contest = package.last_message.text
            contest = self.mem.get.contest(code=contest)
            if not contest:
                package.callback(f"Contest {package.last_message.text} not found")
            else:
                admin = self.mem.get.player(name=self.conf["administrator"])
                index = fifa.bets_complete(admin.bets)
                text = self._get_predictions(contest.players, admin.bets, index)
                if 31 < index < 48:
                    text += self._get_predictions(
                        contest.players, admin.bets, index + 1
                    )
                package.callback(text.strip())

    def _get_predictions(self, players, bet_results, index):
        """get predictions for players for one game"""
        text = bet_results[index][0] + " "
        for i in players:
            player = self.mem.get.player(name=i)
            if player:
                text += player.name + " "
                if not player.bets[index][1]:
                    text += "missing bets"
                else:
                    text += str(player.bets[index][1][0])
                    text += ":"
                    text += str(player.bets[index][1][1])
                text += " "
        return text

    def results(self, package):
        """return results of all players within contest"""
        data = package.conversation.data["admin mode"]["data"]
        if "contest" not in data:
            package.callback("For which contest?")
            data["contest"] = ""
        elif not data["contest"]:
            contest = package.last_message.text
            contest = self.mem.get.contest(code=contest)
            if not contest:
                package.callback(f"Contest {package.last_message.text} not found")
            else:
                admin = self.mem.get.player(name=self.conf["administrator"])
                index = fifa.bets_complete(admin.bets)
                players = []
                for name in contest.players:
                    player = self.mem.get.player(name=name)
                    if player.name != self.conf["administrator"]:
                        players.append(self.mem.get.player(name=name))
                results = fifa.get_player_results(players, admin.bets, index)
                results = sorted(
                    [key + " " + str(value) for key, value in results.items()],
                    key=lambda x: int(x.split(" ", maxsplit=2)[1]),
                    reverse=True,
                )
                package.callback(" ".join(results))
