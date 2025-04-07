import logging
import socket
import threading
import queue
import json
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

def send_back(sock: socket.socket, out_queue: queue.Queue, shutdown_flag: threading.Event) -> None:
    """
    Send response messages stored in the outbound queue back to the clients.
    :param sock: the socket used to send response messages back to the clients.
    :param out_queue: the outbound message queue.
    :param shutdown_flag: the global shutdown flag.
    :return: None
    """
    while not shutdown_flag.is_set():
        outbound_map = out_queue.get()
        if outbound_map is None:  # break if poison (None)
            LOGGER.debug("sender UDP socket thread exiting...")
            break
        outbound_addr = outbound_map.pop("address")
        outbound_msg = json.dumps(outbound_map).encode("utf-8")
        sock.sendto(outbound_msg, outbound_addr)
        LOGGER.debug("outbound message [%s] sent to client %s", outbound_msg, outbound_addr)


def is_valid_move(move: int, data: list[int]) -> bool:
    """
    Checks if a move is valid.
    :param move: the move to check. Index of data list.
    :param data: the data list. It represents the board state.
    :return: true if move is valid, false otherwise.
    """
    return 0 <= move < 9 and data[move] == -1


def check_draw_state(data: list[int]) -> bool:
    """
    Checks if the match is a draw.
    :param data: the data list. It represents the board state.
    :return: true if the match is a draw, false otherwise.
    """
    return -1 not in data


def check_win_state(data: list[int]) -> bool:
    """
    Checks if the match reaches a win state.
    :param data: the data list. It represents the board state.
    :return: true if the match reaches a win state, false otherwise.
    """
    end_state = [[0, 1, 2], [3, 4, 5], [6, 7, 8],
                 [0, 4, 7], [1, 4, 7], [2, 5, 8],
                 [0, 4, 8], [2, 4, 6]]
    for i, j, k in end_state:
        if data[i] != -1 and data[i] == data[j] == data[k]:
            return True
    return False


def commit_outbound_message(out_queue: queue.Queue, session_id: str, game_data: list[int], turn: bool,
                            client_address: tuple) -> None:
    """
    Commits outbound messages back to the clients.
    :param out_queue: the outbound message queue.
    :param session_id: the session id.
    :param game_data: the game data, the list that represents the board state.
    :param turn: if the recipient client has the next move. 1 for true, 0 for false, None for no more move.
    :param client_address: the recipient client address.
    :return:
    """
    msg_obj = {
        "id": session_id,
        "data": game_data,
        "turn": turn,
        "address": client_address
    }
    out_queue.put(msg_obj)
    LOGGER.debug("outbound message [%s] commited", msg_obj)


def manage_session(session_lock: threading.Lock, session_map: dict, in_queue: queue.Queue, out_queue: queue.Queue,
                   shutdown_flag: threading.Event):
    """
    Maintain the lifecycle of the sessions stored in the session_map. The access of session map is synchronized with
    the session lock.

    The board state is represented as a list of 9 integers (-1: empty, 0: player one, 1: player two) Each string object
    represents a cell on the board.

    The messages stored in the inbound queue are always of Dict type and has the following format:
    {
        "id": str,          # unique uuid representing the session id
        "data": int,        # index of the board list, representing the last move of the player
        "address": tuple    # (ip:str, port:int) representing the client address
    }

    The messages stored in the outbound queue are always of Dict type and has the following format:
    {
        "id": str,          # unique uuid representing the session id
        "data": list[int],  # list representation of the board used for client side rendering
        "turn": bool,       # true, false or None, representing if the recipient has the next move
        "address": tuple    # (ip:str, port:int) representing the client address
    }

    :param session_lock: the session map lock.
    :param session_map: the session map.
    :param in_queue: the inbound message queue.
    :param out_queue: the outbound message queue.
    :param shutdown_flag: the global shutdown flag.
    :return: None
    """
    LOGGER.debug("worker thead %s starting...", threading.get_ident())
    while not shutdown_flag.is_set():
        msg_obj = in_queue.get()
        LOGGER.debug("worker thead %s received: %s", threading.get_ident(), msg_obj)
        # break if poison (None)
        if msg_obj is None:
            LOGGER.debug("worker thread exiting...")
            break
        # retrieve data
        session_id = msg_obj["id"]
        player_addr = msg_obj["address"]
        player_move = msg_obj["data"]
        # acquire lock
        with session_lock:
            session = None if session_id not in session_map else session_map[session_id]
            # ----------------------- if session does not exist -----------------------
            if not session:
                # create session
                session_map[session_id] = {
                    "id": session_id,
                    "players": [player_addr],
                    "turn": 0,
                    "data": [-1 for _ in range(9)]
                }
                LOGGER.debug("session [%s] created for client %s", session_id, player_addr)
                # commit outbound message
                commit_outbound_message(out_queue, session_id, [], False, player_addr)
                continue
            # ----------------------- if session exists but the second player is missing -----------------------
            if len(session["players"]) == 1:
                if player_addr != session["players"][0]:
                    session["players"].append(player_addr)
                    LOGGER.debug("session [%s] added client %s", session_id, player_addr)
                    # commit outbound message to p1 and p2, p1 always has first move
                    commit_outbound_message(out_queue, session_id, session["data"], True, session["players"][0])
                    commit_outbound_message(out_queue, session_id, session["data"], False, session["players"][1])
                    LOGGER.debug("session [%s] started", session_id)
                    continue
            # ----------------------- if session exists and both players are present -----------------------
            # if the same player tries to update the session again, ignore update
            if player_addr != session["players"][session["turn"]]:
                LOGGER.debug("session [%s] is not expecting update from client %s", session_id, player_addr)
                continue
            # if the player move is invalid, inform the player to send again
            if not is_valid_move(player_move, session["data"]):
                commit_outbound_message(out_queue, session_id, session["data"], True, player_addr)
                LOGGER.debug("session [%s] encounters invalid update from client %s", session_id, player_addr)
                continue
            # if move is valid, update player move
            session["data"][player_move] = session["turn"]
            LOGGER.debug("session [%s] updated by client %s", session_id, player_addr)
            # check for session termination [start] -----------------------
            if check_win_state(session["data"]):
                LOGGER.debug("terminating session [%s] since client %s has won", session_id, player_addr)
                # commit outbound message
                commit_outbound_message(out_queue, session_id, session["data"], False, session["players"][0])
                commit_outbound_message(out_queue, session_id, session["data"], False, session["players"][1])
                # delete session
                session_map.pop(session_id)
                LOGGER.debug("session [%s] terminated", session_id)
                break
            if check_draw_state(session["data"]):
                LOGGER.debug("terminating session [%s] since match is a draw", session_id)
                # commit outbound message
                commit_outbound_message(out_queue, session_id, session["data"], False, session["players"][0])
                commit_outbound_message(out_queue, session_id, session["data"], False, session["players"][1])
                # delete session
                session_map.pop(session_id)
                LOGGER.debug("session [%s] terminated", session_id)
                break
            # check for session termination [end] -----------------------
            # if session not terminated, switch turns
            session["turn"] = (session["turn"] + 1) % 2
            LOGGER.debug("session [%s] now expects next move from client %s", session_id, session["players"][session["turn"]])
            # commit outbound message
            commit_outbound_message(out_queue, session_id, session["data"], session["turn"] == 0, session["players"][0])
            commit_outbound_message(out_queue, session_id, session["data"], session["turn"] == 1, session["players"][1])
            continue


