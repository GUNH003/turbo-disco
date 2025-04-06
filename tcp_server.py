"""
TCP control message send by client:
{
    "type": -1 (game over)
    "data": -1 (lost) / 0 (draw) / 1 (win)
}
"""

import json
import uuid
import logging
import queue
import socket
import threading
from concurrent.futures import ThreadPoolExecutor


class Logger:
    """
    Represents a logger object that is used to log messages. This class implements a Singleton pattern, call
    get_logger() to get the logger object after instantiation.
    """

    def __init__(self, logger_name: str, log_level: int, log_format: str, log_file: str, log_mode: str):
        """
        Constructor for Logger class.
        :param logger_name: the name of the logger.
        :param log_level: the log level.
        :param log_format: the log format.
        :param log_file: the log file path.
        """
        # Create a file handler for logging to a file
        self.file_handler = logging.FileHandler(log_file, mode=log_mode)
        self.file_handler.setLevel(log_level)  # Log level for file, can be adjusted as needed
        self.file_handler.setFormatter(logging.Formatter(log_format))
        # Create a stream handler for logging to the console
        self.stream_handler = logging.StreamHandler()
        self.stream_handler.setLevel(log_level)  # Log level for console, can be adjusted as needed
        self.stream_handler.setFormatter(logging.Formatter(log_format))
        # Add both handlers to the root logger
        self.logger = logging.getLogger(logger_name)
        self.logger.addHandler(self.file_handler)
        self.logger.addHandler(self.stream_handler)
        self.logger.setLevel(log_level)

    def get_logger(self) -> logging.Logger:
        """
        Returns the logger object.
        :return: the logger object.
        """
        return self.logger


class ClientConnection:
    """
    Represents a client TCP connection.
    """

    def __init__(self, connection_socket: socket.socket, connection_address):
        """
        Constructor of ClientConnection.
        :param connection_socket: client TCP socket object, created by the server for client connection.
        :param connection_address: client address object.
        """
        self.client_socket = connection_socket
        self.client_address = connection_address


class Session:
    """
    Represents a game session. A game session contains two client TCP connections, which are used for message
    transmission.
    """

    def __init__(self, client_connection_1: ClientConnection, client_connection_2: ClientConnection) -> None:
        """
        Constructor of Session.
        :param client_connection_1: first client TCP connection.
        :param client_connection_2: second client TCP connection.
        """
        self.client_connection_1 = client_connection_1
        self.client_connection_1.client_socket.settimeout(CLIENT_TIMEOUT)  # sets timeout
        self.client_connection_2 = client_connection_2
        self.client_connection_2.client_socket.settimeout(CLIENT_TIMEOUT)  # sets timeout
        self.session_shutdown = threading.Event()
        self.session_shutdown.set()

    def forward_message(self, client_connection_1: ClientConnection, client_connection_2: ClientConnection) -> None:
        """
        Forwards messages from the first client to the second client.
        :param client_connection_1: the first client TCP connection.
        :param client_connection_2: the second client TCP connection.
        :return:
        """
        while self.session_shutdown.is_set():
            try:
                message = client_connection_1.client_socket.recv(MESSAGE_BUFFER_SIZE)  # bytes
                # break if client disconnects, seems to cause exception if client process is interrupted
                if not message:
                    break
                # if client sends control messages, parse and process
                try:
                    message_json = json.JSONDecoder().decode(message.decode("utf8"))
                    if message_json["type"] == -1:  # break if game is over
                        # TODO: cache player statistics
                        if message_json["data"] == -1:
                            LOGGER.debug("client %s: lost", client_connection_1.client_address)
                        if message_json["data"] == 0:
                            LOGGER.debug("client %s: draw", client_connection_1.client_address)
                        if message_json["data"] == 1:
                            LOGGER.debug("client %s: won", client_connection_1.client_address)
                        self.session_shutdown.clear()
                        break
                    else:
                        # TODO: add more control messages in JSON format if needed
                        continue
                # if fails to parse the JSON message, treats it as normal message and forwards it to the other client
                except json.JSONDecodeError:
                    LOGGER.debug("client %s sends a message [%s] to client %s",
                                 client_connection_1.client_address,
                                 message.decode("utf-8").strip(),
                                 client_connection_2.client_address)
                    client_connection_2.client_socket.send(message)
            except socket.timeout:
                LOGGER.error("client %s timeout", self.client_connection_1.client_address)
                break
            except socket.error:
                LOGGER.debug("client %s disconnected", client_connection_1.client_address)
                break
            except Exception as e:
                LOGGER.error("connection error for client %s: %s", self.client_connection_1.client_address, e)
                break
        LOGGER.debug("match over for client %s", client_connection_1.client_address)

    def run(self) -> None:
        """
        Runs the session. When a new session is started, the TCP server sends UDP server address and port information
        to clients. Clients send game state data with session ID to the UDP server and the game state is maintained by
        the UDP server.
        :return: None
        """
        # sends UDP server info
        LOGGER.info("session started for %s and %s", self.client_connection_1.client_address,
                    self.client_connection_2.client_address)
        udp_bytes = json.JSONEncoder().encode({
            "type": "match found",
            "id": str(uuid.uuid4()),
            "ip": UDP_SERVER_IP,
            "port": UDP_SERVER_PORT,
        }).encode("utf8")
        self.client_connection_1.client_socket.send(udp_bytes)
        LOGGER.debug("UDP message %s send to %s", udp_bytes.decode("utf-8"), self.client_connection_1.client_address)
        self.client_connection_2.client_socket.send(udp_bytes)
        LOGGER.debug("UDP message %s send to %s", udp_bytes.decode("utf-8"), self.client_connection_2.client_address)
        # starts two threads to handle bidirectional message exchange between clients because recv() call is blocking
        thread_1 = threading.Thread(target=self.forward_message,
                                    args=(self.client_connection_1, self.client_connection_2))
        thread_2 = threading.Thread(target=self.forward_message,
                                    args=(self.client_connection_2, self.client_connection_1))
        # starts threads
        thread_1.start()
        LOGGER.debug("starting message forwarding from %s to %s", self.client_connection_1.client_address,
                     self.client_connection_2.client_address)
        thread_2.start()
        LOGGER.debug("starting message forwarding from %s to %s", self.client_connection_2.client_address,
                     self.client_connection_1.client_address)

        # wait on session shutdown
        self.session_shutdown.wait()

        # joint threads
        LOGGER.debug("joining thread %s in session %s", thread_1.__str__(), self.__str__())
        thread_1.join()
        LOGGER.debug("joining thread %s in session %s", thread_2.__str__(), self.__str__())
        thread_2.join()

        # close client sockets
        self.client_connection_1.client_socket.close()
        LOGGER.debug("client socket closed: %s", self.client_connection_1.client_address)
        self.client_connection_2.client_socket.close()
        LOGGER.debug("client socket closed: %s", self.client_connection_2.client_address)
        LOGGER.info("session ended for %s and %s", self.client_connection_1.client_address,
                    self.client_connection_2.client_address)


