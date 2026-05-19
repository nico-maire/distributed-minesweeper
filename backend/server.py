import sys
import os
import time
import socket
import threading
from model import Minesweeper
from protocol import send_message, receive_message

clients = []
slave_socket = None
games = {}  # Diccionario global de salas
games_lock = threading.Lock()

def get_or_create_game(room):
    with games_lock:
        if room not in games:
            # Crear nueva partida
            games[room] = Minesweeper(10, 10, 10)
        return games[room]

def broadcast(message):
    disconnected = []
    for client_socket in clients:
        try:
            if not send_message(client_socket, message):
                disconnected.append(client_socket)
        except Exception:
            disconnected.append(client_socket)
    for c in disconnected:
        if c in clients:
            clients.remove(c)

def handle_client(client_socket, address):
    print(f'[*] Client connected from {address}')
    clients.append(client_socket)
    
    with games_lock:
        initial_state = {room: game.to_dict() for room, game in games.items()}
    send_message(client_socket, {'type': 'init_rooms', 'rooms': initial_state})
    
    try:
        while True:
            msg = receive_message(client_socket)
            if not msg:
                break
            
            action = msg.get('action')
            room = msg.get('room', 'default')
            r = msg.get('r', 0)
            c = msg.get('c', 0)
            
            game = get_or_create_game(room)
            needs_broadcast = False
            
            with games_lock:
                if action == 'reveal':
                    game.reveal(r, c)
                    needs_broadcast = True
                elif action == 'flag':
                    game.toggle_flag(r, c)
                    needs_broadcast = True
                elif action == 'restart':
                    game.__init__(game.rows, game.cols, game.num_mines)
                    needs_broadcast = True
                    
                if needs_broadcast:
                    current_state = game.to_dict()
                    update_message = {'type': 'update_room', 'room': room, 'state': current_state}
                    if slave_socket:
                        try:
                            send_message(slave_socket, update_message)
                        except Exception:
                            pass
            
            if needs_broadcast:
                broadcast(update_message)
                
    except Exception as e:
        print(e)
    finally:
        if client_socket in clients:
            clients.remove(client_socket)
        client_socket.close()

def start_server():
    global slave_socket
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', 5000))
    SLAVE_HOST = os.environ.get('SLAVE_HOST', 'localhost')
    SLAVE_PORT = int(os.environ.get('SLAVE_PORT', 6000))
    
    slave_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    while True:
        try:
            slave_socket.connect((SLAVE_HOST, SLAVE_PORT))
            break
        except socket.error:
            time.sleep(2)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    
    try:
        while True:
            client_socket, address = server_socket.accept()
            client_thread = threading.Thread(target=handle_client, args=(client_socket, address))
            client_thread.daemon = True
            client_thread.start()
    except KeyboardInterrupt:
        pass
    finally:
        server_socket.close()

if __name__ == '__main__':
    start_server()
