import tkinter as tk
import socket
import threading
import queue
import json
import logging
from logger.logger import Logger


class TCPService:
    """
    The TCP connection service.
    """

    def __init__(self, client_ip: str, client_port: int, server_ip: str, server_port: int):
        """
        Constructor for the TCP connection service.
        :param client_ip:  the client IP
        :param client_port:  the client port, note that it is not advised to bind client TCP socket to a dedicated port
                             unless all servers and clients are running on the same localhost and TCP server is set to
                             identify clients using client TCP socket address. i.e. (IP, PORT) tuple
        :param server_ip:  the server IP
        :param server_port: the server port
        """
        self.socket_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # only binds the TCP socket to dedicated address if both ip and port are specified
        if client_ip is not None and client_port is not None:
            self.socket_tcp.bind((client_ip, client_port))
        self.socket_tcp.connect((server_ip, server_port))
        self.buffer_in = queue.Queue()
        self.buffer_out = queue.Queue()
        self.thread_send = threading.Thread(target=self.send_message)
        self.thread_recv = threading.Thread(target=self.recv_message)
        self.shutdown = threading.Event()

    def send_message(self) -> None:
        """
        Sends message to the TCP server.
        :return: None
        """
        while not self.shutdown.is_set():
            message = self.buffer_out.get()
            if message is None:
                self.shutdown.set()
                break
            try:
                self.socket_tcp.send(message.encode())
                LOGGER.debug(f"successfully sent TCP message {message}")
            except socket.error as e:
                LOGGER.error(f"failed to send message {message}", e)
                self.shutdown.set()
                break
            except KeyboardInterrupt:
                LOGGER.debug("TCP send service received keyboard interrupt")
                self.shutdown.set()
                break

    def recv_message(self) -> None:
        """
        Receives messages from the TCP server.
        :return: None
        """
        while not self.shutdown.is_set():
            try:
                message_bytes = self.socket_tcp.recv(MESSAGE_BUFFER_SIZE)
                if not message_bytes:
                    LOGGER.debug("TCP recv connection closed")
                    self.shutdown.set()
                    break
                self.buffer_in.put(message_bytes.decode())
                LOGGER.debug(f"successfully received TCP message {message_bytes.decode()}")
            except socket.error as e:
                LOGGER.debug(f"TCP recv service closed due to socket error {e}")
                self.shutdown.set()
                break
            except KeyboardInterrupt:
                LOGGER.debug("TCP recv service received keyboard interrupt")
                self.shutdown.set()
                break

    def start(self) -> None:
        """
        Starts the TCP service.
        :return: None
        """
        self.thread_send.start()
        self.thread_recv.start()
        LOGGER.debug("TCP service started")

    def get_message(self) -> str:
        """
        Get the next TCP message form the inbound blocking queue buffer.
        :return: the next TCP message
        """
        return self.buffer_in.get()  # blocking

    def put_message(self, message: str) -> None:
        """
        Puts the outbound TCP message into the outbound blocking queue.
        :param message: the outbound message
        :return: None
        """
        self.buffer_out.put(message)

    def stop(self) -> None:
        """
        Stops the TCP service.
        :return: None
        """
        self.shutdown.set()
        self.buffer_out.put(None)
        self.thread_send.join()
        self.socket_tcp.close()
        self.thread_recv.join()
        self.buffer_in.put(None)
        LOGGER.debug("TCP service stopped")


