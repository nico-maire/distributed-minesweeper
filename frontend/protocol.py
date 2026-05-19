import json
import struct
import socket

def send_message(sock, message_dict):
    """
    Converts a dictionary to JSON, encodes it to UTF-8 and sends it over the socket
    packing a 4-byte prefix indicating the message length.
    """
    try:
        # Convert to JSON and encode
        data = json.dumps(message_dict).encode('utf-8')
        
        # Pack the length as a 4-byte unsigned integer in 'network byte order' (big-endian)
        length_prefix = struct.pack('!I', len(data))
        
        # Send everything
        sock.sendall(length_prefix + data)
        return True
    except (socket.error, Exception) as e:
        print(f"Error sending message: {e}")
        return False

def receive_message(sock):
    """
    Reads a 4-byte prefix to know the length, then reads the rest of the message,
    decodes it from UTF-8 and parses the JSON to the original dictionary.
    """
    try:
        # Read the 4 header bytes
        raw_msglen = _recvall(sock, 4)
        if not raw_msglen:
            return None
        
        # Unpack the length
        msglen = struct.unpack('!I', raw_msglen)[0]
        
        # Read the expected length of JSON data
        msg_data = _recvall(sock, msglen)
        if not msg_data:
            return None
        
        # Decode JSON and reconstruct the dictionary
        return json.loads(msg_data.decode('utf-8'))
    except (socket.error, struct.error, json.JSONDecodeError, Exception) as e:
        print(f"Error receiving message: {e}")
        return None

def _recvall(sock, n):
    """
    Helper function to read exactly 'n' bytes from the socket.
    Essential for TCP because recv() does not guarantee reading the required amount at once.
    """
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            # Connection closed from the other side
            return None
        data.extend(packet)
    return data
