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
# Module-level state
# ---------------------------------------------------------------------------

state_machine = GameStateMachine()
room_manager  = RoomManager()

# Sequence counter used only after promotion to leader
_seq_counter = 0
_seq_lock    = threading.Lock()

# ACK table for F2 (used while acting as follower-1)
_f2_ack_received = {}
_f2_ack_lock     = threading.Lock()

# ACK table for promoted-leader mode (used after promotion when there is a next replica)
_promoted_ack_received = {}
_promoted_ack_lock     = threading.Lock()


def _next_seq() -> int:
    global _seq_counter
    with _seq_lock:
        _seq_counter += 1
        return _seq_counter


# ---------------------------------------------------------------------------
# Follower helper: ACKs received from next replica (F2)
# ---------------------------------------------------------------------------

def _listen_f2_acks(f2_socket) -> None:
    """Daemon thread: reads PREPARE_ACK / COMMIT_ACK from the next replica."""
    while True:
        try:
            msg = receive_message(f2_socket)
            if not msg:
                break
            msg_type = msg.get('type')
            op_id    = msg.get('op_id')
            if msg_type in (PREPARE_ACK, COMMIT_ACK) and op_id:
                with _f2_ack_lock:
                    _f2_ack_received[(op_id, msg_type)] = True
        except Exception:
            break


def _wait_f2_ack(op_id: str, ack_type: str, timeout: float = 5.0) -> bool:
    key      = (op_id, ack_type)
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _f2_ack_lock:
            if key in _f2_ack_received:
                _f2_ack_received.pop(key)
                return True
        time.sleep(0.01)
    with _f2_ack_lock:
        _f2_ack_received.pop(key, None)
    return False


# ---------------------------------------------------------------------------
# Promoted-leader helper: ACKs received from next replica after promotion
# ---------------------------------------------------------------------------

def _listen_promoted_acks(next_replica_socket) -> None:
    """Daemon thread: reads PREPARE_ACK / COMMIT_ACK from next replica after promotion."""
    while True:
        try:
            msg = receive_message(next_replica_socket)
            if not msg:
                break
            msg_type = msg.get('type')
            op_id    = msg.get('op_id')
            if msg_type in (PREPARE_ACK, COMMIT_ACK) and op_id:
                with _promoted_ack_lock:
                    _promoted_ack_received[(op_id, msg_type)] = True
        except Exception:
            break


def _wait_promoted_ack(op_id: str, ack_type: str, timeout: float = 5.0) -> bool:
    if not _promoted_next_replica:
        return True
    key      = (op_id, ack_type)
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _promoted_ack_lock:
            if key in _promoted_ack_received:
                _promoted_ack_received.pop(key)
                return True
        time.sleep(0.01)
    with _promoted_ack_lock:
        _promoted_ack_received.pop(key, None)
    return False


# Socket to the next replica (set once, used by promoted-leader handlers)
_promoted_next_replica = None


def _replicate_promoted(command: dict) -> bool:
    """2-phase PREPARE/COMMIT towards next replica, used after promotion."""
    if not _promoted_next_replica:
        return True
    seq   = command['seq']
    op_id = command['op_id']
    try:
        send_message(_promoted_next_replica, {
            'type': PREPARE_COMMAND, 'seq': seq,
            'op_id': op_id, 'command': command,
        })
    except Exception as e:
        print(f'[!] Failed to send PREPARE to next replica: {e}')
        return False
    if not _wait_promoted_ack(op_id, PREPARE_ACK):
        print(f'[!] PREPARE_ACK timeout for op {op_id}')
        return False
    try:
        send_message(_promoted_next_replica, {
            'type': COMMIT_COMMAND, 'seq': seq, 'op_id': op_id,
        })
    except Exception as e:
        print(f'[!] Failed to send COMMIT to next replica: {e}')
        return False
    if not _wait_promoted_ack(op_id, COMMIT_ACK):
        print(f'[!] COMMIT_ACK timeout for op {op_id}')
        return False
    return True


# ---------------------------------------------------------------------------
# Replica mode: handle replication protocol from leader
# ---------------------------------------------------------------------------