class UDPService:
    """
    The UDP connection service.
    """

    def __init__(self, client_ip: str, client_port: int, server_ip: str, server_port: int):
        """
        Constructor for the UDP connection service.
        :param client_ip: the client IP
        :param client_port: the client port
        :param server_ip:  the server IP
        :param server_port:  the server port
        """
        self.socket_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_udp.bind((client_ip, client_port))
        self.server_ip = server_ip
        self.server_port = server_port
        self.buffer_in = queue.Queue()
        self.buffer_out = queue.Queue()
        self.thread_send = threading.Thread(target=self.send_message)
        self.thread_recv = threading.Thread(target=self.recv_message)
        self.shutdown = threading.Event()

    def send_message(self) -> None:
        """
        Sends messages to the UDP server.
        :return: None
        """
        while not self.shutdown.is_set():
            message = self.buffer_out.get()
            if message is None:
                self.shutdown.set()
                break
            try:
                self.socket_udp.sendto(message.encode(), (self.server_ip, self.server_port))
                LOGGER.debug(f"successfully sent UDP message {message}")
            except socket.error as e:
                LOGGER.debug(f"failed to send message {message} due to socket error {e}")
                self.shutdown.set()
                break
            except KeyboardInterrupt:
                LOGGER.debug("UDP send service received keyboard interrupt")
                self.shutdown.set()
                break

    def recv_message(self) -> None:
        """
        Receives messages from the UDP server.
        :return: None
        """
        while not self.shutdown.is_set():
            try:
                message_bytes, addr = self.socket_udp.recvfrom(MESSAGE_BUFFER_SIZE)
                self.buffer_in.put(message_bytes.decode())
                LOGGER.debug(f"successfully received UDP message {message_bytes.decode()}")
            except socket.error as e:
                LOGGER.debug(f"UDP recv service closed due to socket error {e}")
                self.shutdown.set()
                break
            except KeyboardInterrupt:
                LOGGER.debug("UDP recv service received keyboard interrupt")
                self.shutdown.set()
                break

    def start(self) -> None:
        """
        Starts the UDP service.
        :return: None
        """
        self.thread_send.start()
        self.thread_recv.start()
        LOGGER.debug("UDP service started")

    def get_message(self) -> str:
        """
        Get the next UDP message form the inbound blocking queue buffer.
        :return: the next UDP message
        """
        return self.buffer_in.get()  # blocking

    def put_message(self, message: str) -> None:
        """
        Puts the outbound UDP message into the outbound blocking queue.
        :param message: the outbound UDP message
        :return: None
        """
        self.buffer_out.put(message)

    def stop(self) -> None:
        """
        Stops the UDP service.
        :return: None
        """
        self.shutdown.set()
        self.buffer_out.put(None)
        self.thread_send.join()
        self.socket_udp.close()
        self.thread_recv.join()
        self.buffer_in.put(None)
        LOGGER.debug("UDP service stopped")


