#!/usr/bin/env python

"""
FRC (FIRST Robotics) Power Up game score simulation.

TODO: Split this file into framework simulation.py, agents, and game.py.
TODO: Support random distributions for action duration and success.
"""

from collections import namedtuple, OrderedDict
import csv
from enum import Enum  # PyPI enum34
import itertools
import os.path

AUTONOMOUS_SECS = 15
TELEOP_SECS = 2 * 60 + 15
GAME_SECS = AUTONOMOUS_SECS + TELEOP_SECS
ENDGAME_SECS = 30
POWER_UP_SECS = 10

CROSS_LINE_AUTO_POINTS = 5
GAIN_SWITCH_AUTO_POINTS = 2
GAIN_SCALE_AUTO_POINTS = 2


class Color(str):
    """An alliance color name that supports a .opposite property."""
    def __init__(self, name):
        super(Color, self).__init__(name)
        self.opposite = None  # filled in after creating the instances


# Singleton alliance Color objects.
RED, BLUE = Color('RED'), Color('BLUE')
RED.opposite, BLUE.opposite = BLUE, RED
ALLIANCES = (RED, BLUE)

# FMS start-of-match choices.
# They could be random or just set how you want the simulation run to go.
SWITCH_FRONT_COLOR, SCALE_FRONT_COLOR = BLUE, RED


ScoreFactor = Enum('ScoreFactor', 'NOT_YET ACHIEVED COUNTED')

# Robot Locations.
#
# Cubes can be:
#   in these Locations except *_PLATFORM_CLIMBED,
#   in Robots,
#   on Switch Plates,
#   on Scale Plates,
#   in Vault Columns,
#   on Exchange conveyor Plates (from Robot to STATION),
#   with Human players.
#
# The Scoring Table is at the 'BACK'.
# The RED/BLUE "outer zone" is between the Alliance wall and the auto-line.
#
# TODO: Split these zones finer, esp. front/back outer zone?
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

TRAVEL_TIMES = dict()  # map (location1, location2) -> Robot travel time in seconds


def find_location(pattern, *args):
    """Find a Location by name pattern with substitution *args."""
    return Location[pattern.format(*args)]


def _init_locations():
    """
    Initialize Location properties and TRAVEL_TIMES for direct paths.
    In this simulation, a Robot will jump to the destination after this
    many seconds. Drive longer routes as a sequence of direct paths via
    intermediate Locations *OUTER_ZONE, *INNER_ZONE, *SWITCH_FENCE,
    *PLATFORM, *NULL_TERRITORY.
    """
    def locate(location_name, color1):
        """
        Get the concrete Location from the name after substituting
        alliance color names RED/BLUE or vice versa for the template's
        token color names 'red'/'blue'.
        """
        color2 = color1.opposite
        return Location[
            location_name.replace('red', color1).replace('blue', color2)]

    def set_pairs(location_name1, location_name2, time):
        """Set RED and BLUE forward and reverse travel times."""
        for alliance in ALLIANCES:
            location1 = locate(location_name1, alliance)
            location2 = locate(location_name2, alliance)
            TRAVEL_TIMES[(location1, location2)] \
                = TRAVEL_TIMES[(location2, location1)] = time

    for loc in Location:
        loc.is_inner_zone = loc.name.endswith('_INNER_ZONE')

    set_pairs('red_OUTER_ZONE', 'red_EXCHANGE_ZONE', 2)
    set_pairs('red_OUTER_ZONE', 'blue_FRONT_PORTAL', 5)
    set_pairs('red_OUTER_ZONE', 'blue_BACK_PORTAL', 5)
    set_pairs('red_OUTER_ZONE', 'red_POWER_CUBE_ZONE', 2)
    set_pairs('red_OUTER_ZONE', 'red_FRONT_INNER_ZONE', 6)
    set_pairs('red_OUTER_ZONE', 'red_BACK_INNER_ZONE', 6)

    set_pairs('red_SWITCH_FENCE', 'red_FRONT_INNER_ZONE', 4)
    set_pairs('red_SWITCH_FENCE', 'red_BACK_INNER_ZONE', 4)
    set_pairs('red_SWITCH_FENCE', 'red_PLATFORM', 2)
    set_pairs('red_PLATFORM', 'red_FRONT_INNER_ZONE', 4)
    set_pairs('red_PLATFORM', 'red_BACK_INNER_ZONE', 4)

    set_pairs('red_FRONT_INNER_ZONE', 'FRONT_NULL_TERRITORY', 6)
    set_pairs('red_BACK_INNER_ZONE', 'BACK_NULL_TERRITORY', 6)


