import os
import random
import socket
import threading
import time
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

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

state_machine = GameStateMachine()
room_manager  = RoomManager()
replication   = ChainReplicationManager()


# ---------------------------------------------------------------------------
# Client handler
# ---------------------------------------------------------------------------

def _handle_client(client_socket, address) -> None:
    print(f'[*] Client connected from {address}')
    send_message(client_socket, {
        'type' : INIT_ROOMS,
        'rooms': state_machine.get_all_states(),
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
                    'last_committed_seq': state_machine.last_committed_seq,
                    'committed_log_len' : state_machine.get_committed_log_length(),
                    'rooms'             : state_machine.get_all_states(),
                })
                continue

            action = msg.get('action')
            room   = msg.get('room', 'default')

            if action == ACTION_JOIN:
                client_username = msg.get('username', 'Anonymous')
                client_room     = room

                if not state_machine.has_room(room):
                    seed = random.randint(0, 2**32)
                    cmd  = {
                        'seq'  : replication.next_seq(),
                        'op_id': str(uuid.uuid4()),
                        'type' : ACTION_CREATE_ROOM,
                        'room' : room,
                        'rows' : 10, 'cols': 10, 'mines': 10,
                        'seed' : seed,
                    }
                    if not replication.replicate(cmd):
                        send_message(client_socket, {
                            'type': 'error',
                            'reason': 'room_creation_replication_failed',
                        })
                        continue
                    state_machine.apply_command(cmd)

                room_manager.add_client(room, client_socket)
                users = room_manager.add_user(room, client_username)
                # UPDATE_USERS is fire-and-forget: active user sessions are
                # transient state and are reconstructed on client rejoin.
                users_msg = {'type': UPDATE_USERS, 'room': room, 'users': users}
                replication.send_direct(users_msg)
                room_manager.broadcast_to_room(room, users_msg)
                send_message(client_socket, {
                    'type' : UPDATE_ROOM,
                    'room' : room,
                    'state': state_machine.get_state(room),
                })
                continue

            r = msg.get('r', 0)
            c = msg.get('c', 0)

            if action in (ACTION_REVEAL, ACTION_FLAG):
                cmd = {
                    'seq'  : replication.next_seq(),
                    'op_id': str(uuid.uuid4()),
                    'type' : action,
                    'room' : room, 'row': r, 'col': c,
                }
                if not replication.replicate(cmd):
                    send_message(client_socket, {
                        'type': 'error', 'reason': 'replication_failed',
                    })
                    continue
                new_state = state_machine.apply_command(cmd)
                room_manager.broadcast_to_room(room, {
                    'type': UPDATE_ROOM, 'room': room, 'state': new_state,
                })

            elif action == ACTION_RESTART:
                seed = random.randint(0, 2**32)
                cmd  = {
                    'seq'  : replication.next_seq(),
                    'op_id': str(uuid.uuid4()),
                    'type' : ACTION_RESTART,
                    'room' : room, 'seed': seed,
                }
                if not replication.replicate(cmd):
                    send_message(client_socket, {
                        'type': 'error', 'reason': 'replication_failed',
                    })
                    continue
                new_state = state_machine.apply_command(cmd)
                room_manager.broadcast_to_room(room, {
                    'type': UPDATE_ROOM, 'room': room, 'state': new_state,
                })

    except Exception as e:
        print(f'[client error] {e}')
    finally:
        client_socket.close()
        if client_username and client_room:
            users = room_manager.remove_user(client_room, client_username)
            room_manager.remove_client(client_socket)
            room_manager.broadcast_to_room(client_room, {
                'type': UPDATE_USERS, 'room': client_room, 'users': users,
            })
        else:
            room_manager.remove_client(client_socket)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _admin_server(host: str, port: int) -> None:
    """Introspection endpoint used by integration tests."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(5)
    while True:
        try:
            conn, _ = s.accept()
            msg = receive_message(conn)
            if msg and msg.get('type') == GET_STATE:
                send_message(conn, {
                    'type'              : STATE_REPLY,
                    'last_committed_seq': state_machine.last_committed_seq,
                    'committed_log_len' : state_machine.get_committed_log_length(),
                    'rooms'             : state_machine.get_all_states(),
                })
            conn.close()
        except Exception:
            pass


def start_server() -> None:
    HOST       = os.environ.get('HOST', '0.0.0.0')
    PORT       = int(os.environ.get('PORT', 5000))
    SLAVE_HOST = os.environ.get('SLAVE_HOST', 'localhost')
    SLAVE_PORT = int(os.environ.get('SLAVE_PORT', 6000))
    ADMIN_PORT = int(os.environ.get('ADMIN_PORT', PORT + 100))

    # Connect to follower-1
    follower_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    while True:
        try:
            follower_sock.connect((SLAVE_HOST, SLAVE_PORT))
            print(f'[+] Connected to follower-1 at {SLAVE_HOST}:{SLAVE_PORT}')
            break
        except socket.error:
            print('[*] Retrying connection to follower-1...')
            time.sleep(2)

    replication.set_follower(follower_sock)

    # Send current state (including seq) so followers start in sync
    send_message(follower_sock, {
        'type'              : INIT_ROOMS,
        'rooms'             : state_machine.get_all_states(),
        'last_committed_seq': state_machine.last_committed_seq,
    })

    threading.Thread(target=replication.listen_for_acks, daemon=True).start()
    threading.Thread(target=_admin_server, args=(HOST, ADMIN_PORT), daemon=True).start()
    print(f'[+] Admin introspection on {HOST}:{ADMIN_PORT}')

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(10)
    print(f'[+] Leader listening on {HOST}:{PORT}')

    try:
        while True:
            client_sock, addr = server_socket.accept()
            threading.Thread(
                target=_handle_client,
                args=(client_sock, addr),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        pass
    finally:
        server_socket.close()


if __name__ == '__main__':
    start_server()
