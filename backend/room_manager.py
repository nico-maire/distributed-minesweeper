import threading
from protocol import send_message, UPDATE_ROOM, UPDATE_USERS


class RoomManager:
    """
    Manages the mapping between rooms, connected client sockets, and usernames.
    Thread-safe. Does NOT hold game state — that lives in GameStateMachine.
    """

    def __init__(self):
        self._clients = {}
        self._users   = {}
        self._lock    = threading.Lock()

    def add_client(self, room: str, sock) -> None:
        with self._lock:
            self._clients.setdefault(room, [])
            if sock not in self._clients[room]:
                self._clients[room].append(sock)

    def remove_client(self, sock) -> tuple:
        """
        Removes a socket from all rooms.
        Returns (room, username) of the client that was removed, or (None, None).
        """
        with self._lock:
            for room, socks in list(self._clients.items()):
                if sock in socks:
                    socks.remove(sock)
                    return room, None
        return None, None

    def broadcast_to_room(self, room: str, message: dict) -> None:
        with self._lock:
            sockets = list(self._clients.get(room, []))

        dead = []
        for sock in sockets:
            try:
                send_message(sock, message)
            except Exception:
                dead.append(sock)

        if dead:
            with self._lock:
                bucket = self._clients.get(room, [])
                for s in dead:
                    try:
                        bucket.remove(s)
                    except ValueError:
                        pass

    def broadcast_all(self, message: dict) -> None:
        with self._lock:
            rooms = list(self._clients.keys())
        for room in rooms:
            self.broadcast_to_room(room, message)

    def add_user(self, room: str, username: str) -> list:
        """Adds username to room and returns the updated list."""
        with self._lock:
            self._users.setdefault(room, [])
            if username not in self._users[room]:
                self._users[room].append(username)
            return list(self._users[room])

    def remove_user(self, room: str, username: str) -> list:
        """Removes username from room and returns the updated list."""
        with self._lock:
            if room in self._users and username in self._users[room]:
                self._users[room].remove(username)
            return list(self._users.get(room, []))

    def get_users(self, room: str) -> list:
        with self._lock:
            return list(self._users.get(room, []))

    def get_all_rooms(self) -> list:
        with self._lock:
            return list(self._clients.keys())