_init_locations()


def typename(value):
    """Return the name of value's type without any module name."""
    return type(value).__name__


class Score(namedtuple('Score', 'red blue')):
    """An incremental or final match score."""

    @classmethod
    def pick(cls, color, value):
        """Return a Score where RED or BLUE or neither gets the given value."""
        return cls(value if color is RED else 0, value if color is BLUE else 0)

    def __add__(self, other):
        """Add two Score values. Useful with sum([scores...], Score.ZERO)."""
        return Score(self.red + other.red, self.blue + other.blue)

    def wlt_rp(self):
        """Return the Win-Loss-Tie Ranking Point Score for this final point
        Score, e.g. (0, 2) for a BLUE win; (1, 1) for a tie.
        """
        # __cmp__() returns {-1, 0, 1} for {loss, tie, win}. +1 -> {0, 1, 2}.
        red_points = self.red.__cmp__(self.blue) + 1
        return Score(red_points, 2 - red_points)


Score.ZERO = Score(0, 0)


def sep(value):
    """Turn value into a string and append a separator space if needed."""
    string = str(value)
    return string + ' ' if string else ''


class Agent(object):
    """An Agent in a Simulation has time-based behaviors. Its name will
    be formed like "RED 1 Robot" or "BLUE STATION Human" and be useful
    for lookups.
    """
    def __init__(self, simulation, alliance, position=''):
        """
        :param alliance: RED, BLUE, or ''
        :param position: to distinguish, e.g. the RED Robots
        """
        self.simulation = simulation
        self.alliance = alliance
        self.position = position
        self.name = "{}{}{}".format(sep(alliance), sep(position), typename(self))

        self.eta = None  # when to perform scheduled_action
        self.scheduled_action = None  # a callable to perform at ETA
        self.scheduled_action_description = ''  # typically a method name

        simulation.add(self)

    @property
    def time(self):
        return self.simulation.time

    @property
    def autonomous(self):
        """Return True during the autonomous period."""
        return self.simulation.autonomous

    def update(self, time):
        """Called once per time step to update this Agent."""
        if time == self.eta:
            action = self.scheduled_action
            self.eta = None
            self.scheduled_action = None
            self.scheduled_action_description = ''

            # Run action() and scheduled_action_done() AFTER updating
            # state in case one of them schedules another action.
            action()
            self.scheduled_action_done()

    def score(self):
        """
        Returns the Score(red_points, blue_points) earned this time step.
        Called exactly once per time step.
        """
        return Score.ZERO

    def endgame_score(self):
        """Returns the Score earned for actions completed at game end."""
        return Score.ZERO

    def csv_header(self):
        """Return a list of 0 or more CSV header column name strings."""
        return []

    def csv_row(self):
        """Return a list of 0 or more CSV values corresponding to csv_header()."""
        return []

    def csv_end_header(self):
        """Endgame list of 0 or more CSV header column name strings."""
        return []

    def csv_end_row(self):
        """Endgame list of 0 or more CSV values corresponding to csv_end_header()."""
        return []

    def schedule_action(self, seconds, action, description):
        """
        Schedule action() and self.scheduled_action_done() in `seconds`
        from now, replacing any currently scheduled action.
        """
        self.eta = self.time + seconds
        self.scheduled_action = action
        self.scheduled_action_description = description

    def scheduled_action_done(self):
        """Called after a scheduled action completed."""
        pass

    def wait(self, seconds):
        """Wait 1 or more seconds, e.g. to simulate Robot turning in place
        or driver decision-making time.
        """
        delay = max(seconds, 1)
        self.schedule_action(delay, lambda: "done", "wait")

    def wait_for_teleop(self):
        """Schedule an action that just waits until the Teleop period. Yield if
        this returns True, otherwise just go on since it's already Teleop.
        """
        delay = AUTONOMOUS_SECS - self.time
        if delay > 0:
            self.schedule_action(delay, lambda: "done", "wait for Teleop")
            return True
        return False


class GameOver(Exception):
    pass


