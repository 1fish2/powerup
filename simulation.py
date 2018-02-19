#!/usr/bin/env python

"""
FRC PowerUp game score simulation.

TODO: More robot_player and human_player behaviors.
TODO: Ranking points: 2 for win, 1 for tie, +1 for 3-robot climb, +1 for
auto-quest (3 auto-runs AND own your Switch).

TODO: Split this file into framework simulation.py, agents, and game.py.
TODO: Unit tests.
"""

from collections import namedtuple
import csv
from enum import Enum  # PyPI enum34
import itertools

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


def location_by_pattern(pattern, *args):
    """Lookup a Location by name pattern with substitution *args."""
    return Location[pattern.format(*args)]


def _init_locations():
    """
    Initialize Location properties and TRAVEL_TIMES for direct paths.
    In this simulation, a Robot will jump to the destination after this
    many seconds. Drive longer routes as a sequence of direct paths via
    intermediate Locations *OUTER_ZONE, *INNER_ZONE, *SWITCH_FENCE,
    *PLATFORM, *NULL_TERRITORY.

    NOTE: An expedient approach here keeps simulation-specific state
    .adjacent_plate and .cubes in Location properties. Call this again
    to reset before re-running the simulation. A better approach would
    store that state in dicts in the Simulation object.
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
        loc.cubes = 0  # The number of cubes in this Location.
        loc.adjacent_plate = None  # Adjacent seesaw Plate; set by seesaw __init__().

    for alliance in ALLIANCES:
        location_by_pattern('{}_SWITCH_FENCE', alliance).cubes = 6
        location_by_pattern('{}_POWER_CUBE_ZONE', alliance).cubes = 10

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
    return type(value).__name__


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

        self.eta = None  # when to perform scheduled_action
        self.scheduled_action = None  # a callable to perform at ETA
        self.scheduled_action_description = ''  # typically a method name

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
        Schedule a callable action to perform seconds from now, replacing any
        current scheduled action.
        """
        self.eta = self.time + seconds
        self.scheduled_action = action
        self.scheduled_action_description = description

    def scheduled_action_done(self):
        """Called after a scheduled action completed."""
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
        if time > GAME_SECS:
            raise GameOver()
        self.time = time

        for agent in self.agents:
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
    def __init__(self, alliance, team_position, location=None):
        """
        :param alliance: RED or BLUE
        :param team_position: 1, 2, or 3
        :param location: a Location (defaults to the alliance's outer zone)
        """
        super(Robot, self).__init__()
        self.alliance = alliance
        self.team_position = team_position

        if location is None:
            location = Location.RED_OUTER_ZONE if alliance is RED else Location.BLUE_OUTER_ZONE
        self.location = location
        self.cubes = 0
        self.climbed = ''  # one of {'', 'Climbed', 'Levitated'}
        self.auto_run = ScoreFactor.NOT_YET
        self.player = itertools.repeat("--")  # a no-op generator

    @property
    def name(self):
        return "{}{} Robot".format(self.alliance, self.team_position)

    def __str__(self):
        return "{} in {} with {} Cube(s)".format(self.name, self.location, self.cubes)

    @property
    def at_platform(self):
        """True if the Robot is on (Parked) or above (Climbed) its Platform."""
        platform = location_by_pattern('{}_PLATFORM', self.alliance)
        return self.location is platform

    def csv_header(self):
        name = self.name
        return [name + ' Location', name + ' Cubes', name + ' Action']

    def csv_row(self):
        return [self.location.name, self.cubes, str(self.scheduled_action_description)]

    def csv_end_header(self):
        name = self.name
        return [name + ' Endgame']

    def csv_end_row(self):
        return [self.climbed]

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
        # TODO: Put the returned description in CSV output? Else have
        # the generator just return ().
        self.player.next()

    def set_player(self, generator):
        """
        Set the generator that chooses Robot actions and call it once
        to do the initial actions.
        """
        self.player = generator
        self.scheduled_action_done()

    def drive_to(self, destination):
        """
        Begin driving to the destination Location or Location name,
        replacing any current action. Does no p
        ath planning -- raises
        KeyError if the destination is not adjacent.
        """
        if self.climbed:
            return  # Can't drive now.

        if isinstance(destination, str):
            destination = Location[destination]

        def arrive():
            self.location = destination
            if (self.auto_run is ScoreFactor.NOT_YET
                    and destination.is_inner_zone and self.autonomous):
                self.auto_run = ScoreFactor.ACHIEVED

        travel_time = TRAVEL_TIMES[(self.location, destination)]
        self.schedule_action(travel_time, arrive, ('drive_to', destination.name))

    def pickup(self):
        """If there's a Cube here and room in the Robot, pick it up."""
        def finish():
            if self.location.cubes > 0 and self.cubes == 0:
                self.location.cubes -= 1
                self.cubes += 1

        self.schedule_action(1, finish, 'pickup')

    def drop(self):
        """
        If the Robot has a Cube, drop it here. Next to a seesaw Plate or
        Exchange Plate, this just drops a Cube on the ground; call place()
        to place the Cube on the adjacent Switch/Scale/Exchange Plate.
        """
        def finish():
            if self.cubes > 0:
                self.location.cubes += 1
                self.cubes -= 1

        self.schedule_action(1, finish, 'drop')

    def place(self):
        """
        If possible, place a Cube from the Robot on the adjacent
        Switch/Scale/Exchange Plate.
        TODO: Should the Exchange conveyor Plate support multiple Cubes?
        """
        def finish():
            plate = self.location.adjacent_plate
            if plate is not None and self.cubes > 0:
                plate.cubes += 1
                self.cubes -= 1

        self.schedule_action(1, finish, 'place')

    def climb(self):
        """If possible, climb the Scale, canceling driving or any other action."""
        def finish():
            if self.at_platform:
                self.climbed = 'Climbed'

        if self.at_platform:
            self.schedule_action(4, finish, 'climb')


