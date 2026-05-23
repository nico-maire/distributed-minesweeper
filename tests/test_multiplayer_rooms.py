"""
Multiplayer and room isolation tests.

Verifies broadcast correctness within a room and the absence of
cross-room interference.
"""

import time
import unittest

from helpers import (
    ThreeNodeCluster,
    _connect, _drain_until, _join_room, _reveal, _get_replica_state,
)


class Test6TwoClientsSameRoom(ThreeNodeCluster):

    def test_two_clients_same_room(self):
        """Client A reveals a cell; Client B (same room) receives the same update."""
        s_a = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s_a, lambda m: m.get('type') == 'init_rooms')
        _join_room(s_a, 'alice', 'room6')

        s_b = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s_b, lambda m: m.get('type') == 'init_rooms')
        _join_room(s_b, 'bob', 'room6')
        # Drain any update_users broadcast from alice's join
        _drain_until(s_b, lambda m: m.get('type') != 'update_users', timeout=2.0)

        state_a = _reveal(s_a, 'room6', 0, 0)
        self.assertIsNotNone(state_a, 'Client A reveal not confirmed')

        msg_b = _drain_until(
            s_b,
            lambda m: m.get('type') == 'update_room' and m.get('room') == 'room6',
            timeout=6.0,
        )
        self.assertIsNotNone(msg_b, 'Client B did not receive update_room broadcast')
        self.assertEqual(
            msg_b['state']['revealed'], state_a['revealed'],
            'Client B received a different board state than Client A',
        )
        s_a.close()
        s_b.close()


class Test7RoomIsolation(ThreeNodeCluster):

    def test_room_isolation(self):
        """A reveal in roomA must not affect roomB."""
        s_a = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s_a, lambda m: m.get('type') == 'init_rooms')
        _join_room(s_a, 'alice', 'roomA')

        s_b = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s_b, lambda m: m.get('type') == 'init_rooms')
        state_b_before = _join_room(s_b, 'bob', 'roomB')

        _reveal(s_a, 'roomA', 0, 0)

        unexpected = _drain_until(
            s_b,
            lambda m: m.get('type') == 'update_room' and m.get('room') == 'roomB',
            timeout=3.0,
        )
        self.assertIsNone(unexpected, 'roomB received an unsolicited update after roomA reveal')

        leader_rep   = _get_replica_state('127.0.0.1', self.LEADER_ADMIN)
        state_b_after = leader_rep['rooms'].get('roomB', {})
        self.assertEqual(
            state_b_before.get('revealed'), state_b_after.get('revealed'),
            'roomB board changed after roomA reveal',
        )
        s_a.close()
        s_b.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