class Simulation(object):
    """A Simulation advances time and updates its Agents."""

    def __init__(self):
        self.time = 0
        self.agents = OrderedDict()

        self.cubes = {}  # map of Location -> # Cubes
        self.plates = {}  # map of Location -> adjacent Plate to place() Cubes
        for loc in Location:
            cubes = 0
            if loc.name.endswith('_SWITCH_FENCE'):  # initial Cubes on field
                cubes = 6
            elif loc.name.endswith('_POWER_CUBE_ZONE'):
                cubes = 10
            self.cubes[loc] = cubes
            self.plates[loc] = None

    @property
    def autonomous(self):
        """Return True during the autonomous period."""
        return self.time <= AUTONOMOUS_SECS

    def add(self, agent):
        """Add an Agent to this Simulation.
        REQUIRES: agent.simulation and agent.name already set.
        """
        assert agent.simulation == self
        self.agents[agent.name] = agent

    def tick(self):
        """Advance time by 1 second and update all Agents. In the first
        tick, update(1) computes what an Agent does in second #1.
        """
        time = self.time + 1
        if time > GAME_SECS:
            raise GameOver()
        self.time = time

        for agent in self.agents.itervalues():
            agent.update(time)


# NOTE: This won't allow more than 1 action (Cube or driving) at a time
# by the simple (and a bit fragile) mechanism where these action methods
# just schedule the completion code which does the actual changes and
# schedule_action() replaces any previously scheduled action.
#
# TODO: Make pickup() claim the Cube at the start of the second (and
# release it if the action gets cancelled)?
class Robot(Agent):
    """A Robot Agent, responsible for actions, not decisions."""
    def __init__(self, simulation, alliance, position, location=None):
        super(Robot, self).__init__(simulation, alliance, position)

        # The Player can adjust these parameters to model Robot differences.
        self.extra_drive_time = 0  # additional seconds per travel hop
        self.pickup_time = 1  # seconds to pickup() a Cube
        self.drop_time = 1  # seconds to drop() a Cube on the field
        self.place_time = 2  # seconds to place() a Cube on a plate
        self.climb_time = 4  # seconds to climb()

        if location is None:
            location = Location.RED_OUTER_ZONE if alliance is RED else Location.BLUE_OUTER_ZONE
        self.location = location
        self.cubes = 0
        self.climbed = ''  # one of {'', 'Climbed', 'Levitated'}
        self.auto_run = ScoreFactor.NOT_YET
        self.behavior = ''
        self.player = itertools.repeat("--")  # a no-op generator

    def __str__(self):
        return "{} in {} with {} Cube(s)".format(self.name, self.location, self.cubes)

    @property
    def at_platform(self):
        """True if the Robot is on (Parked) or above (Climbed) its Platform."""
        platform = find_location('{}_PLATFORM', self.alliance)
        return self.location is platform

    def csv_header(self):
        name = self.name
        return [name + ' Behavior', name + ' Action', name + ' Location', name + ' Cubes']

    def csv_row(self):
        return [self.behavior, str(self.scheduled_action_description),
                self.location.name, self.cubes]

    def csv_end_header(self):
        name = self.name
        return [name + ' Endgame']

    def csv_end_row(self):
        return [self.climbed]

    def update(self, time):
        # Start/resume the action generator if it's not waiting for a
        # scheduled_action to finish.
        if not self.scheduled_action:
            self.scheduled_action_done()  # Start the generator.
        super(Robot, self).update(time)

    def score(self):
        if self.auto_run is ScoreFactor.ACHIEVED:
            points = Score.pick(self.alliance, 5)
            self.auto_run = ScoreFactor.COUNTED
        else:
            points = Score.ZERO
        return points

    def endgame_score(self):
        return Score.pick(
            self.alliance,
            30 if self.climbed else 5 if self.at_platform else 0)

    def scheduled_action_done(self):
        """A scheduled action completed so start the next one."""
        self.behavior = self.player.next()

    def set_player(self, generator):
        """Set the generator that chooses Robot actions and initialize."""
        self.player = generator

    def drive_to(self, destination, *args):
        """
        Begin driving to the destination Location or Location name
        pattern + args, replacing any current action. Raise KeyError if
        the destination is not adjacent (no path planning here).
        """
        if self.climbed:
            return  # Can't drive now.

        if isinstance(destination, str):
            destination = find_location(destination, *args)

        def arrive():
            self.location = destination
            # Check if this Robot completed the auto-run. Allow 1 extra
            # second because this completion action runs at the start of
            # a second, noticing that the Robot finished its drive_to()
            # step, and actually the Robot's bumper just needs to break
            # the vertical plane of the Auto Line; the Robot needn't
            # finish driving into the Inner Zone.
            if (self.auto_run is ScoreFactor.NOT_YET
                    and destination.is_inner_zone
                    and self.time <= AUTONOMOUS_SECS + 1):
                self.auto_run = ScoreFactor.ACHIEVED

        travel_time = (TRAVEL_TIMES[(self.location, destination)]
                       + self.extra_drive_time)
        self.schedule_action(travel_time, arrive, ('drive_to', destination.name))

    def drive_path(self, *locations):
        """Drive a sequence of Location steps, yielding after each step."""
        for step in locations:
            self.drive_to(step)
            yield "driving through"

    def pickup(self):
        """If there's a Cube here and room in the Robot, pick it up."""
        def finish():
            if self.simulation.cubes[self.location] > 0 and self.cubes == 0:
                self.simulation.cubes[self.location] -= 1
                self.cubes += 1

        self.schedule_action(self.pickup_time, finish, 'pickup')

    def drop(self):
        """
        If the Robot has a Cube, drop it here. Next to a seesaw Plate or
        Exchange Plate, this just drops a Cube on the ground; call place()
        to place the Cube on the adjacent Switch/Scale/Exchange Plate.
        """
        def finish():
            if self.cubes > 0:
                self.simulation.cubes[self.location] += 1
                self.cubes -= 1

        self.schedule_action(self.drop_time, finish, 'drop')

    def place(self):
        """
        If possible, place a Cube from the Robot on the adjacent
        Switch/Scale/Exchange Plate.

        ASSUMES: Each Plate can hold all Cubes we can get to place() on
        it, including the Exchange conveyor Plate, whether the
        STATION Human is getting them or not.
        """
        def finish():
            plate = self.simulation.plates[self.location]
            if plate is not None and self.cubes > 0:
                plate.cubes += 1
                self.cubes -= 1

        self.schedule_action(self.place_time, finish, 'place')

    def climb(self):
        """If possible, climb the Scale, canceling driving or any other action."""
        def finish():
            if self.at_platform:
                self.climbed = 'Climbed'

        if self.at_platform:
            self.schedule_action(self.climb_time, finish, 'climb')


