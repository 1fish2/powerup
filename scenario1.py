#!/usr/bin/env python

"""
An example scenario of Power Up game scoring simulation.
"""

from simulation import *


def robot_player(robot):
    """
    A Robot "game player" (decider) -- a generator that chooses behaviors
    like drive to a destination. The Robot yields to this generator each
    time it needs instructions; this generator in turn updates the Robot
    and returns a behavior description.
    """
    # First cut: Preload Cubes in all Robots, drive to earn auto-run
    # points, and place a Cube.

    alliance = robot.alliance
    simulation = robot.simulation
    switch_side = "FRONT" if SWITCH_FRONT_COLOR is alliance else "BACK"
    scale_side = "FRONT" if SCALE_FRONT_COLOR is alliance else "BACK"

    exchange_zone = find_location("{}_EXCHANGE_ZONE", alliance)
    front_inner_zone = find_location("{}_{}_INNER_ZONE", alliance, "FRONT")
    outer_zone = find_location("{}_OUTER_ZONE", alliance)

    # (A drive_path() subroutine would be ugly without Python 3 'yield from'.)
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
        # Model a slightly slower Robot in one alliance. With both #2
        # Robots placing Cubes on the Scale, RED will own the Scale for
        # 1 second before BLUE matches its Cube.
        if alliance is BLUE:
            robot.place_time += 1

        robot.cubes = 1

        drive_to("{}_{}_INNER_ZONE", alliance, scale_side)
        yield "auto-run"

        drive_to("{}_NULL_TERRITORY", scale_side)
        yield "go to my Scale plate"

        robot.place()
        yield "place a Cube on the Scale"

        while True:
            yield "done"

    def red3():
        robot.cubes = 1

        drive_to(exchange_zone)
        yield "to Exchange"

        robot.place()
        yield "place a Cube in the Exchange"

        for _ in robot.drive_path(outer_zone, front_inner_zone):
            yield "auto-run"

        # A smart-enough Autonomous mode with great navigation sensors
        # could start moving Cubes from the Power Cube Zone...
        if robot.wait_for_teleop():
            yield "wait for Teleop"

        # Move up to 8 more Cubes from the Power Cube Zone into the Exchange.
        moved_cubes = 0
        power_cube_zone = find_location('{}_POWER_CUBE_ZONE', alliance)
        while simulation.cubes[power_cube_zone] and moved_cubes < 8:
            for _ in robot.drive_path(outer_zone, power_cube_zone):
                yield "go get a Power Cube"

            robot.pickup()
            yield "pickup a Power Cube"

            for _ in robot.drive_path(outer_zone, exchange_zone):
                yield "bring it to the Exchange"

            robot.place()
            yield "place a Cube in the Exchange"
            moved_cubes += 1

        while True:
            yield "done"

    def blue3():
        # Model a slightly slower robot.
        robot.extra_drive_time += 1
        robot.pickup_time += 2
        robot.drop_time += 1
        robot.place_time += 0
        robot.climb_time += 2

        robot.cubes = 1

        drive_to(exchange_zone)
        yield "to Exchange"

        robot.place()
        yield "place a Cube in the Exchange"

        drive_to(outer_zone)
        yield "auto-run"

        drive_to(front_inner_zone)
        yield "auto-run"

        while True:
            yield "done"

    # Here's one way to pick a different player for each Robot.
    # Alternatively, map tuples (alliance, robot.position) to functions.
    # Or make them methods in a class then use getattr() for lookup.
    generator = {'RED 1 Robot': player1, 'BLUE 1 Robot': player1,
                 'RED 2 Robot': player2, 'BLUE 2 Robot': player2,
                 'RED 3 Robot': red3,    'BLUE 3 Robot': blue3}[robot.name]()
    robot.set_player(generator)


def human_player(human):
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
        # The STATION Human ought to move Cubes from the Exchange into
        # Vault columns. The others ought to push Cubes through Portals.
        while True:
            yield "done"

    human.set_player(player())


if __name__ == "__main__":
    """If desired, set different values for these FMS start-of-match choices:
        SWITCH_FRONT_COLOR, SCALE_FRONT_COLOR = BLUE, RED
    """

    play(robot_player, human_player, __file__)
