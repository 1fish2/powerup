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


def plural(count, singular_form, plural_form):
    """Returns singular_form for plural_form as befits count."""
    return singular_form if count == 1 else plural_form


def num_cubes(count):
    """Returns '0 Cubes' or '1 Cube' or ..."""
    return "{} {}".format(count, plural(count, 'Cube', 'Cubes'))


class Color(str):
    """An alliance color value that allows a .opposite property."""
    pass


# Singleton alliance Color objects.
RED, BLUE = Color('red'), Color('blue')
RED.opposite, BLUE.opposite = BLUE, RED


class Score(object):
    """An incremental or final match score."""

    @classmethod
    def pick(cls, color, value):
        # type: (Color, int) -> Score
        """Returns a Score where RED or BLUE or neither gets the given value."""
        return cls(value if color is RED else 0, value if color is BLUE else 0)

    def __init__(self, red, blue):
        # type: (int, int) -> None
        """Returns a Score with the given red and blue point values."""
        self._red_points = red
        self._blue_points = blue

    @property
    def red(self):
        """Returns red's points."""
        return self._red_points

    @property
    def blue(self):
        """Returns blue's points."""
        return self._blue_points

    def __repr__(self):
        return 'Score(red={}, blue={})'.format(self.red, self.blue)

    def __add__(self, other):
        """Adds two Score values. Useful with sum([scores...], Score.ZERO)."""
        return type(self)(self.red + other.red, self.blue + other.blue)


Score.ZERO = Score(0, 0)


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

    def score(self):
        """
        Returns the RED and BLUE points Score earned this time step.
        Called exactly once per time step.
        """
        return Score.ZERO


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
        if time > GAME_SECS:
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

        self.cubes = 0

    def __str__(self):
        return "Robot({}{}) with {}".format(
            self.alliance, self.player, num_cubes(self.cubes))

    def pickup(self):
        """Pick up a cube here."""
        # TODO: Check and decrement the number of cubes in this place.
        if self.cubes > 0:
            raise RuntimeError("{} can't pick up another Cube".format(self))
        self.cubes = 1

    def drop(self):
        """Drop a cube here."""
        # TODO: Increment the number of cubes in this place.
        if self.cubes < 1:
            raise RuntimeError("{} can't drop a Cube".format(self))
        self.cubes = 0


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

    def __str__(self):
        return "{}(/{}) with {}".format(
            self.__class__, self.front_color, num_cubes(self.cubes))

    def add_cube(self, side):
        """Add a cube to the front (0) or back (1) side of the Switch."""
        self.cubes[side] += 1

    def force(self, alliance):
        """
        Start an alliance Force power-up.
        NOTE: VaultColumn.play() relies on this method selector name and signature.
        """
        if self.autonomous:
            raise RuntimeError("Can't Force during autonomous")
        self.forced = True
        self.force_timeout = self.time + FORCE_SECS
        self.force_alliance = alliance

    def boost(self, alliance):
        """
        Start an alliance Boost power-up.
        NOTE: VaultColumn.play() relies on this method selector name and signature.
        """
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
        if owner is not self.previous_owner:  # established ownership this time step
            self.previous_owner = owner
            value *= 2
        return Score.pick(owner, value)


class Switch(Scale):
    def __init__(self, alliance_end, front_color):
        """
        :param alliance_end: RED or BLUE end of the field
        :param front_color: RED or BLUE, selected by the FMS
        """
        super(Switch, self).__init__(front_color)
        self.alliance_end = alliance_end

    def __str__(self):
        return "{}({}/{}) with {}".format(
            self.__class__, self.alliance_end, self.front_color,
            num_cubes(self.cubes))

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


class VaultColumn(Agent):
    def __init__(self, alliance, action, switch, scale):
        """
        RED or BLUE alliance.
        action is 'force' or 'boost' (a Scale/Switch method selector) or 'levitate'.
        """
        super(VaultColumn, self).__init__()
        self.alliance = alliance
        self.action = action
        self.switch, self.scale = switch, scale

        self._cubes = 0
        self.previous_cubes = 0

    @property
    def cubes(self):
        return self._cubes

    def __str__(self):
        return "VaultColumn({} {}) with {} Cubes".format(
            self.alliance, self.action, self._cubes)

    def add(self, cubes):
        # type: (int) -> int
        """Adds the given number of Cubes. Returns the new count."""
        if cubes < 0:
            raise RuntimeError("Can't remove {} cubes from {}".format(-cubes, self))
        if self._cubes + cubes > 3:
            raise RuntimeError("{} can't hold {} more cubes".format(self, cubes))
        self._cubes += cubes
        return self._cubes

    def selected(self):
        """Returns a tuple of the seesaws selected by the current number of cubes."""
        return ((), (self.switch,), (self.scale,), (self.switch, self.scale))[self._cubes]

    def play(self):
        """Play this power-up."""
        if self.action == "levitate":
            if self.cubes == 3:
                # TODO: Implement.
                pass
        else:
            # TODO: Queueing, one-shot, and no-op cases.
            for seesaw in self.selected():
                getattr(seesaw, self.action)(self.alliance)

    def score(self):
        score = Score.pick(self.alliance, 5 * (self._cubes - self.previous_cubes))
        self.previous_cubes = self._cubes
        return score


class Vault(Agent):
    """
    An alliance's Vault for power-ups.
    Example usage: vault.force.play().
    """

    def __init__(self, alliance, switch, scale):
        super(Vault, self).__init__()
        self.alliance = alliance
        self.columns = tuple(VaultColumn(alliance, action, switch, scale)
                             for action in ('force', 'levitate', 'boost'))
        self.force, self.levitate, self.boost = self.columns
        self.switch, self.scale = switch, scale

    def __str__(self):
        cubes = [column.cubes for column in self.columns]
        return "Vault({}) with {} Cubes".format(self.alliance, cubes)

    def update(self, time):
        super(Vault, self).update(time)
        for column in self.columns:
            column.update(time)

    def score(self):
        return sum((column.score() for column in self.columns), Score.ZERO)


class PowerUpGame(Simulation):
    def __init__(self):
        super(PowerUpGame, self).__init__()
        # TODO: An initial-conditions vector for the FMS choices.
        switch_front_color = RED
        scale_front_color = BLUE

        self.robots = [Robot(alliance, player)
                       for alliance in (RED, BLUE)
                       for player in xrange(1, 4)]
        red_switch = Switch(RED, switch_front_color)
        blue_switch = Switch(BLUE, switch_front_color)
        scale = Scale(scale_front_color)
        self.seesaws = [red_switch, blue_switch, scale]
        self.vaults = {RED: Vault(RED, red_switch, scale),
                       BLUE: Vault(BLUE, blue_switch, scale)}

        for agent in chain(self.robots, self.seesaws, self.vaults.itervalues()):
            self.add(agent)

        self.score = Score.ZERO

    def tick(self):
        """Advance time and update the running score."""
        super(PowerUpGame, self).tick()
        self.score = sum((agent.score() for agent in self.agents), self.score)

    def play(self):
        """Play out the simulated game."""
        for t in xrange(GAME_SECS):
            self.tick()
            # TODO: Output a CSV row of score and state data.
        print "Final score: {}".format(self.score)

    def force(self, alliance):
        self.vaults[alliance].force.play()

    def levitate(self, alliance):
        self.vaults[alliance].levitate.play()

    def boost(self, alliance):
        self.vaults[alliance].boost.play()


if __name__ == "__main__":
    game = PowerUpGame()
    game.play()