class Human(Agent):
    """
    A Human player Agent, responsible for actions in the Alliance
    station or at a Portal. Its "player" makes the game decisions.
    """
    # TODO: Model travel steps in the Alliance station? Currently the
    # Cube actions just include some average travel time.
    def __init__(self, simulation, alliance, position, vault):
        """
        A Human player in the Alliance STATION (with a Vault ref, an
        Exchange Location ref, and an Exchange Plate) or at a FRONT/BACK
        Portal (with a Portal Location ref). (Those refs are None when
        irrelevant to catch any buggy attempts for the wrong Human
        player to access them.)

        :param position: 'FRONT', 'BACK', or 'STATION'.
        """
        super(Human, self).__init__(simulation, alliance, position)

        # The Player can adjust these parameters to model Human differences.
        self.get_from_exchange_time = 4
        self.put_to_exchange_time = 4
        self.put_to_vault_time = 6
        self.put_through_portal_time = 3
        self.activate_power_up_time = 3

        self.vault = self.exchange_plate = self.exchange_zone = self.portal = None
        if position == 'STATION':
            self.vault = vault
            self.exchange_plate = Plate("{} Exchange Plate".format(alliance))
            self.exchange_zone = find_location('{}_EXCHANGE_ZONE', alliance)
            simulation.plates[self.exchange_zone] = self.exchange_plate
        else:
            self.portal = find_location('{}_{}_PORTAL', alliance, position)

        self.cubes = 0  # PowerUpGame will preload Cubes for Portal Humans
        self.behavior = ''
        self.player = itertools.repeat("--")  # a no-op generator

    def __str__(self):
        return "{} with {} Cube(s)".format(self.name, self.cubes)

    def csv_header(self):
        name = self.name
        header = [name + ' Behavior', name + ' Action', name + ' Cubes']
        if self.exchange_plate:
            header.append('{} Exchange Cubes'.format(self.alliance))
        return header

    def csv_row(self):
        row = [self.behavior, str(self.scheduled_action_description), self.cubes]
        if self.exchange_plate:
            row.append(self.exchange_plate.cubes)
        return row

    def update(self, time):
        if not self.scheduled_action:
            self.scheduled_action_done()  # Start the generator.
        super(Human, self).update(time)

    def scheduled_action_done(self):
        """A scheduled action completed so start the next one."""
        self.behavior = self.player.next()

    def set_player(self, generator):
        """Set the generator that chooses Human actions and initialize."""
        self.player = generator

    @property
    def vault_cubes(self):
        """The number of Cubes in my (force, levitate, boost) Vault columns."""
        return self.vault.cubes

    def get_from_exchange(self):
        """Get a Cube from the Exchange Plate."""
        def finish():
            if self.exchange_plate.cubes > 0:
                self.exchange_plate.cubes -= 1
                self.cubes += 1

        self.schedule_action(self.get_from_exchange_time, finish,
                             'get from Exchange')

    def put_to_exchange(self):
        """
        Put a Cube through the Exchange Return to the Exchange zone on the field.
        """
        def finish():
            if self.cubes > 0:
                self.cubes -= 1
                self.simulation.cubes[self.exchange_zone] += 1

        self.schedule_action(self.put_to_exchange_time, finish,
                             'put to Exchange')

    def put_to_vault(self, column_name):
        """Put a Cube into a Vault column 'force', 'levitate', or 'boost'."""
        def finish():
            if self.cubes > 0:
                self.cubes -= 1
                self.vault.column_map[column_name].add_cube(1)

        self.schedule_action(self.put_to_vault_time, finish,
                             'put to {} Vault'.format(column_name))

    def put_through_portal(self):
        """Put a Cube through the Portal onto the field."""
        def finish():
            if self.cubes > 0:
                self.cubes -= 1
                self.simulation.cubes[self.portal] += 1

        self.schedule_action(self.put_through_portal_time, finish,
                             'put through Portal')

    def activate_power_up(self, column_name):
        """Push a Power-up button on a Vault column to try to Activate it."""
        def finish():
            self.vault.column_map[column_name].activate()

        # The delay models the average time for the Human player to get
        # to the Vault, check the lights and Cubes, and push a button.
        self.schedule_action(self.activate_power_up_time, finish,
                             'activate {} Power-up'.format(column_name))