LOG_LEVEL = logging.DEBUG
LOG_FORMAT = "%(asctime)s [%(filename)s] [%(levelname)s] %(message)s"
LOG_FILE = "./tcp_server.log"
LOGGER = Logger(__file__, LOG_LEVEL, LOG_FORMAT, LOG_FILE, "a").get_logger()

RECV_UDP_IP = "127.0.0.1"
RECV_UDP_PORT = 55555
SEND_UDP_IP = "127.0.0.1"
SEND_UDP_PORT = 55556
BUFFER_SIZE = 1024
WORKER_POOL_SIZE = 2


if __name__ == '__main__':
    LOGGER.info("initializing UDP server...")
    # setup sessions and lock
    lock = threading.Lock()
    sessions = {}

    # setup global shutdown flag
    global_shutdown = threading.Event()

    # setup inbound and outbound queue
    inbound_queue = queue.Queue()
    outbound_queue = queue.Queue()

    LOGGER.info("initializing sender UDP socket at %s...", (SEND_UDP_IP, SEND_UDP_PORT))
    # setup sender socket, sender get message from outbound queue and send them to each client
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_sock.bind((SEND_UDP_IP, SEND_UDP_PORT))
    send_sock_thread = threading.Thread(target=send_back, args=(send_sock, outbound_queue, global_shutdown))
    send_sock_thread.start()

    LOGGER.info("initializing worker pool...")
    # setup worker pool to manage sessions, worker get message inbound queue, update session information, and put update information into the outbound queue
    worker_pool = ThreadPoolExecutor(max_workers=WORKER_POOL_SIZE)
    for i in range(WORKER_POOL_SIZE):
        worker_pool.submit(manage_session, lock, sessions, inbound_queue, outbound_queue, global_shutdown)

    LOGGER.info("initializing receiver UDP socket at %s...", (RECV_UDP_IP, RECV_UDP_PORT))
    # setup receiver socket
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.bind((RECV_UDP_IP, RECV_UDP_PORT))
    LOGGER.info("server running...")
    while not global_shutdown.is_set():
        try:
            inbound_msg, inbound_addr = recv_sock.recvfrom(BUFFER_SIZE)
            LOGGER.debug("received incoming message [%s] from client %s", inbound_msg, inbound_addr)
            inbound_map = json.loads(inbound_msg)
            inbound_map["address"] = inbound_addr
            inbound_queue.put(inbound_map)
            LOGGER.debug("enqueued incoming message: %s", inbound_map)
        except json.JSONDecodeError as e:
            LOGGER.error("failed to parse inbound message: %s", e)
        except socket.error as e:
            LOGGER.error("receiver socket connection error: %s", e)
            break
        except KeyboardInterrupt:
            global_shutdown.set()
            LOGGER.debug("submitting poison to inbound blocking queue...")
            # put poison into inbound queue to kill worker thread pool
            for i in range(WORKER_POOL_SIZE):
                inbound_queue.put(None)
            LOGGER.debug("submitting poison to pool outbound blocking queue...")
            # put poison into outbound queue
            outbound_queue.put(None)
    LOGGER.info("closing receiver UDP socket...")
    recv_sock.close()
    LOGGER.info("closing worker pool...")
    worker_pool.shutdown()
    LOGGER.info("closing sender UDP socket...")
    send_sock.close()
    LOGGER.info("server successfully shut down")
