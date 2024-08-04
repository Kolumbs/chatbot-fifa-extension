"""Functions relatesd to FIFA World Cup"""
from dataclasses import dataclass, field

from .exceptions import DrawNotAllowed


groups = {
    "A": ("Germany", "Hungary", "Switzerland", "Scotland"),
    "B": ("Spain", "Croatia", "Italy", "Albania"),
    "C": ("Slovenia", "Denmark", "Serbia", "England"),
    "D": ("Netherlands", "France", "Poland", "Austria"),
    "E": ("Ukraine", "Slovakia", "Belgium", "Romania"),
    "F": ("Portugal", "Czechia", "Georgia", "Turkiye"),
}

qualifiers = (
    "Germany and Scotland",
    "Hungary and Switzerland",
    "Spain and Croatia",
    "Italy and Albania",
    "Poland and Netherlands",
    "Slovenia and Denmark",
    "England and Serbia",
    "Romania and Ukraine",
    "Belgium and Slovakia",
    "France and Austria",
    "Turkiye and Georgia",
    "Portugal and Czechia",
    "Croatia and Albania",
    "Germany and Hungary",
    "Scotland and Switzerland",
    "Slovenia and Serbia",
    "England and Denmark",
    "Italy and Spain",
    "Slovakia and Ukraine",
    "Poland and Austria",
    "Netherlands and France",
    "Georgia and Czechia",
    "Turkiye and Portugal",
    "Belgium and Romania",
    "Germany and Switzerland",
    "Scotland and Hungary",
    "Spain and Albania",
    "Croatia and Italy",
    "Netherlands and Austria",
    "France and Poland",
    "Slovenia and England",
    "Serbia and Denmark",
    "Romania and Slovakia",
    "Ukraine and Belgium",
    "Georgia and Portugal",
    "Czechia and Turkiye",
)

group16 = (
    "Switzerland and Italy",
    "Germany and Denmark",
    "England and Slovakia",
    "Spain and Georgia",
    "France and Belgium",
    "Portugal and Slovenia",
    "Romania and Netherlands",
    "Austria and Turkiye",
)

quarters = (
    "Spain and Germany",
    "Portugal and France",
    "England and Switzerland",
    "Netherlands and Turkiye",
)

finals = (
    "Spain and France",
    "England and Netherlands",
)

knockout_stage = None
(
    ("A1", "B2"),
    ("C1", "D2"),
    ("D1", "C2"),
    ("B1", "A2"),
    ("E1", "F2"),
    ("G1", "H2"),
    ("F1", "E2"),
    ("H1", "G2"),
)

quarter_finals = (
    (4, 5),
    (0, 1),
    (6, 7),
    (2, 3),
)

semi_finals = (
    (0, 1),
    (2, 3),
)


class BaseScorer:
    """Allows ranking teams by their points and goals"""

    def __init__(self, results):
        """initialise Scorer with results"""
        # pylint: disable=invalid-name
        self.results = results
        teams = set()
        for i in results:
            a, b = i.split(" and ", maxsplit=2)
            teams.add(a)
            teams.add(b)
        self._points = {i: 0 for i in teams}
        self._goal_diff = {i: 0 for i in teams}
        self._goals = {i: 0 for i in teams}
        for game, result in results.items():
            a, b = game.split(" and ", maxsplit=2)
            self._goals[a] += result[0]
            self._goals[b] += result[1]
            if result[0] == result[1]:
                self._points[a] += 1
                self._points[b] += 1
            elif result[0] > result[1]:
                self._points[a] += 3
                self._goal_diff[a] += result[0] - result[1]
                self._goal_diff[b] -= result[0] - result[1]
            else:
                self._points[b] += 3
                self._goal_diff[a] += result[0] - result[1]
                self._goal_diff[b] -= result[0] - result[1]

    def score(self, team):
        """return total points scored by team"""
        return self._points[team]

    def goal_diff(self, team):
        """return total points scored by team"""
        return self._goal_diff[team]

    def goals(self, team):
        """return total goals scored by team"""
        return self._goals[team]

    def triple_score(self, team):
        """return combined result of points, goals and goal diff"""
        return self.score(team), self.goal_diff(team), self.goals(team)

    def sort(self, teams):
        """perform basic sort
        (a) greatest number of points obtained in all group matches;
        (b) superior goal difference in all group matches;
        (c) greatest number of goals scored in all group matches.
        """
        sort = sorted(teams, key=self.goals, reverse=True)
        sort = sorted(sort, key=self.goal_diff, reverse=True)
        return sorted(sort, key=self.score, reverse=True)