class Plate(object):
    """
    A Plate holding Cubes on one side of a "seesaw" (Scale or Switch) or
    an Exchange conveyor. Robots can put Cubes on Plates.
    """
    def __init__(self, name):
        self.name = name
        self.cubes = 0

    def __str__(self):
        return "{} {} with {} Cubes".format(self.name, typename(self), self.cubes)


class Scale(Agent):
    """A Scale, also the base class for Switch."""
    def __init__(self, simulation, power_up_queue, front_color, alliance=''):
        """
        :param front_color: RED or BLUE, selected by the FMS
        """
        super(Scale, self).__init__(simulation, alliance)
        self.power_up_queue = power_up_queue
        self.front_color = front_color
        self.front_plate = Plate(self._plate_name("Front"))
        self.back_plate = Plate(self._plate_name("Back"))

        self.forced, self.force_alliance = (False, '')
        self.boosted, self.boost_alliance = (False, '')
        self.previous_owner = ''

        self._setup_locations()

    def _plate_name(self, front_back):
        """Return a string like 'Front Scale' to make 'Front Scale Plate'."""
        return "{} {}".format(front_back, typename(self))

    def _setup_locations(self):
        """Set the adjacent Locations to point to the Plates."""
        self.simulation.plates[Location.FRONT_NULL_TERRITORY] = self.front_plate
        self.simulation.plates[Location.BACK_NULL_TERRITORY] = self.back_plate

    @property
    def power_up_state(self):
        return '{}/{}'.format('Forced' if self.forced else '',
                              'Boosted' if self.boosted else '')

    def __str__(self):
        return "{} with {} Cube(s)".format(self.name, self.cubes)

    def csv_header(self):
        name = self.name
        return [name + ' Owner',
                '{} (Front:{}, Back) Cubes'.format(name, self.front_color),
                name + ' Power-Ups']

    def csv_row(self):
        return [self.owner(), self.cubes, self.power_up_state]

    @property
    def cubes(self):
        """Returns (# front Plate Cubes, # back Plate Cubes)."""
        return self.front_plate.cubes, self.back_plate.cubes

    def force(self, alliance, is_start):
        """
        Start/end an alliance Force Power-up, stopping any Boost Power-up.
        The caller handles timing and queuing across all Switches/Scales.

        NOTE: VaultColumn.activate() relies on this method selector name and signature.
        """
        if self.autonomous:
            raise RuntimeError("Can't Force during autonomous")
        self.forced, self.force_alliance = (True, alliance) if is_start else (False, '')
        self.boosted, self.boost_alliance = (False, '')

    def boost(self, alliance, is_start):
        """
        Start/end an alliance Boost Power-up, stopping any Force Power-up.
        The caller handles timing and queuing across all Switches/Scales.

        NOTE: VaultColumn.activate() relies on this method selector name and signature.
        """
        if self.autonomous:
            raise RuntimeError("Can't Boost during autonomous")
        self.boosted, self.boost_alliance = (True, alliance) if is_start else (False, '')
        self.forced, self.force_alliance = (False, '')

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
    def __init__(self, simulation, power_up_queue, front_color, alliance):
        """
        :param front_color: RED or BLUE, selected by the FMS
        :param alliance: RED or BLUE end of the field
        """
        super(Switch, self).__init__(
            simulation, power_up_queue, front_color, alliance)
        self.active_power_up = None  # interlock between Force and Boost Power-Ups
        self.levitate_activated = False

    def _plate_name(self, front_back):
        """Return a string like 'Front RED Switch' to make 'Front RED Switch Plate'."""
        return "{} {} {}".format(front_back, self.alliance, typename(self))

    def _setup_locations(self):
        """Set up the adjacent Locations to refer to the Plates."""
        plates = self.simulation.plates
        alliance = self.alliance
        plates[find_location("{}_FRONT_INNER_ZONE", alliance)] = self.front_plate
        plates[find_location("{}_BACK_INNER_ZONE", alliance)] = self.back_plate

    def force(self, alliance, is_start):
        """Start/end an alliance Force; no-op if this isn't the alliance's Switch."""
        if alliance is self.alliance:
            super(Switch, self).force(alliance, is_start)

    def boost(self, alliance, is_start):
        """Start/end an alliance Boost; no-op if this isn't the alliance's Switch."""
        if alliance is self.alliance:
            super(Switch, self).boost(alliance, is_start)

    def owner(self):
        o = super(Switch, self).owner()
        return o if o is self.alliance else ''


