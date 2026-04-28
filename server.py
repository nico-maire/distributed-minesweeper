import socket
from model import Minesweeper
from protocol import send_message, receive_message

def start_server(host='localhost', port=5000):
    # Initialize a new game: 10x10 with 10 mines
    game = Minesweeper(10, 10, 10)
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(1)
    
    print(f"[*] Server listening on {host}:{port}...")
    
    while True:
        client_socket, address = server_socket.accept()
        print(f"[*] Client connected from {address}")
        
        # Send initial game state to the client
        send_message(client_socket, game.to_dict())
        
        while True:
            # Receive command from client
            msg = receive_message(client_socket)
            if not msg:
                print("[*] Client disconnected")
                break
            
            action = msg.get('action')
            r = msg.get('r', 0)
            c = msg.get('c', 0)
            
            if action == 'reveal':
                game.reveal(r, c)
            elif action == 'flag':
                game.toggle_flag(r, c)
            elif action == 'restart':
                game = Minesweeper(10, 10, 10)
                
            # Send updated state back
            if not send_message(client_socket, game.to_dict()):
                break
                
        client_socket.close()

if __name__ == '__main__':
    start_server()