class SubScorer(BaseScorer):
    """Handles subgroup scoring"""

    def __init__(self, subgroup, total_results):
        """Initialises only results for the subgroup"""
        results = {}
        for game in total_results:
            teams = game.split(" and ", maxsplit=2)
            if teams[0] in subgroup and teams[1] in subgroup:
                results[game] = total_results[game]
        BaseScorer.__init__(self, results)

    def sort(self, teams):
        """Sort in descending order
        Uses sort rules as defined by PointsScorer for when to resolve teams
        having equal point, goals and gola differences between

        Not implemented:
            highest teamconduct (yellow and red cards)
            drawing of lots by FIFA
        """
        return BaseScorer.sort(self, teams)


class PointsScorer(BaseScorer):
    """Allows to rank teams by their scores for FIFA tournaments"""

    def sort(self, teams):
        """Sort in descending order results of teams
        (a) greatest number of points obtained in all group matches;
        (b) superior goal difference in all group matches;
        (c) greatest number of goals scored in all group matches.
        (d) greatest number of points obtained in the group matches between the teams concerned;
        (e) superior goal difference resulting from the group matches between the teams concerned;
        (f) greatest number of goals scored in all group matches between the teams concerned;
        (g) highest team conduct score relating to the number of yellow and red cards
        obtained:
        – yellow card: minus 1 point
        – indirect red card (as a result of two yellow cards): minus 3 points
        – direct red card: minus 4 points
        – yellow card and direct red card: minus 5 points
        Only one of the above deductions shall be applied to a player in a single match.
        The team with the highest number of points shall be ranked highest.
        (h) drawing of lots by FIFA
        """
        teams = self._get_sorted_subgroups(teams)
        sort = BaseScorer.sort(self, teams)
        return sort

    def _get_sorted_subgroups(self, teams):
        """return teams sorted by subgroups if present"""
        teams = sorted(teams, key=self.triple_score, reverse=True)
        subgroups = []
        sub_score = set()
        i = -1
        for i in range(len(teams) - 1):
            if self.triple_score(teams[i]) == self.triple_score(teams[i+1]):
                sub_score.add(teams[i])
                sub_score.add(teams[i+1])
            else:
                if sub_score:
                    scorer = SubScorer(sub_score, self.results)
                    subgroups += scorer.sort(list(sub_score))
                    sub_score.clear()
                else:
                    subgroups.append(teams[i])
        if sub_score:
            scorer = SubScorer(sub_score, self.results)
            subgroups += scorer.sort(list(sub_score))
        else:
            if i > -1:
                subgroups.append(teams[i])
        return subgroups


def get_player_results(players, bets, count):
    """Calculate score for player bets against actual bets with a count of games
    return dictionary player: points
    """
    results = {i.name: 0 for i in players}
    for i, correct_bet in enumerate(bets[:count]):
        perfect_bet = False
        closest_betters = []
        closest_diff = 100
        for player in players:
            bet_status, bet_diff = get_score_bet(correct_bet[1], player.bets[i][1])
            if bet_status and bet_diff == 0:
                perfect_bet = True
                results[player.name] += 3
            elif bet_status:
                results[player.name] += 1
                if bet_diff < closest_diff:
                    closest_betters = [player.name]
                    closest_diff = bet_diff
                elif bet_diff == closest_diff:
                    closest_betters.append(player.name)
        if not perfect_bet:
            for player in closest_betters:
                results[player] += 1
    return results