class PowerUpQueue(Agent):
    """The FMS queue of Switch/Scale Power-Ups."""
    def __init__(self, simulation):
        super(PowerUpQueue, self).__init__(simulation, '')
        self.queue = []  # queue[0] is the current action

    def _start_current_action(self):
        """Start the current action and schedule to end it and revisit the queue."""
        self.queue[0](True)
        self.schedule_action(POWER_UP_SECS, lambda: (), 'dequeue')

    def run_or_enqueue(self, power_up_action):
        """
        Run or enqueue the Power-Up action.
        power_up_action(True) starts the action; power_up_action(False) ends it.
        """
        idle = not self.queue
        self.queue.append(power_up_action)
        if idle:
            self._start_current_action()

    def scheduled_action_done(self):
        """End the current action and revisit the queue."""
        self.queue.pop(0)(False)
        if self.queue:
            self._start_current_action()


class VaultColumn(object):
    def __init__(self, alliance, action, switch, scale):
        """
        alliance: RED or BLUE.
        action: 'force' or 'boost' (a Scale/Switch method selector) or 'levitate'.
        """
        super(VaultColumn, self).__init__()
        self.alliance = alliance
        self.action = action
        self.switch, self.scale = switch, scale

        self._cubes = 0
        self.previous_cubes = 0
        self.played = False

    @property
    def name(self):
        return "{} {} VaultColumn".format(self.alliance, self.action)

    @property
    def cubes(self):
        return self._cubes

    def __str__(self):
        return "{} with {} Cubes".format(self.name, self.cubes)

    def add_cube(self, cubes):
        # type: (int) -> int
        """Add the given number of Cubes. Return the new count."""
        if cubes < 0:
            raise RuntimeError("Can't remove Cubes from {}".format(self.name))

        total = self._cubes + cubes
        if total > 3:
            raise RuntimeError("{} can't hold {} Cubes".format(self.name, total))

        self._cubes = total
        return total

    def selected(self):
        """Returns a tuple of the seesaws selected by the current number of Cubes."""
        return ((), (self.switch,), (self.scale,), (self.switch, self.scale))[self._cubes]

    def activate(self):
        """
        Activate this Power-Up if possible. Return True if the Power-Up
        started or queued; False if nothing happened because it was already
        played, a competing Power-Up is active, need more Cubes, etc.
        """
        if self.played:
            return False

        if self.action == 'levitate':
            if self.cubes == 3:
                self.switch.levitate_activated = True
                self.played = True
                return True
            return False

        if self.cubes > 0 and not self.switch.active_power_up:
            self.played = True
            self.switch.active_power_up = self.action

            # ASSUMES: The number of Cubes in the Vault column counts when the
            # button is pushed, not when the queued action begins.
            selected_seesaws = self.selected()

            def power_up_action(is_start):
                for seesaw in selected_seesaws:
                    getattr(seesaw, self.action)(self.alliance, is_start)
                if not is_start:
                    self.switch.active_power_up = None
            self.switch.power_up_queue.run_or_enqueue(power_up_action)
            return True

        return False

    def score(self):
        score = Score.pick(self.alliance, 5 * (self._cubes - self.previous_cubes))
        self.previous_cubes = self._cubes
        return score


