import json
import struct
import socket

PREPARE_COMMAND = 'prepare_command'
PREPARE_ACK     = 'prepare_ack'
COMMIT_COMMAND  = 'commit_command'
COMMIT_ACK      = 'commit_ack'

INIT_ROOMS   = 'init_rooms'
UPDATE_ROOM  = 'update_room'
UPDATE_USERS = 'update_users'

GET_STATE    = 'get_state'
STATE_REPLY  = 'state_reply'

ACTION_JOIN       = 'join'
ACTION_REVEAL     = 'reveal'
ACTION_FLAG       = 'flag'
ACTION_RESTART    = 'restart'
ACTION_CREATE_ROOM = 'create_room'

def send_message(sock, message_dict):
    """
    Converts a dictionary to JSON, encodes it to UTF-8 and sends it over the socket
    packing a 4-byte prefix indicating the message length.
    """
    try:
        data = json.dumps(message_dict).encode('utf-8')

        length_prefix = struct.pack('!I', len(data))

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
        raw_msglen = _recvall(sock, 4)
        if not raw_msglen:
            return None

        msglen = struct.unpack('!I', raw_msglen)[0]

        msg_data = _recvall(sock, msglen)
        if not msg_data:
            return None

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
            return None
        data.extend(packet)
    return data
