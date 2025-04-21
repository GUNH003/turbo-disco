import tkinter as tk
import socket
import threading
import queue
import json


class TCPService:
    def __init__(self, serve_ip: str, server_port: int):
        self.socket_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket_tcp.connect((serve_ip, server_port))
        self.buffer_in = queue.Queue()
        self.buffer_out = queue.Queue()
        self.thread_send = threading.Thread(target=self.send_message)
        self.thread_recv = threading.Thread(target=self.recv_message)

    def send_message(self):
        while True:
            message = self.buffer_out.get()
            if message is None:
                break
            try:
                self.socket_tcp.send(message.encode())
            except socket.error as e:
                print(f"failed to send message {message}", e)
                break
            except KeyboardInterrupt:
                print("tcp send service received keyboard interrupt")
                break

    def recv_message(self):
        while True:
            try:
                message_bytes = self.socket_tcp.recv(MESSAGE_BUFFER_SIZE)
                if not message_bytes:
                    print("tcp socket connection closed")
                    break
                self.buffer_in.put(message_bytes.decode())
            except socket.error as e:
                print(f"failed to receive message from server", e)
                break
            except KeyboardInterrupt:
                print("tcp recv service received keyboard interrupt")
                break

    def start(self):
        self.thread_send.start()
        self.thread_recv.start()
        print("TCP service started")

    def recv(self):
        try:
            message = self.buffer_in.get_nowait()
            return message
        except queue.Empty:
            return None

    def send(self, message:str):
        self.buffer_out.put(message)

    def stop(self):
        self.buffer_out.put(None)
        self.socket_tcp.close()
        self.thread_send.join()
        self.thread_recv.join()
        print("TCP service stopped")


class UDPService:
    def __init__(self, client_ip: str, client_port: int, serve_ip: str, server_port: int):
        self.socket_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_udp.bind((client_ip, client_port))
        self.server_ip = serve_ip
        self.server_port = server_port
        self.buffer_in = queue.Queue()
        self.buffer_out = queue.Queue()
        self.thread_send = threading.Thread(target=self.send_message)
        self.thread_recv = threading.Thread(target=self.recv_message)

    def send_message(self):
        while True:
            message = self.buffer_out.get()
            if message is None:
                break
            try:
                self.socket_udp.sendto(message.encode(), (self.server_ip, self.server_port))
            except socket.error as e:
                print(f"Failed to send message {message}: {e}")
                break
            except KeyboardInterrupt:
                print("UDP send service received keyboard interrupt")
                break

    def recv_message(self):
        while True:
            try:
                message_bytes, addr = self.socket_udp.recvfrom(MESSAGE_BUFFER_SIZE)
                if not message_bytes:
                    print("UDP socket connection closed")
                    break
                self.buffer_in.put(message_bytes.decode())
            except socket.error as e:
                print(f"Failed to receive message from server: {e}")
                break
            except KeyboardInterrupt:
                print("UDP recv service received keyboard interrupt")
                break

    def start(self):
        self.thread_send.start()
        self.thread_recv.start()
        print("UDP service started")

    def recv(self):
        try:
            message = self.buffer_in.get_nowait()
            return message
        except queue.Empty:
            return None

    def send(self, message:str):
        self.buffer_out.put(message)

    def stop(self):
        self.buffer_out.put(None)
        self.socket_udp.close()
        self.thread_send.join()
        self.thread_recv.join()
        print("UDP service stopped")



