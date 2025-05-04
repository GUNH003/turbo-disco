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
import logging
from logger.logger import Logger
from concurrent.futures import ThreadPoolExecutor

class StatsDict:
    """
    Concurrent statistics cache.
    """

    def __init__(self):
        """
        Constructor for StatsDict.
        """
        self.lock = threading.Lock()
        self.stats = {}

    def increment(self, key: str, field: str) -> None:
        """
        Increment a field in the value that corresponds to the given key.
        :param key: the given key
        :param field: the field
        :return: None
        """
        with self.lock:
            if key not in self.stats:
                self.stats[key] = {"win": 0, "loss": 0, "draw": 0}
            self.stats[key][field] += 1
            LOGGER.debug(f"Stats updated for {key}: incremented {field}")

    def put(self, key: str, value: dict) -> None:
        """
        Puts a value into dictionary using the given key.
        :param key: the given key
        :param value: the value
        :return: None
        """
        with self.lock:
            if key not in self.stats:
                self.stats[key] = value
                LOGGER.debug(f"Stats created for {key}: {value}")

    def get(self, key: str) -> None:
        """
        Gets the value of a given key in the dictionary.
        :param key: the given key.
        :return: None
        """
        with self.lock:
            res = None
            if key in self.stats:
                res = self.stats[key]
            return res


class ClientConnection:
    """
    ClientConnection class. Represents a client connection.
    """

    def __init__(self, connection_socket: socket.socket, connection_address: tuple):
        self.client_socket = connection_socket
        self.client_address = connection_address


class Session:
    """
    Session class. Represents a session.
    """

    def __init__(self, client_1: ClientConnection, client_2: ClientConnection, ip_udp: str, port_udp: int,
                 message_buffer_size: int, stats: StatsDict, ip_only_identifier: bool) -> None:
        """
        Constructor for Session.
        :param client_1: the first client connection
        :param client_2: the second client connection
        :param ip_udp: the UDP server IP
        :param port_udp: the UDP server port
        :param message_buffer_size: the reception buffer size
        :param stats: the statistics cache
        :param ip_only_identifier: indicating if only IP is used as key for client statistics caching
        """
        self.client_1 = client_1
        self.client_2 = client_2
        self.ip_udp = ip_udp
        self.port_udp = port_udp
        self.message_buffer_size = message_buffer_size
        self.stats = stats
        self.ip_only = ip_only_identifier
        self.session_shutdown = threading.Event()

    def send_stats(self, key, client_to, res) -> None:
        """
        Sends an updated statistics message to the client.
        :param key: the key
        :param client_to: the recipient client
        :param res: the result of the match session
        :return: None
        """
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
        LOGGER.debug(f"Stats sent to {client_to.client_address}: {res}")

    def process_message(self, client_from: ClientConnection, client_to: ClientConnection) -> None:
        """
        Processes a message from a client connection and forward to the other if needed.
        :param client_from: the sender client
        :param client_to: the recipient client
        :return: None
        """
        LOGGER.debug(
            f"worker thread {threading.current_thread().name} for client {client_from.client_address} starting...")
        client_to_key = client_to.client_address[
            0] if self.ip_only else client_to.client_address.__str__()  # serialize client key
        client_from_key = client_from.client_address[
            0] if self.ip_only else client_from.client_address.__str__()  # serialize client key
        while not self.session_shutdown.is_set():
            try:
                message_bytes = client_from.client_socket.recv(self.message_buffer_size)  # bytes
                if not message_bytes:
                    self.send_stats(client_to_key, client_to, 1)
                    self.stats.increment(client_from_key, "loss")
                    client_from.client_socket.close()
                    client_to.client_socket.close()
                    break
                # parse and process message received
                try:
                    message_json = json.loads(message_bytes)
                    LOGGER.debug(f"Received message from {client_from.client_address}: {message_json}")
                    # control message
                    if message_json["type"] == "control":
                        data_json = message_json["data"]  # get data
                        # ------------------------ if game is finished ------------------------
                        if data_json["flag"] == "fin":
                            # update the stats
                            if data_json["res"] == -1:
                                LOGGER.debug(f"Client {client_from.client_address} has lost the game.")
                                self.send_stats(client_from_key, client_from, -1)
                            elif data_json["res"] == 0:
                                LOGGER.debug(f"Client {client_from.client_address} and {client_to.client_address} ended in a draw.")
                                self.send_stats(client_from_key, client_from, 0)
                            elif data_json["res"] == 1:
                                LOGGER.debug(f"Client {client_from.client_address} has won the game.")
                                self.send_stats(client_from_key, client_from, 1)
                            self.session_shutdown.set()
                            break
                    # chat message
                    elif message_json["type"] == "message":
                        client_to.client_socket.send(message_bytes)
                        LOGGER.debug(
                            f"Forwarded message from {client_from.client_address} to {client_to.client_address}")
                except json.decoder.JSONDecodeError:
                    LOGGER.error(f"Failed to parse message from {client_from.client_address}")
                    continue
            except socket.error as e:
                LOGGER.error(f"Socket error: {e}")
                self.session_shutdown.set()
                break
            except Exception as e:
                LOGGER.error(f"Session error: {e}")
                self.session_shutdown.set()
                break
        LOGGER.debug(
            f"worker thread {threading.current_thread().name} for client {client_from.client_address} exiting...")

    def run(self) -> None:
        """
        Starts a session.
        :return: None
        """
        # sends UDP server info
        self.init_match()
        # starts two threads to handle bidirectional message exchange between clients because recv() call is blocking
        thread_1 = threading.Thread(target=self.process_message, args=(self.client_1, self.client_2))
        thread_2 = threading.Thread(target=self.process_message, args=(self.client_2, self.client_1))
        # starts threads
        thread_1.start()
        thread_2.start()
        LOGGER.debug(f"Session threads started for match")
        # wait on session shutdown
        self.session_shutdown.wait()
        # joint threads
        thread_1.join()
        thread_2.join()
        LOGGER.debug("Session threads stopped")
        # close client sockets
        self.client_1.client_socket.close()
        self.client_2.client_socket.close()
        LOGGER.debug(f"session ended for client {self.client_1.client_address} and {self.client_2.client_address}")
        LOGGER.debug("Client sockets closed")

    def init_match(self) -> None:
        """
        Initialize a match.
        :return: None
        """
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
        match_id = message['data']['id']
        LOGGER.debug(f"Match {match_id} created")
        self.client_1.client_socket.send(message_bytes)
        self.client_2.client_socket.send(message_bytes)
        LOGGER.debug(f"Init messages sent to both clients for match {match_id}")


