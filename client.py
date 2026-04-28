import socket
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

def start_client(host='localhost', port=5000):
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client_socket.connect((host, port))
        print(f"[*] Connected to server at {host}:{port}")
        
        # Recibir estado inicial
        initial_state = receive_message(client_socket)
        if initial_state:
            print_board(initial_state)
            
        while True:
            cmd = input("Enter action (e.g., 'r 2 3' to reveal, 'f 2 3' to flag, 'q' to quit): ").strip().split()
            if not cmd:
                continue
                
            command_type = cmd[0].lower()
            
            if command_type == 'q':
                break
                
            action = ''
            if command_type == 'r':
                action = 'reveal'
            elif command_type == 'f':
                action = 'flag'
            else:
                print("Unknown command. Use 'r r c' or 'f r c' or 'q'.")
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
                
            state = receive_message(client_socket)
            if not state:
                print("Connection to server lost.")
                break
                
            print_board(state)
            
            if state['state'] != 'playing':
                print(f"Game over! You {state['state']}.")
                restart = input("Play again? (y/n): ")
                if restart.lower().startswith('y'):
                    send_message(client_socket, {'action': 'restart'})
                    state = receive_message(client_socket)
                    if not state: break
                    print_board(state)
                else:
                    break
    
    except ConnectionRefusedError:
        print("[!] Could not connect to the server. Is it running?")
    finally:
        client_socket.close()

if __name__ == '__main__':
    start_client()