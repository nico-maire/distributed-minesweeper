import threading
import time

from protocol import (
    send_message, receive_message,
    PREPARE_COMMAND, PREPARE_ACK,
    COMMIT_COMMAND, COMMIT_ACK,
)


class ChainReplicationManager:
    """
    Manages the PREPARE/COMMIT replication chain towards the next node.

    Used in two contexts:
      - By the leader to replicate to follower-1.
      - By a promoted follower to replicate to the next surviving replica.

    A single instance is created per node and shared across both the follower
    and promoted-leader phases so the ACK listener thread and the follower
    socket are reused without a race condition.
    """

    def __init__(self):
        self._follower    = None
        self._seq_counter = 0
        self._seq_lock    = threading.Lock()
        self._ack_received = {}
        self._ack_lock     = threading.Lock()
        self._repl_lock    = threading.Lock()

    def next_seq(self) -> int:
        with self._seq_lock:
            self._seq_counter += 1
            return self._seq_counter

    def set_seq(self, value: int) -> None:
        with self._seq_lock:
            self._seq_counter = value

    def set_follower(self, sock) -> None:
        self._follower = sock

    def has_follower(self) -> bool:
        return self._follower is not None

    def listen_for_acks(self) -> None:
        """Reads PREPARE_ACK / COMMIT_ACK from the next replica indefinitely."""
        while True:
            if not self._follower:
                time.sleep(0.5)
                continue
            try:
                msg = receive_message(self._follower)
                if not msg:
                    time.sleep(1)
                    continue
                msg_type = msg.get('type')
                op_id    = msg.get('op_id')
                if msg_type in (PREPARE_ACK, COMMIT_ACK) and op_id:
                    with self._ack_lock:
                        self._ack_received[(op_id, msg_type)] = True
            except Exception:
                time.sleep(1)

    def wait_ack(self, op_id: str, ack_type: str, timeout: float = 5.0) -> bool:
        key      = (op_id, ack_type)
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._ack_lock:
                if key in self._ack_received:
                    self._ack_received.pop(key)
                    return True
            time.sleep(0.01)
        with self._ack_lock:
            self._ack_received.pop(key, None)
        return False

    def send_to_follower(self, message: dict) -> bool:
        """Send a message directly to the next replica. Returns False on error."""
        if not self._follower:
            return False
        try:
            send_message(self._follower, message)
            return True
        except Exception as e:
            print(f'[!] send_to_follower failed: {e}')
            return False

    def send_direct(self, message: dict) -> None:
        """Fire-and-forget to the next replica (no ACK expected)."""
        if self._follower:
            try:
                send_message(self._follower, message)
            except Exception:
                pass

    def replicate(self, command: dict) -> bool:
        """
        Executes the two-phase PREPARE/COMMIT protocol with the next replica.
        Returns True only after the full chain has committed the operation.
        Returns True immediately if no next replica is configured (solo mode).
        """
        if not self._follower:
            return True

        with self._repl_lock:
            seq   = command['seq']
            op_id = command['op_id']

            try:
                send_message(self._follower, {
                    'type': PREPARE_COMMAND,
                    'seq': seq, 'op_id': op_id, 'command': command,
                })
            except Exception as e:
                print(f'[!] PREPARE send failed: {e}')
                return False

            if not self.wait_ack(op_id, PREPARE_ACK):
                print(f'[!] PREPARE_ACK timeout for op {op_id}')
                return False

            try:
                send_message(self._follower, {
                    'type': COMMIT_COMMAND,
                    'seq': seq, 'op_id': op_id,
                })
            except Exception as e:
                print(f'[!] COMMIT send failed: {e}')
                return False

            if not self.wait_ack(op_id, COMMIT_ACK):
                print(f'[!] COMMIT_ACK timeout for op {op_id}')
                return False

            return True
