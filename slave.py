import socket
import threading
from model import Minesweeper
from protocol import send_message, receive_message

clients = []

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
    
    # Regla de oro 1 (Evitar Ceguera):
    # Enviar estado inicial seguro al cliente reconectado para repintar el tablero.
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
            
            # Regla de oro 2 (Último nodo vivo):
            # Solo actualizar estado local y enviar broadcast a clientes sin replicar a ningún lado.
            with game_lock:
                if action == 'reveal':
                    game.reveal(r, c)
                    needs_broadcast = True
                elif action == 'flag':
                    game.toggle_flag(r, c)
                    needs_broadcast = True
                elif action == 'restart':
                    # Reiniciamos guardando las dimensiones originales del juego transferido.
                    game.__init__(game.rows, game.cols, game.num_mines)
                    needs_broadcast = True
                    
                if needs_broadcast:
                    current_state = game.to_dict()
            
            if needs_broadcast:
                broadcast(current_state)
                
    except Exception as e:
        print(f"[*] Client {address} error: {e}")
    finally:
        if client_socket in clients:
            clients.remove(client_socket)
        client_socket.close()

def start_slave(host='localhost', port=6000):
    # Inicializar una instancia dummy de Minesweeper
    local_replica = Minesweeper(1, 1, 0)
    
    slave_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    slave_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    slave_socket.bind((host, port))
    slave_socket.listen(1)
    
    print(f"[*] Slave (Passive Replica) listening on {host}:{port}...")
    
    leader_socket, address = slave_socket.accept()
    print(f"[*] Leader connected from {address}")
    
    try:
        while True:
            # Recibir estado del líder
            data = receive_message(leader_socket)
            if not data:
                print("[*] Leader disconnected.")
                break
            
            # Reconstruir la réplica local usando el método de clase averiado
            try:
                local_replica = Minesweeper.from_dict(data)
                print("[*] Received replica state")
            except KeyError as e:
                print(f"[!] Invalid state format received, missing key: {e}")
            except Exception as e:
                print(f"[!] Error reconstructing state: {e}")
                
    except socket.error as e:
        print(f"[!] Connection error: {e}")
    finally:
        leader_socket.close()
        
    print("\n[!] Leader death detected. Promoting to Leader...")
    
    # Hemos salido del bucle (fallo detectado). El esclavo se auto-promociona a Líder.
    # El socket original `slave_socket` escuchaba para 1 conexion del líder,
    # podríamos cerrarlo y crear otro para clientes, pero como ya lo tenemos bindeado al 6000, 
    # basta con cambiarle el modo listen para múltiples conexiones.
    
    slave_socket.listen(5)
    game_lock = threading.Lock()
    
    print(f"[*] New Leader listening for clients on {host}:{port}...")
    
    try:
        while True:
            client_socket, address = slave_socket.accept()
            client_thread = threading.Thread(
                target=handle_client, 
                args=(client_socket, address, local_replica, game_lock)
            )
            client_thread.daemon = True
            client_thread.start()
    except KeyboardInterrupt:
        print("\n[*] Promoted Leader stopping...")
    finally:
        slave_socket.close()

if __name__ == '__main__':
    start_slave()