class Human(Agent):
    """
    A Human player Agent, responsible for actions in the Alliance
    station or at a Portal. Its "player" makes the game decisions.
    """
    # TODO: Model travel steps in the Alliance station? Currently the
    # Cube actions just include some average travel time.
    def __init__(self, alliance, position, vault):
        """
        A Human player in the Alliance STATION (with a Vault ref, an
        Exchange Location ref, and an Exchange Plate) or at a FRONT/BACK
        Portal (with a Portal Location ref). (Those refs are None when
        irrelevant to catch any buggy attempts for the wrong Human
        player to access them.)

        position: 'FRONT', 'BACK', or 'STATION'.
        """
        super(Human, self).__init__()
        self.alliance = alliance
        self.position = position

        self.vault = self.exchange_plate = self.exchange_zone = self.portal = None
        if position == 'STATION':
            self.vault = vault
            self.exchange_plate = Plate("{} Exchange Plate".format(alliance))
            self.exchange_zone = location_by_pattern('{}_EXCHANGE_ZONE', alliance)
            self.exchange_zone.adjacent_plate = self.exchange_plate
        else:
            self.portal = location_by_pattern('{}_{}_PORTAL', alliance, position)

        self.cubes = 0  # PowerUpGame will preload Cubes for Portal Humans
        self.player = itertools.repeat("--")  # a no-op generator

    @property
    def name(self):
        return "{} {} Human Player".format(self.alliance, self.position)

    def __str__(self):
        return "{} with {} Cube(s)".format(self.name, self.cubes)

    def csv_header(self):
        name = self.name
        header = [name + ' Cubes', name + ' Action']
        if self.exchange_plate:
            header.append('{} Exchange Cubes'.format(self.alliance))
        return header

    def csv_row(self):
        row = [self.cubes, str(self.scheduled_action_description)]
        if self.exchange_plate:
            row.append(self.exchange_plate.cubes)
        return row

    def scheduled_action_done(self):
        """A scheduled action completed so start the next one."""
        self.player.next()

    def set_player(self, generator):
        """Set the player decider and generate its initial action."""
        self.player = generator
        self.scheduled_action_done()

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

        self.schedule_action(4, finish, 'get from Exchange')

    def put_to_exchange(self):
        """
        Put a Cube through the Exchange Return to the Exchange zone on the field.
        """
        def finish():
            if self.cubes > 0:
                self.cubes -= 1
                self.exchange_zone.cubes += 1

        self.schedule_action(4, finish, 'put to Exchange')

    def put_to_vault(self, column_name):
        """Put a Cube into a Vault column 'force', 'levitate', or 'boost'."""
        def finish():
            if self.cubes > 0:
                self.cubes -= 1
                self.vault.column_map[column_name].add_cube(1)

        self.schedule_action(6, finish, 'put to {} Vault'.format(column_name))

    def put_through_portal(self):
        """Put a Cube through the Portal onto the field."""
        def finish():
            if self.cubes > 0:
                self.cubes -= 1
                self.portal.cubes += 1

        self.schedule_action(3, finish, 'put through Portal')

    def activate_power_up(self, column_name):
        """Push a Power-up button on a Vault column to try to Activate it."""
        def finish():
            self.vault.column_map[column_name].activate()

        # The delay models the average time for the Human player to get
        # to the Vault, check the lights and Cubes, and push a button.
        self.schedule_action(3, finish, 'activate {} Power-up'.format(column_name))


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
    def __init__(self, power_up_queue, front_color, alliance_end=''):
        """
        :param front_color: RED or BLUE, selected by the FMS
        """
        super(Scale, self).__init__()
        self.power_up_queue = power_up_queue
        self.alliance_end = alliance_end
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
        Location.FRONT_NULL_TERRITORY.adjacent_plate = self.front_plate
        Location.BACK_NULL_TERRITORY.adjacent_plate = self.back_plate

    @property
    def name(self):
        spacer = ' ' if self.alliance_end else ''
        return "{}{}{} front:{}".format(
            self.alliance_end, spacer, typename(self), self.front_color)

    @property
    def power_up_state(self):
        return '{}/{}'.format('Forced' if self.forced else '',
                              'Boosted' if self.boosted else '')

    def __str__(self):
        return "{} with {} Cube(s)".format(self.name, self.cubes)

    def csv_header(self):
        name = self.name
        return [name + ' Owner', name + ' (Front, Back) Cubes', name + ' Power-Ups']

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
    def __init__(self, power_up_queue, front_color, alliance_end):
        """
        :param alliance_end: RED or BLUE end of the field
        :param front_color: RED or BLUE, selected by the FMS
        """
        super(Switch, self).__init__(power_up_queue, front_color, alliance_end)
        self.active_power_up = None  # interlock between Force and Boost Power-Ups
        self.levitate_activated = False

    def _plate_name(self, front_back):
        """Return a string like 'Front RED Switch' to make 'Front RED Switch Plate'."""
        return "{} {} {}".format(front_back, self.alliance_end, typename(self))

    def _setup_locations(self):
        """Set up the adjacent Locations to refer to the Plates."""
        location_by_pattern("{}_FRONT_INNER_ZONE", self.alliance_end
                            ).adjacent_plate = self.front_plate
        location_by_pattern("{}_BACK_INNER_ZONE", self.alliance_end
                            ).adjacent_plate = self.back_plate

    def force(self, alliance, is_start):
        """Start/end an alliance Force; no-op if this isn't the alliance's Switch."""
        if alliance is self.alliance_end:
            super(Switch, self).force(alliance, is_start)

    def boost(self, alliance, is_start):
        """Start/end an alliance Boost; no-op if this isn't the alliance's Switch."""
        if alliance is self.alliance_end:
            super(Switch, self).boost(alliance, is_start)

    def owner(self):
        o = super(Switch, self).owner()
        return o if o is self.alliance_end else ''


