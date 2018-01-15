#!/usr/bin/env python

"""
FRC PowerUp game score simulation.

TODO: Scale, robot behaviors, driver behaviors;
More scoring: auto-run across the line, parked on platform, climb, ...;
Robot locations:
    outer zone {red, blue} outside the auto-line (TODO: Finer-grained?),
    inner zone {red, blue} inside the auto-line (TODO: Finer-grained?),
    platform zone {red, blue},
    null territory {front, back},
Cube locations (optionally preloaded in robots at game start):
    portals {red, blue} x {front, back},
    exchange (zone) {red, blue},
    outer zone {red, blue} outside the auto-line,
    inner zone {red, blue} inside the auto-line,
    platform zone {red, blue},
    null territory {front, back},
    on a Switch plate {red, blue} x {front, back},
    on a Scale plate {front, back},
    in a robot {red 1 - 3, blue 1 - 3},
    Vault {red, blue} x {force, levitate, boost}.
Power-ups {force, levitate, boost} {unused, queued, played};
Portals;
Ranking points: 2 for win, 1 for tie, +1 for 3-robot climb, +1 for auto-quest (3 auto-runs AND own your switch).
Enforce various rules, e.g. at least 5 cubes in each portal at start-of-match.

TODO: Track details and output CSV data. One row per second? Columns for all the scoring components + RPs?
"""

from itertools import chain

AUTONOMOUS_SECS = 15
TELEOP_SECS = 2 * 60 + 15
GAME_SECS = AUTONOMOUS_SECS + TELEOP_SECS
ENDGAME_SECS = 30
BOOST_SECS = 10
FORCE_SECS = 10

CROSS_LINE_AUTO_POINTS = 5
GAIN_SWITCH_AUTO_POINTS = 2
GAIN_SCALE_AUTO_POINTS = 2


class Color(str):
    pass


# Alliance colors.
RED, BLUE = Color('red'), Color('blue')
RED.opposite, BLUE.opposite = BLUE, RED


class Agent(object):
    """An Agent in a Simulation has time-based behaviors."""

    def __init__(self):
        self.simulation = None

    @property
    def time(self):
        return self.simulation.time

    @property
    def autonomous(self):
        return self.simulation.autonomous

    def update(self, time):
        """Update this Agent for the new value of time."""
        pass


class GameOver(Exception):
    pass


class Simulation(object):
    """A Simulation advances time and updates its Agents."""

    def __init__(self):
        self.time = 0
        self.agents = []

    @property
    def autonomous(self):
        """Return True during the autonomous period."""
        return self.time < AUTONOMOUS_SECS

    def add(self, agent):
        """Add an Agent to this Simulation."""
        agent.simulation = self
        self.agents.append(agent)

    def tick(self):
        """Advance time by 1 second, updating all Agents."""
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
        """Pick up a cube here."""
        # TODO: Check if not self.has_cube? Check and decrement the number of cubes in this place.
        self.has_cube = True

    def drop(self):
        """Drop a cube here."""
        # TODO: Check if self.has_cube? Increment the number of cubes in this place.
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
        """Add a cube to the front (0) or back (1) side of the Switch."""
        self.cubes[side] += 1

    def force(self, alliance):
        if alliance == self.alliance_end:
            self.forced = True
            self.forced_timeout = self.time + FORCE_SECS

    def boost(self, alliance):
        """Start an alliance Boost now."""
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
        :return: RED, '', or BLUE, indicating which alliance currently controls this Switch.
        """
        if self.forced:
            return self.alliance_end
        tilt = self.cubes[0].__cmp__(self.cubes[1])  # <, ==, > :: -1, 0, 1
        return [self.front_color.opposite, '', self.front_color][tilt + 1]

    def score(self):
        """
        :return: (red_score, blue_score) earned this time unit
        """
        # TODO: Add points when gaining control of the switch? Or is it ownership at end of the period?
        # Can an alliance boost a Switch when the other alliance is scoring it?
        value = (2 if self.autonomous else 1) * (2 if self.boosted else 1)
        c = self.controlled_by()
        return value if c == RED else 0, value if c == BLUE else 0


class PowerUpGame(Simulation):
    def __init__(self):
        super(PowerUpGame, self).__init__()
        self.red_score = 0
        self.blue_score = 0

        self.robots = [Robot(alliance, player) for alliance in (RED, BLUE) for player in xrange(1, 4)]

        # TODO: Define an initial-conditions vector for these FMS choices
        switch_front_colors = {RED: RED, BLUE: RED}  # alliance_end -> front_color
        self.switches = [Switch(alliance, switch_front_colors[alliance]) for alliance in (RED, BLUE)]

        for agent in chain(self.robots, self.switches):
            self.add(agent)

    def tick(self):
        super(PowerUpGame, self).tick()
        for switch in self.switches:
            red, blue = switch.score()
            self.red_score += red
            self.blue_score += blue

    def play(self):
        """Play out the simulated game."""
        for t in xrange(GAME_SECS):
            self.tick()
            # TODO: Output a CSV row of score data?
        print "Final score Red: {}, Blue: {}".format(self.red_score, self.blue_score)


if __name__ == "__main__":
    game = PowerUpGame()
    game.play()
