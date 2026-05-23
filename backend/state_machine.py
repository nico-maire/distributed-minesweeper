import threading
from model import Minesweeper
from protocol import (
    ACTION_REVEAL, ACTION_FLAG, ACTION_RESTART, ACTION_CREATE_ROOM
)


class GameStateMachine:
    """
    Deterministic replicated state machine for the minesweeper game.

    Each room's board evolves strictly through apply_command(), which takes
    an ordered command dict with a monotonically increasing 'seq' number.
    All replicas that start from the same initial state and apply the same
    sequence of commands in the same order will converge to identical state.
    """

    def __init__(self):
        self._lock             = threading.Lock()
        self._games            = {}
        self.last_committed_seq = 0
        self.committed_log     = []

    def apply_command(self, command: dict) -> dict:
        """
        Applies a single committed command to the state machine.
        Returns the resulting game state dict for the affected room,
        or {} if the room is not found after the command.
        Raises ValueError if the sequence number is out of order.
        """
        t    = command.get('type')
        room = command.get('room')
        seq  = command.get('seq', 0)

        with self._lock:
            if seq <= self.last_committed_seq:
                # Duplicate — idempotent: return current state unchanged
                return self._games[room].to_dict() if room in self._games else {}

            expected = self.last_committed_seq + 1
            if seq != expected:
                raise ValueError(
                    f'Sequence gap: expected {expected}, got {seq}'
                )

            if t == ACTION_CREATE_ROOM:
                self._games[room] = Minesweeper(
                    command['rows'], command['cols'],
                    command['mines'], seed=command.get('seed')
                )
            elif t == ACTION_REVEAL:
                game = self._games.get(room)
                if game:
                    game.reveal(command['row'], command['col'])
            elif t == ACTION_FLAG:
                game = self._games.get(room)
                if game:
                    game.toggle_flag(command['row'], command['col'])
            elif t == ACTION_RESTART:
                game = self._games.get(room)
                if game:
                    game.__init__(
                        game.rows, game.cols, game.num_mines,
                        seed=command.get('seed')
                    )

            self.last_committed_seq = command['seq']
            self.committed_log.append(command)

            return self._games[room].to_dict() if room in self._games else {}

    def get_state(self, room: str) -> dict:
        with self._lock:
            game = self._games.get(room)
            return game.to_dict() if game else {}

    def get_all_states(self) -> dict:
        with self._lock:
            return {room: game.to_dict() for room, game in self._games.items()}

    def has_room(self, room: str) -> bool:
        with self._lock:
            return room in self._games

    def get_committed_log_length(self) -> int:
        with self._lock:
            return len(self.committed_log)