class PowerUpQueue(Agent):
    """The FMS queue of Switch/Scale Power-Ups."""
    def __init__(self):
        super(PowerUpQueue, self).__init__()
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
    def __init__(self, alliance, switch, scale):
        super(Vault, self).__init__()
        self.alliance = alliance
        self.columns = tuple(VaultColumn(alliance, action, switch, scale)
                             for action in ('force', 'levitate', 'boost'))
        self.column_map = {column.action: column for column in self.columns}
        self.switch, self.scale = switch, scale

    @property
    def name(self):
        return "{} Vault".format(self.alliance)

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
    # First cut: Preload Cubes in all Robots, drive to earn auto-run
    # points, and place a Cube.

    alliance = robot.alliance
    switch_side = "FRONT" if SWITCH_FRONT_COLOR is alliance else "BACK"
    scale_side = "FRONT" if SCALE_FRONT_COLOR is alliance else "BACK"

    def drive_to(pattern, *args):
        robot.drive_to(location_by_pattern(pattern, *args))

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
        yield "place a Cube into the Exchange"

        drive_to("{}_OUTER_ZONE", alliance)
        yield "auto-run"

        drive_to("{}_{}_INNER_ZONE", alliance, "FRONT")
        yield "auto-run"

        while True:
            yield "done"

    generator = {1: player1, 2: player2, 3: player3}[robot.team_position]()
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
        # TODO: Human player behaviors...
        while True:
            yield "done"

    human.set_player(player())


