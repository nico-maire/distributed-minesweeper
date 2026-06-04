"""
Shared infrastructure for distributed minesweeper integration tests.

Provides protocol helpers, connection helpers, and the ThreeNodeCluster
base class that boots and tears down a full leader + F1 + F2 cluster.
"""

import json
import os
import socket
import struct
import subprocess
import sys
import time
import unittest

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
    """Send a join action and wait for the update_room reply. Returns board state."""
    _send(sock, {'action': 'join', 'username': username, 'room': room})
    msg = _drain_until(sock, lambda m: m.get('type') == 'update_room' and m.get('room') == room)
    if msg is None:
        raise RuntimeError(f'Did not receive update_room for room {room}')
    return msg['state']


def _reveal(sock, room: str, row: int, col: int, timeout: float = 8.0) -> dict | None:
    """
    Send a reveal action and wait for the update_room broadcast.
    Returns the new state dict, or None if rejected / timed out.
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
    """Query a node's admin introspection port. Returns STATE_REPLY or None."""
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
    Admin ports (PORT + 100) expose GET_STATE even while nodes are in
    follower mode, without interfering with the replication protocol.
    """

    LEADER_PORT = 5100   # offset from defaults to avoid port conflicts
    F1_PORT     = 6100
    F2_PORT     = 7100

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
        time.sleep(1.5)

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
        time.sleep(1.5)

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
        time.sleep(3)

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
