# Project 2: Tic-Tac-Toe
## Project Requirements
This project involves developing a multiplayer Tic-Tac-Toe game where two players can connect over a network and play in real time. The application will feature a user interface with real-time networking capabilities. The designed project should have the following features:
1. Players take turns and moves update instantly.
2. Users can join and wait for an opponent
3. Ensure both players see the same board
4. Players can message each other while playing
5. Track wins, losses, and draws
6. Logs or dashboards for tracking connection activity
7. Intuitive and user-friendly front end  
## Project Implementation
The current implementation is a Tic-Tac-Toe game demo featuring a TCP socket server, a UDP scoket server and two dummy clients with GUI support.
### Highlights
* Decoupled design based on Producer-Consumer pattern.
* Scalability for TCP and UDP servers.
* Server side cache support for player match statistics.
* In-game messaging support.
* Responsive and intuitive GUI for client application.
### Running Instructions
1. Specify host ip and port for TCP server in `tcp.py`.
2. Starts the TCP server `tcp.py`.
3. Specify host ip and port for UDP server in `tcp.py`.
4. Starts the UDP server `udp.py`.
5. Specify host ip and port for client sockets in `client1.py`.
6. Starts dummy client `client1`.
7. Specify host ip and port for client sockets in `client2.py`.
8. Starts dummy client `client2`.  
***Note: the TCP server tracks player statistics based on the IP address and Port number bound to each player's TCP socket.***
