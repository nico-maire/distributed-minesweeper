import os
import socket
import threading
import time

from protocol import send_message, receive_message, GET_STATE, STATE_REPLY
from follower_runtime import FollowerRuntime
from promoted_leader_runtime import PromotedLeaderRuntime
from replication import ChainReplicationManager
from room_manager import RoomManager
from state_machine import GameStateMachine

state_machine = GameStateMachine()
room_manager  = RoomManager()

def _admin_server(host: str, port: int) -> None:
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
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', 6000))

    ADMIN_PORT        = int(os.environ.get('ADMIN_PORT', PORT + 100))
    NEXT_REPLICA_HOST = os.environ.get('NEXT_REPLICA_HOST')
    NEXT_REPLICA_PORT = os.environ.get('NEXT_REPLICA_PORT')

    threading.Thread(
        target=_admin_server, args=(HOST, ADMIN_PORT), daemon=True,
    ).start()
    print(f'[+] Admin introspection on {HOST}:{ADMIN_PORT}')

    # Build the ChainReplicationManager once; shared by both phases so the
    # ACK listener and socket are not duplicated after promotion.
    replication = ChainReplicationManager()

    if NEXT_REPLICA_HOST and NEXT_REPLICA_PORT:
        NEXT_REPLICA_PORT = int(NEXT_REPLICA_PORT)
        while True:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((NEXT_REPLICA_HOST, NEXT_REPLICA_PORT))
                replication.set_follower(s)
                print(f'[+] Connected to next replica at {NEXT_REPLICA_HOST}:{NEXT_REPLICA_PORT}')
                break
            except socket.error:
                print('[*] Retrying connection to next replica...')
                time.sleep(2)

        # Start the ACK listener once; reused in promoted-leader phase.
        threading.Thread(
            target=replication.listen_for_acks, daemon=True,
        ).start()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    print(f'[+] Follower listening on {HOST}:{PORT}')

    leader_socket, leader_addr = server_socket.accept()
    print(f'[+] Upstream connected from {leader_addr}')

    follower = FollowerRuntime(state_machine, room_manager, replication)
    follower.run(leader_socket)

    print('[+] Promoted to leader — accepting client connections')
    replication.set_seq(state_machine.last_committed_seq)

    promoted = PromotedLeaderRuntime(state_machine, room_manager, replication)

    server_socket.listen(10)
    try:
        while True:
            client_sock, addr = server_socket.accept()
            threading.Thread(
                target=promoted.handle_client,
                args=(client_sock, addr),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        pass
    finally:
        server_socket.close()


if __name__ == '__main__':
    start_slave()
