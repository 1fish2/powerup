"""
Simulation framework for FRC Powerup sim.

TODO: The rest of scoring, ranking points, scale, robot behaviors, driver behaviors.
TODO: Using RED/''/BLUE strings seems Pythonic but would integers be simpler?
"""

from itertools import chain

# Alliance colors.
RED = 'red'
BLUE = 'blue'

AUTONOMOUS_SECS = 15
TELEOP_SECS = 2 * 60 + 15
GAME_SECS = AUTONOMOUS_SECS + TELEOP_SECS
BOOST_SECS = 10
FORCE_SECS = 10

CROSS_LINE_AUTO_POINTS = 5
GAIN_SWITCH_AUTO_POINTS = 2
GAIN_SCALE_AUTO_POINTS = 2


def opposite(color):
    return {RED: BLUE, BLUE: RED}[color]


class Agent(object):
    """
    An Agent has time-based behaviors in a Simulation.
    """

    def __init__(self):
        self.simulation = None

    @property
    def time(self):
        return self.simulation.time

    @property
    def autonomous(self):
        return self.simulation.autonomous

    def update(self, time):
        pass


class GameOver(Exception):
    pass


class Simulation(object):
    """
    A Simulation advances time and updates its Agents.
    """

    def __init__(self):
        self.time = 0
        self.agents = []

    @property
    def autonomous(self):
        return self.time < AUTONOMOUS_SECS

    def add(self, agent):
        agent.simulation = self
        self.agents.append(agent)

    def tick(self):
        time = self.time + 1
        if time >= GAME_SECS:
            raise GameOver()
        self.time = time

        for agent in self.agents:
            agent.update(time)


class Robot(Agent):
    def __init__(self, alliance, player):
        """
        :param alliance: RED or BLUE
        :param player: 1, 2, or 3
        """
        super(Robot, self).__init__()
        self.alliance = alliance
        self.player = player

        self.has_cube = False

    def pickup(self):
        # TODO: Check if not self.has_cube? Check and decrement the number of cubes here.
        self.has_cube = True

    def drop(self):
        # TODO: Check if self.has_cube? Increment the number of cubes here.
        self.has_cube = False


class Switch(Agent):
    def __init__(self, alliance_end, front_color):
        """
        :param alliance_end: RED or BLUE end of the field
        :param front_color: RED or BLUE, selected by the FMS
        """
        super(Switch, self).__init__()
        self.alliance_end = alliance_end
        self.front_color = front_color

        self.cubes = [0, 0]  # [front, back] side cube counts
        self.forced = False
        self.forced_timeout = 0
        self.boosted = False
        self.boost_timeout = 0

    def add_cube(self, side):
        self.cubes[side] += 1

    def force(self, alliance):
        if alliance == self.alliance_end:
            self.forced = True
            self.forced_timeout = self.time + FORCE_SECS

    def boost(self, alliance):
        self.boosted = True
        self.boost_timeout = self.time + BOOST_SECS

    def update(self, time):
        super(Switch, self).update(time)
        if time >= self.boost_timeout:
            self.boosted = False
        if time >= self.forced_timeout:
            self.forced = False

    def controlled_by(self):
        """
        :return: RED, '', or BLUE, indicating which alliance controls this Switch.
        """
        if self.forced:
            return self.alliance_end
        tilt = self.cubes[0].__cmp__(self.cubes[1])  # <, ==, > :: -1, 0, 1
        return [opposite(self.front_color), '', self.front_color][tilt + 1]

    def score(self):
        """
        :return: (red_score, blue_score) earned this time unit
        """
        # TODO: Add points when gaining control of the switch? Or is it ownership at end of the period?
        # Can an alliance boost a Switch when the other alliance is scoring it?
        value = (2 if self.autonomous else 1) * (2 if self.boosted else 1)
        c = self.controlled_by()
        return value if c == RED else 0, value if c == BLUE else 0


class PowerupGame(Simulation):
    def __init__(self):
        super(PowerupGame, self).__init__()
        self.red_score = 0
        self.blue_score = 0

        self.robots = [Robot(alliance, player) for alliance in (RED, BLUE) for player in xrange(1, 4)]

        switch_colors = {RED: RED, BLUE: RED}  # TODO: Define an initial-conditions vector for these FMS choices
        self.switches = [Switch(alliance, switch_colors[alliance]) for alliance in (RED, BLUE)]

        for agent in chain(self.robots, self.switches):
            self.add(agent)

    def tick(self):
        super(PowerupGame, self).tick()
        for switch in self.switches:
            red, blue = switch.score()
            self.red_score += red
            self.blue_score += blue
