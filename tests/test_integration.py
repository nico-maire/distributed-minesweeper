import unittest
import subprocess
import time
import socket
import os
import sys

# Rutas absolutas a los archivos del backend
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
SERVER_PY = os.path.join(BASE_DIR, "backend", "server.py")
SLAVE_PY = os.path.join(BASE_DIR, "backend", "slave.py")

class TestLeaderElectionAndRecovery(unittest.TestCase):
    def setUp(self):
        # Configure environment variables for the follower (slave)
        slave_env = os.environ.copy()
        slave_env["PORT"] = "6000"
        
        # Start the Follower process (Port 6000)
        self.slave_process = subprocess.Popen(
            [sys.executable, SLAVE_PY],
            env=slave_env,
            cwd=BACKEND_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        time.sleep(1)

        # Configure environment variables for the leader
        leader_env = os.environ.copy()
        leader_env["SLAVE_HOST"] = "127.0.0.1"
        leader_env["SLAVE_PORT"] = "6000"

        # Start the Leader process (Port 5000 by default)
        self.leader_process = subprocess.Popen(
            [sys.executable, SERVER_PY],
            env=leader_env,
            cwd=BACKEND_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Wait for the processes to setup their sockets correctly
        time.sleep(3)

    def tearDown(self):
        # Ensure cleanup and kill hung processes
        if self.leader_process.poll() is None:
            self.leader_process.terminate()
        if self.slave_process.poll() is None:
            self.slave_process.terminate()
        
        self.leader_process.wait()
        self.slave_process.wait()

        # Explicitly close pipes to avoid ResourceWarning
        if self.leader_process.stdout:
            self.leader_process.stdout.close()
        if self.leader_process.stderr:
            self.leader_process.stderr.close()
        if self.slave_process.stdout:
            self.slave_process.stdout.close()
        if self.slave_process.stderr:
            self.slave_process.stderr.close()

    def test_failure_recovery_and_reconnection(self):
        """
        Simulates a connection to a leader, turns it off abruptly and verifies
        that the client can connect to the slave promoted to leader.
        """
        # 1. Initial dummy connection with the Leader with retries
        connected = False
        for attempt in range(10):
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(2.0)
            try:
                client_socket.connect(("127.0.0.1", 5000))
                connected = True
                client_socket.close()
                break
            except Exception:
                client_socket.close()
                time.sleep(1)
                
        if not connected:
            self.leader_process.poll()
            stderr_output = self.leader_process.stderr.read().decode('utf-8', errors='ignore')
            self.fail(f"Could not connect to the original leader after 10 retries. Leader stderr:\n{stderr_output}")

        # 2. Trigger a failure: kill the leader
        print("\n[TEST] Killing leader to force election...")
        self.leader_process.terminate()
        self.leader_process.wait()

        # Wait for the distributed system to detect the crash (adjust according to the ping timeout in your code)
        time.sleep(3)

        # 3. Try reconnection to the next available node (new leader on port 6000)
        reconnected = False
        print("[TEST] Attempting to reconnect client to the new leader (port 6000)...")
        for attempt in range(5):
            client_socket_retry = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket_retry.settimeout(3.0)
            try:
                client_socket_retry.connect(("127.0.0.1", 6000))
                reconnected = True
                print(f"[TEST] Successful reconnection on attempt {attempt + 1}")
                client_socket_retry.close()
                break
            except Exception:
                time.sleep(1)

        self.assertTrue(reconnected, "Client could not reconnect to the new leader after the original crashed. Recovery failed.")

if __name__ == '__main__':
    unittest.main()
