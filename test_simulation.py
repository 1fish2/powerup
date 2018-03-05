"""Unit tests for Power Up simulation.

To run all tests in this directory, run a PyCharm py.test Run Configuration
or the shell command:
    pytest

TODO: More tests: Robot, Human, Plate, Scale, Switch, PowerUpQueue,
VaultColumn, Vault, PowerUpGame.
"""

from pytest import raises
from simulation import *


class TestSimulation(object):
    def test_find_location(self):
        loc1 = find_location('FRONT_NULL_TERRITORY')
        loc2 = find_location('{}_{}_TERRITORY', 'FRONT', 'NULL')
        assert loc1 is Location.FRONT_NULL_TERRITORY
        assert loc1 is loc2

    def test_location_travel_times(self):
        """Sample the TRAVEL_TIMES[] dict and location.is_inner_zone ."""
        bfiz = Location.BLUE_FRONT_INNER_ZONE
        boz = Location.BLUE_OUTER_ZONE
        rfiz = Location.RED_FRONT_INNER_ZONE
        assert TRAVEL_TIMES[(bfiz, boz)] > 0
        assert TRAVEL_TIMES[(bfiz, boz)] == TRAVEL_TIMES[(boz, bfiz)]

        with raises(KeyError):
            _ = TRAVEL_TIMES[(bfiz, rfiz)]

        assert bfiz.is_inner_zone
        assert not boz.is_inner_zone

    def test_typename(self):
        assert typename(self) == 'TestSimulation'

    def test_score(self):
        s1 = Score(10, 20)
        s2 = Score(100, 200)
        s3 = Score(110, 220)
        assert s1 + s2 == s3

        s4 = Score.pick(RED, 11)
        assert s4 == Score(red=11, blue=0)

        s5 = Score.pick(BLUE, 9)
        assert s5 == Score(red=0, blue=9)

    def test_score_is_immutable(self):
        s = Score(0, 0)
        assert s.red == 0
        assert s.blue == 0
        assert s == Score.ZERO

        with raises(AttributeError):
            s.red = 10

    def test_score_wlt(self):
        s1 = Score(10, 11)
        assert s1.wlt_rp() == Score(0, 2)

        s2 = Score(100, 11)
        assert s2.wlt_rp() == Score(2, 0)

        s3 = Score(0, 0)
        assert s3.wlt_rp() == Score(1, 1)

    def test_sep(self):
        assert sep(3.14) == '3.14 '
        assert sep('') == ''

    def test_agent(self):
        """Run basic tests on the Agent class."""
        class Agent99(Agent):
            def __init__(self, simulation, alliance, position):
                super(Agent99, self).__init__(simulation, alliance, position)
                self.actions = 0

            def score(self):
                return super(Agent99, self).score() + Score(self.time + 100, self.actions + 100)

            def scheduled_action_done(self):
                self.actions += 1

        sim = Simulation()
        agent = Agent99(sim, RED, 'best')
        sim.test_actions_done = 0  # test state

        def doit():
            sim.test_actions_done += 1

        assert agent.name == 'RED best Agent99'
        assert agent.simulation is sim
        assert agent.alliance is RED
        assert agent.eta is None
        assert agent.scheduled_action is None
        assert agent.scheduled_action_description == ''
        assert agent.autonomous
        assert agent.score() == Score(100, 100)
        assert agent.endgame_score() == Score.ZERO

        assert len(sim.agents) == 1
        assert sim.agents[agent.name] is agent

        # Schedule an action and step time forward to run it.
        agent.schedule_action(2, doit, 'inc')
        assert agent.time == 0
        assert sim.test_actions_done == 0
        assert agent.actions == 0
        assert agent.score() == Score(100, 100)  # 0 time ticks, 0 actions done
        assert agent.scheduled_action_description == 'inc'
        assert agent.scheduled_action is not None

        sim.tick()
        assert sim.test_actions_done == 0
        assert agent.actions == 0
        assert agent.score() == Score(101, 100)  # 1 time tick, 0 actions done
        assert agent.scheduled_action_description == 'inc'
        assert agent.scheduled_action is not None

        sim.tick()
        assert agent.time == 2
        assert sim.test_actions_done == 1
        assert agent.actions == 1
        assert agent.score() == Score(102, 101)  # 2 ticks, 1 action done
        assert agent.scheduled_action is None
        assert agent.scheduled_action_description == ''

        assert agent.wait_for_teleop()
        assert agent.time == 2
        for step in xrange(AUTONOMOUS_SECS - 1):
            assert agent.autonomous
            sim.tick()
            assert sim.test_actions_done == 1

        assert not agent.autonomous
        assert agent.actions == 2
        assert agent.score() == Score(116, 102)  # 16 ticks, 2 actions done
