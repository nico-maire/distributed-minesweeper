# 💣 Distributed Minesweeper - Distributed Systems Project

Welcome to the project! We have built a distributed architecture from scratch based on pure Python and TCP Sockets, prioritizing Fault Tolerance, Availability, and Strong Consistency.

## 📂 Project Structure
- **/backend**: Contains the logic for the servers (server.py and slave.py), as well as the game state model (model.py) and protocol serialization definitions (protocol.py).
- **/frontend**: Houses the client application structured under an **MVC** (Model-View-Controller) pattern. Includes network handling (client.py), logic management (controller.py), and a dynamic Tkinter interface (gui.py).
- **/tests**: Contains automated integration tests (	est_integration.py).

## 🏗️ Architecture & Features

### Multiplayer Rooms & User Tracking
The system supports real-time multiplayer instances. Players can join or create isolated game rooms right from a centralized Login UI. The backend handles live user tracking and room state instances, broadcasting updates efficiently to all clients within a given room.

### Client MVC Pattern
The client uses the Model-View-Controller pattern:
- **Model**: Driven by the JSON state synced from the backend over TCP sockets.
- **View (gui.py)**: A modern, dark-themed Tkinter interface containing screens for Login and the Game grid.
- **Controller (controller.py)**: Translates user inputs (clicks, flags, login) into serialized protocol commands and communicates with the network layer.

### Fault Tolerance & Active-Passive Replication
We implemented a **Primary-Backup (Leader-Follower)** model utilizing **Deterministic Failover**.
- **Leader (Port 5000)**: Consolidates updates and maintains strong consistency by sequentially replicating to Follower 1.
- **Followers (Ports 6000 & 7000)**: Act as replicas. If the master node goes offline, the followers auto-promote. The client detects connection drops and instantly routes traffic to the newly promoted leader seamlessly.

## 🧪 Automated Integration Tests
The project features a rigorous validation suite (	ests/test_integration.py). It simulates real failure scenarios including Node Crashes, cascading reconnections, leader elections, and data retention over multiple simulated clients using the unittest framework. It automatically manages process spawning and validates that our fault-tolerance mechanism reacts adequately.

## 🚀 How to Run

To avoid native OS limitations with Docker dealing with Tkinter/X11 displays, the backend runs in Docker while the frontend runs natively.

1. **Start the Backend Servers:**
   Deploy the Leader and the two Follower replicated servers using Docker.
   ``bash
   docker compose up --build
   ``

2. **Run the Client Interface:**
   Open a new terminal (or multiple, to verify multiplayer interactions) and launch the client natively to render the graphical interface:
   ``bash
   python frontend/client.py
   ``
