import os
import random
import socket
import threading
import time
import uuid

from protocol import (
    send_message, receive_message,
    PREPARE_COMMAND, PREPARE_ACK,
    COMMIT_COMMAND, COMMIT_ACK,
    INIT_ROOMS, UPDATE_ROOM, UPDATE_USERS,
    GET_STATE, STATE_REPLY,
    ACTION_JOIN, ACTION_REVEAL, ACTION_FLAG, ACTION_RESTART, ACTION_CREATE_ROOM,
)
from room_manager import RoomManager
from state_machine import GameStateMachine

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

state_machine  = GameStateMachine()
room_manager   = RoomManager()
follower_socket = None          # connection to follower-1

# Sequence counter — total order across all rooms
_seq_counter = 0
_seq_lock    = threading.Lock()

# ACK table: (op_id, ack_type) -> True
_ack_received = {}
_ack_lock     = threading.Lock()


def _next_seq() -> int:
    global _seq_counter
    with _seq_lock:
        _seq_counter += 1
        return _seq_counter


# ---------------------------------------------------------------------------
# Replication helpers
# ---------------------------------------------------------------------------

def _listen_for_acks() -> None:
    """Daemon thread: reads PREPARE_ACK / COMMIT_ACK from follower-1."""
    global follower_socket
    while True:
        if not follower_socket:
            time.sleep(0.5)
            continue
        try:
            msg = receive_message(follower_socket)
            if not msg:
                time.sleep(1)
                continue
            msg_type = msg.get('type')
            op_id    = msg.get('op_id')
            if msg_type in (PREPARE_ACK, COMMIT_ACK) and op_id:
                with _ack_lock:
                    _ack_received[(op_id, msg_type)] = True
        except Exception:
            time.sleep(1)


def _wait_for_ack(op_id: str, ack_type: str, timeout: float = 5.0) -> bool:
    key      = (op_id, ack_type)
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _ack_lock:
            if key in _ack_received:
                _ack_received.pop(key)
                return True
        time.sleep(0.01)
    with _ack_lock:
        _ack_received.pop(key, None)
    return False


def _replicate(command: dict) -> bool:
    """
    Runs the 2-phase PREPARE/COMMIT protocol with follower-1.
    Returns True only when the follower (chain) has committed the operation.
    If no follower is connected, returns True (solo mode).
    """
    if not follower_socket:
        return True

    seq   = command['seq']
    op_id = command['op_id']

    # Phase 1 — PREPARE
    try:
        send_message(follower_socket, {
            'type': PREPARE_COMMAND,
            'seq': seq,
            'op_id': op_id,
            'command': command,
        })
    except Exception as e:
        print(f'[!] Failed to send PREPARE to follower: {e}')
        return False

    if not _wait_for_ack(op_id, PREPARE_ACK):
        print(f'[!] PREPARE_ACK timeout for op {op_id} seq={seq}')
        return False

    # Phase 2 — COMMIT
    try:
        send_message(follower_socket, {
            'type': COMMIT_COMMAND,
            'seq': seq,
            'op_id': op_id,
        })
    except Exception as e:
        print(f'[!] Failed to send COMMIT to follower: {e}')
        return False

    if not _wait_for_ack(op_id, COMMIT_ACK):
        print(f'[!] COMMIT_ACK timeout for op {op_id} seq={seq}')
        return False

    return True


# ---------------------------------------------------------------------------
# Client handler
# ---------------------------------------------------------------------------

