"""
Integration tests for the Distributed Minesweeper backend.

Each test spins up real OS processes (leader + follower-1 + follower-2),
interacts via TCP sockets, and verifies distributed-systems guarantees:
  - SMR consistency across all three replicas
  - Fault-tolerance: operations survive leader crash
  - Fault-tolerance: operations survive leader + follower-1 crash
  - Consistency: rejected when follower-2 is down
  - Correctness: uncommitted ops are discarded after failover
  - Multi-client broadcast correctness
  - Room isolation
  - Operation order preservation
"""

import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
import threading
import unittest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(BASE_DIR, 'backend')
SERVER_PY   = os.path.join(BACKEND_DIR, 'server.py')
SLAVE_PY    = os.path.join(BACKEND_DIR, 'slave.py')

# ---------------------------------------------------------------------------
# Low-level protocol helpers (mirrors backend/protocol.py)
# ---------------------------------------------------------------------------

def _send(sock, d: dict) -> None:
    data   = json.dumps(d).encode('utf-8')
    prefix = struct.pack('!I', len(data))
    sock.sendall(prefix + data)


def _recv(sock) -> dict | None:
    def recvall(n):
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return buf

    raw = recvall(4)
    if not raw:
        return None
    length = struct.unpack('!I', raw)[0]
    body   = recvall(length)
    if not body:
        return None
    return json.loads(body.decode('utf-8'))


def _drain_until(sock, pred, timeout=8.0) -> dict | None:
    """Read messages from sock until pred(msg) is True, or timeout expires."""
    sock.settimeout(timeout)
    try:
        while True:
            msg = _recv(sock)
            if msg is None:
                return None
            if pred(msg):
                return msg
    except socket.timeout:
        return None


# ---------------------------------------------------------------------------
# Higher-level helpers
# ---------------------------------------------------------------------------

