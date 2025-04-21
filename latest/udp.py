"""
UDP message protocol

Server -> Client:
{
    "id": str, uuid for match
    "turn": bool, indicates if it's player's turn
    "data": list[int],
             [-1], lost
        or   [0], draw
        or   [1], win
        or   [-1, -1, -1, 0, 1, -1, 0, 1, -1], board state
}

Client -> Server:
{
    "id": str, uuid for match
    "data": int, representing client's move
}
"""

import socket
import threading
import queue
import json
from concurrent.futures import ThreadPoolExecutor

class UDPService:
    def __init__(self, ip_udp: str, port_udp: int, message_buffer_size: int, buffer_in: queue.Queue, buffer_out: queue.Queue):
        self.ip_udp = ip_udp
        self.port_udp_recv = port_udp
        self.port_udp_send = port_udp + 1
        self.buffer_in = buffer_in
        self.buffer_out = buffer_out
        self.message_buffer_size = message_buffer_size
        # recv socket
        self.socket_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_recv.bind((self.ip_udp, self.port_udp_recv))
        # send socket
        self.socket_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_send.bind((self.ip_udp, self.port_udp_send))
        # worker threads
        self.thread_recv = threading.Thread(target=self.recv_message)
        self.thread_send = threading.Thread(target=self.send_message)

    def recv_message(self):
        while True:
            try:
                message_bytes, client_address = self.socket_recv.recvfrom(self.message_buffer_size)
                if not message_bytes:
                    print("UDP socket connection closed")
                    break
                message_json = json.loads(message_bytes.decode("utf8"))
                print(f"received {message_json} from {client_address}")
                self.buffer_in.put(
                    {
                        "client": client_address,
                        "message": message_json
                    }
                )
            except OSError as e:
                print("failed to receive message, socket closed", e)
                break

    def send_message(self):
        while True:
            try:
                message_json = self.buffer_out.get()
                if message_json is None:
                    break
                client_address = message_json["client"]
                message_bytes = json.dumps(message_json["message"]).encode("utf8")
                print(f"send {message_json}")
                self.socket_send.sendto(message_bytes, client_address)
            except Exception as e:
                print("failed to send message", e)
                break

    def start(self):
        print("starting udp service...")
        self.thread_send.start()
        self.thread_recv.start()


    def stop(self):
        print("stopping udp service...")
        self.buffer_out.put(None)
        self.socket_recv.close()
        self.socket_send.close()
        self.thread_send.join()
        self.thread_recv.join()


