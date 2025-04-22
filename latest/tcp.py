"""
TCP message protocol

Server -> Client:
{
    "type": 1) "message": type player message, 2) "control": type control command,
    "data": 1) player message str, 2) command JSON:
                                                    {
                                                        "flag": str, "init"
                                                        "id": str, # uuid
                                                        "ip": str, # udp ip
                                                        "port": int, # udp port
                                                    }
                                                    {
                                                        "flag": str, "stats"
                                                        "res": str, "win:x,loss:x,draw:x"
                                                    }
}

Client -> Server:
{
    "type": 1) "message": type player message, 2) "control": type control command,
    "data": 1) player message str, 2) command JSON:
                                                    {
                                                        "flag": str, "fin"
                                                        "res": int, -1 lost, 0 draw, 1 won
                                                    }
}

"""

import socket
import threading
import json
import uuid
import queue
from concurrent.futures import ThreadPoolExecutor


class StatsDict:
    def __init__(self):
        self.lock = threading.Lock()
        self.stats = {}

    def increment(self, key: str, field: str):
        with self.lock:
            if key not in self.stats:
                self.stats[key] = {"win": 0, "loss": 0, "draw": 0}
            self.stats[key][field] += 1

    def put(self, key: str, value: dict):
        with self.lock:
            if key not in self.stats:
                self.stats[key] = value

    def get(self, key: str):
        with self.lock:
            res = None
            if key in self.stats:
                res = self.stats[key]
            return res


class ClientConnection:
    def __init__(self, connection_socket: socket.socket, connection_address: tuple):
        self.client_socket = connection_socket
        self.client_address = connection_address


class Session:
    def __init__(self, client_1: ClientConnection, client_2: ClientConnection, ip_udp: str, port_udp: int,
                 message_buffer_size: int, stats: StatsDict) -> None:
        self.client_1 = client_1
        self.client_2 = client_2
        self.ip_udp = ip_udp
        self.port_udp = port_udp
        self.message_buffer_size = message_buffer_size
        self.stats = stats
        self.session_shutdown = threading.Event()

    def send_stats(self, key, client_to, res):
        # update the stats
        if res == -1:
            self.stats.increment(key, "loss")
        elif res == 0:
            self.stats.increment(key, "draw")
        elif res == 1:
            self.stats.increment(key, "win")
        # create stats message and send it back
        res = self.stats.get(key)
        message = {"type": "control", "data": {"flag": "stats", "res": res}}
        client_to.client_socket.send(json.dumps(message).encode("utf8"))

    def process_message(self, client_from: ClientConnection, client_to: ClientConnection) -> None:
        while not self.session_shutdown.is_set():
            try:
                message_bytes = client_from.client_socket.recv(self.message_buffer_size)  # bytes
                if not message_bytes:
                    client_key = client_to.client_address.__str__()  # serialize client key
                    self.send_stats(client_key, client_to, 1)
                    break
                # parse and process message received
                try:
                    message_json = json.loads(message_bytes)
                    print(f"received message: {message_json}")
                    # control message
                    if message_json["type"] == "control":
                        data_json = message_json["data"]  # get data
                        # ------------------------ if game is finished ------------------------
                        if data_json["flag"] == "fin":
                            client_key = client_from.client_address.__str__()  # serialize client key
                            # update the stats
                            if data_json["res"] == -1:
                                self.send_stats(client_key, client_from, -1)
                            elif data_json["res"] == 0:
                                self.send_stats(client_key, client_from, 0)
                            elif data_json["res"] == 1:
                                self.send_stats(client_key, client_from, 1)
                            self.session_shutdown.set()
                            break
                    # chat message
                    elif message_json["type"] == "message":
                        client_to.client_socket.send(message_bytes)
                        print(
                            f"forwarded {json.loads(message_bytes)} from {client_from.client_address} to {client_to.client_address}")
                except json.decoder.JSONDecodeError:
                    print("failed to parse message")
                    continue
            except socket.error as e:
                print("socket error", e)
                self.session_shutdown.set()
                break
            except Exception as e:
                print("session error:", e)
                self.session_shutdown.set()
                break

    def run(self) -> None:
        # sends UDP server info
        self.init_match()
        # starts two threads to handle bidirectional message exchange between clients because recv() call is blocking
        thread_1 = threading.Thread(target=self.process_message, args=(self.client_1, self.client_2))
        thread_2 = threading.Thread(target=self.process_message, args=(self.client_2, self.client_1))
        # starts threads
        thread_1.start()
        thread_2.start()
        # wait on session shutdown
        self.session_shutdown.wait()
        # joint threads
        thread_1.join()
        thread_2.join()
        # close client sockets
        self.client_1.client_socket.close()
        self.client_2.client_socket.close()

    def init_match(self) -> None:
        message = {
            "type": "control",
            "data": {
                "flag": "init",
                "id": str(uuid.uuid4()),
                "ip": self.ip_udp,
                "port": self.port_udp
            }
        }
        message_bytes = json.dumps(message).encode("utf8")
        print(f"match {message["data"]["id"]} created")
        self.client_1.client_socket.send(message_bytes)
        self.client_2.client_socket.send(message_bytes)