class Client:
    def __init__(self, ip_tcp: str, port_tcp: int):
        # Game state
        self.game_state = 0  # 0: waiting, 1: match running, 2: match ends
        self.player = "X"
        self.board_state = [["" for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        # GUI
        self.top_level_widget = tk.Tk()
        self.top_level_widget.title("Tic Tac Toe")
        self.canvas_game_board = self.create_canvas_game_board()
        self.widget_message_display = self.create_widget_message_display()
        self.entry_message_input = self.create_entry_message_input()
        self.create_button_game_state()
        # Networking TCP
        self.ip_tcp = ip_tcp
        self.port_tcp = port_tcp
        self.tcp_service = None
        # Networking UDP
        self.udp_service = None

    def create_canvas_game_board(self) -> tk.Canvas:
        canvas = tk.Canvas(self.top_level_widget, width=CELL_SIZE * BOARD_SIZE, height=CELL_SIZE * BOARD_SIZE)
        canvas.pack(pady=CANVAS_PADDING)
        for i in range(1, BOARD_SIZE):
            canvas.create_line(i * CELL_SIZE, 0, i * CELL_SIZE, CELL_SIZE * BOARD_SIZE)
            canvas.create_line(0, i * CELL_SIZE, CELL_SIZE * BOARD_SIZE, i * CELL_SIZE)
        canvas.bind("<Button-1>", self.on_click)
        return canvas

    def on_click(self, event):
        if self.game_state == 1:
            col = event.x // CELL_SIZE
            row = event.y // CELL_SIZE
            if 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE:
                if self.board_state[row][col] == "":
                    self.board_state[row][col] = self.player  # update board state
                    self.draw_board()  # draw latest board state
                else:
                    self.display_message("Invalid move!")

    def draw_board(self):
        # Clear canvas
        self.canvas_game_board.delete("all")  # Clear previous drawings
        # Draw grid
        for i in range(1, BOARD_SIZE):
            self.canvas_game_board.create_line(i * CELL_SIZE, 0, i * CELL_SIZE, CELL_SIZE * BOARD_SIZE)
            self.canvas_game_board.create_line(0, i * CELL_SIZE, CELL_SIZE * BOARD_SIZE, i * CELL_SIZE)
        # Draw symbols from board_state
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                symbol = self.board_state[row][col]
                if symbol:
                    x_center = col * CELL_SIZE + CELL_SIZE // 2
                    y_center = row * CELL_SIZE + CELL_SIZE // 2
                    color = "blue" if symbol == "X" else "red"
                    self.canvas_game_board.create_text(x_center, y_center, text=symbol, font=("Arial", 48, "bold"),
                                                       fill=color)
        # Sets next turn, only for testing
        self.player = "O" if self.player == "X" else "X"

    def create_widget_message_display(self) -> tk.Text:
        frame_message_display = tk.Frame(self.top_level_widget)
        frame_message_display.pack(pady=FRAMES_PADDING, fill="both", expand=True)
        widget_text = tk.Text(frame_message_display, height=TEXT_WIDGET_HEIGHT, state="disabled", wrap="word")
        widget_text.pack(side="left", fill="both", expand=True)
        scrollbar_text = tk.Scrollbar(frame_message_display, command=widget_text.yview)
        scrollbar_text.pack(side="right", fill="y")
        widget_text.config(yscrollcommand=scrollbar_text.set)
        return widget_text

    def create_entry_message_input(self) -> tk.Entry:
        frame_message_input = tk.Frame(self.top_level_widget)
        frame_message_input.pack(pady=FRAMES_PADDING, fill="x")
        entry_message_input = tk.Entry(frame_message_input)
        entry_message_input.pack(side="left", fill="x", expand=True, padx=(0, FRAMES_PADDING))
        button_send = tk.Button(frame_message_input, text="Send", command=self.send_message)
        button_send.pack(side="right")
        return entry_message_input

    def create_button_game_state(self) -> None:
        frame_game_sate = tk.Frame(self.top_level_widget)
        frame_game_sate.pack(pady=FRAMES_PADDING, fill="x")
        button_find_new_match = tk.Button(frame_game_sate, text="Find New Match", command=self.find_new_match)
        button_find_new_match.pack(side="left")
        button_exit = tk.Button(frame_game_sate, text="Exit Game", command=self.shutdown)
        button_exit.pack(padx=12, side="left")

    def display_message(self, message) -> None:
        self.widget_message_display.config(state="normal")
        self.widget_message_display.insert("end", message + "\n")
        self.widget_message_display.see("end")
        self.widget_message_display.config(state="disabled")

    def send_message(self) -> str:
        message = self.entry_message_input.get().strip()
        if message:
            self.display_message(f"You: {message}")
            # TODO: Send message to opponent over TCP
            self.entry_message_input.delete(0, tk.END)
        return message

    def find_new_match(self):
        self.tcp_service = TCPService(self.ip_tcp, self.port_tcp)
        self.tcp_service.start()
        try:
            while True:
                message_bytes = self.tcp_service.recv()
                json.JSONDecoder.decode(message_bytes)

        except socket.error as e:
            print()

    def run(self):
        self.top_level_widget.mainloop()

    def shutdown(self):
        if self.tcp_service:
            self.tcp_service.stop()
        if self.udp_service:
            self.udp_service.stop()
        self.top_level_widget.quit()

CELL_SIZE = 100
BOARD_SIZE = 3
CANVAS_PADDING = 20
FRAMES_PADDING = 5
TEXT_WIDGET_HEIGHT = 12
SOCKET_BACK_LOG = 128
MESSAGE_BUFFER_SIZE = 1024


if __name__ == '__main__':
    client = Client("127.0.0.1", 33333)
    client.run()
