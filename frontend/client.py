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
        self.port_index = 0             # index of node trying to connect to
        self.lock = threading.Lock()    # mutex


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


def receive_updates(gui, room_name):
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
                    continue
                else:
                    gui.after(0, lambda: gui.show_error("Exhausted all servers"))
                    gui.after(0, gui.quit)
                    break
            continue
            
        msg_type = msg.get('type')
        if msg_type == 'init_rooms':
            rooms = msg.get('rooms', {})
            state = rooms.get(room_name)
            if state:
                gui.after(0, lambda s=state: gui.update_board(s))
        elif msg_type == 'update_room':
            if msg.get('room') == room_name:
                state = msg.get('state')
                gui.after(0, lambda s=state: gui.update_board(s))


import tkinter as tk
from tkinter import simpledialog

def main():
    root = tk.Tk()
    root.withdraw()
    room_name = simpledialog.askstring("Room Selection", "Enter the room name to join:")
    if not room_name:
        room_name = "default"
    root.destroy()
    
    controller = MinesweeperController(conn_state, room_name)
    app = MinesweeperGUI(controller)
    app.title(f"Distributed Minesweeper - Sala: {room_name}")
    controller.set_view(app)

    if not connect_to_server():
        app.show_error("Could not connect to server")
        app.quit()
        app.destroy()
        return

    listener_thread = threading.Thread(target=receive_updates, args=(app, room_name))
    listener_thread.daemon = True
    listener_thread.start()

    app.mainloop()


if __name__ == "__main__":
    main()