class Client:
    """
    Client class with GUI.
    """

    def __init__(self, ip_tcp_server: str, port_tcp_server: int, ip_client: str, port_tcp_client: int,
                 port_udp_client: int):
        """
        Constructor for the client class.
        :param ip_tcp_server: the ip address of the tcp server.
        :param port_tcp_server: the port of the tcp server.
        :param ip_client: the ip address of the client host.
        :param port_tcp_client: the port that the client TCP socket binds to.
        :param port_udp_client: the port that the client UDO socket binds to.
        """
        # Game state
        self.session_id = None
        self.turn = None  # False: opponent's turn, True: your turn
        self.player = None  # 0: X, 1:O
        self.board = None  # list[int]
        self.stats = None  # str
        self.match_over = True
        # GUI
        self.top_level_widget = tk.Tk()
        self.top_level_widget.title("Tic Tac Toe")
        self.top_level_widget.protocol("WM_DELETE_WINDOW", self.stop)
        self.canvas_game_board = self.create_canvas_game_board()
        self.widget_message_display = self.create_widget_message_display()
        self.entry_message_input = self.create_entry_message_input()
        self.create_button_game_state()
        self.draw_board()
        self.update_lock = threading.Lock()
        self.update_queue = queue.Queue()
        # Networking
        self.ip_tcp_server = ip_tcp_server
        self.port_tcp_server = port_tcp_server
        self.ip_client = ip_client
        self.port_tcp_client = port_tcp_client
        self.port_udp_client = port_udp_client
        self.tcp_service = None
        self.udp_service = None
        # Shutdown flag
        self.shutdown = threading.Event()
        # Update GUI
        self.thread_tcp_consumer = None
        self.thread_udp_consumer = None
        self.top_level_widget.after(10, self.process_gui_updates)

    def process_gui_updates(self) -> None:
        """
        Processes GUI updates. Handler function used for main thread to process update events from the update_queue.
        :return: None
        """
        try:
            while True:
                update_type, *args = self.update_queue.get_nowait()
                if update_type == "message":
                    self.display_message(*args)
                elif update_type == "start_tcp":
                    self.display_message("[SERVER] Connecting to TCP server...")
                    self.thread_tcp_consumer = threading.Thread(target=self.consume_message_tcp)
                    self.thread_tcp_consumer.start()
                    self.tcp_service = TCPService(self.ip_client, self.port_tcp_client, self.ip_tcp_server,
                                                  self.port_tcp_server)
                    self.tcp_service.start()
                    self.display_message("[MATCH] Match making...")
                    LOGGER.debug(f"Client initialized with TCP server {self.ip_tcp_server}:{self.port_tcp_server}")
                elif update_type == "restart":
                    if not self.match_over:
                        self.display_message("[ERROR] Current match is not over, cannot find new match...")
                        LOGGER.info("Restart rejected: match in progress")
                    else:
                        LOGGER.info("Restarting game services and finding new match")
                        self.stop_services()
                        self.session_id = None
                        self.turn = None
                        self.player = None
                        self.board = None
                        self.stats = None
                        self.shutdown.clear()
                        self.update_queue.put(("start_tcp",))
                elif update_type == "start_udp":
                    self.display_message("[SERVER] Connecting to UDP server...")
                    self.thread_udp_consumer = threading.Thread(target=self.consume_message_udp)
                    self.thread_udp_consumer.start()
                    msg_json = args[0]
                    self.session_id = msg_json["data"]["id"]
                    ip_udp = msg_json["data"]["ip"]
                    port_udp = msg_json["data"]["port"]
                    LOGGER.debug(f"UDP connection to {ip_udp}:{port_udp} for session {self.session_id}")
                    self.udp_service = UDPService(self.ip_client, self.port_udp_client, ip_udp, port_udp)
                    self.udp_service.start()
                    self.udp_service.put_message(json.dumps({"id": self.session_id, "data": -1}))
                    self.match_over = False
                elif update_type == "init_match":
                    msg_json = args[0]
                    self.session_id = msg_json["id"]
                    self.player = 0 if msg_json["turn"] else 1
                    LOGGER.debug(f"Match initialized: session {self.session_id}, player {self.player}")
                    self.display_message("[MATCH] Waiting for opponent")
                elif update_type == "update_match":
                    msg_json = args[0]
                    if self.board is None:
                        self.display_message("[MATCH] Opponent has joined")
                        LOGGER.debug("Opponent joined the match")
                    self.turn = msg_json["turn"]
                    if self.turn:
                        turn_status = "[TURN] Your Turn!"
                    else:
                        turn_status = "[TURN] Opponents Turn!"
                    self.display_message(turn_status)
                    LOGGER.info(f"Turn update: {turn_status}")
                    self.board = msg_json["data"]
                    LOGGER.debug(f"Board state: {self.board} ")
                    self.draw_board()
                elif update_type == "end_match":
                    msg_json = args[0]
                    res = msg_json["res"]
                    if res == -1:
                        result_message = "[GAME] You lost :("
                        self.tcp_service.put_message(
                            json.dumps({"type": "control", "data": {"flag": "fin", "res": res}}))
                    elif res == 0:
                        result_message = "[GAME] Draw!"
                        self.tcp_service.put_message(
                            json.dumps({"type": "control", "data": {"flag": "fin", "res": res}}))
                    elif res == 1:
                        result_message = "[GAME] You Won! :)"
                        self.tcp_service.put_message(
                            json.dumps({"type": "control", "data": {"flag": "fin", "res": res}}))
                    LOGGER.info(f"Match ended: {result_message}")
                    self.display_message(result_message)
                    self.board = msg_json["data"]
                    self.draw_board()
                    self.udp_service.put_message(json.dumps({"id": self.session_id, "data": -2}))
                    LOGGER.debug("UDP Clean message sent")
                elif update_type == "stats":
                    self.udp_service.put_message(
                        json.dumps({"id": self.session_id, "data": -2}))  # sends the clean message
                    msg_json = args[0]
                    stats_json = msg_json["data"]["res"]
                    wins = stats_json.get("win", 0)
                    losses = stats_json.get("loss", 0)
                    draws = stats_json.get("draw", 0)
                    stats_message = f"[STATS] Game Stats: {wins} Wins, {losses} Losses, {draws} Draws"
                    self.display_message(stats_message)
                    LOGGER.debug(f"Stats received: {stats_json}")
                    self.match_over = True
                elif update_type == "exit":
                    LOGGER.debug("Exit Requested")
                    self.shutdown.set()
                    self.stop()
        except queue.Empty:
            pass
        self.top_level_widget.after(10, self.process_gui_updates)

    def create_canvas_game_board(self) -> tk.Canvas:
        """
        Creates and initializes a Canvas instance.
        :return: a Canvas instance
        """
        canvas = tk.Canvas(self.top_level_widget, width=CELL_SIZE * BOARD_SIZE, height=CELL_SIZE * BOARD_SIZE)
        canvas.pack(pady=CANVAS_PADDING)
        canvas.bind("<Button-1>", self.on_click)
        return canvas

    def on_click(self, event) -> None:
        """
        Callback function for click event.
        :param event: click event
        :return: None
        """
        if self.match_over:
            return
        if self.turn:
            col = event.x // CELL_SIZE
            row = event.y // CELL_SIZE
            index = row * BOARD_SIZE + col
            if 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE and self.board[index] == -1:  # BOARD_SIZE = 3
                self.board[index] = self.player  # update board state
                LOGGER.debug(f"Player made a move at position {index}")
                self.update_queue.put(("board", self.board.copy()))  # Sends a copy
                if self.udp_service:
                    self.udp_service.put_message(json.dumps({
                        "id": self.session_id,
                        "data": index
                    }))
            else:
                LOGGER.debug(f"Invalid move attempted at position {index}")
                self.display_message("[ERROR] Invalid Move!")
        else:
            LOGGER.debug("Move attempted when not player's turn")
            self.display_message("[ERROR] Not your Turn!")

    def draw_board(self) -> None:
        """
        Updates board.
        :return: None
        """
        # Clear canvas
        self.canvas_game_board.delete("all")
        # Draw grid
        for i in range(1, BOARD_SIZE):
            self.canvas_game_board.create_line(i * CELL_SIZE, 0, i * CELL_SIZE, CELL_SIZE * BOARD_SIZE)
            self.canvas_game_board.create_line(0, i * CELL_SIZE, CELL_SIZE * BOARD_SIZE, i * CELL_SIZE)
        if self.board and len(self.board) == 9:
            # Draw symbols from board (1D list)
            for row in range(BOARD_SIZE):
                for col in range(BOARD_SIZE):
                    index = row * BOARD_SIZE + col
                    value = self.board[index]
                    symbol = "X" if value == 0 else "O" if value == 1 else None
                    color = "blue" if symbol == "X" else "red"
                    if symbol:
                        x_center = col * CELL_SIZE + CELL_SIZE // 2
                        y_center = row * CELL_SIZE + CELL_SIZE // 2
                        self.canvas_game_board.create_text(x_center, y_center, text=symbol, font=("Arial", 48, "bold"),
                                                           fill=color)

    def create_widget_message_display(self) -> tk.Text:
        """
        Creates and initializes a Text instance.
        :return: the Text instance
        """
        frame_message_display = tk.Frame(self.top_level_widget)
        frame_message_display.pack(pady=FRAMES_PADDING, fill="both", expand=True)
        widget_text = tk.Text(frame_message_display, height=TEXT_WIDGET_HEIGHT, state="disabled", wrap="word")
        widget_text.pack(side="left", fill="both", expand=True)
        scrollbar_text = tk.Scrollbar(frame_message_display, command=widget_text.yview)
        scrollbar_text.pack(side="right", fill="y")
        widget_text.config(yscrollcommand=scrollbar_text.set)
        return widget_text

    def create_entry_message_input(self) -> tk.Entry:
        """
        Creates and initializes an Entry instance.
        :return: the Entry instance
        """
        frame_message_input = tk.Frame(self.top_level_widget)
        frame_message_input.pack(pady=FRAMES_PADDING, fill="x")
        entry_message_input = tk.Entry(frame_message_input)
        entry_message_input.pack(side="left", fill="x", expand=True, padx=(0, FRAMES_PADDING))
        button_send = tk.Button(frame_message_input, text="Send", command=self.send_message)
        button_send.pack(side="right")
        return entry_message_input

    def create_button_game_state(self) -> None:
        """
        Creates and initializes button instances in the GUI.
        :return: None
        """
        frame_game_sate = tk.Frame(self.top_level_widget)
        frame_game_sate.pack(pady=FRAMES_PADDING, fill="x")
        button_find_new_match = tk.Button(frame_game_sate, text="Find New Match", command=self.find_new_match)
        button_find_new_match.pack(side="left")
        button_exit = tk.Button(frame_game_sate, text="Exit Game", command=self.stop)
        button_exit.pack(padx=12, side="left")

    def display_message(self, message) -> None:
        """
        Display a message in the GUI.
        :param message: the message displayed in the GUI
        :return: None
        """
        self.widget_message_display.config(state="normal")
        self.widget_message_display.insert("end", message + "\n")
        self.widget_message_display.see("end")
        self.widget_message_display.config(state="disabled")

    def send_message(self) -> str:
        """
        Sends a message to the TCP server and displays the same message in GUI.
        :return: the message
        """
        message = self.entry_message_input.get().strip()
        if message:
            self.update_queue.put(("message", "[YOU]: " + message))
            if self.tcp_service:
                self.tcp_service.put_message(json.dumps({"type": "message", "data": message}))
                LOGGER.debug(f"Chat message sent: {message}")
            self.entry_message_input.delete(0, tk.END)
        return message

    def find_new_match(self) -> None:
        """
        Call back function. Finds a new match.
        :return: None
        """
        # finds new match
        LOGGER.info("Finding new match requested")
        if self.tcp_service is None:
            self.update_queue.put(("start_tcp",))
        else:
            self.update_queue.put(("restart",))

    def consume_message_tcp(self) -> None:
        """
        TCP service message consumer task.
        :return: None
        """
        LOGGER.debug("TCP consumer thread started")
        while not self.shutdown.is_set():
            if self.tcp_service:
                msg = self.tcp_service.get_message()
                if msg is None:
                    break
                msg_json = json.loads(msg)
                LOGGER.debug(f"TCP message received: {msg_json}")
                if msg_json["type"] == "control" and msg_json["data"]["flag"] == "init":
                    self.update_queue.put(("start_udp", msg_json))
                elif msg_json["type"] == "control" and msg_json["data"]["flag"] == "stats":
                    self.update_queue.put(("stats", msg_json))
                elif msg_json["type"] == "message":
                    self.update_queue.put(("message", "[OPPONENT]: " + msg_json["data"]))
        LOGGER.debug("TCP consumer thread stopped")

    def consume_message_udp(self) -> None:
        """
        UDP service message consumer task.
        :return: None
        """
        LOGGER.debug("UDP consumer thread started")
        while not self.shutdown.is_set():
            if self.udp_service:
                msg = self.udp_service.get_message()
                if msg is None:
                    break
                msg_json = json.loads(msg)
                LOGGER.debug(f"UDP message received: {msg_json}")
                # match state
                res = msg_json["res"]
                if res == -3:
                    self.update_queue.put(("init_match", msg_json))
                elif res == -2:
                    self.update_queue.put(("update_match", msg_json))
                else:
                    self.update_queue.put(("end_match", msg_json))
        LOGGER.debug("UDP consumer thread stopped")

    def run(self) -> None:
        """
        Runs the client GUI.
        :return:
        """
        LOGGER.info("Client main loop starting")
        self.top_level_widget.mainloop()

    def stop_services(self) -> None:
        """
        Stops network services.
        :return: None
        """
        LOGGER.info("Stopping client services")
        self.shutdown.set()
        if self.tcp_service:
            self.tcp_service.stop()
            self.tcp_service = None
        if self.udp_service:
            self.udp_service.stop()
            self.udp_service = None
        if self.thread_tcp_consumer and self.thread_tcp_consumer.is_alive():
            self.thread_tcp_consumer.join()
            self.thread_tcp_consumer = None
        if self.thread_udp_consumer and self.thread_udp_consumer.is_alive():
            self.thread_udp_consumer.join()
            self.thread_udp_consumer = None

    def stop(self) -> None:
        """
        Stops the network services and the client GUI.
        :return: None
        """
        self.stop_services()
        self.top_level_widget.quit()
        LOGGER.info("Client stopped")

    def exit(self) -> None:
        """
        Call back function. Exits the GUI.
        :return: None
        """
        self.update_queue.put(("exit",))

