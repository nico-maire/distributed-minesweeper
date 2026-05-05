# 💣 Distributed Minesweeper - Distributed Systems Project

Welcome to the project! We have built a distributed architecture from scratch based on pure Python and TCP Sockets, prioritizing Fault Tolerance, Availability, and Strong Consistency (just as requested by professor Omicini).

## 🏗️ Current Architecture (Final Phase Completed)

We currently have a containerized **Primary-Backup (Leader-Follower)** model. We do not use complex consensus algorithms like Raft/Paxos to save time; instead, we use a **Deterministic Failover** strategy. No external databases are used; our nodes act as their own in-memory DB.

* **3 Nodes & Chain Replication:** The system is composed of 3 nodes replicating data sequentially. 
  * **Leader (server.py):** Listens on port 5000. Receives moves from clients, updates its RAM, and replicates the state down the chain to **Follower-1** to ensure *Strong Consistency*.
  * **Follower-1 (slave.py):** Listens on port 6000. Receives replication data from the Leader and forwards it to **Follower-2**. If the Leader crashes, it auto-promotes to Leader.
  * **Follower-2 (slave.py):** Listens on port 7000. The tail of the chain. If Follower-1 crashes, it will take over as the new Leader.
* **Dumb Clients (client.py):** They have no game logic. If they detect the Leader is down, they use a *Retry with Backoff* algorithm (waiting 1.5s to avoid Race Conditions) and automatically reconnect to the next available port in the sequence (6000, then 7000), recovering the board without losing the game state.

## 🤝 Cooperative Multiplayer

Multiple clients (client.py) can connect at the same time from different terminals to play together. The server manages concurrent threads for each connection and **broadcasts** the game state. This means all players see how the board updates in real time without needing to manually reload or refresh their screens.

## 🚀 How to run and test the environment

The infrastructure is orchestrated with Docker. To bring up the cluster:

1. Make sure you have Docker Desktop running.
2. In your terminal, run: docker compose up --build
3. Open normal terminals (outside of Docker) for the players and run: python client.py

### 🧪 Fault Tolerance Test: Cascading Failure

Follow these steps to see fault tolerance in action!
1. Start the cluster with Docker and connect a couple of clients.
2. Make a few moves in the game to see real-time multiplayer updates.
3. Go to Docker Desktop and **kill/stop the Leader container** (simulating a Crash Failure).
4. Watch the clients' terminals: they will detect the crash, wait, and auto-reconnect to **Follower-1** on port 6000 (which is now the Leader). The board will seamlessly reappear.
5. **Cascading Failure:** Now, kill the **Follower-1** container.
6. Watch the clients survive the second crash! They will auto-jump to port 7000 (**Follower-2**), proving our 3-node resilience.

## 🎯 Next Steps

1. **Final Report:** Begin drafting the Final Report in LaTeX, properly justifying our design decisions (Primary-Backup, Strong Consistency, Chain Replication, and Docker orchestration) and how we met the requirements for Dependability, Communication, Replication, and Orchestration.
