import sys
import os
import socket
import threading
from model import Minesweeper
from protocol import send_message, receive_message

HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', 5000))
SLAVE_HOST = os.environ.get('SLAVE_HOST', 'localhost')
SLAVE_PORT = int(os.environ.get('SLAVE_PORT', 6000))

clients = []
slave_socket = None

def broadcast(state_dict):
    """Envía el nuevo estado del juego a todos los clientes conectados."""
    disconnected = []
    for client_socket in clients:
        try:
            if not send_message(client_socket, state_dict):
                disconnected.append(client_socket)
        except Exception:
            disconnected.append(client_socket)
            
    # Limpiar clientes desconectados
    for c in disconnected:
        if c in clients:
            clients.remove(c)

def handle_client(client_socket, address, game, game_lock):
    print(f"[*] Client connected from {address}")
    clients.append(client_socket)
    
    # Enviar estado inicial seguro
    with game_lock:
        initial_state = game.to_dict()
    send_message(client_socket, initial_state)
    
    try:
        while True:
            msg = receive_message(client_socket)
            if not msg:
                print(f"[*] Client {address} disconnected")
                break
            
            action = msg.get('action')
            r = msg.get('r', 0)
            c = msg.get('c', 0)
            
            needs_broadcast = False
            
            with game_lock:
                if action == 'reveal':
                    game.reveal(r, c)
                    needs_broadcast = True
                elif action == 'flag':
                    game.toggle_flag(r, c)
                    needs_broadcast = True
                elif action == 'restart':
                    # Reiniciamos reinvocando __init__ para mantener la misma referencia en la memoria (thread sharing)
                    game.__init__(10, 10, 10)
                    needs_broadcast = True
                    
                if needs_broadcast:
                    current_state = game.to_dict()
                    # Replicación Síncrona: Asegura Consistencia Fuerte enviando primero al esclavo
                    if not send_message(slave_socket, current_state):
                        print("[!] Error replicating state to slave.")
            
            if needs_broadcast:
                broadcast(current_state)
                
    except Exception as e:
        print(f"[*] Client {address} error: {e}")
    finally:
        if client_socket in clients:
            clients.remove(client_socket)
        client_socket.close()

def start_server(host=HOST, port=PORT):
    global slave_socket
    # Conexión bloqueante al esclavo (Strong Consistency requirement)
    try:
        slave_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        slave_socket.connect((SLAVE_HOST, SLAVE_PORT))
        print(f"[*] Successfully connected to passive replica at {SLAVE_HOST}:{SLAVE_PORT}")
    except socket.error:
        print("ERROR: Could not connect to replica")
        sys.exit(1)

    game = Minesweeper(10, 10, 10)
    game_lock = threading.Lock()
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    
    print(f"[*] Server listening on {host}:{port} with multi-threading...")
    
    try:
        while True:
            client_socket, address = server_socket.accept()
            client_thread = threading.Thread(
                target=handle_client, 
                args=(client_socket, address, game, game_lock)
            )
            client_thread.daemon = True
            client_thread.start()
    except KeyboardInterrupt:
        print("\n[*] Server stopping...")
    finally:
        server_socket.close()

if __name__ == '__main__':
    start_server()