class Vault(Agent):
    """An alliance's Vault for power-ups."""
    def __init__(self, simulation, alliance, switch, scale):
        super(Vault, self).__init__(simulation, alliance)
        self.columns = tuple(VaultColumn(alliance, action, switch, scale)
                             for action in ('force', 'levitate', 'boost'))
        self.column_map = {column.action: column for column in self.columns}
        self.switch, self.scale = switch, scale

    @property
    def cubes(self):
        """The number of Cubes in the (force, levitate, boost) Vault columns."""
        return tuple(column.cubes for column in self.columns)

    def __str__(self):
        return "{} Vault with {} Cubes".format(self.alliance, self.cubes)

    def csv_header(self):
        name = self.name
        return [name + ' (Force, Levitate, Boost) Cubes']

    def csv_row(self):
        return [self.cubes]

    def score(self):
        return sum((column.score() for column in self.columns), Score.ZERO)


def example_robot_player(robot):
    """
    A Robot "game player" (decider) -- a generator that chooses behaviors
    like drive to a destination. The Robot yields to this generator each
    time it needs instructions; this generator in turn updates the Robot
    and returns a behavior description.
    """
    # Here: Preload Cubes in all Robots, drive to earn auto-run points,
    # and place Cubes.

    alliance = robot.alliance
    switch_side = "FRONT" if SWITCH_FRONT_COLOR is alliance else "BACK"
    scale_side = "FRONT" if SCALE_FRONT_COLOR is alliance else "BACK"

    def drive_to(pattern, *args):
        robot.drive_to(pattern, *args)

    def player1():
        robot.cubes = 1  # preload a Cube

        drive_to("{}_{}_INNER_ZONE", alliance, switch_side)
        yield "auto-run to my Switch plate"

        robot.place()
        yield "place a Cube on the Switch"

        while True:
            yield "done"

    def player2():
        robot.cubes = 1

        drive_to("{}_{}_INNER_ZONE", alliance, scale_side)
        yield "auto-run"

        drive_to("{}_NULL_TERRITORY", scale_side)
        yield "go to my Scale plate"

        robot.place()
        yield "place a Cube on the Scale"

        while True:
            yield "done"

    def player3():
        robot.cubes = 1

        drive_to("{}_EXCHANGE_ZONE", alliance)
        yield "to Exchange"

        robot.place()
        yield "place a Cube in the Exchange"

        drive_to("{}_OUTER_ZONE", alliance)
        yield "auto-run"

        drive_to("{}_{}_INNER_ZONE", alliance, "FRONT")
        yield "auto-run"

        while True:
            yield "done"

    generator = {1: player1, 2: player2, 3: player3}[robot.position]()
    robot.set_player(generator)


def example_human_player(human):
    """
    A Human "game player" (decider) -- a generator that chooses behaviors
    like put Cube through Portal. The Human yields to this generator each
    time it needs instructions; this generator in turn updates the Human
    and returns a behavior description.

    The actions depend on player position.
    """
    def player():
        if human.wait_for_teleop():
            yield "wait for Teleop"

        # TODO: Human player behaviors...
        while True:
            yield "done"

    human.set_player(player())


def partition_by_alliance(elements):
    """Partition elements into a dict from alliance color to relevant elements."""
    d = {}
    for e in elements:
        d.setdefault(e.alliance, []).append(e)
    return d