def get_score_bet(actual, prediction):
    """get a difference between actual and prediction and if winner was correct"""
    if actual == prediction:
        return True, 0
    if actual[0] == actual[1] and prediction[0] == prediction[1]:
        return True, get_diff(actual, prediction)
    if actual[0] > actual[1] and prediction[0] > prediction[1]:
        return True, get_diff(actual, prediction)
    if actual[0] < actual[1] and prediction[0] < prediction[1]:
        return True, get_diff(actual, prediction)
    return False, -1

# pylint: disable=invalid-name
def get_diff(a, b):
    """total diff between a and b tuples"""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def get_group_winners(results):
    """Calculate 1st and 2nd place from results and return it
    """
    if len(results) != 6:
        raise RuntimeError("Total of 6 games should have been played in a group")
    teams = list(set(i.split(" and ")[0] for i in results))
    if len(teams) != 4:
        raise RuntimeError("There must be 4 unique teams in group")
    scorer = PointsScorer(results)
    teams = scorer.sort(teams)
    return teams[0], teams[1]


def add_qualifier_stage(bets):
    """Adds to bets games for qualifying round"""
    return bets + [[i, 0] for i in qualifiers]


def add_more_games(bets, games):
    """Add more games to bets list."""
    bets += [[i, 0] for i in games]


def get_group16_stage(bets):
    """Gives games for group16"""
    knockout = []
    result_table = {i: {} for i in "ABCDEFGH"}
    # pylint: disable=consider-using-dict-items
    group_map = {j: i for i in groups for j in groups[i]}
    if len(bets) != 48:
        raise RuntimeError("There must be 48 games in qualifier bets")
    for game, result in bets:
        group = group_map[game.split(" and ")[0]]
        result_table[group][game] = result
    group16 = {}
    for group, results in result_table.items():
        group16[group + "1"], group16[group + "2"] = get_group_winners(results)
    for i in knockout_stage:
        game = group16[i[0]] + " and " + group16[i[1]]
        knockout.append([game, 0])
    return knockout

def get_knock_win(bet):
    """Returns name of the knockout winner"""
    team1, team2 = bet[0].split(" and ", maxsplit=2)
    return team1 if bet[1][0] > bet[1][1] else team2

def get_knock_loser(bet):
    """Returns name of the knockout loser"""
    team1, team2 = bet[0].split(" and ", maxsplit=2)
    return team1 if bet[1][0] < bet[1][1] else team2

def get_quarters_stage(bets):
    """Gives quarter-final games"""
    if len(bets) != 8:
        raise RuntimeError("There must be 8 games played in round of 16")
    quarters = []
    quarters.append([get_knock_win(bets[4]) + " and " + get_knock_win(bets[5]), 0])
    quarters.append([get_knock_win(bets[0]) + " and " + get_knock_win(bets[1]), 0])
    quarters.append([get_knock_win(bets[6]) + " and " + get_knock_win(bets[7]), 0])
    quarters.append([get_knock_win(bets[2]) + " and " + get_knock_win(bets[3]), 0])
    return quarters


def get_semis_stage(bets):
    """return list of semi-finals teams"""
    if len(bets) != 4:
        raise RuntimeError("There must be 4 games played in quarter-finals")
    semis = []
    semis.append([get_knock_win(bets[0]) + " and " + get_knock_win(bets[1]), 0])
    semis.append([get_knock_win(bets[2]) + " and " + get_knock_win(bets[3]), 0])
    return semis


def get_finals_stage(bets):
    """return list of finals teams"""
    if len(bets) != 2:
        raise RuntimeError("There must be 2 games played in semi-finals")
    finals = []
    finals.append([get_knock_loser(bets[0]) + " and " + get_knock_loser(bets[1]), 0])
    finals.append([get_knock_win(bets[0]) + " and " + get_knock_win(bets[1]), 0])
    return finals


def get_next_qualifier_bet(bets):
    """Gives next match name for which there is missing bet
    Otherwise return empty string
    """
    for i in qualifiers:
        if i not in bets:
            return i
    return ""


def get_next_bet(bets):
    """Gives next match name that misses results"""
    for game, value in bets.items():
        if not value:
            return game
    return ""