class SessionManager:
    """
    Represents a game session manager. Note this game session manager only manages bidirectional message exchange
    between clients using TCP connections.
    """

    def __init__(self, client_connection_queue: queue.Queue, worker_size: int, shutdown_flag: threading.Event) -> None:
        """
        Constructor of SessionManager.
        :param client_connection_queue: the blocking queue used to store client connections.
        :param worker_size: the size of the session manager's worker thread pool.
        """
        self.global_shutdown = shutdown_flag
        self.connection_queue = client_connection_queue
        self.worker_pool = ThreadPoolExecutor(max_workers=worker_size)

    def run(self) -> None:
        """
        Runs the session manager.
        :return: None
        """
        LOGGER.debug("session manager starting...")
        while not self.global_shutdown.is_set():
            try:
                client_1 = connection_queue.get()
                if client_1 is None:
                    break
                client_2 = connection_queue.get()
                if client_2 is None:
                    break
                self.worker_pool.submit(SessionManager.run_session, Session(client_1, client_2))
            except Exception as e:
                LOGGER.error("session manager error: ", e)
                continue
        self.worker_pool.shutdown(wait=True)
        LOGGER.debug("session manager stopped")

    @staticmethod
    def run_session(session: Session) -> None:
        """
        Runs a session.
        :param session: the session to run.
        :return: None
        """
        session.run()


# -------------------------- logger setup --------------------------
LOG_LEVEL = logging.DEBUG
LOG_FORMAT = "%(asctime)s [%(filename)s] [%(levelname)s] %(message)s"
LOG_FILE = "./tcp_server.log"
LOGGER = Logger(__file__, LOG_LEVEL, LOG_FORMAT, LOG_FILE, "a").get_logger()
# -------------------------- tcp socket --------------------------
TCP_SERVER_IP = "127.0.0.1"
TCP_SERVER_PORT = 33333
SOCKET_BACK_LOG = 128
MESSAGE_BUFFER_SIZE = 1024
# -------------------------- udp server parameters --------------------------
UDP_SERVER_IP = "127.0.0.1"
UDP_SERVER_PORT = 44444
CLIENT_TIMEOUT = 600
# -------------------------- session manager --------------------------
SESSION_MANAGER_WORKER_POOL_SIZE = 32

if __name__ == "__main__":
    LOGGER.info("initializing TCP server...")
    global_shutdown = threading.Event()  # global shutdown event
    connection_queue = queue.Queue()  # client TCP connection buffer

    LOGGER.info("creating server TCP socket...")
    # set up main thread server socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((TCP_SERVER_IP, TCP_SERVER_PORT))
    server_socket.listen(SOCKET_BACK_LOG)
    LOGGER.info("server TCP socket listening...")

    # set up session manager thread
    LOGGER.info("creating session manager...")
    session_manager = SessionManager(connection_queue, worker_size=SESSION_MANAGER_WORKER_POOL_SIZE,
                                     shutdown_flag=global_shutdown)
    session_manager_thread = threading.Thread(target=session_manager.run)
    try:
        session_manager_thread.start()
        LOGGER.info("session manager running...")
        while not global_shutdown.is_set():
            client_socket, client_address = server_socket.accept()
            LOGGER.debug("accepted connection %s from: %s", client_socket.__str__(), client_address.__str__())
            connection_queue.put(ClientConnection(client_socket, client_address))
            LOGGER.debug("enqueued connection %s from %s", client_socket.__str__(), client_address.__str__())
    except KeyboardInterrupt:
        global_shutdown.set()
        LOGGER.info("shutting down server...")
        # inject poison(None) to blocking queue to shut down worker threads
        LOGGER.debug("submitting poison...")
        for i in range(SESSION_MANAGER_WORKER_POOL_SIZE):
            connection_queue.put(None)
    finally:
        # join session manager thread
        session_manager_thread.join()
        LOGGER.info("session manager shut down")
        # closes server TCP socket
        server_socket.close()
        LOGGER.info("server TCP socket closed")
    LOGGER.info("server successfully shut down")
