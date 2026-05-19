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
        # Configuramos variables de entorno para el seguidor (esclavo)
        slave_env = os.environ.copy()
        slave_env["PORT"] = "6000"
        
        # Iniciar el proceso del Seguidor (Puerto 6000)
        self.slave_process = subprocess.Popen(
            [sys.executable, SLAVE_PY],
            env=slave_env,
            cwd=BACKEND_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        time.sleep(1)

        # Configuramos variables de entorno para el líder
        leader_env = os.environ.copy()
        leader_env["SLAVE_HOST"] = "127.0.0.1"
        leader_env["SLAVE_PORT"] = "6000"

        # Iniciar el proceso del Líder (Puerto 5000 por defecto)
        self.leader_process = subprocess.Popen(
            [sys.executable, SERVER_PY],
            env=leader_env,
            cwd=BACKEND_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Esperar a que los procesos levanten correctamente sus sockets
        time.sleep(3)

    def tearDown(self):
        # Asegurarnos de limpiar y matar procesos colgados
        if self.leader_process.poll() is None:
            self.leader_process.terminate()
        if self.slave_process.poll() is None:
            self.slave_process.terminate()
        
        self.leader_process.wait()
        self.slave_process.wait()

    def test_failure_recovery_and_reconnection(self):
        """
        Simula una conexión a un líder, lo apaga abruptamente y verifica
        que el cliente pueda conectarse al esclavo ascendido a líder.
        """
        # 1. Conexión dummy inicial con el Líder con reintentos
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
            self.fail(f"No se pudo conectar al líder original tras 10 intentos. Stderr del líder:\n{stderr_output}")

        # 2. Provocar un fallo: matar el líder
        print("\n[TEST] Matando al líder para forzar elección...")
        self.leader_process.terminate()
        self.leader_process.wait()

        # Esperamos a que el sistema distribuido detecte la caída (ajusta según el timeout del ping en tu código)
        time.sleep(3)

        # 3. Intentar reconexión al siguiente nodo disponible (nuevo líder en puerto 6000)
        reconnected = False
        print("[TEST] Intentando reconectar cliente al nuevo líder (puerto 6000)...")
        for attempt in range(5):
            client_socket_retry = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket_retry.settimeout(3.0)
            try:
                client_socket_retry.connect(("127.0.0.1", 6000))
                reconnected = True
                print(f"[TEST] Reconexión exitosa en el intento {attempt + 1}")
                client_socket_retry.close()
                break
            except Exception:
                time.sleep(1)

        self.assertTrue(reconnected, "El cliente no pudo reconectarse al nuevo líder tras la caída del original. Falló la recuperación.")

if __name__ == '__main__':
    unittest.main()
