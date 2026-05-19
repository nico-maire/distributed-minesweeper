from protocol import send_message

# Translates user interactions into game commands and sends them to the active server.
class MinesweeperController:
    def __init__(self, conn_state):
        self.conn_state = conn_state
        self.room_name = "default"
        self.username = "Anonymous"
        self.view = None
        self.start_network_cb = None

    def set_view(self, view):
        self.view = view
        
    def join_game(self, username, room_name):
        self.username = username
        self.room_name = room_name
        if self.start_network_cb:
            self.start_network_cb()
        self._send_to_server({'action': 'join', 'username': self.username})

    def reveal_cell(self, r, c):
        if self.view and self.view.status != "playing":
            return
        if self.view and not self.view.started:
            self.view.started = True
            self.view.start_timer()
        self._send_to_server({'action': 'reveal', 'r': r, 'c': c})

    def flag_cell(self, r, c):
        if self.view and self.view.status != "playing":
            return
        self._send_to_server({'action': 'flag', 'r': r, 'c': c})

    def restart_game(self):
        self._send_to_server({'action': 'restart'})
        if self.view:
            self.view.reset_timer()

    def _send_to_server(self, message):
        message['room'] = self.room_name
        with self.conn_state.lock:
            sock = self.conn_state.sock
        if sock:
            send_message(sock, message)