def _handle_client(client_socket, address) -> None:
    print(f'[*] Client connected from {address}')

    # Send current state of all rooms
    send_message(client_socket, {
        'type': INIT_ROOMS,
        'rooms': state_machine.get_all_states(),
    })

    client_username = None
    client_room     = None

    try:
        while True:
            msg = receive_message(client_socket)
            if not msg:
                break

            # Introspection endpoint (used by integration tests)
            if msg.get('type') == GET_STATE:
                send_message(client_socket, {
                    'type': STATE_REPLY,
                    'last_committed_seq': state_machine.last_committed_seq,
                    'committed_log_len': state_machine.get_committed_log_length(),
                    'rooms': state_machine.get_all_states(),
                })
                continue

            action = msg.get('action')
            room   = msg.get('room', 'default')

            # ----------------------------------------------------------------
            # JOIN
            # ----------------------------------------------------------------
            if action == ACTION_JOIN:
                client_username = msg.get('username', 'Anonymous')
                client_room     = room

                # Create room via SMR if it doesn't exist yet
                if not state_machine.has_room(room):
                    seed = random.randint(0, 2**32)
                    cmd  = {
                        'seq'  : _next_seq(),
                        'op_id': str(uuid.uuid4()),
                        'type' : ACTION_CREATE_ROOM,
                        'room' : room,
                        'rows' : 10,
                        'cols' : 10,
                        'mines': 10,
                        'seed' : seed,
                    }
                    if _replicate(cmd):
                        state_machine.apply_command(cmd)
                    else:
                        print(f'[!] Could not replicate create_room for {room}')

                # Register socket and user in the room manager
                room_manager.add_client(room, client_socket)
                users = room_manager.add_user(room, client_username)

                # Propagate user-list update to follower (fire-and-forget, not via PREPARE/COMMIT)
                users_msg = {'type': UPDATE_USERS, 'room': room, 'users': users}
                if follower_socket:
                    try:
                        send_message(follower_socket, users_msg)
                    except Exception:
                        pass
                room_manager.broadcast_to_room(room, users_msg)

                # Send current board to the joining client
                send_message(client_socket, {
                    'type' : UPDATE_ROOM,
                    'room' : room,
                    'state': state_machine.get_state(room),
                })
                continue

            # ----------------------------------------------------------------
            # GAME ACTIONS
            # ----------------------------------------------------------------
            r = msg.get('r', 0)
            c = msg.get('c', 0)

            if action in (ACTION_REVEAL, ACTION_FLAG):
                cmd = {
                    'seq'  : _next_seq(),
                    'op_id': str(uuid.uuid4()),
                    'type' : action,
                    'room' : room,
                    'row'  : r,
                    'col'  : c,
                }
                if not _replicate(cmd):
                    send_message(client_socket, {
                        'type'  : 'error',
                        'reason': 'replication_failed',
                        'op_id' : cmd['op_id'],
                    })
                    continue
                new_state = state_machine.apply_command(cmd)
                room_manager.broadcast_to_room(room, {
                    'type' : UPDATE_ROOM,
                    'room' : room,
                    'state': new_state,
                })

            elif action == ACTION_RESTART:
                seed = random.randint(0, 2**32)
                cmd  = {
                    'seq'  : _next_seq(),
                    'op_id': str(uuid.uuid4()),
                    'type' : ACTION_RESTART,
                    'room' : room,
                    'seed' : seed,
                }
                if not _replicate(cmd):
                    send_message(client_socket, {
                        'type'  : 'error',
                        'reason': 'replication_failed',
                        'op_id' : cmd['op_id'],
                    })
                    continue
                new_state = state_machine.apply_command(cmd)
                room_manager.broadcast_to_room(room, {
                    'type' : UPDATE_ROOM,
                    'room' : room,
                    'state': new_state,
                })

    except Exception as e:
        print(f'[client error] {e}')
    finally:
        client_socket.close()
        if client_username and client_room:
            users = room_manager.remove_user(client_room, client_username)
            room_manager.remove_client(client_socket)
            room_manager.broadcast_to_room(client_room, {
                'type' : UPDATE_USERS,
                'room' : client_room,
                'users': users,
            })
        else:
            room_manager.remove_client(client_socket)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _admin_server(host: str, port: int) -> None:
    """
    Lightweight introspection endpoint used by integration tests.
    Listens on ADMIN_PORT and responds to GET_STATE queries.
    Runs as a daemon thread alongside the main server.
    """
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
    global follower_socket

    HOST        = os.environ.get('HOST', '0.0.0.0')
    PORT        = int(os.environ.get('PORT', 5000))
    SLAVE_HOST  = os.environ.get('SLAVE_HOST', 'localhost')
    SLAVE_PORT  = int(os.environ.get('SLAVE_PORT', 6000))
    ADMIN_PORT  = int(os.environ.get('ADMIN_PORT', PORT + 100))

    # Connect to follower-1
    follower_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    while True:
        try:
            follower_socket.connect((SLAVE_HOST, SLAVE_PORT))
            print(f'[+] Connected to follower-1 at {SLAVE_HOST}:{SLAVE_PORT}')
            break
        except socket.error:
            print('[*] Retrying connection to follower-1...')
            time.sleep(2)

    # Start ACK listener thread
    threading.Thread(target=_listen_for_acks, daemon=True).start()

    # Start admin / introspection server
    threading.Thread(target=_admin_server, args=(HOST, ADMIN_PORT), daemon=True).start()
    print(f'[+] Admin introspection on {HOST}:{ADMIN_PORT}')

    # Accept clients
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
