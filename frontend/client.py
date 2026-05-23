import os
import socket
import threading
import time
from protocol import receive_message
from gui import MinesweeperGUI
from controller import MinesweeperController

LEADER_HOST = os.environ.get('LEADER_HOST', 'localhost')
LEADER_PORT = int(os.environ.get('LEADER_PORT', 5000))
SLAVE_1_HOST = os.environ.get('SLAVE_1_HOST', 'localhost')
SLAVE_1_PORT = int(os.environ.get('SLAVE_1_PORT', 6000))
SLAVE_2_HOST = os.environ.get('SLAVE_2_HOST', 'localhost')
SLAVE_2_PORT = int(os.environ.get('SLAVE_2_PORT', 7000))

NODES = [
    (LEADER_HOST, LEADER_PORT),
    (SLAVE_1_HOST, SLAVE_1_PORT),
    (SLAVE_2_HOST, SLAVE_2_PORT)
]


class ConnectionState:
    def __init__(self):
        self.sock = None
        self.connected = False
        self.port_index = 0
        self.lock = threading.Lock()


conn_state = ConnectionState()


def connect_to_server():
    with conn_state.lock:
        if conn_state.sock:
            try:
                conn_state.sock.close()
            except:
                pass

        while conn_state.port_index < len(NODES):
            host, port = NODES[conn_state.port_index]
            try:
                if conn_state.port_index > 0:
                    print(f"\n[!] Connection lost. Attempting to reconnect to backup server at {host}:{port}...")
                else:
                    print(f"[*] Attempting to connect to server at {host}:{port}...")

                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((host, port))
                conn_state.sock = sock
                conn_state.connected = True
                print(f"[*] Successfully connected to {host}:{port}")
                return True
            except socket.error:
                print(f"[!] Could not connect to {host}:{port}")
                conn_state.port_index += 1
                time.sleep(1)

        conn_state.connected = False
        print("\n[!] All servers are down. Exiting.")
        return False


def receive_updates(gui):
    while True:
        with conn_state.lock:
            sock = conn_state.sock
        if not conn_state.connected or not sock:
            time.sleep(0.5)
            continue
        msg = receive_message(sock)
        if not msg:
            needs_reconnect = False
            exhausted = False
            with conn_state.lock:
                if sock == conn_state.sock and conn_state.connected:
                    conn_state.connected = False
                    conn_state.port_index += 1
                    if conn_state.port_index < len(NODES):
                        needs_reconnect = True
                    else:
                        exhausted = True
            if exhausted:
                gui.after(0, lambda: gui.show_error("All servers are down"))
                gui.after(0, gui.quit)
                break
            if needs_reconnect:
                time.sleep(1.5)
                if connect_to_server():
                    gui.controller.rejoin()
                    continue
                else:
                    gui.after(0, lambda: gui.show_error("Exhausted all servers"))
                    gui.after(0, gui.quit)
                    break
            continue

        msg_type = msg.get('type')
        room_name = gui.controller.room_name
        if msg_type == 'init_rooms':
            rooms = msg.get('rooms', {})
            room_names = list(rooms.keys())
            gui.after(0, lambda r=room_names: gui.update_room_list(r))

            state = rooms.get(room_name)
            if state:
                gui.after(0, lambda s=state: gui.update_board(s))
        elif msg_type == 'update_room':
            if msg.get('room') == room_name:
                state = msg.get('state')
                gui.after(0, lambda s=state: gui.update_board(s))
        elif msg_type == 'update_users':
            if msg.get('room') == room_name:
                users = msg.get('users', [])
                gui.after(0, lambda u=users: gui.update_user_list(u))


def main():
    controller = MinesweeperController(conn_state)
    
    if not connect_to_server():
        print("[!] No servers available")
        return

    app = MinesweeperGUI(controller)
    controller.set_view(app)

    listener_thread = threading.Thread(target=receive_updates, args=(app,))
    listener_thread.daemon = True
    listener_thread.start()

    app.mainloop()


if __name__ == "__main__":
    main()