class PowerUpGame(Simulation):
    def __init__(self, robot_player, human_player):
        super(PowerUpGame, self).__init__()

        # Create and add all the game objects.
        # Construction order affects update() order.
        self.power_up_queue = pq = PowerUpQueue(self)

        self.robots = [Robot(self, alliance, position)
                       for alliance in ALLIANCES
                       for position in xrange(1, 4)]
        self.robots_map = partition_by_alliance(self.robots)

        self.red_switch = Switch(self, pq, SWITCH_FRONT_COLOR, RED)
        self.blue_switch = Switch(self, pq, SWITCH_FRONT_COLOR, BLUE)
        self.scale = Scale(self, pq, SCALE_FRONT_COLOR)
        self.switches = {RED: self.red_switch, BLUE: self.blue_switch}
        self.seesaws = [self.red_switch, self.blue_switch, self.scale]

        self.vaults = [Vault(self, RED, self.red_switch, self.scale),
                       Vault(self, BLUE, self.blue_switch, self.scale)]
        self.vault_map = {vault.alliance: vault for vault in self.vaults}

        self.humans = [Human(self, alliance, position, self.vault_map[alliance])
                       for alliance in ALLIANCES
                       for position in ('FRONT', 'BACK', 'STATION')]
        self.humans_map = {(human.alliance, human.position): human
                           for human in self.humans}

        # Start keeping score.
        self.score = Score.ZERO
        self.auto_switch_owners = Score.ZERO

        # Set up the players. Robots can preload Cubes.
        [robot_player(robot) for robot in self.robots]
        [human_player(human) for human in self.humans]

        # Now give the remaining Cubes to the Human players at the Portals.
        for alliance in ALLIANCES:
            cubes_in_robots = sum(robot.cubes for robot in self.robots
                                  if robot.alliance is alliance)
            portal_cubes = 7 * 2 - cubes_in_robots
            front_cubes = portal_cubes // 2
            self.humans_map[(alliance, 'FRONT')].cubes = front_cubes
            self.humans_map[(alliance, 'BACK')].cubes = portal_cubes - front_cubes

    def tick(self):
        """Advance time and update the running score."""
        super(PowerUpGame, self).tick()

        if self.time == AUTONOMOUS_SECS:
            self.auto_switch_owners = Score(int(self.red_switch.owner() is RED),
                                            int(self.blue_switch.owner() is BLUE))

        self.score = sum((agent.score() for agent in self.agents.itervalues()),
                         self.score)

    def endgame_score(self):
        """Credit Levitate Power-Ups then calculate endgame Score points."""
        # Prefer to credit Robots that didn't climb or park.
        for switch in self.switches.values():
            if switch.levitate_activated:
                alliance = switch.alliance
                robots = self.robots_map[alliance]
                picks = sorted(robots, key=lambda r: bool(r.climbed) * 2 + r.at_platform)
                picks[0].climbed = 'Levitated'

        return sum((agent.endgame_score() for agent in self.agents.itervalues()),
                   Score.ZERO)

    def face_the_boss_rp(self):
        """Return a Ranking Point Score for Facing the Boss (3-robot climbs)."""
        return Score(sum(bool(robot.climbed) for robot in self.robots_map[RED]) // 3,
                     sum(bool(robot.climbed) for robot in self.robots_map[BLUE]) // 3)

    def auto_quest_rp(self):
        """Return a Ranking Point Score for the Auto-Quest (3 auto-runs + own Switch)."""
        reds = sum(robot.auto_run == ScoreFactor.COUNTED for robot in self.robots_map[RED]) // 3
        blues = sum(robot.auto_run == ScoreFactor.COUNTED for robot in self.robots_map[BLUE]) // 3
        return Score(reds * self.auto_switch_owners.red,
                     blues * self.auto_switch_owners.blue)

    def csv_header(self):
        return ['Time', 'Score']

    def csv_row(self):
        return [self.time, self.score]

    def csv_end_header(self):
        return ['Time', 'Score']

    def csv_end_row(self):
        return ['Final', self.score]

    def play(self, output_file):
        """Play out the simulated game, writing a CSV report to `output_file`."""
        # TODO: Include # Cubes at each Location in the CSV output?
        csv_writer = csv.writer(output_file)

        csv_contributors = [self] + self.agents.values()
        header = sum((c.csv_header() for c in csv_contributors), [])
        csv_writer.writerow(header)

        # Play the match. Output CSV rows.
        for t in xrange(GAME_SECS):
            self.tick()
            row = sum((c.csv_row() for c in csv_contributors), [])
            csv_writer.writerow(row)

        # Compute endgame points.
        self.score += self.endgame_score()

        # Output another CSV section with endgame points.
        csv_writer.writerow(())
        header = sum((c.csv_end_header() for c in csv_contributors), [])
        csv_writer.writerow(header)
        row = sum((c.csv_end_row() for c in csv_contributors), [])
        csv_writer.writerow(row)

        # Compute RPs. Output another CSV section.
        wlt = self.score.wlt_rp()
        faced_the_boss = self.face_the_boss_rp()
        auto_quest = self.auto_quest_rp()
        rp = wlt + faced_the_boss + auto_quest
        csv_writer.writerow(())
        csv_writer.writerow(('Time', 'WLT RPs', 'AUTO-QUEST RPs', 'BOSS RPs', 'TOTAL RPs'))
        csv_writer.writerow(('Final', wlt, auto_quest, faced_the_boss, rp))

        print "*** Final {}, Ranking Points {}. ***".format(self.score, rp)
        print


def play(robot_player, human_player, output_root_name):
    """Play a simulation, deriving the output .csv filename from output_root_name.
    (Within a Python source file, __file__ is its full filename.)
    """
    output_filename = os.path.splitext(os.path.basename(output_root_name))[0] + '.csv'

    with open(output_filename, 'wb') as out:
        game = PowerUpGame(robot_player, human_player)
        game.play(out)


if __name__ == "__main__":
    play(example_robot_player, example_human_player, __file__)
