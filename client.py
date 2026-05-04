import os
import socket
import threading
import time
import sys
import tkinter as tk
from tkinter import messagebox
from protocol import send_message, receive_message

LEADER_HOST = os.environ.get('LEADER_HOST', 'localhost')
LEADER_PORT = int(os.environ.get('LEADER_PORT', 5000))
SLAVE_HOST = os.environ.get('SLAVE_HOST', 'localhost')
SLAVE_PORT = int(os.environ.get('SLAVE_PORT', 6000))

NODES = [(LEADER_HOST, LEADER_PORT), (SLAVE_HOST, SLAVE_PORT)]

class ConnectionState:
    def __init__(self):
        self.sock = None
        self.connected = False
        self.port_index = 0
        self.lock = threading.Lock()

conn_state = ConnectionState()

class MinesweeperGUI(tk.Tk):
    COUNT_COLORS = ["", "#00e5ff", "#69ff47", "#ff6b6b", "#ffe66d", "#ff9f43", "#fd79a8", "#a29bfe", "#dfe6e9"]
    
    def __init__(self):
        super().__init__()
        self.title("Distributed Minesweeper")
        self.config(bg="#0a0a0a")
        self.conn_state = conn_state
        self.rows = 0
        self.cols = 0
        self.mines = 0
        self.flags = 0
        self.time = 0
        self.status = "playing"
        self.started = False
        self.timer_id = None
        self.cells = []
        self.create_widgets()
        self.connect_and_start()

    def create_widgets(self):
        # Title
        self.title_label = tk.Label(self, text="◈ MINESWEEPER ◈", font=("Courier", 24, "bold"), fg="#00e5ff", bg="#0a0a0a")
        self.title_label.pack(pady=10)
        
        # Top panel
        self.panel = tk.Frame(self, bg="#111")
        self.panel.pack(pady=10)
        self.mine_label = tk.Label(self.panel, text="Mines: 0", font=("Courier", 16), fg="#ff6b6b", bg="#111")
        self.mine_label.pack(side=tk.LEFT, padx=20)
        self.face_button = tk.Button(self.panel, text="🤖", command=self.reset, font=("Courier", 20), bg="#1a1a1a", fg="white", relief="raised", bd=2)
        self.face_button.pack(side=tk.LEFT)
        self.time_label = tk.Label(self.panel, text="Time: 000", font=("Courier", 16), fg="#69ff47", bg="#111")
        self.time_label.pack(side=tk.LEFT, padx=20)
        
        # Grid frame
        self.grid_frame = tk.Frame(self, bg="#0a0a0a")
        self.grid_frame.pack()
        
        # Status label
        self.status_label = tk.Label(self, text="Click left to reveal, right to flag", font=("Courier", 10), fg="#00e5ff", bg="#0a0a0a")
        self.status_label.pack(pady=5)

    def create_grid(self, rows, cols):
        self.rows = rows
        self.cols = cols
        self.cells = [[None for _ in range(cols)] for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                btn = tk.Button(self.grid_frame, text="?", width=2, height=1, font=("Courier", 12), bg="#1a1a2e", fg="white",
                                relief="flat", bd=0, highlightthickness=0, highlightbackground="#1a1a2e", highlightcolor="#1a1a2e",
                                activebackground="#16213e", activeforeground="white",
                                command=lambda r=r, c=c: self.reveal(r, c))
                btn.bind("<Button-3>", lambda e, r=r, c=c: self.flag(r, c))
                btn.bind("<Enter>", lambda e: e.widget.config(bg="#16213e") if e.widget['text'] == '?' else None)
                btn.bind("<Leave>", lambda e: e.widget.config(bg="#1a1a2e") if e.widget['text'] == '?' else None)
                btn.grid(row=r, column=c, padx=0, pady=0)
                self.cells[r][c] = btn

    def update_board(self, state):
        self.rows = state['rows']
        self.cols = state['cols']
        revealed = state['revealed']
        flags = state['flags']
        mines = state['mines']
        adjacent_mines = state['adjacent_mines']
        self.status = state['state']
        self.mines = sum(sum(row) for row in mines)
        self.flags = sum(sum(row) for row in flags)
        if not self.cells:
            self.create_grid(self.rows, self.cols)
        for r in range(self.rows):
            for c in range(self.cols):
                cell = self.cells[r][c]
                if revealed[r][c]:
                    cell.config(relief="flat", bd=0, highlightthickness=0, highlightbackground=cell['bg'], highlightcolor=cell['bg'])
                    if mines[r][c]:
                        cell.config(text="💣", bg="#ff6b6b", fg="white")
                    else:
                        adj = adjacent_mines[r][c]
                        if adj > 0:
                            cell.config(text=str(adj), fg=self.COUNT_COLORS[adj], bg="#1b1b1b")
                        else:
                            # More visible gray shades for empty revealed cells
                            shade = "#232323" if (r + c) % 2 == 0 else "#181818"
                            cell.config(text="", bg=shade)
                    cell.unbind("<Enter>")
                    cell.unbind("<Leave>")
                elif flags[r][c]:
                    cell.config(text="🚩", bg="#ff9f43", fg="black")
                    cell.unbind("<Enter>")
                    cell.unbind("<Leave>")
                else:
                    cell.config(text="?", bg="#1a1a2e", fg="white")
        self.mine_label.config(text=f"Mines: {self.mines - self.flags}")
        if self.status == "won":
            self.face_button.config(text="😎", bg="#69ff47")
            self.status_label.config(text="CAMPO DESPEJADO — MISIÓN CUMPLIDA", fg="#69ff47")
        elif self.status == "lost":
            self.face_button.config(text="💀", bg="#ff6b6b")
            self.status_label.config(text="DETONACIÓN — GAME OVER", fg="#ff6b6b")
        else:
            self.face_button.config(text="🤖", bg="#1a1a1a")
            self.status_label.config(text="Click left to reveal, right to flag", fg="#00e5ff")
        if self.status != "playing" and self.timer_id:
            self.after_cancel(self.timer_id)
            self.timer_id = None

    def reveal(self, r, c):
        if self.status != "playing":
            return
        if not self.started:
            self.started = True
            self.start_timer()
        msg = {'action': 'reveal', 'r': r, 'c': c}
        with self.conn_state.lock:
            sock = self.conn_state.sock
        if sock:
            send_message(sock, msg)

    def flag(self, r, c):
        if self.status != "playing":
            return
        msg = {'action': 'flag', 'r': r, 'c': c}
        with self.conn_state.lock:
            sock = self.conn_state.sock
        if sock:
            send_message(sock, msg)

    def reset(self):
        msg = {'action': 'restart'}
        with self.conn_state.lock:
            sock = self.conn_state.sock
        if sock:
            send_message(sock, msg)
        self.time = 0
        self.started = False
        if self.timer_id:
            self.after_cancel(self.timer_id)
        self.timer_id = None
        self.time_label.config(text="Time: 000")

    def start_timer(self):
        self.update_timer()

    def update_timer(self):
        if self.status == "playing":
            self.time += 1
            self.time_label.config(text=f"Time: {self.time:03d}")
            self.timer_id = self.after(1000, self.update_timer)

    def connect_and_start(self):
        if not connect_to_server():
            messagebox.showerror("Error", "Could not connect to server")
            self.quit()
            return
        # Start listener thread
        listener_thread = threading.Thread(target=self.receive_updates)
        listener_thread.daemon = True
        listener_thread.start()

    def receive_updates(self):
        while True:
            with self.conn_state.lock:
                sock = self.conn_state.sock
            if not self.conn_state.connected or not sock:
                time.sleep(0.5)
                continue
            state = receive_message(sock)
            if not state:
                # Handle disconnection
                needs_reconnect = False
                exhausted = False
                with self.conn_state.lock:
                    if sock == self.conn_state.sock and self.conn_state.connected:
                        self.conn_state.connected = False
                        self.conn_state.port_index += 1
                        if self.conn_state.port_index < len(NODES):
                            needs_reconnect = True
                        else:
                            exhausted = True
                if exhausted:
                    self.after(0, lambda: messagebox.showerror("Error", "All servers are down"))
                    self.after(0, self.quit)
                    break
                if needs_reconnect:
                    time.sleep(1.5)
                    if connect_to_server():
                        continue
                    else:
                        self.after(0, lambda: messagebox.showerror("Error", "Exhausted all servers"))
                        self.after(0, self.quit)
                        break
                continue
            # Update GUI in main thread
            self.after(0, lambda: self.update_board(state))

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

def print_board(state):
    pass  # Removed for GUI

def receive_updates():
    """
    Función que corre en un hilo separado para recibir el estado
    del juego asíncronamente y pintar el tablero si ocurren cambios.
    """
    while True:
        with conn_state.lock:
            sock = conn_state.sock
        
        if not conn_state.connected or not sock:
            time.sleep(0.5)
            continue
            
        state = receive_message(sock)
        if not state:
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
                print("\n[!] Connection to server lost and no backups available. Press Enter to exit.")
                break
                
            if needs_reconnect:
                print("\n[!] Conexión perdida. Reconectando al servidor de respaldo...")
                print("[*] Esperando 1.5s para que el servidor de respaldo se estabilice...")
                time.sleep(1.5)
                if connect_to_server():
                    continue
                else:
                    print("\n[!] Exhausted all servers. Press Enter to exit.")
                    break
                    
            continue
            
        print_board(state)
        
        if state['state'] != 'playing':
            print(f"> Game Over! You {state['state']}.")
            print("> Enter 'restart' to play again or 'q' to quit.")

def start_client():
    if not connect_to_server():
        sys.exit()
    
    # Iniciar hilo de escucha en modo 'daemon' para que se cierre al terminar la app principal
    listener_thread = threading.Thread(target=receive_updates)
    listener_thread.daemon = True
    listener_thread.start()
        
    while True:
        try:
            # El hilo de main queda única y exclusivamente a expensas del input del user.
            cmd_line = input()
        except (EOFError, KeyboardInterrupt):
            break
            
        if not conn_state.connected:
            continue
            
        cmd = cmd_line.strip().split()
        if not cmd:
            continue
            
        command_type = cmd[0].lower()
        
        if command_type == 'q':
            break
        elif command_type == 'restart':
            with conn_state.lock:
                sock = conn_state.sock
            if not send_message(sock, {'action': 'restart'}):
                print("Failed to send message.")
            continue
            
        action = ''
        if command_type == 'r':
            action = 'reveal'
        elif command_type == 'f':
            action = 'flag'
        else:
            print("Unknown command. Use 'r row col' or 'f row col', 'restart' or 'q'.")
            continue
            
        if len(cmd) < 3:
            print("Please provide row and col coordinates (e.g. 'r 2 3')")
            continue
            
        try:
            r = int(cmd[1])
            c = int(cmd[2])
        except ValueError:
            print("Coordinates must be integers.")
            continue
            
        msg = {'action': action, 'r': r, 'c': c}
        
        with conn_state.lock:
            sock = conn_state.sock
            
        if not send_message(sock, msg):
            print("Failed to send message.")
            
    try:
        with conn_state.lock:
            if conn_state.sock:
                conn_state.sock.close()
    except Exception:
        pass

if __name__ == "__main__":
    app = MinesweeperGUI()
    app.mainloop()