import socket
import threading
import time
import sys
from protocol import send_message, receive_message

PORTS = [5000, 6000]
HOST = 'localhost'

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
        
        while conn_state.port_index < len(PORTS):
            port = PORTS[conn_state.port_index]
            try:
                if conn_state.port_index > 0:
                    print(f"\n[!] Connection lost. Attempting to reconnect to backup server on port {port}...")
                else:
                    print(f"[*] Attempting to connect to server at {HOST}:{port}...")
                    
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((HOST, port))
                conn_state.sock = sock
                conn_state.connected = True
                print(f"[*] Successfully connected to {HOST}:{port}")
                return True
            except socket.error:
                print(f"[!] Could not connect to {HOST}:{port}")
                conn_state.port_index += 1
                time.sleep(1)
                
        conn_state.connected = False
        print("\n[!] All servers are down. Exiting.")
        return False

def print_board(state):
    rows = state['rows']
    cols = state['cols']
    revealed = state['revealed']
    flags = state['flags']
    mines = state['mines']
    adjacent_mines = state['adjacent_mines']
    game_state = state['state']
    
    print(f"\n--- Game State: {game_state.upper()} ---")
    
    # Print column headers
    print("   " + " ".join([str(c) for c in range(cols)]))
    
    for r in range(rows):
        row_display = [f"{r:2} "]
        for c in range(cols):
            if revealed[r][c]:
                if mines[r][c]:
                    row_display.append('*') # Mine
                else:
                    adj = adjacent_mines[r][c]
                    row_display.append(str(adj) if adj > 0 else '.')
            elif flags[r][c]:
                row_display.append('F')
            else:
                row_display.append('?') # Hidden
        print(" ".join(row_display))
    print()

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
            with conn_state.lock:
                if sock == conn_state.sock and conn_state.connected:
                    conn_state.connected = False
                    conn_state.port_index += 1
                    
                    if conn_state.port_index < len(PORTS):
                        print("\n[!] Connection lost. Attempting to reconnect to backup server...")
                        # Intenta reconectar
                        if connect_to_server():
                            continue
                        else:
                            print("\n[!] Exhausted all servers. Press Enter to exit.")
                            break
                    else:
                        print("\n[!] Connection to server lost and no backups available. Press Enter to exit.")
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

if __name__ == '__main__':
    start_client()