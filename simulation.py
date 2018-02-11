#!/usr/bin/env python

"""
FRC PowerUp game score simulation.

TODO: Robot behaviors, driver behaviors, queued power-ups;
More scoring: auto-run reach the line, parked, climbed, ...;
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

from collections import namedtuple
from enum import Enum  # PyPI enum34
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
    """An alliance color name that supports a .opposite property."""
    pass


# Singleton alliance Color objects.
RED, BLUE = Color('RED'), Color('BLUE')
RED.opposite, BLUE.opposite = BLUE, RED
ALLIANCES = (RED, BLUE)


# Robot locations. Cubes can also be in these locations and in Robots,
# Switch plates, Scale plates, and Vault columns, but not *_PLATFORM_CLIMBED.
# The Scoring Table is at the "back side."
# The red/blue "outer zone" is between the alliance wall and the auto-line.
#
# TODO: Split these finer, esp. front/back outer zone?
Location = Enum(
    'Location',
    'RED_EXCHANGE_ZONE BLUE_EXCHANGE_ZONE '
    'RED_FRONT_PORTAL RED_BACK_PORTAL BLUE_FRONT_PORTAL BLUE_BACK_PORTAL '
    'RED_POWER_CUBE_ZONE BLUE_POWER_CUBE_ZONE '
    'RED_SWITCH_FENCE BLUE_SWITCH_FENCE '
    'RED_OUTER_ZONE BLUE_OUTER_ZONE '
    'RED_FRONT_INNER_ZONE RED_BACK_INNER_ZONE BLUE_FRONT_INNER_ZONE BLUE_BACK_INNER_ZONE '
    'RED_PLATFORM BLUE_PLATFORM RED_PLATFORM_CLIMBED BLUE_PLATFORM_CLIMBED '
    'FRONT_NULL_TERRITORY BACK_NULL_TERRITORY ')

for loc in Location:
    loc.is_inner_zone = loc.name.endswith('_INNER_ZONE')
    loc.cubes = 0  # The number of cubes in this Location.
    loc.adjacent_plate = None  # Adjacent seesaw Plate to place Cubes.

ScoreFactor = Enum('ScoreFactor', 'NOT_YET ACHIEVED COUNTED')

TRAVEL_TIMES = dict()  # map from (location1, location2) -> Robot travel time in seconds


def _init_travel_times():
    """
    Initialize travel times for direct paths. In this simulation, a Robot will
    jump to the destination after this many seconds. Take longer routes in a
    sequence of direct paths via intermediate Locations *OUTER_ZONE,
    *INNER_ZONE, *SWITCH_FENCE, *PLATFORM, *NULL_TERRITORY.
    """
    def set_pairs(location_name1, location_name2, time):
        """Set RED and BLUE forward and reverse travel times."""
        for alliance in ALLIANCES:
            location1 = Location[location_name1.replace(RED, alliance)]
            location2 = Location[location_name2.replace(RED, alliance)]
            TRAVEL_TIMES[(location1, location2)] \
                = TRAVEL_TIMES[(location2, location1)] = time

    set_pairs('RED_OUTER_ZONE', 'RED_EXCHANGE_ZONE', 2)
    set_pairs('RED_OUTER_ZONE', 'RED_FRONT_PORTAL', 5)
    set_pairs('RED_OUTER_ZONE', 'RED_BACK_PORTAL', 5)
    set_pairs('RED_OUTER_ZONE', 'RED_POWER_CUBE_ZONE', 2)
    set_pairs('RED_OUTER_ZONE', 'RED_FRONT_INNER_ZONE', 6)
    set_pairs('RED_OUTER_ZONE', 'RED_BACK_INNER_ZONE', 6)

    set_pairs('RED_SWITCH_FENCE', 'RED_FRONT_INNER_ZONE', 4)
    set_pairs('RED_SWITCH_FENCE', 'RED_BACK_INNER_ZONE', 4)
    set_pairs('RED_SWITCH_FENCE', 'RED_PLATFORM', 2)
    set_pairs('RED_PLATFORM', 'RED_FRONT_INNER_ZONE', 4)
    set_pairs('RED_PLATFORM', 'RED_BACK_INNER_ZONE', 4)

    set_pairs('RED_FRONT_INNER_ZONE', 'FRONT_NULL_TERRITORY', 6)
    set_pairs('RED_BACK_INNER_ZONE', 'BACK_NULL_TERRITORY', 6)


_init_travel_times()


class Score(namedtuple('Score', 'red blue')):
    """An incremental or final match score."""

    @classmethod
    def pick(cls, color, value):
        """Returns a Score where RED or BLUE or neither gets the given value."""
        return cls(value if color is RED else 0, value if color is BLUE else 0)

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
        Returns the Score(red_points, blue_points) earned this time step.
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


# TODO: pickup(), drop(), and place() should take at least 1 second.
# TODO: Disallow more than 1 action (Cube or driving) at a time, either by
# canceling the current action or not starting another.
class Robot(Agent):
    def __init__(self, alliance, player, location=None):
        """
        :param alliance: RED or BLUE
        :param player: 1, 2, or 3
        :param location: a Location (defaults to the alliance's outer zone)
        """
        super(Robot, self).__init__()
        self.alliance = alliance
        self.player = player

        if location is None:
            location = Location.RED_OUTER_ZONE if alliance is RED else Location.BLUE_OUTER_ZONE
        self.destination = self.location = location
        self.eta = None  # => not driving
        self.cubes = 0
        self.auto_run = ScoreFactor.NOT_YET

    def __str__(self):
        # TODO: Include the current action and destination.
        return "Robot({}{}) in {} with {} Cube(s)".format(
            self.alliance, self.player, self.location, self.cubes)

    def update(self, time):
        super(Robot, self).update(time)
        if self.time == self.eta:
            self.location = self.destination
            self.eta = None

            if (self.auto_run is ScoreFactor.NOT_YET and self.autonomous
                    and self.location.is_inner_zone):
                self.auto_run = ScoreFactor.ACHIEVED

    def score(self):
        if self.auto_run is ScoreFactor.ACHIEVED:
            points = Score.pick(self.alliance, 5)
            self.auto_run = ScoreFactor.COUNTED
        else:
            points = Score.ZERO
        # TODO: Add Parking or Climbing points.
        return points

    def head_to(self, destination):
        """
        Begin driving to the given destination. Cancel any current destination.
        Does no path planning -- raises KeyError if destination is not adjacent.
        """
        self.destination = destination
        self.eta = self.time + TRAVEL_TIMES[(self.location, destination)]

    def pickup(self):
        """If there's a Cube here and room in the Robot, pick it up and return True."""
        if self.location.cubes > 0 and self.cubes == 0:
            self.location.cubes -= 1
            self.cubes += 1
            return True
        return False

    def drop(self):
        """
        If the Robot has a Cube, drop it here and return True. In an Exchange zone
        or Portal zone, this puts the Cube in the Exchange or Portal. Next to a
        seesaw Plate, this drops a Cube on the ground; call place() to place the
        Cube on the Plate.
        """
        if self.cubes > 0:
            self.location.cubes += 1
            self.cubes -= 1
            return True
        return False

    def place(self):
        """If possible, place a Cube from the Robot on the adjacent Plate and return True."""
        plate = self.location.adjacent_plate
        if plate is not None and self.cubes > 0:
            plate.cubes += 1
            self.cubes -= 1
            return True
        return False


class Plate(object):
    """A Plate holding Cubes on one side of a "seesaw" (Scale or Switch)."""
    def __init__(self, name):
        self.name = name
        self.cubes = 0

    def __str__(self):
        return "{} {} with {} Cubes".format(self.name, type(self), self.cubes)


class Scale(Agent):
    """A Scale, also the base class for Switch."""
    def __init__(self, front_color):
        """
        :param front_color: RED or BLUE, selected by the FMS
        """
        super(Scale, self).__init__()
        self.alliance_end = ''
        self.front_color = front_color
        self.front_plate = Plate(self._plate_name("Front"))
        self.back_plate = Plate(self._plate_name("Back"))

        self.forced = False
        self.force_timeout = 0
        self.force_alliance = ''
        self.boosted = False
        self.boost_timeout = 0
        self.boost_alliance = ''
        self.previous_owner = ''

        self._setup_locations()

    def _plate_name(self, front_back):
        return "{} Scale".format(front_back)

    def _setup_locations(self):
        """Set the adjacent Locations to point to the Plates."""
        Location.FRONT_NULL_TERRITORY.adjacent_plate = self.front_plate
        Location.BACK_NULL_TERRITORY.adjacent_plate = self.back_plate

    def __str__(self):
        return "{}({}/{}) with {} Cube(s)".format(
            type(self), self.alliance_end, self.front_color, self.cubes)

    @property
    def cubes(self):
        """Returns (# front Plate Cubes, # back Plate Cubes)."""
        return self.front_plate.cubes, self.back_plate.cubes

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
        """
        Returns which alliance currently "owns" this Scale: RED, '', or BLUE.

        ASSUMES: Only the number of Cubes on each Plate determines the tilt;
        this simulation does not model the lever distance of each Cube.
        """
        if self.forced:
            return self.force_alliance
        tilt = self.front_plate.cubes.__cmp__(self.back_plate.cubes)  # <, ==, > :: -1, 0, 1
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
    """A Switch."""
    def __init__(self, alliance_end, front_color):
        """
        :param alliance_end: RED or BLUE end of the field
        :param front_color: RED or BLUE, selected by the FMS
        """
        super(Switch, self).__init__(front_color)
        self.alliance_end = alliance_end

    def _plate_name(self, front_back):
        return "{} {} Switch".format(front_back, self.alliance_end)

    def _setup_locations(self):
        """Set up the adjacent Locations to point to the Plates."""
        if self.alliance_end is RED:
            Location.RED_FRONT_INNER_ZONE.adjacent_plate = self.front_plate
            Location.RED_BACK_INNER_ZONE.adjacent_plate = self.back_plate
        else:
            Location.BLUE_FRONT_INNER_ZONE.adjacent_plate = self.front_plate
            Location.BLUE_BACK_INNER_ZONE.adjacent_plate = self.back_plate

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


class RobotPlayer(object):
    """Chooses a Robot's actions: Preload a Cube or not, driving plans, etc."""
    def __init__(self, robot):
        self.robot = robot

        # First cut decisions: Preload Cubes in all Robots and drive to
        # earn auto-run points.
        robot.cubes = 1
        destination_name = "{}_{}_INNER_ZONE".format(
            robot.alliance, "FRONT" if robot.player < 3 else "BACK")
        robot.head_to(Location[destination_name])

    # TODO: A generator to yield Robot actions as the game proceeds.


class HumanPlayer(object):
    """Chooses a human player's actions."""
    def __init__(self, alliance):
        self.alliance = alliance

    # TODO: A generator to yield human player actions as the game proceeds.


class PowerUpGame(Simulation):
    def __init__(self):
        super(PowerUpGame, self).__init__()
        # TODO: An initial-conditions vector for the FMS choices.
        switch_front_color = RED
        scale_front_color = BLUE

        # Create and add all the game objects.
        self.robots = [Robot(alliance, player)
                       for alliance in ALLIANCES
                       for player in xrange(1, 4)]

        red_switch = Switch(RED, switch_front_color)
        blue_switch = Switch(BLUE, switch_front_color)
        scale = Scale(scale_front_color)
        self.seesaws = [red_switch, blue_switch, scale]
        self.vaults = {RED: Vault(RED, red_switch, scale),
                       BLUE: Vault(BLUE, blue_switch, scale)}

        for agent in chain(self.robots, self.seesaws, self.vaults.itervalues()):
            self.add(agent)

        # Start keeping score.
        self.score = Score.ZERO

        # Create the player decision objects.
        self.robot_players = [RobotPlayer(robot) for robot in self.robots]
        self.human_players = [HumanPlayer(alliance) for alliance in ALLIANCES]

        # Place the remaining Cubes on the field now that RobotPlayers preloaded some.
        self._place_cubes()

    def _initial_portal_cubes(self, alliance):
        """Returns (# front portal cubes, # back portal cubes) for the given Alliance."""
        cubes_in_robots = sum(robot.cubes for robot in self.robots if robot.alliance is alliance)
        total_portal_cubes = 7 * 2 - cubes_in_robots
        front_portal_cubes = total_portal_cubes // 2
        return front_portal_cubes, (total_portal_cubes - front_portal_cubes)

    def _place_cubes(self):
        Location.RED_FRONT_PORTAL.cubes, Location.RED_BACK_PORTAL.cubes \
            = self._initial_portal_cubes(RED)
        Location.BLUE_FRONT_PORTAL.cubes, Location.BLUE_BACK_PORTAL.cubes \
            = self._initial_portal_cubes(BLUE)
        Location.RED_SWITCH_FENCE.cubes = Location.BLUE_SWITCH_FENCE.cubes = 6
        Location.RED_POWER_CUBE_ZONE.cubes = Location.BLUE_POWER_CUBE_ZONE.cubes = 10

    def tick(self):
        """Advance time and update the running score."""
        super(PowerUpGame, self).tick()
        self.score = sum((agent.score() for agent in self.agents), self.score)

    def play(self):
        """Play out the simulated game."""
        for t in xrange(GAME_SECS):
            self.tick()
            # TODO: Output a CSV row of score and state data.
        print "*** Final score: {} ***".format(self.score)
        print

    def force(self, alliance):
        self.vaults[alliance].force.play()

    def levitate(self, alliance):
        self.vaults[alliance].levitate.play()

    def boost(self, alliance):
        self.vaults[alliance].boost.play()


if __name__ == "__main__":
    game = PowerUpGame()
    game.play()
