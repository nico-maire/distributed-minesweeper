"""
Consistency-failure tests.

Verifies that the system rejects operations correctly when the chain is
broken (CP guarantees) and that uncommitted operations are discarded on
failover (no phantom writes).
"""

import threading
import time
import unittest

from helpers import (
    ThreeNodeCluster,
    _connect, _drain_until, _join_room, _reveal, _kill,
)


class Test4NoConfirmIfF2Down(ThreeNodeCluster):

    def test_no_confirm_if_f2_down(self):
        """
        With F2 down, the PREPARE chain cannot complete past F1.
        The leader must reject the operation — no update_room broadcast.
        We create the room while the cluster is healthy, then kill F2.
        """
        s = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s, lambda m: m.get('type') == 'init_rooms')
        _join_room(s, 'alice', 'room4')

        _kill(self.f2_proc)
        time.sleep(2)

        state = _reveal(s, 'room4', 0, 0, timeout=12.0)
        self.assertIsNone(state, 'Leader confirmed an operation without F2 — consistency violated!')
        s.close()


class Test5UncommittedDiscardedAfterFailover(ThreeNodeCluster):
    """
    Kills F2 so that PREPARE propagates only to F1 (stored in pending_ops)
    but F1 cannot ACK the leader (no F2 ACK). Then kills the leader.
    F1 promotes and must NOT surface the pending (uncommitted) operation.
    """

    def test_uncommitted_op_discarded_after_failover(self):
        # First confirm a reveal so the room exists on all replicas
        s = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s, lambda m: m.get('type') == 'init_rooms')
        _join_room(s, 'alice', 'room5')
        confirmed_state = _reveal(s, 'room5', 0, 0)
        self.assertIsNotNone(confirmed_state, 'Initial reveal should succeed')
        s.close()

        # Kill F2 — next ops will be stuck in PREPARE on F1
        _kill(self.f2_proc)
        time.sleep(2)

        s2 = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s2, lambda m: m.get('type') == 'init_rooms')
        _join_room(s2, 'bob', 'room5')

        # Kick off a reveal in a background thread (will block on ACK timeout)
        rejected = []

        def do_reveal():
            result = _reveal(s2, 'room5', 9, 9, timeout=12.0)
            rejected.append(result is None)

        t = threading.Thread(target=do_reveal, daemon=True)
        t.start()

        # Kill the leader while the reveal is pending
        time.sleep(1)
        _kill(self.leader_proc)
        t.join(timeout=15)
        s2.close()

        time.sleep(3)   # F1 detects leader disconnect and promotes

        s3 = _connect('127.0.0.1', self.F1_PORT, timeout=8.0)
        _drain_until(s3, lambda m: m.get('type') == 'init_rooms')
        state_after = _join_room(s3, 'carol', 'room5')
        s3.close()

        self.assertFalse(
            state_after['revealed'][9][9],
            'Cell (9,9) is revealed on promoted F1 — uncommitted op leaked!',
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