def get_previous_group16_bet(bets):
    """Gives next match name that misses results"""
    for game, value in bets.items():
        if value:
            return game
    return ""


def contains_bets(bets):
    """Returns true or false depending if there is at least one valid bet or not"""
    if not bets:
        raise RuntimeError("There must be at least one bet to check for bets")
    return bool(bets[0][1])


def bets_complete(bets):
    """Returns count of completed bets"""
    count = 0
    for bet in bets:
        if bet[1]:
            count += 1
    return count


def remove_previous_bet(bets):
    """Removes result for last bet
    Returns removed game
    """
    for bet in bets[::-1]:
        if bet[1]:
            bet[1] = 0
            return bet[0]
    return ""


@dataclass
class Player:
    name: str
    bets: list = field(default_factory=list)


class Scorer:
    """Takes bets from each player."""

    def __init__(self, player):
        """
        player is an object that will be updated during processing

        player.next_bet is an external flag that is changed during object's lifetime
        player.bets is a dictionary that is changed during object's lifetime

        bet_results is a key/value map that contains actual results of the cup
        """
        self.player = player
        if not self.player.bets:
            self.player.bets = add_qualifier_stage(self.player.bets)

    def get_next_bet(self):
        """returns next available bet"""
        for bet in self.player.bets:
            if not bet[1]:
                return bet[0]
        return ""

    def load_next_bet(self):
        """looks into player.bets and loads next required bet to player.next_bet
        if there is no bet left does nothing
        """
        bet_count = bets_complete(self.player.bets)
        bet_results = bets_complete(self.bet_results)
        if bet_count == 48 and bet_results > 47:
            new = get_group16_stage(self.bet_results[:48])
            self.player.bets = self.player.bets[:48] + new
        elif bet_count == 56 and bet_results > 55:
            new = get_quarters_stage(self.bet_results[48:56])
            self.player.bets = self.player.bets[:56] + new
        elif bet_count == 60 and bet_results > 59:
            new = get_semis_stage(self.bet_results[56:60])
            self.player.bets = self.player.bets[:60] + new
        elif bet_count == 62 and bet_results > 61:
            new = get_finals_stage(self.bet_results[60:62])
            self.player.bets = self.player.bets[:62] + new
        self.player.next_bet = self.get_next_bet()

    def load_next_admin_bet(self):
        """loads next bet for admin"""
        bet_count = bets_complete(self.player.bets)
        if bet_count == 48:
            self.player.bets = (self.player.bets[:48]
                                + get_group16_stage(self.player.bets[:48]))
        elif bet_count == 56:
            self.player.bets = (self.player.bets[:56]
                               + get_quarters_stage(self.player.bets[48:56]))
        elif bet_count == 60:
            self.player.bets = (self.player.bets[:60]
                               + get_semis_stage(self.player.bets[56:60]))
        elif bet_count == 62:
            self.player.bets = (self.player.bets[:62]
                               + get_finals_stage(self.player.bets[60:62]))
        self.player.next_bet = self.get_next_bet()

    def cancel_previous_bet(self):
        """cancels previous bet, clears player.next_bet flag and returns canceled game"""
        previous = remove_previous_bet(self.player.bets)
        self.player.next_bet = ""
        return previous

    def add_bet(self, result):
        """adds bet of the player"""
        result = [int(i) for i in result]
        for i, bet in enumerate(self.player.bets):
            if not bet[1]:
                if i > 48 and result[0] == result[1]:
                    raise DrawNotAllowed("Draws are not allowed in knockout stages")
                bet[1] = result
                self.player.next_bet = ""
                break


def results_summary(players, score, game):
    """Return summary of results for players."""
    results = get_player_results(players.values(), score.player.bets, game)
    results = [(k, v) for k, v in results.items()]
    results.sort(key=lambda x: x[1], reverse=True)
    for i in results:
        print(i[0], i[1])
    print("Nākamā spēle:", score.player.bets[game][0])
    for i in players.values():
        print(i.name, i.bets[game][1])
    print(score.player.bets[game])