class SessionManager:
    """
    SessionManager class.
    """

    def __init__(self, client_connection_queue: queue.Queue, worker_size: int, ip_udp: str, port_udp: int,
                 message_buffer_size: int, stats: StatsDict, ip_only_identifier: bool) -> None:
        """
        Constructor for SessionManager class.
        :param client_connection_queue: the match making queue
        :param worker_size: the worker thread pool size
        :param ip_udp: the UDP server IP
        :param port_udp: the UDP server port
        :param message_buffer_size: the reception buffer size
        :param stats: the statistics cache
        :param ip_only_identifier: indicating if only IP is used as key for client statistics caching
        """
        self.connection_queue = client_connection_queue
        self.worker_pool = ThreadPoolExecutor(max_workers=worker_size)
        self.ip_udp = ip_udp
        self.port_udp = port_udp
        self.message_buffer_size = message_buffer_size
        self.stats = stats
        self.ip_only = ip_only_identifier

    def run(self) -> None:
        """
        Starts the session manager.
        :return: None
        """
        LOGGER.info("Session manager running")
        while True:
            try:
                client_1 = self.connection_queue.get()  # blocking call
                if client_1 is None:  # if poison, break
                    LOGGER.debug("Received shutdown signal")
                    break
                LOGGER.info(f"First client connected: {client_1.client_address}")
                client_2 = self.connection_queue.get()  # blocking call
                if client_2 is None:  # if poison, break
                    LOGGER.debug("Received shutdown signal")
                    break
                LOGGER.info(f"Second client connected: {client_2.client_address}")
                LOGGER.info(f"Creating match between {client_1.client_address} and {client_2.client_address}")
                self.worker_pool.submit(SessionManager.run_session,
                                        Session(client_1, client_2, self.ip_udp, self.port_udp,
                                                self.message_buffer_size, self.stats,
                                                self.ip_only))  # if two players arrive
            except Exception as e:
                LOGGER.error(f"Session manager error: {e}")
                continue
        LOGGER.info("Session manager shutting down")
        self.worker_pool.shutdown(wait=False)  # does not wait for client to close connections

    @staticmethod
    def run_session(session: Session) -> None:
        session.run()


