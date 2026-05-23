import random
import threading
import uuid

from protocol import (
    send_message, receive_message,
    INIT_ROOMS, UPDATE_ROOM, UPDATE_USERS,
    GET_STATE, STATE_REPLY,
    ACTION_JOIN, ACTION_REVEAL, ACTION_FLAG, ACTION_RESTART, ACTION_CREATE_ROOM,
)
from replication import ChainReplicationManager
from room_manager import RoomManager
from state_machine import GameStateMachine


class PromotedLeaderRuntime:
    """
    Client-facing handler for a follower that has been promoted to leader.

    Accepts game actions from clients and replicates them to the next
    surviving replica (if any) via the shared ChainReplicationManager.
    When no next replica exists the node operates in degraded mode:
    it accepts writes without further replication — state is no longer
    fault-tolerant but the game remains available.
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

    def handle_client(self, client_socket, address) -> None:
        print(f'[*] Promoted leader: client connected from {address}')

        send_message(client_socket, {
            'type' : INIT_ROOMS,
            'rooms': self._sm.get_all_states(),
        })

        client_username = None
        client_room     = None

        try:
            while True:
                msg = receive_message(client_socket)
                if not msg:
                    break

                if msg.get('type') == GET_STATE:
                    send_message(client_socket, {
                        'type'              : STATE_REPLY,
                        'last_committed_seq': self._sm.last_committed_seq,
                        'committed_log_len' : self._sm.get_committed_log_length(),
                        'rooms'             : self._sm.get_all_states(),
                    })
                    continue

                action = msg.get('action')
                room   = msg.get('room', 'default')

                if action == ACTION_JOIN:
                    client_username = msg.get('username', 'Anonymous')
                    client_room     = room

                    if not self._sm.has_room(room):
                        seed = random.randint(0, 2**32)
                        cmd  = {
                            'seq'  : self._repl.next_seq(),
                            'op_id': str(uuid.uuid4()),
                            'type' : ACTION_CREATE_ROOM,
                            'room' : room,
                            'rows' : 10, 'cols': 10, 'mines': 10,
                            'seed' : seed,
                        }
                        if not self._repl.replicate(cmd):
                            send_message(client_socket, {
                                'type': 'error',
                                'reason': 'room_creation_replication_failed',
                            })
                            continue
                        self._sm.apply_command(cmd)

                    self._rm.add_client(room, client_socket)
                    users = self._rm.add_user(room, client_username)
                    self._rm.broadcast_to_room(room, {
                        'type': UPDATE_USERS, 'room': room, 'users': users,
                    })
                    send_message(client_socket, {
                        'type' : UPDATE_ROOM,
                        'room' : room,
                        'state': self._sm.get_state(room),
                    })
                    continue

                r = msg.get('r', 0)
                c = msg.get('c', 0)

                if action in (ACTION_REVEAL, ACTION_FLAG):
                    cmd = {
                        'seq'  : self._repl.next_seq(),
                        'op_id': str(uuid.uuid4()),
                        'type' : action,
                        'room' : room, 'row': r, 'col': c,
                    }
                    if not self._repl.replicate(cmd):
                        send_message(client_socket, {
                            'type': 'error', 'reason': 'replication_failed',
                        })
                        continue
                    new_state = self._sm.apply_command(cmd)
                    self._rm.broadcast_to_room(room, {
                        'type': UPDATE_ROOM, 'room': room, 'state': new_state,
                    })

                elif action == ACTION_RESTART:
                    seed = random.randint(0, 2**32)
                    cmd  = {
                        'seq'  : self._repl.next_seq(),
                        'op_id': str(uuid.uuid4()),
                        'type' : ACTION_RESTART,
                        'room' : room, 'seed': seed,
                    }
                    if not self._repl.replicate(cmd):
                        send_message(client_socket, {
                            'type': 'error', 'reason': 'replication_failed',
                        })
                        continue
                    new_state = self._sm.apply_command(cmd)
                    self._rm.broadcast_to_room(room, {
                        'type': UPDATE_ROOM, 'room': room, 'state': new_state,
                    })

        except Exception as e:
            print(f'[promoted leader client error] {e}')
        finally:
            client_socket.close()
            if client_username and client_room:
                users = self._rm.remove_user(client_room, client_username)
                self._rm.remove_client(client_socket)
                self._rm.broadcast_to_room(client_room, {
                    'type': UPDATE_USERS, 'room': client_room, 'users': users,
                })
            else:
                self._rm.remove_client(client_socket)
