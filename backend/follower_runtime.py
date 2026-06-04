from model import Minesweeper
from protocol import (
    send_message, receive_message,
    PREPARE_COMMAND, PREPARE_ACK,
    COMMIT_COMMAND, COMMIT_ACK,
    INIT_ROOMS, UPDATE_USERS,
)
from replication import ChainReplicationManager
from room_manager import RoomManager
from state_machine import GameStateMachine


class FollowerRuntime:
    """
    Replica loop for a follower node.

    Reads PREPARE_COMMAND / COMMIT_COMMAND from the upstream (leader or
    promoted F1). If a next replica exists, forwards commands through the
    chain via a shared ChainReplicationManager and waits for ACKs before
    ACKing the upstream. Uncommitted pending_ops are discarded on exit.

    The ChainReplicationManager instance is shared with the promoted-leader
    phase so the same ACK listener thread and socket are reused, avoiding
    the race condition that would occur if two threads read from the same
    socket simultaneously.
    """

    def __init__(
        self,
        state_machine: GameStateMachine,
        room_manager: RoomManager,
        replication: ChainReplicationManager,
    ):
        self._sm   = state_machine
        self._rm   = room_manager
        self._repl = replication

    def run(self, leader_socket) -> None:
        """
        Blocks until the upstream connection closes.
        Pending (uncommitted) operations are discarded on exit.
        """
        pending_ops: dict = {}

        try:
            while True:
                data = receive_message(leader_socket)
                if not data:
                    print('[!] Upstream disconnected — preparing for promotion')
                    break

                msg_type = data.get('type')
                op_id    = data.get('op_id')
                seq      = data.get('seq')

                if msg_type == PREPARE_COMMAND:
                    command = data.get('command', {})
                    pending_ops[seq] = {'op_id': op_id, 'command': command}

                    if self._repl.has_follower():
                        # Upstream ACK is sent only after downstream durability in the chain.
                        if not self._repl.send_to_follower(data):
                            continue
                        if not self._repl.wait_ack(op_id, PREPARE_ACK):
                            continue

                    try:
                        send_message(leader_socket, {
                            'type': PREPARE_ACK, 'op_id': op_id, 'seq': seq,
                        })
                    except Exception:
                        pass

                elif msg_type == COMMIT_COMMAND:
                    if self._repl.has_follower():
                        if not self._repl.send_to_follower(data):
                            continue
                        if not self._repl.wait_ack(op_id, COMMIT_ACK):
                            continue

                    entry = pending_ops.pop(seq, None)
                    applied = True
                    if entry:
                        try:
                            self._sm.apply_command(entry['command'])
                        except ValueError as e:
                            print(f'[!] State machine error: {e}')
                            applied = False

                    if applied:
                        try:
                            send_message(leader_socket, {
                                'type': COMMIT_ACK, 'op_id': op_id, 'seq': seq,
                            })
                        except Exception:
                            pass

                elif msg_type == INIT_ROOMS:
                    with self._sm._lock:
                        for room, st in data.get('rooms', {}).items():
                            self._sm._games[room] = Minesweeper.from_dict(st)
                        seq_val = data.get('last_committed_seq')
                        if seq_val is not None:
                            self._sm.last_committed_seq = seq_val
                    if self._repl.has_follower():
                        self._repl.send_to_follower(data)

                elif msg_type == UPDATE_USERS:
                    room  = data.get('room')
                    users = data.get('users', [])
                    if room:
                        with self._rm._lock:
                            self._rm._users[room] = list(users)

        except Exception as e:
            print(f'[follower error] {e}')
        finally:
            pending_ops.clear()
            leader_socket.close()
