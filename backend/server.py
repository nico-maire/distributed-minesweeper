import sys
import os
import time
import socket
import threading
import uuid
from model import Minesweeper
from protocol import send_message, receive_message

room_clients = {}  # Dict: room -> [socket1, socket2, ...]
room_clients_lock = threading.Lock()  # Lock for room_clients
slave_socket = None
replication_lock = threading.Lock()  # Lock for waiting on ACKs
ack_received = {}  # Dictionary to store ACK status: {op_id: True/False}
games = {}  # Global dictionary for rooms
games_lock = threading.Lock()
room_users = {}
users_lock = threading.Lock()

def get_or_create_game(room):
    with games_lock:
        if room not in games:
            # Create new game
            games[room] = Minesweeper(10, 10, 10)
        return games[room]

def wait_for_slave_ack(op_id, timeout=5):
    """
    Wait for slave to acknowledge an operation.
    Returns True if ACK received, False on timeout.
    """
    if not slave_socket:
        return True  # If no slave, proceed as if replicated
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        if op_id in ack_received:
            result = ack_received.pop(op_id)
            return result
        time.sleep(0.01)  # Small sleep to avoid busy-waiting
    
    # Timeout: remove pending op
    ack_received.pop(op_id, None)
    return False

def broadcast_to_room(room, message):
    """
    Broadcast a message only to clients in a specific room.
    Removes disconnected sockets from the room.
    """
    with room_clients_lock:
        if room not in room_clients:
            return
        
        disconnected = []
        for client_socket in room_clients[room]:
            try:
                if not send_message(client_socket, message):
                    disconnected.append(client_socket)
            except Exception:
                disconnected.append(client_socket)
        
        for c in disconnected:
            if c in room_clients[room]:
                room_clients[room].remove(c)

def handle_client(client_socket, address):
    print(f'[*] Client connected from {address}')
    
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
                
                # Add client to room
                with room_clients_lock:
                    if room not in room_clients:
                        room_clients[room] = []
                    if client_socket not in room_clients[room]:
                        room_clients[room].append(client_socket)
                
                with users_lock:
                    if room not in room_users:
                        room_users[room] = []
                    if client_username not in room_users[room]:
                        room_users[room].append(client_username)
                    users_list = list(room_users[room])
                    
                update_msg = {'type': 'update_users', 'room': room, 'users': users_list}
                
                # Send to slave and wait for ACK
                op_id = str(uuid.uuid4())
                update_msg['op_id'] = op_id
                if slave_socket:
                    try:
                        send_message(slave_socket, update_msg)
                        # Wait for ACK before broadcasting to clients
                        if not wait_for_slave_ack(op_id):
                            print(f'[!] Slave ACK timeout for operation {op_id}')
                    except Exception as e:
                        print(f'[!] Failed to send update to slave: {e}')
                
                broadcast_to_room(room, update_msg)
                
                game = get_or_create_game(room)
                with games_lock:
                    current_state = game.to_dict()
                send_message(client_socket, {'type': 'update_room', 'room': room, 'state': current_state})
                
                continue
            
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
                    
                    # Send to slave and wait for ACK
                    op_id = str(uuid.uuid4())
                    update_message['op_id'] = op_id
                    if slave_socket:
                        try:
                            send_message(slave_socket, update_message)
                            # Wait for ACK before broadcasting to clients
                            if not wait_for_slave_ack(op_id):
                                print(f'[!] Slave ACK timeout for operation {op_id}')
                        except Exception as e:
                            print(f'[!] Failed to send update to slave: {e}')
            
            if needs_broadcast:
                broadcast_to_room(room, update_message)
                
    except Exception as e:
        print(e)
    finally:
        # Remove client from room
        with room_clients_lock:
            for room_name in list(room_clients.keys()):
                if client_socket in room_clients[room_name]:
                    room_clients[room_name].remove(client_socket)
        
        client_socket.close()
        
        if client_username and client_room:
            with users_lock:
                if client_room in room_users and client_username in room_users[client_room]:
                    room_users[client_room].remove(client_username)
                users_list = list(room_users.get(client_room, []))
            update_msg = {'type': 'update_users', 'room': client_room, 'users': users_list}
            
            op_id = str(uuid.uuid4())
            update_msg['op_id'] = op_id
            if slave_socket:
                try:
                    send_message(slave_socket, update_msg)
                    wait_for_slave_ack(op_id)
                except Exception as e:
                    print(f'[!] Failed to send disconnect update to slave: {e}')
            broadcast_to_room(client_room, update_msg)

def listen_for_acks():
    """
    Separate thread that listens for ACK messages from the slave.
    """
    global slave_socket
    while True:
        if not slave_socket:
            time.sleep(0.5)
            continue
        try:
            ack_msg = receive_message(slave_socket)
            if ack_msg and ack_msg.get('type') == 'ack':
                op_id = ack_msg.get('op_id')
                if op_id:
                    ack_received[op_id] = True
        except Exception:
            # Connection lost, will try to reconnect in start_server
            time.sleep(1)

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
            print(f'[+] Connected to slave at {SLAVE_HOST}:{SLAVE_PORT}')
            break
        except socket.error:
            print(f'[*] Retrying connection to slave...')
            time.sleep(2)
    
    # Start ACK listener thread
    ack_thread = threading.Thread(target=listen_for_acks, daemon=True)
    ack_thread.start()

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