def _replica_loop(leader_socket, next_replica_socket) -> None:
    """
    Processes PREPARE_COMMAND / COMMIT_COMMAND messages from the leader.
    Forwards them through the chain if there is a next replica and ACKs back.
    Returns when the leader connection closes (triggering promotion).
    Uncommitted pending_ops are discarded on exit.
    """
    pending_ops = {}   # seq -> {'op_id': str, 'command': dict}

    try:
        while True:
            data = receive_message(leader_socket)
            if not data:
                print('[!] Leader disconnected — preparing for promotion')
                break

            msg_type = data.get('type')
            op_id    = data.get('op_id')
            seq      = data.get('seq')

            # ---- PREPARE_COMMAND ------------------------------------------
            if msg_type == PREPARE_COMMAND:
                command = data.get('command', {})
                pending_ops[seq] = {'op_id': op_id, 'command': command}

                if next_replica_socket:
                    try:
                        send_message(next_replica_socket, data)
                    except Exception as e:
                        print(f'[!] Failed to forward PREPARE to next replica: {e}')
                        continue  # Don't ACK leader → operation aborted

                    if _wait_f2_ack(op_id, PREPARE_ACK):
                        try:
                            send_message(leader_socket, {
                                'type': PREPARE_ACK, 'op_id': op_id, 'seq': seq,
                            })
                        except Exception:
                            pass
                    # else: next replica timed out — do not ACK leader
                else:
                    try:
                        send_message(leader_socket, {
                            'type': PREPARE_ACK, 'op_id': op_id, 'seq': seq,
                        })
                    except Exception:
                        pass

            # ---- COMMIT_COMMAND -------------------------------------------
            elif msg_type == COMMIT_COMMAND:
                if next_replica_socket:
                    try:
                        send_message(next_replica_socket, data)
                    except Exception as e:
                        print(f'[!] Failed to forward COMMIT to next replica: {e}')
                        continue

                    if _wait_f2_ack(op_id, COMMIT_ACK):
                        entry = pending_ops.pop(seq, None)
                        if entry:
                            state_machine.apply_command(entry['command'])
                        try:
                            send_message(leader_socket, {
                                'type': COMMIT_ACK, 'op_id': op_id, 'seq': seq,
                            })
                        except Exception:
                            pass
                    # else: next replica timed out — do not ACK leader
                else:
                    entry = pending_ops.pop(seq, None)
                    if entry:
                        state_machine.apply_command(entry['command'])
                    try:
                        send_message(leader_socket, {
                            'type': COMMIT_ACK, 'op_id': op_id, 'seq': seq,
                        })
                    except Exception:
                        pass

            # ---- INIT_ROOMS (initial state sync on first connect) ----------
            elif msg_type == INIT_ROOMS:
                from model import Minesweeper
                with state_machine._lock:
                    for room, st in data.get('rooms', {}).items():
                        state_machine._games[room] = Minesweeper.from_dict(st)

            # ---- UPDATE_USERS (replicated user-list changes) ---------------
            elif msg_type == UPDATE_USERS:
                room  = data.get('room')
                users = data.get('users', [])
                if room:
                    with room_manager._lock:
                        room_manager._users[room] = list(users)

    except Exception as e:
        print(f'[replica loop error] {e}')
    finally:
        # Discard all uncommitted operations — they were never confirmed to clients
        pending_ops.clear()
        leader_socket.close()


# ---------------------------------------------------------------------------
# Promoted-leader mode: serve clients directly
# ---------------------------------------------------------------------------

def _handle_client(client_socket, address) -> None:
    """Handles a direct client after promotion."""
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

            # Introspection (used by integration tests)
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
                        'seq'  : _next_seq(),
                        'op_id': str(uuid.uuid4()),
                        'type' : ACTION_CREATE_ROOM,
                        'room' : room,
                        'rows' : 10, 'cols': 10, 'mines': 10,
                        'seed' : seed,
                    }
                    if _replicate_promoted(cmd):
                        state_machine.apply_command(cmd)

                room_manager.add_client(room, client_socket)
                users = room_manager.add_user(room, client_username)
                room_manager.broadcast_to_room(room, {
                    'type': UPDATE_USERS, 'room': room, 'users': users,
                })
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
                    'seq'  : _next_seq(),
                    'op_id': str(uuid.uuid4()),
                    'type' : action,
                    'room' : room,
                    'row'  : r,
                    'col'  : c,
                }
                if not _replicate_promoted(cmd):
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
                    'seq'  : _next_seq(),
                    'op_id': str(uuid.uuid4()),
                    'type' : ACTION_RESTART,
                    'room' : room, 'seed': seed,
                }
                if not _replicate_promoted(cmd):
                    send_message(client_socket, {
                        'type': 'error', 'reason': 'replication_failed',
                    })
                    continue
                new_state = state_machine.apply_command(cmd)
                room_manager.broadcast_to_room(room, {
                    'type': UPDATE_ROOM, 'room': room, 'state': new_state,
                })

    except Exception as e:
        print(f'[promoted client error] {e}')
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
    """Introspection endpoint (same as server.py version)."""
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


def start_slave() -> None:
    global _seq_counter, _promoted_next_replica

    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', 6000))

    ADMIN_PORT        = int(os.environ.get('ADMIN_PORT', PORT + 100))
    NEXT_REPLICA_HOST = os.environ.get('NEXT_REPLICA_HOST')
    NEXT_REPLICA_PORT = os.environ.get('NEXT_REPLICA_PORT')

    # Start admin / introspection server (works in both follower and promoted-leader mode)
    threading.Thread(target=_admin_server, args=(HOST, ADMIN_PORT), daemon=True).start()
    print(f'[+] Admin introspection on {HOST}:{ADMIN_PORT}')

    # Connect to the next replica in the chain (if configured)
    next_replica_socket = None
    if NEXT_REPLICA_HOST and NEXT_REPLICA_PORT:
        NEXT_REPLICA_PORT = int(NEXT_REPLICA_PORT)
        while True:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((NEXT_REPLICA_HOST, NEXT_REPLICA_PORT))
                next_replica_socket = s
                print(f'[+] Connected to next replica at {NEXT_REPLICA_HOST}:{NEXT_REPLICA_PORT}')
                break
            except socket.error:
                print('[*] Retrying connection to next replica...')
                time.sleep(2)

        # Start F2-ACK listener thread (used while in follower mode)
        threading.Thread(
            target=_listen_f2_acks,
            args=(next_replica_socket,),
            daemon=True,
        ).start()

    # Listen for the leader to connect
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    print(f'[+] Follower listening on {HOST}:{PORT}')

    leader_socket, leader_addr = server_socket.accept()
    print(f'[+] Leader connected from {leader_addr}')

    # Run replica loop (blocks until leader drops)
    _replica_loop(leader_socket, next_replica_socket)

    # ---- PROMOTION ----
    print('[+] Promoted to leader — accepting client connections')

    # Align seq counter with last committed operation
    with _seq_lock:
        _seq_counter = state_machine.last_committed_seq

    # Share the next-replica socket with promoted client handlers (module-level)
    _promoted_next_replica = next_replica_socket

    # If there is a next replica, start the promoted-ACK listener thread
    if _promoted_next_replica:
        threading.Thread(
            target=_listen_promoted_acks,
            args=(_promoted_next_replica,),
            daemon=True,
        ).start()

    server_socket.listen(10)
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
    start_slave()