class SessionManager:
    def __init__(self, buffer_in: queue.Queue, buffer_out: queue.Queue, worker_pool_size: int) -> None:
        self.buffer_in = buffer_in
        self.buffer_out = buffer_out
        self.worker_pool_size = worker_pool_size
        self.worker_pool = ThreadPoolExecutor(max_workers=self.worker_pool_size)
        self.sessions = {}
        self.lock_sessions = threading.Lock()

    def is_valid_move(self, move: int, data: list[int]) -> bool:
        return 0 <= move < 9 and data[move] == -1

    def is_win_state(self, data: list[int]) -> bool:
        end_state = [[0, 1, 2], [3, 4, 5], [6, 7, 8],
                     [0, 4, 7], [1, 4, 7], [2, 5, 8],
                     [0, 4, 8], [2, 4, 6]]
        for i, j, k in end_state:
            if data[i] != -1 and data[i] == data[j] == data[k]:
                return True
        return False

    def is_draw_state(self, data: list[int]) -> bool:
        return -1 not in data

    def to_buffer_out(self, client_address: tuple, session_id: str, turn: bool, game_data: list[int]) -> None:
        message_json = {
            "client": client_address,
            "message": {
                "id": session_id,
                "turn": turn,
                "data": game_data,
            }
        }
        self.buffer_out.put(message_json)


    def manage_session(self):
        while True:
            message_in = self.buffer_in.get()
            if message_in is None:
                break
            # retrieve data
            client_address = message_in["client"] # tuple
            client_move = message_in["message"]["data"] # int
            session_id = message_in["message"]["id"] # str
            # acquire lock
            with self.lock_sessions:
                session = None if session_id not in self.sessions else self.sessions[session_id]
                # ----------------------- if session does not exist -----------------------
                if session is None:
                    self.sessions[session_id] = {
                        "id": session_id,
                        "clients": [client_address],
                        "turn": 0,
                        "data": [-1 for _ in range(9)]
                    }
                    # commit outbound message
                    self.to_buffer_out(client_address, session_id, False, self.sessions[session_id]["data"])
                    continue
                # ----------------------- if session exists but the second player is missing -----------------------
                if len(session["clients"]) == 1 and client_address is not session["clients"][0]:
                    session["clients"].append(client_address)
                    # commit outbound message to both clients, client 0 always has first move
                    self.to_buffer_out(session["clients"][0], session_id,True, session["data"])
                    self.to_buffer_out(session["clients"][1], session_id,False, session["data"])
                    continue
                # ----------------------- if session exists and both players are present -----------------------
                current_player = session["turn"] # gets the current player, which equals "turn" and index of "clients"
                # ignores update if the same player tries to update the session again
                if client_address != session["clients"][current_player]:
                    continue
                # if the player move is invalid, informs the player to send again
                if not self.is_valid_move(client_move, session["data"]):
                    self.to_buffer_out(client_address, session_id, True, session["data"])
                    continue
                # if move is valid, update player move
                session["data"][client_move] = current_player
                # check for session termination [start] -----------------------
                if self.is_win_state(session["data"]):
                    # commit outbound message
                    self.to_buffer_out(session["clients"][current_player], session_id,False, [1])
                    self.to_buffer_out(session["clients"][(current_player + 1) % 2], session_id, False, [-1])
                    # delete session
                    self.sessions.pop(session_id)
                    break
                if self.is_draw_state(session["data"]):
                    # commit outbound message
                    self.to_buffer_out(session["players"][current_player], session_id,  False, [0])
                    self.to_buffer_out(session["clients"][(current_player + 1) % 2], session_id, False, [0])
                    # delete session
                    self.sessions.pop(session_id)
                    break
                # check for session termination [end] -----------------------
                # if session not terminated, switch turns
                session["turn"] = (current_player + 1) % 2
                # commit outbound message
                self.to_buffer_out(session["clients"][current_player], session_id, False, session["data"])
                self.to_buffer_out(session["clients"][session["turn"]], session_id, True, session["data"])

    def start(self):
        for i in range(self.worker_pool_size):
            self.worker_pool.submit(self.manage_session)

    def stop(self):
        for i in range(self.worker_pool_size):
            self.buffer_in.put(None)
        self.worker_pool.shutdown(wait=True)


class UDPServer:
    def __init__(self, ip_udp: str, port_udp: int, message_buffer_size: int, session_manager_worker_pool_size: int):
        self.ip_udp = ip_udp
        self.port_udp = port_udp
        self.message_buffer_size = message_buffer_size
        self.session_manager_worker_pool_size = session_manager_worker_pool_size
        self.buffer_in = queue.Queue()
        self.buffer_out = queue.Queue()
        self.udp_service = UDPService(self.ip_udp, self.port_udp, self.message_buffer_size, self.buffer_in, self.buffer_out)
        self.session_manager = SessionManager(self.buffer_in, self.buffer_out, self.session_manager_worker_pool_size)

    def start(self):
        self.session_manager.start()
        print("session manager started...")
        self.udp_service.start()
        print("udp service started...")

    def stop(self):
        self.udp_service.stop()
        print("udp service stopped")
        self.session_manager.stop()
        print("session manager stopped")



UDP_SERVER_IP = "127.0.0.1"
UDP_SERVER_PORT = 55555
MESSAGE_BUFFER_SIZE = 1024
SESSION_MANAGER_WORKER_POOL_SIZE = 2

if __name__ == '__main__':
    udp_server = UDPServer(UDP_SERVER_IP, UDP_SERVER_PORT, MESSAGE_BUFFER_SIZE, SESSION_MANAGER_WORKER_POOL_SIZE)
    udp_server.start()
    try:
        while True:
            threading.Event().wait()
    except KeyboardInterrupt:
        udp_server.stop()