class PowerUpGame(Simulation):
    def __init__(self, robot_player, human_player):
        super(PowerUpGame, self).__init__()

        # Create and add all the game objects.
        self.power_up_queue = pq = PowerUpQueue()

        self.robots = [Robot(alliance, position)
                       for alliance in ALLIANCES
                       for position in xrange(1, 4)]

        self.red_switch = Switch(pq, SWITCH_FRONT_COLOR, RED)
        self.blue_switch = Switch(pq, SWITCH_FRONT_COLOR, BLUE)
        self.scale = Scale(pq, SCALE_FRONT_COLOR)
        self.switches = {RED: self.red_switch, BLUE: self.blue_switch}
        self.seesaws = [self.red_switch, self.blue_switch, self.scale]

        self.vaults = [Vault(RED, self.red_switch, self.scale),
                       Vault(BLUE, self.blue_switch, self.scale)]
        self.vault_map = {vault.alliance: vault for vault in self.vaults}

        self.humans = [Human(alliance, position, self.vault_map[alliance])
                       for alliance in ALLIANCES
                       for position in ('FRONT', 'BACK', 'STATION')]
        self.humans_map = {(human.alliance, human.position): human
                           for human in self.humans}

        # The order affects update() order and CSV column order.
        for agent in itertools.chain(
                self.robots, self.humans, self.seesaws, self.vaults, [pq]):
            self.add(agent)

        # Start keeping score.
        self.score = Score.ZERO

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
        self.score = sum((agent.score() for agent in self.agents), self.score)

    def endgame_score(self):
        # Credit Levitate Power-Ups to (preferably) Robots that didn't climb or park.
        for switch in self.switches.values():
            if switch.levitate_activated:
                alliance = switch.alliance_end
                robots = [r for r in self.robots if r.alliance is alliance]
                picks = sorted(robots, key=lambda r: bool(r.climbed) * 2 + r.at_platform)
                picks[0].climbed = 'Levitated'

        return sum((agent.endgame_score() for agent in self.agents), Score.ZERO)

    def csv_header(self):
        return ['Time', 'Score']

    def csv_row(self):
        return [self.time, self.score]

    def csv_end_header(self):
        return ['', 'Score']

    def csv_end_row(self):
        return ['Final', self.score]

    def play(self, csv_writer):
        """Play out the simulated game."""
        # TODO: Include # Cubes at each Location in the CSV output?
        csv_contributors = [self] + self.agents
        header = sum((c.csv_header() for c in csv_contributors), [])
        csv_writer.writerow(header)

        for t in xrange(GAME_SECS):
            self.tick()
            row = sum((c.csv_row() for c in csv_contributors), [])
            csv_writer.writerow(row)

        self.score += self.endgame_score()
        csv_writer.writerow(())

        header = sum((c.csv_end_header() for c in csv_contributors), [])
        csv_writer.writerow(header)
        row = sum((c.csv_end_row() for c in csv_contributors), [])
        csv_writer.writerow(row)

        print "*** Final {}. ***".format(self.score)
        print


if __name__ == "__main__":
    with open('powerup-output.csv', 'wb') as f:
        writer = csv.writer(f)
        game = PowerUpGame(robot_player=example_robot_player,
                           human_player=example_human_player)
        game.play(writer)
