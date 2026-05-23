"""
Replication correctness tests.

Verifies that all replicas converge to the same state and that the
total order of operations is preserved across the entire chain.
"""

import time
import unittest

from helpers import (
    ThreeNodeCluster,
    _connect, _drain_until, _join_room, _reveal, _get_replica_state,
)


class Test1AllReplicasSameState(ThreeNodeCluster):

    def test_all_replicas_same_state(self):
        """After a confirmed reveal, all three nodes share the same last_committed_seq and board."""
        s = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s, lambda m: m.get('type') == 'init_rooms')
        _join_room(s, 'alice', 'room1')
        state = _reveal(s, 'room1', 0, 0)
        self.assertIsNotNone(state, 'Reveal was not confirmed (replication failed?)')
        s.close()

        time.sleep(1)

        leader_rep = _get_replica_state('127.0.0.1', self.LEADER_ADMIN)
        f1_rep     = _get_replica_state('127.0.0.1', self.F1_ADMIN)
        f2_rep     = _get_replica_state('127.0.0.1', self.F2_ADMIN)

        self.assertIsNotNone(leader_rep, 'Could not query leader admin state')
        self.assertIsNotNone(f1_rep,     'Could not query follower-1 admin state')
        self.assertIsNotNone(f2_rep,     'Could not query follower-2 admin state')

        l_seq  = leader_rep['last_committed_seq']
        f1_seq = f1_rep['last_committed_seq']
        f2_seq = f2_rep['last_committed_seq']

        self.assertEqual(l_seq, f1_seq, f'Leader seq {l_seq} != F1 seq {f1_seq}')
        self.assertEqual(l_seq, f2_seq, f'Leader seq {l_seq} != F2 seq {f2_seq}')
        self.assertGreater(l_seq, 0, 'No operations were committed')

        l_board  = leader_rep['rooms'].get('room1')
        f1_board = f1_rep['rooms'].get('room1')
        f2_board = f2_rep['rooms'].get('room1')
        self.assertEqual(l_board['revealed'], f1_board['revealed'])
        self.assertEqual(l_board['revealed'], f2_board['revealed'])


class Test8OperationOrderPreserved(ThreeNodeCluster):

    def test_operation_order_preserved(self):
        """
        Two successive reveals must advance last_committed_seq monotonically
        and all replicas must reflect the same final sequence number.
        """
        s = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s, lambda m: m.get('type') == 'init_rooms')
        _join_room(s, 'alice', 'room8')

        state1 = _reveal(s, 'room8', 0, 0)
        self.assertIsNotNone(state1, 'First reveal not confirmed')

        rep_after_1 = _get_replica_state('127.0.0.1', self.LEADER_ADMIN)
        seq_1 = rep_after_1['last_committed_seq']

        state2 = _reveal(s, 'room8', 9, 9)
        self.assertIsNotNone(state2, 'Second reveal not confirmed')

        rep_after_2 = _get_replica_state('127.0.0.1', self.LEADER_ADMIN)
        seq_2 = rep_after_2['last_committed_seq']

        self.assertGreater(seq_2, seq_1, 'Second op did not advance the sequence number')

        time.sleep(0.5)
        f1_rep = _get_replica_state('127.0.0.1', self.F1_ADMIN)
        f2_rep = _get_replica_state('127.0.0.1', self.F2_ADMIN)
        self.assertIsNotNone(f1_rep, 'Could not query F1 admin state')
        self.assertIsNotNone(f2_rep, 'Could not query F2 admin state')
        self.assertEqual(f1_rep['last_committed_seq'], seq_2, 'F1 seq mismatch after second op')
        self.assertEqual(f2_rep['last_committed_seq'], seq_2, 'F2 seq mismatch after second op')
        s.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
