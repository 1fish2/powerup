#!/usr/bin/env python

"""
FRC PowerUp game score simulation.

TODO: Robot behaviors, driver behaviors, queued power-ups;
More scoring: auto-run reach the line, parked, climbed, ...;
Robot locations:
    Exchange zone {red, blue}
    Portal {red, blue} x {front, back} -- Scoring Table is at the back side
    Power Cube zone {red, blue}
    Switch fence {red, blue}
    outer zone {red, blue} outside the auto-line
    inner zone {red, blue} inside the auto-line
    Platform zone {red, blue} (climbed, parked, or not)
    Null Territory {front, back}
Cube locations:
    Exchange zone {red, blue}
    Portal {red, blue} x {front, back}
    Power Cube zone {red, blue}
    Switch fence {red, blue}
    outer zone {red, blue} outside the auto-line (excluding the Power Cube zones)
    inner zone {red, blue} inside the auto-line (excluding the Power Cube zones)
    Platform zone {red, blue} (excluding the Switch fences)
    Null Territory {front, back}
    Switch plate {red, blue} x {front, back}
    Scale plate {front, back}
    Vault {red, blue} x {force, levitate, boost}
    in a Robot {red 1 - 3, blue 1 - 3}
Power-ups {red, blue} x {force, levitate, boost} {unused, queued, played};
Portals;
Ranking points: 2 for win, 1 for tie, +1 for 3-robot climb, +1 for auto-quest
(3 auto-runs AND own your switch).
Enforce various rules, e.g. at least 5 cubes in each portal at start-of-match.

TODO: Output one CSV row per time step:
    Time
    Scores
    Switch and Scale ownership, #cubes, TODO: also forced and boosted state?
    Robots: location, #cubes [0 .. 1], {climbed, parked, not}, current action
    Other cube locations

Example robot actions: "scoring in switch", "getting cube from left portal",
"going to climb", "climbing".

Maybe split this file into framework simulation.py, agents, and game.py.
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
        """Called once per time step to update this Agent."""
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


class Scale(Agent):
    """A Scale, also the base class for Switch."""
    def __init__(self, front_color):
        """
        :param front_color: RED or BLUE, selected by the FMS
        """
        super(Scale, self).__init__()
        self.front_color = front_color

        self.cubes = [0, 0]  # [front, back] side cube counts
        self.forced = False
        self.force_timeout = 0
        self.force_alliance = ''
        self.boosted = False
        self.boost_timeout = 0
        self.boost_alliance = ''
        self.previous_owner = ''

    def add_cube(self, side):
        """Add a cube to the front (0) or back (1) side of the Switch."""
        self.cubes[side] += 1

    def force(self, alliance):
        """Start an alliance Force."""
        if self.autonomous:
            raise RuntimeError("Can't Force during autonomous")
        self.forced = True
        self.force_timeout = self.time + FORCE_SECS
        self.force_alliance = alliance

    def boost(self, alliance):
        """Start an alliance Boost."""
        if self.autonomous:
            raise RuntimeError("Can't Boost during autonomous")
        self.boosted = True
        self.boost_timeout = self.time + BOOST_SECS
        self.boost_alliance = alliance

    def update(self, time):
        super(Scale, self).update(time)
        if self.forced and time >= self.force_timeout:
            self.forced = False
            self.force_alliance = ''
        if self.boosted and time >= self.boost_timeout:
            self.boosted = False
            self.boost_alliance = ''

    def owner(self):
        """Returns which alliance currently "owns" this Scale: RED, '', or BLUE."""
        if self.forced:
            return self.force_alliance
        tilt = self.cubes[0].__cmp__(self.cubes[1])  # <, ==, > :: -1, 0, 1
        return (self.front_color.opposite, '', self.front_color)[tilt + 1]

    def score(self):
        """Returns (red_score, blue_score) earned this time step."""
        owner = self.owner()
        boosted = self.boosted and self.boost_alliance is owner
        value = 2 if self.autonomous or boosted else 1
        if owner is not self.previous_owner:  # just established ownership
            self.previous_owner = owner
            value *= 2
        return value if owner is RED else 0, value if owner is BLUE else 0


class Switch(Scale):
    def __init__(self, alliance_end, front_color):
        """
        :param alliance_end: RED or BLUE end of the field
        :param front_color: RED or BLUE, selected by the FMS
        """
        super(Switch, self).__init__(front_color)
        self.alliance_end = alliance_end

    def force(self, alliance):
        """Start an alliance Force; no-op if this isn't the alliance's Switch."""
        if alliance is self.alliance_end:
            super(Switch, self).force(alliance)

    def boost(self, alliance):
        """Start an alliance Boost; no-op if this isn't the alliance's Switch."""
        if alliance is self.alliance_end:
            super(Switch, self).boost(alliance)

    def owner(self):
        o = super(Switch, self).owner()
        return o if o is self.alliance_end else ''


class PowerUpGame(Simulation):
    def __init__(self):
        super(PowerUpGame, self).__init__()
        # TODO: An initial-conditions vector for the FMS choices.
        switch_front_color = RED
        scale_front_color = BLUE

        self.red_score = 0
        self.blue_score = 0

        self.robots = [Robot(alliance, player) for alliance in (RED, BLUE) for player in xrange(1, 4)]

        self.seesaws = [Switch(alliance, switch_front_color) for alliance in (RED, BLUE)]
        self.seesaws.append(Scale(scale_front_color))

        for agent in chain(self.robots, self.seesaws):
            self.add(agent)

    def tick(self):
        super(PowerUpGame, self).tick()
        for seesaw in self.seesaws:
            red, blue = seesaw.score()
            self.red_score += red
            self.blue_score += blue

    def play(self):
        """Play out the simulated game."""
        for t in xrange(GAME_SECS):
            self.tick()
            # TODO: Output a CSV row of score and state data.
        print "Final score Red: {}, Blue: {}".format(self.red_score, self.blue_score)

    def force(self, alliance):
        # TODO: Switch, Scale, or both depending on #cubes.
        # TODO: Once per type per alliance, with queuing.
        for seesaw in self.seesaws:
            seesaw.force(alliance)

    def boost(self, alliance):
        # TODO: Switch, Scale, or both depending on #cubes.
        # TODO: Once per type per alliance, with queuing.
        for seesaw in self.seesaws:
            seesaw.boost(alliance)


if __name__ == "__main__":
    game = PowerUpGame()
    game.play()