class TCPServer:
    def __init__(self, ip_tcp: str, port_tcp: int, ip_udp: str, port_udp: int, message_buffer_size: int,
                 socket_back_log: int, session_manager_worker_pool_size: int, ip_only_identifier: bool) -> None:
        """
        Constructor for TCPServer class.
        :param ip_tcp: the TCP server IP
        :param port_tcp: the TCP server port
        :param ip_udp: the UDP server IP
        :param port_udp: the UDP server port
        :param message_buffer_size: the reception buffer size
        :param socket_back_log: backlog size for TCP connections
        :param session_manager_worker_pool_size:
        :param ip_only_identifier: indicating if only IP is used as key for client statistics caching
        """
        # parameters
        self.ip_tcp = ip_tcp
        self.port_tcp = port_tcp
        self.ip_udp = ip_udp
        self.port_udp = port_udp
        self.message_buffer_size = message_buffer_size
        self.socket_back_log = socket_back_log
        self.session_manager_worker_pool_size = session_manager_worker_pool_size
        self.ip_only = ip_only_identifier
        self.stats = StatsDict()
        # blocking queue for client connections
        self.connection_queue = queue.Queue()  # client TCP connection buffer
        # server TCP socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.ip_tcp, self.port_tcp))
        # session manager
        self.session_manager = SessionManager(self.connection_queue, self.session_manager_worker_pool_size, self.ip_udp,
                                              self.port_udp, self.message_buffer_size, self.stats, self.ip_only)
        self.session_manager_thread = threading.Thread(target=self.session_manager.run)

    def start(self) -> None:
        try:
            self.session_manager_thread.start()
            LOGGER.debug("Session manager thread started")
            self.server_socket.listen(self.socket_back_log)
            LOGGER.debug(f"TCP server listening at {self.ip_tcp}:{self.port_tcp}")
            while True:
                client_socket, client_address = self.server_socket.accept()  # blocking call
                LOGGER.info(f"Client {client_address} connected")
                self.connection_queue.put(ClientConnection(client_socket, client_address))
                LOGGER.info(f"Client {client_address} enqueued for matchmaking")
        except KeyboardInterrupt:
            LOGGER.info("Keyboard interrupt received, shutting down TCP server")
            for i in range(self.session_manager_worker_pool_size):
                self.connection_queue.put(None)
            LOGGER.debug("Shutdown signals sent to session manager")
            self.server_socket.close()
            LOGGER.debug("Server socket closed")
        finally:
            self.session_manager_thread.join()
            LOGGER.debug("Session manager thread stopped")


# ------------------------------- logger setup -------------------------------
LOG_LEVEL = logging.DEBUG
LOG_FORMAT = "%(asctime)s [%(filename)s] [%(levelname)s] %(message)s"
LOG_FILE = "./tcp_server.log"
LOGGER = Logger(__file__, LOG_LEVEL, LOG_FORMAT, LOG_FILE, "a").get_logger()
# ------------------------------- server setup -------------------------------
SERVER_TCP_IP = "127.0.0.1"
SERVER_TCP_PORT = 55500
SERVER_UDP_IP = "127.0.0.1"
SERVER_UDP_PORT = 55501
MESSAGE_BUFFER_SIZE = 1024
SOCKET_BACK_LOG = 512
SESSION_MANAGER_WORKER_POOL_SIZE = 32
# 1) If running all servers and clients on different machines within a LAN:
#    Set IP_ONLY_IDENTIFIER = True and CLIENT_TCP_PORT = None.
#    This is the recommended configuration, as it avoids port conflicts by relying solely on the client's IP address
#    for identification.
# 2) If running all servers and clients on localhost (same machine):
#    Set IP_ONLY_IDENTIFIER = False and assign a user-specified value to CLIENT_TCP_PORT.
#    Note: This setup may raise "OSError: [Errno 48] Address already in use" when attempting to initiate a new game
#    after one has ended. This occurs because a recently closed socket may still be in the TIME_WAIT state, preventing
#    the same address from being rebound immediately.
IP_ONLY_IDENTIFIER = False

if __name__ == "__main__":
    LOGGER.info("Starting Tic Tac Toe TCP server")
    tcp_server = TCPServer(SERVER_TCP_IP, SERVER_TCP_PORT, SERVER_UDP_IP, SERVER_UDP_PORT, MESSAGE_BUFFER_SIZE,
                           SOCKET_BACK_LOG, SESSION_MANAGER_WORKER_POOL_SIZE, IP_ONLY_IDENTIFIER)
    tcp_server.start()
