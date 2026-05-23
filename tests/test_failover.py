"""
Fault-tolerance tests: leader crash and cascading crashes.

Verifies that confirmed operations survive node failures and that
each surviving node correctly promotes to leader and serves clients.
"""

import time
import unittest

from helpers import (
    ThreeNodeCluster,
    _connect, _drain_until, _join_room, _reveal, _get_replica_state, _kill,
)


class Test2SurvivesLeaderCrash(ThreeNodeCluster):

    def test_operation_survives_leader_crash(self):
        """After a confirmed reveal and leader crash, promoted F1 still shows the move."""
        s = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s, lambda m: m.get('type') == 'init_rooms')
        _join_room(s, 'alice', 'room2')
        state = _reveal(s, 'room2', 0, 0)
        self.assertIsNotNone(state, 'Reveal was not confirmed before leader crash')
        revealed_before = [row[:] for row in state['revealed']]
        s.close()

        _kill(self.leader_proc)
        time.sleep(3)   # wait for F1 to detect disconnection and promote

        s2 = _connect('127.0.0.1', self.F1_PORT, timeout=8.0)
        _drain_until(s2, lambda m: m.get('type') == 'init_rooms')
        state_after = _join_room(s2, 'bob', 'room2')
        s2.close()

        self.assertEqual(
            state_after['revealed'], revealed_before,
            'Board state changed after leader crash — data lost!',
        )


class Test3SurvivesLeaderAndF1Crash(ThreeNodeCluster):

    def test_operation_survives_leader_and_f1_crash(self):
        """After a confirmed reveal, even killing both leader and F1, F2 retains the state."""
        s = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s, lambda m: m.get('type') == 'init_rooms')
        _join_room(s, 'alice', 'room3')
        state = _reveal(s, 'room3', 0, 0)
        self.assertIsNotNone(state, 'Reveal not confirmed before crashes')
        revealed_before = [row[:] for row in state['revealed']]
        s.close()

        _kill(self.leader_proc)
        time.sleep(1)
        _kill(self.f1_proc)
        time.sleep(3)

        f2_rep = _get_replica_state('127.0.0.1', self.F2_ADMIN)
        self.assertIsNotNone(f2_rep, 'Could not query F2 admin state after crashes')

        f2_board = f2_rep['rooms'].get('room3')
        self.assertIsNotNone(f2_board, 'room3 not present in F2 after crashes')
        self.assertEqual(
            f2_board['revealed'], revealed_before,
            'F2 board differs after leader + F1 crash',
        )


class TestF2AcceptsClientsAfterBothCrashes(ThreeNodeCluster):
    """
    After leader crash (F1 promotes) and then F1 crash (F2 promotes),
    F2 must serve client connections with the correctly committed state.

    This test goes beyond introspection: it connects an actual client to F2
    and verifies it receives the right board, proving promotion is complete.
    """

    def test_f2_accepts_clients_after_both_crashes(self):
        s = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s, lambda m: m.get('type') == 'init_rooms')
        _join_room(s, 'alice', 'room_f2')
        state = _reveal(s, 'room_f2', 0, 0)
        self.assertIsNotNone(state, 'Reveal must be confirmed before crashes')
        revealed_before = [row[:] for row in state['revealed']]
        s.close()

        # Kill leader — F1 detects EOF and promotes
        _kill(self.leader_proc)
        time.sleep(3)

        # Kill F1 (now promoted) — F2 detects its upstream closed and promotes
        _kill(self.f1_proc)
        time.sleep(3)

        # F2 should now accept client connections
        s2 = _connect('127.0.0.1', self.F2_PORT, timeout=10.0)
        _drain_until(s2, lambda m: m.get('type') == 'init_rooms')
        state_after = _join_room(s2, 'bob', 'room_f2')
        s2.close()

        self.assertEqual(
            state_after['revealed'], revealed_before,
            'F2 served incorrect board after both crashes',
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