class SessionManager:
    def __init__(self, client_connection_queue: queue.Queue, worker_size: int, ip_udp: str, port_udp: int,
                 message_buffer_size: int, stats: StatsDict) -> None:
        self.connection_queue = client_connection_queue
        self.worker_pool = ThreadPoolExecutor(max_workers=worker_size)
        self.ip_udp = ip_udp
        self.port_udp = port_udp
        self.message_buffer_size = message_buffer_size
        self.stats = stats

    def run(self) -> None:
        while True:
            try:
                client_1 = self.connection_queue.get()  # blocking call
                if client_1 is None:  # if poison, break
                    break
                client_2 = self.connection_queue.get()  # blocking call
                if client_2 is None:  # if poison, break
                    break
                self.worker_pool.submit(SessionManager.run_session,
                                        Session(client_1, client_2, self.ip_udp, self.port_udp,
                                                self.message_buffer_size, self.stats))  # if two players arrive
            except Exception as e:
                print("session manager error:", e)
                continue
        self.worker_pool.shutdown(wait=False)  # does not wait for client to close connections

    @staticmethod
    def run_session(session: Session) -> None:
        session.run()


class TCPServer:
    def __init__(self, ip_tcp: str, port_tcp: int, ip_udp: str, port_udp: int, message_buffer_size: int,
                 socket_back_log: int, session_manager_worker_pool_size: int) -> None:
        # parameters
        self.ip_tcp = ip_tcp
        self.port_tcp = port_tcp
        self.ip_udp = ip_udp
        self.port_udp = port_udp
        self.message_buffer_size = message_buffer_size
        self.socket_back_log = socket_back_log
        self.session_manager_worker_pool_size = session_manager_worker_pool_size
        self.stats = StatsDict()
        # blocking queue for client connections
        self.connection_queue = queue.Queue()  # client TCP connection buffer
        # server TCP socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.ip_tcp, self.port_tcp))
        # session manager
        self.session_manager = SessionManager(self.connection_queue, self.session_manager_worker_pool_size, self.ip_udp,
                                              self.port_udp, self.message_buffer_size, self.stats)
        self.session_manager_thread = threading.Thread(target=self.session_manager.run)

    def start(self) -> None:
        try:
            self.session_manager_thread.start()
            print("session manager thread started...")
            self.server_socket.listen(self.socket_back_log)
            print("server is listening for incoming connections...")
            while True:
                client_socket, client_address = self.server_socket.accept()  # blocking call
                self.connection_queue.put(ClientConnection(client_socket, client_address))
                print(f"client {client_socket, client_address} is connected end enqueued...")
        except KeyboardInterrupt:
            for i in range(self.session_manager_worker_pool_size):
                self.connection_queue.put(None)
            print("poison submitted to blocking queue...")
            self.server_socket.close()
            print("server socket closed...")
        finally:
            self.session_manager_thread.join()
            print("session manager thread pool stopped...")


SERVER_TCP_IP = "127.0.0.1"
SERVER_TCP_PORT = 55500
SERVER_UDP_IP = "127.0.0.1"
SERVER_UDP_PORT = 55501
MESSAGE_BUFFER_SIZE = 1024
SOCKET_BACK_LOG = 512
SESSION_MANAGER_WORKER_POOL_SIZE = 32

if __name__ == "__main__":
    tcp_server = TCPServer(SERVER_TCP_IP, SERVER_TCP_PORT, SERVER_UDP_IP, SERVER_UDP_PORT, MESSAGE_BUFFER_SIZE,
                           SOCKET_BACK_LOG, SESSION_MANAGER_WORKER_POOL_SIZE)
    tcp_server.start()
