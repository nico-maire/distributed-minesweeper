# 💣 Distributed Minesweeper - Proyecto Sistemas Distribuidos

¡Bienvenido al proyecto! Hemos construido una arquitectura distribuida desde cero basada en Python puro y Sockets TCP, priorizando la Tolerancia a Fallos, la Disponibilidad y la Consistencia Fuerte (tal y como pidió el profesor Omicini).

## 🏗️ Arquitectura Actual (Fase 5 Completada)

Actualmente tenemos un modelo **Primary-Backup (Leader-Follower)** dockerizado. No usamos algoritmos de consenso complejos como Raft/Paxos para ahorrar tiempo; en su lugar, usamos una estrategia de **Failover Determinista**. No usamos Bases de Datos externas; nuestros nodos actúan como su propia BBDD en memoria.

* **Leader (`server.py`):** Escucha en el puerto `5000`. Recibe las jugadas, actualiza su RAM, replica el estado al Follower para asegurar la *Consistencia Fuerte* y luego actualiza a los clientes.
* **Follower (`slave.py`):** Escucha en el puerto `6000`. Es una réplica pasiva. Si el Leader cae, detecta el fallo de red, se "promociona" automáticamente a Leader y empieza a aceptar conexiones de los clientes.
* **Dumb Clients (`client.py`):** No tienen lógica de juego. Si detectan que el Leader cae, tienen un algoritmo de *Retry with Backoff* (esperan 1.5s para evitar Race Conditions) y se reconectan automáticamente al puerto `6000` (el nuevo Leader), recuperando el tablero sin perder la partida.

## 🚀 Cómo ejecutar y testear el entorno

La infraestructura está orquestada con Docker. Para levantar el clúster:

1. Asegúrate de tener Docker Desktop abierto.
2. En la terminal, ejecuta: `docker compose up --build`
3. Abre otras terminales normales (fuera de Docker) para los jugadores y ejecuta: `python client.py`

### 🧪 Prueba de Tolerancia a Fallos (¡Haz esto para entenderlo!)
1. Arranca el clúster con Docker y conecta dos clientes.
2. Haz un par de movimientos en el juego.
3. Ve a Docker Desktop y **apaga/mata el contenedor del Leader** (simulando un Crash Failure).
4. Mira las terminales de los clientes: verás que detectan la caída, esperan, se reconectan al Follower (que ahora es el Leader) y el tablero vuelve a aparecer mágicamente para seguir jugando.

## 🎯 Próximos Pasos

1. **Escalar a 3 Nodos (Sobresaliente):** Modificar el `docker-compose.yml` para añadir un `follower-2` en el puerto `7000`. Actualizar la lista `PORTS` del cliente para que tenga `[5000, 6000, 7000]`. Actualizar el Leader y el primer Follower para que repliquen los datos en cadena.
2. **Mejoras visuales:** Darle un repaso al `client.py` por si quieres que el tablero se vea mejor.
3. **El Reporte:** Empezar a redactar el documento en LaTeX justificando que hemos cumplido con Dependability, Communication, Replication y Orchestration.