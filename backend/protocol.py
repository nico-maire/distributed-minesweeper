import json
import struct
import socket

def send_message(sock, message_dict):
    """
    Convierte un diccionario a JSON, lo codifica en UTF-8 y lo envía a través del socket
    empaquetando un prefijo inicial de 4 bytes que indica la longitud del mensaje.
    """
    try:
        # Convertir a JSON y codificar
        data = json.dumps(message_dict).encode('utf-8')
        
        # Empaquetar la longitud como un entero sin signo de 4 bytes en formato 'network byte order' (big-endian)
        length_prefix = struct.pack('!I', len(data))
        
        # Enviar todo
        sock.sendall(length_prefix + data)
        return True
    except (socket.error, Exception) as e:
        print(f"Error al enviar mensaje: {e}")
        return False

def receive_message(sock):
    """
    Lee un prefijo de 4 bytes para saber la longitud, luego lee el resto del mensaje,
    lo decodifica de UTF-8 y parsea el JSON al diccionario original.
    """
    try:
        # Leer los 4 bytes de encabezado
        raw_msglen = _recvall(sock, 4)
        if not raw_msglen:
            return None
        
        # Desempaquetar la longitud
        msglen = struct.unpack('!I', raw_msglen)[0]
        
        # Leer la longitud esperada de los datos JSON
        msg_data = _recvall(sock, msglen)
        if not msg_data:
            return None
        
        # Decodificar el JSON y reconstruir el diccionario
        return json.loads(msg_data.decode('utf-8'))
    except (socket.error, struct.error, json.JSONDecodeError, Exception) as e:
        print(f"Error al recibir mensaje: {e}")
        return None

def _recvall(sock, n):
    """
    Función de ayuda para leer exactamente 'n' bytes desde el socket.
    Esencial para TCP porque recv() no garantiza leer la cantidad requerida de una vez.
    """
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            # Se ha cerrado la conexión desde el otro lado
            return None
        data.extend(packet)
    return data
