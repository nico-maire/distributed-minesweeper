import socket
import threading
from protocol import send_message, receive_message

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

def receive_updates(sock):
    """
    Función que corre en un hilo separado para recibir el estado
    del juego asíncronamente y pintar el tablero si ocurren cambios.
    """
    while True:
        state = receive_message(sock)
        if not state:
            print("\n[!] Connection to server lost. Press Enter to exit.")
            break
            
        print_board(state)
        
        if state['state'] != 'playing':
            print(f"> Game Over! You {state['state']}.")
            print("> Enter 'restart' to play again or 'q' to quit.")

def start_client(host='localhost', port=5000):
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client_socket.connect((host, port))
        print(f"[*] Connected to server at {host}:{port}")
        
        # Iniciar hilo de escucha en modo 'daemon' para que se cierre al terminar la app principal
        listener_thread = threading.Thread(target=receive_updates, args=(client_socket,))
        listener_thread.daemon = True
        listener_thread.start()
            
        while True:
            try:
                # El hilo de main queda única y exclusivamente a expensas del input del user.
                cmd_line = input()
            except (EOFError, KeyboardInterrupt):
                break
                
            cmd = cmd_line.strip().split()
            if not cmd:
                continue
                
            command_type = cmd[0].lower()
            
            if command_type == 'q':
                break
            elif command_type == 'restart':
                if not send_message(client_socket, {'action': 'restart'}):
                    break
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
            if not send_message(client_socket, msg):
                print("Failed to send message.")
                break
    
    except ConnectionRefusedError:
        print("[!] Could not connect to the server. Is it running?")
    finally:
        client_socket.close()

if __name__ == '__main__':
    start_client()