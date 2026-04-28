import socket
from model import Minesweeper
from protocol import receive_message

def start_slave(host='localhost', port=6000):
    # Inicializar una instancia dummy de Minesweeper
    local_replica = Minesweeper(1, 1, 0)
    
    slave_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    slave_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    slave_socket.bind((host, port))
    slave_socket.listen(1)
    
    print(f"[*] Slave (Passive Replica) listening on {host}:{port}...")
    
    while True:
        leader_socket, address = slave_socket.accept()
        print(f"[*] Leader connected from {address}")
        
        try:
            while True:
                # Recibir estado del líder
                data = receive_message(leader_socket)
                if not data:
                    print("[*] Leader disconnected.")
                    break
                
                # Reconstruir la réplica local usando el método de clase
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

if __name__ == '__main__':
    start_slave()