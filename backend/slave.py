import os
import socket
import threading
import time
from model import Minesweeper
from protocol import send_message, receive_message

HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', 6000))

clients = []
games = {}
games_lock = threading.Lock()
room_users = {}
users_lock = threading.Lock()

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

def handle_client(client_socket, address, next_replica_socket=None):
    clients.append(client_socket)
    
    with games_lock:
        initial_state = {room: game.to_dict() for room, game in games.items()}
    send_message(client_socket, {'type': 'init_rooms', 'rooms': initial_state})
    
    client_username = None
    client_room = None
    
    try:
        while True:
            msg = receive_message(client_socket)
            if not msg:
                break
            
            action = msg.get('action')
            room = msg.get('room', 'default')
            
            if action == 'join':
                client_username = msg.get('username', 'Anonymous')
                client_room = room
                with users_lock:
                    if room not in room_users:
                        room_users[room] = []
                    if client_username not in room_users[room]:
                        room_users[room].append(client_username)
                    users_list = list(room_users[room])
                update_msg = {'type': 'update_users', 'room': room, 'users': users_list}
                if next_replica_socket:
                    try:
                        send_message(next_replica_socket, update_msg)
                    except Exception:
                        pass
                broadcast(update_msg)
                
                with games_lock:
                    if room not in games:
                        games[room] = Minesweeper(10, 10, 10)
                    game = games[room]
                    current_state = game.to_dict()
                send_message(client_socket, {'type': 'update_room', 'room': room, 'state': current_state})
                
                continue
                
            r = msg.get('r', 0)
            c = msg.get('c', 0)
            
            with games_lock:
                if room not in games:
                    games[room] = Minesweeper(10, 10, 10)
                game = games[room]
                
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
            
            if needs_broadcast:
                broadcast(update_message)
                if next_replica_socket:
                    try:
                        send_message(next_replica_socket, update_message)
                    except Exception:
                        pass
                
    except Exception as e:
        print(e)
    finally:
        if client_socket in clients:
            clients.remove(client_socket)
        client_socket.close()
        
        if client_username and client_room:
            with users_lock:
                if client_room in room_users and client_username in room_users[client_room]:
                    room_users[client_room].remove(client_username)
                users_list = list(room_users.get(client_room, []))
            update_msg = {'type': 'update_users', 'room': client_room, 'users': users_list}
            if next_replica_socket:
                try:
                    send_message(next_replica_socket, update_msg)
                except Exception:
                    pass
            broadcast(update_msg)

def start_slave(host=HOST, port=PORT):
    NEXT_REPLICA_HOST = os.environ.get('NEXT_REPLICA_HOST')
    NEXT_REPLICA_PORT = os.environ.get('NEXT_REPLICA_PORT')
    
    next_replica_socket = None
    if NEXT_REPLICA_HOST and NEXT_REPLICA_PORT:
        NEXT_REPLICA_PORT = int(NEXT_REPLICA_PORT)
        while True:
            try:
                next_replica_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                next_replica_socket.connect((NEXT_REPLICA_HOST, NEXT_REPLICA_PORT))
                break
            except socket.error:
                time.sleep(2)

    slave_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    slave_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    slave_socket.bind((host, port))
    slave_socket.listen(1)
    
    leader_socket, address = slave_socket.accept()
    
    try:
        while True:
            data = receive_message(leader_socket)
            if not data:
                break
            
            # Format Data -> {'type': 'update_room', 'type': 'init_rooms', 'type': 'update_users'}
            msg_type = data.get('type')
            
            with games_lock:
                if msg_type == 'update_room':
                    room = data['room']
                    state = data['state']
                    games[room] = Minesweeper.from_dict(state)
                elif msg_type == 'init_rooms':
                    for room, state in data['rooms'].items():
                        games[room] = Minesweeper.from_dict(state)
            
            if msg_type == 'update_users':
                with users_lock:
                    room = data['room']
                    room_users[room] = data['users']
            
            if next_replica_socket:
                try:
                    send_message(next_replica_socket, data)
                except Exception:
                    pass
                
    except Exception as e:
        print(e)
    finally:
        leader_socket.close()
        
    slave_socket.listen(5)
    
    try:
        while True:
            client_socket, address = slave_socket.accept()
            client_thread = threading.Thread(
                target=handle_client, 
                args=(client_socket, address, next_replica_socket)
            )
            client_thread.daemon = True
            client_thread.start()
    except KeyboardInterrupt:
        pass
    finally:
        slave_socket.close()

if __name__ == '__main__':
    start_slave()