def _connect(host: str, port: int, timeout: float = 10.0) -> socket.socket:
    """Connect with retries; raises RuntimeError on failure."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3.0)
            s.connect((host, port))
            return s
        except OSError:
            s.close()
            time.sleep(0.5)
    raise RuntimeError(f'Could not connect to {host}:{port} within {timeout}s')


def _join_room(sock, username: str, room: str) -> dict:
    """
    Send a join action and wait for the update_room reply.
    Returns the board state dict.
    """
    _send(sock, {'action': 'join', 'username': username, 'room': room})
    msg = _drain_until(sock, lambda m: m.get('type') == 'update_room' and m.get('room') == room)
    if msg is None:
        raise RuntimeError(f'Did not receive update_room for room {room}')
    return msg['state']


def _reveal(sock, room: str, row: int, col: int, timeout: float = 8.0) -> dict | None:
    """
    Send a reveal action and wait for the broadcast update_room reply.
    Returns the new state dict, or None if the operation was rejected / timed out.
    """
    _send(sock, {'action': 'reveal', 'room': room, 'r': row, 'c': col})
    msg = _drain_until(
        sock,
        lambda m: (m.get('type') == 'update_room' and m.get('room') == room)
                  or m.get('type') == 'error',
        timeout=timeout,
    )
    if msg is None or msg.get('type') == 'error':
        return None
    return msg.get('state')


def _get_replica_state(host: str, admin_port: int) -> dict | None:
    """
    Connect to a node's ADMIN port and request its introspection state.
    The admin port (PORT + 100) accepts GET_STATE directly without draining init_rooms.
    Returns the STATE_REPLY dict, or None on failure.
    """
    try:
        s = _connect(host, admin_port, timeout=5.0)
        s.settimeout(5.0)
        _send(s, {'type': 'get_state'})
        reply = _drain_until(s, lambda m: m.get('type') == 'state_reply', timeout=5.0)
        s.close()
        return reply
    except Exception:
        return None


def _kill(proc) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# ---------------------------------------------------------------------------
# Base test class: boots the three-node cluster
# ---------------------------------------------------------------------------

class ThreeNodeCluster(unittest.TestCase):
    """
    Starts follower-2, then follower-1, then leader.
    Each subclass can selectively kill nodes mid-test.
    Admin ports (PORT + 100) expose GET_STATE introspection even while nodes
    are in follower mode.
    """

    LEADER_PORT  = 5100   # offset from defaults to avoid port conflicts
    F1_PORT      = 6100
    F2_PORT      = 7100

    @property
    def LEADER_ADMIN(self):
        return self.LEADER_PORT + 100

    @property
    def F1_ADMIN(self):
        return self.F1_PORT + 100

    @property
    def F2_ADMIN(self):
        return self.F2_PORT + 100

    def setUp(self):
        self.f2_proc = self.f1_proc = self.leader_proc = None
        self._start_cluster()

    def _start_cluster(self):
        # follower-2 (terminal node — no next replica)
        f2_env = {
            **os.environ,
            'PORT'      : str(self.F2_PORT),
            'ADMIN_PORT': str(self.F2_PORT + 100),
        }
        self.f2_proc = subprocess.Popen(
            [sys.executable, SLAVE_PY],
            env=f2_env, cwd=BACKEND_DIR,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(0.8)

        # follower-1 (connects to follower-2)
        f1_env = {
            **os.environ,
            'PORT'             : str(self.F1_PORT),
            'ADMIN_PORT'       : str(self.F1_PORT + 100),
            'NEXT_REPLICA_HOST': '127.0.0.1',
            'NEXT_REPLICA_PORT': str(self.F2_PORT),
        }
        self.f1_proc = subprocess.Popen(
            [sys.executable, SLAVE_PY],
            env=f1_env, cwd=BACKEND_DIR,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(0.8)

        # leader (connects to follower-1)
        leader_env = {
            **os.environ,
            'PORT'      : str(self.LEADER_PORT),
            'ADMIN_PORT': str(self.LEADER_PORT + 100),
            'SLAVE_HOST': '127.0.0.1',
            'SLAVE_PORT': str(self.F1_PORT),
        }
        self.leader_proc = subprocess.Popen(
            [sys.executable, SERVER_PY],
            env=leader_env, cwd=BACKEND_DIR,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(3)   # give the cluster time to form

    def tearDown(self):
        for proc in (self.leader_proc, self.f1_proc, self.f2_proc):
            _kill(proc)
        for proc in (self.leader_proc, self.f1_proc, self.f2_proc):
            if proc:
                for pipe in (proc.stdout, proc.stderr):
                    if pipe:
                        try:
                            pipe.close()
                        except Exception:
                            pass


# ---------------------------------------------------------------------------
# Test 1 — All three replicas commit the same operation
# ---------------------------------------------------------------------------

class Test1AllReplicasSameState(ThreeNodeCluster):

    def test_all_replicas_same_state(self):
        """After a reveal is confirmed, all three nodes have the same last_committed_seq."""
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

        self.assertIsNotNone(leader_rep, 'Could not query leader state')
        self.assertIsNotNone(f1_rep,     'Could not query follower-1 state')
        self.assertIsNotNone(f2_rep,     'Could not query follower-2 state')

        l_seq  = leader_rep['last_committed_seq']
        f1_seq = f1_rep['last_committed_seq']
        f2_seq = f2_rep['last_committed_seq']

        self.assertEqual(l_seq, f1_seq, f'Leader seq {l_seq} != F1 seq {f1_seq}')
        self.assertEqual(l_seq, f2_seq, f'Leader seq {l_seq} != F2 seq {f2_seq}')
        self.assertGreater(l_seq, 0, 'No operations were committed')

        # Board state must also match
        l_board  = leader_rep['rooms'].get('room1')
        f1_board = f1_rep['rooms'].get('room1')
        f2_board = f2_rep['rooms'].get('room1')
        self.assertEqual(l_board['revealed'], f1_board['revealed'])
        self.assertEqual(l_board['revealed'], f2_board['revealed'])


# ---------------------------------------------------------------------------
# Test 2 — Confirmed operation survives leader crash
# ---------------------------------------------------------------------------

class Test2SurvivesLeaderCrash(ThreeNodeCluster):

    def test_operation_survives_leader_crash(self):
        """After a confirmed reveal and leader crash, F1 (promoted) still shows the move."""
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


# ---------------------------------------------------------------------------
# Test 3 — Confirmed operation survives leader + follower-1 crash
# ---------------------------------------------------------------------------

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
        time.sleep(3)   # F2 detects F1 loss (it was already in follower mode; stays)

        # F2 was in follower mode for the leader (it received COMMIT from F1).
        # After F1 kills its upstream the F2 process remains up and its state_machine
        # still holds the committed state. F2 was never promoted in this scenario
        # because F2's leader was F1 (which only connects to F2 as next replica, not
        # as a true upstream). F2 will only promote when IT receives a leader connection
        # and that leader disconnects.
        #
        # For this test, we verify F2's committed state via the introspection endpoint.
        f2_rep = _get_replica_state('127.0.0.1', self.F2_ADMIN)
        self.assertIsNotNone(f2_rep, 'Could not query F2 state after crashes')

        f2_board = f2_rep['rooms'].get('room3')
        self.assertIsNotNone(f2_board, 'room3 not present in F2 after crashes')
        self.assertEqual(
            f2_board['revealed'], revealed_before,
            'F2 board differs after leader+F1 crash',
        )


# ---------------------------------------------------------------------------
# Test 4 — No confirmation when follower-2 is down
# ---------------------------------------------------------------------------

class Test4NoConfirmIfF2Down(ThreeNodeCluster):

    def test_no_confirm_if_f2_down(self):
        """
        With F2 down, the PREPARE chain cannot propagate past F1, so the leader
        must not broadcast an update_room — the operation must be rejected.
        We first create the room (while F2 is up) so the join works cleanly,
        then kill F2 and attempt the reveal.
        """
        # Step 1: join and create room while the full cluster is healthy
        s = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s, lambda m: m.get('type') == 'init_rooms')
        _join_room(s, 'alice', 'room4')

        # Step 2: kill F2
        _kill(self.f2_proc)
        time.sleep(2)   # let F1 detect F2 is gone (connection reset / timeout)

        # Step 3: try reveal — should be rejected (no F2 → PREPARE chain breaks)
        state = _reveal(s, 'room4', 0, 0, timeout=12.0)
        self.assertIsNone(state, 'Leader confirmed an operation without F2 — consistency violated!')
        s.close()


# ---------------------------------------------------------------------------
# Test 5 — Uncommitted op is discarded after failover
# ---------------------------------------------------------------------------

class Test5UncommittedDiscardedAfterFailover(ThreeNodeCluster):
    """
    We reveal a cell *after* killing F2 so the PREPARE phase propagates only
    to F1 (F1 stores it in pending_ops) but F1 cannot ACK the leader (no F2 ACK).
    We then kill the leader. F1 promotes. The cell must NOT be visible on F1.
    """

    def test_uncommitted_op_discarded_after_failover(self):
        # First make a confirmed reveal so the room exists on F1
        s = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s, lambda m: m.get('type') == 'init_rooms')
        _join_room(s, 'alice', 'room5')
        confirmed_state = _reveal(s, 'room5', 0, 0)
        self.assertIsNotNone(confirmed_state, 'Initial reveal should succeed')
        s.close()

        # Kill F2 — subsequent ops will be stuck in PREPARE on F1
        _kill(self.f2_proc)
        time.sleep(2)

        # Connect a new client and attempt a second reveal — this will NOT be confirmed
        s2 = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s2, lambda m: m.get('type') == 'init_rooms')
        _join_room(s2, 'bob', 'room5')

        # Kick off the reveal in a background thread (it will block on ACK timeout)
        rejected = []
        def do_reveal():
            result = _reveal(s2, 'room5', 9, 9, timeout=12.0)
            rejected.append(result is None)

        t = threading.Thread(target=do_reveal, daemon=True)
        t.start()

        # While the reveal is pending, kill the leader
        time.sleep(1)
        _kill(self.leader_proc)
        t.join(timeout=15)
        s2.close()

        time.sleep(3)   # F1 detects leader disconnect and promotes

        # Connect to promoted F1 and inspect the board
        s3 = _connect('127.0.0.1', self.F1_PORT, timeout=8.0)
        _drain_until(s3, lambda m: m.get('type') == 'init_rooms')
        state_after = _join_room(s3, 'carol', 'room5')
        s3.close()

        # (9,9) should NOT be revealed — the pending op was discarded on failover
        self.assertFalse(
            state_after['revealed'][9][9],
            'Cell (9,9) is revealed on promoted F1 — uncommitted op leaked!',
        )


# ---------------------------------------------------------------------------
# Test 6 — Two clients in same room receive the same update
# ---------------------------------------------------------------------------

class Test6TwoClientsSameRoom(ThreeNodeCluster):

    def test_two_clients_same_room(self):
        """Client A reveals a cell; Client B (same room) receives the same update."""
        s_a = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s_a, lambda m: m.get('type') == 'init_rooms')
        _join_room(s_a, 'alice', 'room6')

        s_b = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s_b, lambda m: m.get('type') == 'init_rooms')
        _join_room(s_b, 'bob', 'room6')
        # Drain the update_users broadcast that alice triggered
        _drain_until(s_b, lambda m: m.get('type') != 'update_users', timeout=2.0)

        # Client A reveals
        state_a = _reveal(s_a, 'room6', 0, 0)
        self.assertIsNotNone(state_a, 'Client A reveal not confirmed')

        # Client B should receive the broadcast
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


# ---------------------------------------------------------------------------
# Test 7 — Room isolation: reveal in roomA does not change roomB
# ---------------------------------------------------------------------------

class Test7RoomIsolation(ThreeNodeCluster):

    def test_room_isolation(self):
        """An operation in roomA must not affect roomB."""
        s_a = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s_a, lambda m: m.get('type') == 'init_rooms')
        _join_room(s_a, 'alice', 'roomA')

        s_b = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s_b, lambda m: m.get('type') == 'init_rooms')
        state_b_before = _join_room(s_b, 'bob', 'roomB')

        # Reveal in roomA
        _reveal(s_a, 'roomA', 0, 0)

        # roomB must not have changed (no update_room for roomB)
        unexpected = _drain_until(
            s_b,
            lambda m: m.get('type') == 'update_room' and m.get('room') == 'roomB',
            timeout=3.0,
        )
        self.assertIsNone(unexpected, 'roomB received an unsolicited update after roomA reveal')

        # Double-check via introspection
        leader_rep = _get_replica_state('127.0.0.1', self.LEADER_ADMIN)
        state_b_after = leader_rep['rooms'].get('roomB', {})
        self.assertEqual(
            state_b_before.get('revealed'), state_b_after.get('revealed'),
            'roomB board changed after roomA reveal',
        )
        s_a.close()
        s_b.close()


# ---------------------------------------------------------------------------
# Test 8 — Operation order is preserved across replicas
# ---------------------------------------------------------------------------

class Test8OperationOrderPreserved(ThreeNodeCluster):

    def test_operation_order_preserved(self):
        """
        Two successive reveals must appear in the same order on all replicas.
        We verify by comparing committed_log_len (sequence number) after each op.
        """
        s = _connect('127.0.0.1', self.LEADER_PORT)
        _drain_until(s, lambda m: m.get('type') == 'init_rooms')
        _join_room(s, 'alice', 'room8')

        # First reveal
        state1 = _reveal(s, 'room8', 0, 0)
        self.assertIsNotNone(state1, 'First reveal not confirmed')

        rep_after_1 = _get_replica_state('127.0.0.1', self.LEADER_PORT)
        seq_1 = rep_after_1['last_committed_seq']

        # Second reveal (different cell to avoid being a no-op)
        state2 = _reveal(s, 'room8', 9, 9)
        self.assertIsNotNone(state2, 'Second reveal not confirmed')

        rep_after_2 = _get_replica_state('127.0.0.1', self.LEADER_PORT)
        seq_2 = rep_after_2['last_committed_seq']

        self.assertGreater(seq_2, seq_1, 'Second op did not advance the sequence number')

        # All replicas must be at seq_2
        time.sleep(0.5)
        f1_rep = _get_replica_state('127.0.0.1', self.F1_ADMIN)
        f2_rep = _get_replica_state('127.0.0.1', self.F2_ADMIN)
        self.assertIsNotNone(f1_rep, 'Could not query F1 state')
        self.assertIsNotNone(f2_rep, 'Could not query F2 state')
        self.assertEqual(f1_rep['last_committed_seq'], seq_2, 'F1 seq mismatch')
        self.assertEqual(f2_rep['last_committed_seq'], seq_2, 'F2 seq mismatch')
        s.close()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    unittest.main(verbosity=2)