# ------------------------------- logger setup -------------------------------
LOG_LEVEL = logging.DEBUG
LOG_FORMAT = "%(asctime)s [%(filename)s] [%(levelname)s] %(message)s"
LOG_FILE = "./tcp_server.log"
LOGGER = Logger(__file__, LOG_LEVEL, LOG_FORMAT, LOG_FILE, "a").get_logger()
# ------------------------------- client setup -------------------------------
# GUI
CELL_SIZE = 100
BOARD_SIZE = 3
CANVAS_PADDING = 20
FRAMES_PADDING = 5
TEXT_WIDGET_HEIGHT = 12
# Networking
SOCKET_BACK_LOG = 128
MESSAGE_BUFFER_SIZE = 1024
SERVER_TCP_IP = "127.0.0.1"
SERVER_TCP_PORT = 55500
CLIENT_IP = "127.0.0.1"
CLIENT_UDP_PORT = 33335
# 1) If running all servers and clients on different machines within a LAN:
#    Set IP_ONLY_IDENTIFIER = True and CLIENT_TCP_PORT = None.
#    This is the recommended configuration, as it avoids port conflicts by relying solely on the client's IP address
#    for identification.
# 2) If running all servers and clients on localhost (same machine):
#    Set IP_ONLY_IDENTIFIER = False and assign a user-specified value to CLIENT_TCP_PORT.
#    Note: This setup may raise "OSError: [Errno 48] Address already in use" when attempting to initiate a new game
#    after one has ended. This occurs because a recently closed socket may still be in the TIME_WAIT state, preventing
#    the same address from being rebound immediately.
CLIENT_TCP_PORT = 33346  # pass None to port_tcp_client argument in Client, if running across multiple machines

if __name__ == '__main__':
    client = Client(SERVER_TCP_IP, SERVER_TCP_PORT, CLIENT_IP, CLIENT_TCP_PORT, CLIENT_UDP_PORT)
    client.run()
