import socket
import threading
import json
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
import cv2
import pyaudio
import base64
import time
from PIL import Image
import numpy as np
from mss import mss
import sys
import os
import struct # Added for TCP framing

class VideoLabel(QLabel):
    """Custom label for video display with modern styling"""
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #1a1a2e, stop:1 #16213e);
            color: white;
            border-radius: 8px;
        """)
        self.setScaledContents(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

class ConferenceClient(QMainWindow):
    # Signals for thread-safe GUI updates
    participant_list_signal = pyqtSignal(list)
    video_frame_signal = pyqtSignal(str, object)
    screen_share_start_signal = pyqtSignal(str)
    screen_share_stop_signal = pyqtSignal()
    screen_share_frame_signal = pyqtSignal(str, object)
    chat_message_signal = pyqtSignal(dict)
    
    # New signals for file transfers
    file_offer_signal = pyqtSignal(dict)
    file_chunk_signal = pyqtSignal(dict)
    file_end_signal = pyqtSignal(dict)
    file_accept_signal = pyqtSignal(dict)
    
    def __init__(self, server_host, server_port, username):
        super().__init__()
        self.server_host = server_host
        self.tcp_port = server_port
        self.udp_port = None
        self.username = username
        
        # Sockets
        self.tcp_socket = None
        self.udp_socket = None
        self.running = False
        
        # Media flags
        self.video_enabled = False
        self.audio_enabled = False
        self.screen_share_enabled = False
        self.screen_share_active = False
        self.screen_share_user = None
        
        # Media devices
        self.cap = None
        self.audio_in = None
        self.stream_in = None
        self.audio_out = None
        self.stream_out = None
        
        # Data
        self.participants = {}
        self.current_page = 0
        self.participants_per_page = 4
        self.chat_windows = []
        self.chat_history = []
        self.shared_screen_frame = None
        
        # File transfer tracking
        self.pending_transfers = {} # {filename: filepath}
        self.incoming_files = {}    # {filename: file_handle}
        
        # Video display
        self.video_labels = {}
        self.screen_share_label = None
        self.screen_share_info = None
        self.presenter_overlay = None
        
        # Connect signals
        self.participant_list_signal.connect(self.update_participant_list)
        self.video_frame_signal.connect(self.update_video_frame)
        self.screen_share_start_signal.connect(self.handle_screen_share_start)
        self.screen_share_stop_signal.connect(self.handle_screen_share_stop)
        self.screen_share_frame_signal.connect(self.update_screen_share_display)
        self.chat_message_signal.connect(self.handle_chat_message)
        
        # Connect new file signals
        self.file_offer_signal.connect(self.handle_file_offer)
        self.file_chunk_signal.connect(self.handle_file_chunk)
        self.file_end_signal.connect(self.handle_file_end)
        self.file_accept_signal.connect(self.handle_file_accept)
        
        self.setup_gui()
        
    def setup_gui(self):
        self.setWindowTitle(f"🎥 Conference - {self.username}")
        self.setGeometry(100, 100, 1400, 800)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Left panel with modern styling
        left_widget = QWidget()
        left_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0f0c29, stop:0.5 #302b63, stop:1 #24243e);
                border-radius: 12px;
            }
        """)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(10)
        
        # Video frame with gradient border
        self.video_frame = QWidget()
        self.video_frame.setMinimumSize(720, 720)
        self.video_frame.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a1a2e, stop:1 #16213e);
                border: 3px solid qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
                border-radius: 10px;
            }
        """)
        self.video_layout = QGridLayout(self.video_frame)
        self.video_layout.setSpacing(3)
        self.video_layout.setContentsMargins(5, 5, 5, 5)
        left_layout.addWidget(self.video_frame, stretch=1)
        
        # Navigation with modern buttons
        nav_widget = QWidget()
        nav_widget.setStyleSheet("background: transparent;")
        nav_layout = QHBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        
        self.prev_btn = QPushButton("◄ Previous")
        self.prev_btn.clicked.connect(self.prev_page)
        self.prev_btn.setFixedWidth(120)
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #764ba2, stop:1 #667eea);
            }
            QPushButton:pressed {
                background: #5a4b8a;
            }
        """)
        nav_layout.addWidget(self.prev_btn)
        
        self.page_label = QLabel("Page 1/1")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setStyleSheet("""
            color: white;
            font-size: 14px;
            font-weight: bold;
            background: transparent;
        """)
        nav_layout.addWidget(self.page_label)
        
        self.next_btn = QPushButton("Next ►")
        self.next_btn.clicked.connect(self.next_page)
        self.next_btn.setFixedWidth(120)
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.setStyleSheet(self.prev_btn.styleSheet()) # Reuse style
        nav_layout.addWidget(self.next_btn)
        
        left_layout.addWidget(nav_widget)
        
        # Control buttons with vibrant colors and icons
        control_widget = QWidget()
        control_widget.setStyleSheet("background: transparent;")
        control_layout = QHBoxLayout(control_widget)
        control_layout.setSpacing(8)
        control_layout.setContentsMargins(0, 0, 0, 0)
        
        self.video_btn = QPushButton("📹 Start Video")
        self.video_btn.clicked.connect(self.toggle_video)
        self.video_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.video_btn.setToolTip("Toggle camera on/off")
        self.video_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #56ab2f, stop:1 #a8e063);
                color: white;
                border: none;
                border-radius: 10px;
                padding: 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #a8e063, stop:1 #56ab2f);
            }
            QPushButton:pressed {
                background: #4a9626;
            }
        """)
        control_layout.addWidget(self.video_btn)
        
        self.audio_btn = QPushButton("🎤 Start Audio")
        self.audio_btn.clicked.connect(self.toggle_audio)
        self.audio_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.audio_btn.setToolTip("Toggle microphone on/off")
        self.audio_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2193b0, stop:1 #6dd5ed);
                color: white;
                border: none;
                border-radius: 10px;
                padding: 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #6dd5ed, stop:1 #2193b0);
            }
            QPushButton:pressed {
                background: #1c7d96;
            }
        """)
        control_layout.addWidget(self.audio_btn)
        
        self.screen_btn = QPushButton("🖥️ Share Screen")
        self.screen_btn.clicked.connect(self.toggle_screen_share)
        self.screen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.screen_btn.setToolTip("Share your screen")
        self.screen_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f2994a, stop:1 #f2c94c);
                color: white;
                border: none;
                border-radius: 10px;
                padding: 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f2c94c, stop:1 #f2994a);
            }
            QPushButton:pressed {
                background: #d6843f;
            }
        """)
        control_layout.addWidget(self.screen_btn)
        
        self.chat_btn = QPushButton("💬 Chat")
        self.chat_btn.clicked.connect(self.open_chat)
        self.chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chat_btn.setToolTip("Open chat window")
        self.chat_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #b92b27, stop:1 #1565C0);
                color: white;
                border: none;
                border-radius: 10px;
                padding: 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1565C0, stop:1 #b92b27);
            }
            QPushButton:pressed {
                background: #a02521;
            }
        """)
        control_layout.addWidget(self.chat_btn)
        
        self.file_btn = QPushButton("📁 Share File")
        self.file_btn.clicked.connect(self.open_file_transfer)
        self.file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.file_btn.setToolTip("Send a file to participants")
        self.file_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #614385, stop:1 #516395);
                color: white;
                border: none;
                border-radius: 10px;
                padding: 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #516395, stop:1 #614385);
            }
            QPushButton:pressed {
                background: #523a71;
            }
        """)
        control_layout.addWidget(self.file_btn)
        
        left_layout.addWidget(control_widget)
        
        main_layout.addWidget(left_widget, stretch=4)
        
        # Right panel with modern participant list
        right_widget = QWidget()
        right_widget.setMaximumWidth(250)
        right_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2c3e50, stop:1 #3498db);
                border-radius: 12px;
            }
        """)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 10, 10, 10)
        
        participants_label = QLabel("👥 Participants")
        participants_label.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: white;
            background: transparent;
            padding: 10px;
        """)
        participants_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(participants_label)
        
        self.participant_list = QListWidget()
        self.participant_list.setStyleSheet("""
            QListWidget {
                background: rgba(255, 255, 255, 0.1);
                color: white;
                border: 2px solid rgba(255, 255, 255, 0.2);
                border-radius: 8px;
                font-size: 12px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 8px;
                border-radius: 5px;
                margin: 2px;
            }
            QListWidget::item:hover {
                background: rgba(255, 255, 255, 0.2);
            }
            QListWidget::item:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
            }
        """)
        right_layout.addWidget(self.participant_list)
        
        main_layout.addWidget(right_widget, stretch=1)
        
        # Global stylesheet for the main window
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0f2027, stop:0.5 #203a43, stop:1 #2c5364);
            }
            QToolTip {
                background-color: #2c3e50;
                color: white;
                border: 2px solid #3498db;
                border-radius: 5px;
                padding: 5px;
                font-size: 11px;
            }
        """)
        
    def connect(self):
        try:
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.connect((self.server_host, self.tcp_port))
            
            # First message is simple JSON for registration
            message = json.dumps({'username': self.username})
            self.tcp_socket.send(message.encode('utf-8'))
            
            # All subsequent messages will use framing, starting with this one
            msg = self.receive_tcp_message()
            if not msg or msg.get('type') != 'connection_info':
                raise Exception("Failed to get connection info from server")
                
            self.udp_port = msg.get('udp_port')
            
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2097152)
            self.udp_socket.bind(('', 0))
            
            # Send UDP registration packet (as JSON)
            register_msg = json.dumps({'type': 'register', 'username': self.username})
            self.udp_socket.sendto(register_msg.encode('utf-8'), (self.server_host, self.udp_port))
            
            self.running = True
            
            self.audio_out = None
            self.stream_out = None
            
            tcp_thread = threading.Thread(target=self.receive_tcp)
            tcp_thread.daemon = True
            tcp_thread.start()
            
            udp_thread = threading.Thread(target=self.receive_udp)
            udp_thread.daemon = True
            udp_thread.start()
            
            return True
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", f"Could not connect:\n{e}")
            return False

    def init_audio_output(self):
        """Initialize audio playback (PyAudio) on-demand."""
        if self.stream_out and self.audio_out:
            return True
        try:
            self.audio_out = pyaudio.PyAudio()
            self.stream_out = self.audio_out.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                output=True,
                frames_per_buffer=2048
            )
            return True
        except Exception as e:
            print(f"Audio output init error: {e}")
            try:
                if self.audio_out:
                    self.audio_out.terminate()
            except: pass
            self.audio_out = None
            self.stream_out = None
            return False

    # --- New TCP Helper Functions ---
    def send_tcp(self, message_dict):
        """Encodes and sends a JSON message with a 4-byte length prefix."""
        if not self.running or not self.tcp_socket:
            return
        try:
            message_json = json.dumps(message_dict).encode('utf-8')
            message_length = struct.pack('!I', len(message_json)) # 4-byte network-order unsigned int
            self.tcp_socket.sendall(message_length + message_json)
        except Exception as e:
            print(f"Error sending TCP message: {e}")
            self.running = False # Assume connection is dead

    def receive_tcp_message(self):
        """Receives and decodes one complete JSON message."""
        try:
            # Read the 4-byte length prefix
            raw_length = self.tcp_socket.recv(4)
            if not raw_length:
                return None # Connection closed
            
            message_length = struct.unpack('!I', raw_length)[0]
            
            # Read the full message
            message_data = b""
            while len(message_data) < message_length:
                chunk = self.tcp_socket.recv(message_length - len(message_data))
                if not chunk:
                    return None # Connection closed
                message_data += chunk
                
            return json.loads(message_data.decode('utf-8'))
        except Exception as e:
            print(f"Error receiving TCP message: {e}")
            self.running = False
            return None
    # --- End TCP Helper Functions ---

    def receive_tcp(self):
        while self.running:
            try:
                message = self.receive_tcp_message()
                if message is None:
                    break # Server disconnected
                
                msg_type = message.get('type')
                
                if msg_type == 'participant_list':
                    self.participant_list_signal.emit(message['participants'])
                elif msg_type == 'chat':
                    self.chat_message_signal.emit(message)
                
                # Handle file transfer messages
                elif msg_type == 'file_offer':
                    self.file_offer_signal.emit(message)
                elif msg_type == 'file_accept':
                    self.file_accept_signal.emit(message)
                elif msg_type == 'file_chunk':
                    self.file_chunk_signal.emit(message)
                elif msg_type == 'file_end':
                    self.file_end_signal.emit(message)
                elif msg_type == 'pong':
                    pass # Keep-alive response
                        
            except Exception as e:
                if self.running:
                    print(f"TCP error: {e}")
                break
        
        self.running = False
        print("TCP connection lost.")

    def receive_udp(self):
        while self.running:
            try:
                data, addr = self.udp_socket.recvfrom(131072)
                
                # Try to parse as JSON first (for screen share control)
                try:
                    message = json.loads(data.decode('utf-8'))
                    msg_type = message.get('type')
                    username = message.get('username')
                    
                    if msg_type == 'screen_share':
                        action = message.get('action')
                        if action == 'start' and username != self.username:
                            self.screen_share_start_signal.emit(username)
                        elif action == 'stop':
                            self.screen_share_stop_signal.emit()
                    continue

                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Not JSON, so it's a binary media packet. This is normal.
                    pass

                # Handle binary media packets
                packet_type = data[0]
                username_len = data[1]
                username_end_idx = 2 + username_len
                username = data[2:username_end_idx].decode('utf-8')
                payload = data[username_end_idx:]

                if packet_type == 1: # Video
                    self.handle_video_frame(username, payload)
                elif packet_type == 2: # Audio
                    if username != self.username:
                        self.handle_audio_frame(payload)
                elif packet_type == 3: # Screen Share Frame
                    self.handle_screen_share_frame(username, payload)
                    
            except Exception as e:
                if self.running:
                    print(f"UDP error: {e}")
    
    def handle_video_frame(self, username, payload):
        if username and username in self.participants:
            try:
                frame = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    self.participants[username]['frame'] = frame
                    self.video_frame_signal.emit(username, frame)
            except Exception as e:
                print(f"Video frame error: {e}")
            
    def handle_audio_frame(self, payload):
        try:
            if not self.stream_out:
                ok = self.init_audio_output()
                if not ok:
                    return # Can't play audio

            if self.stream_out and self.stream_out.is_active():
                self.stream_out.write(payload)
        except Exception as e:
            # Playback error, try to reset stream
            print(f"Audio playback error: {e}")
            try:
                self.stream_out.stop_stream()
                self.stream_out.close()
            except: pass
            try:
                if self.audio_out:
                    self.audio_out.terminate()
            except: pass
            self.stream_out = None
            self.audio_out = None
            
    def handle_screen_share_frame(self, username, payload):
        if not self.screen_share_active or self.screen_share_user != username:
            return
        try:
            frame = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
            if frame is not None:
                self.shared_screen_frame = frame
                if self.current_page == 0:
                    self.screen_share_frame_signal.emit(username, frame)
        except Exception as e:
            pass
    
    # --- GUI Update Functions (Mostly Unchanged) ---
    
    def update_participant_list(self, participants):
        # (This function is unchanged from your original code)
        for p in participants:
            username = p['username']
            if username not in self.participants:
                self.participants[username] = {
                    'video': p['video'],
                    'audio': p['audio'],
                    'frame': None
                }
            else:
                self.participants[username]['video'] = p['video']
                self.participants[username]['audio'] = p['audio']
        
        current_usernames = [p['username'] for p in participants]
        for username in list(self.participants.keys()):
            if username not in current_usernames:
                del self.participants[username]
        
        self.participant_list.clear()
        for username in self.participants.keys():
            p_data = self.participants[username]
            status = ""
            if p_data['video']:
                status += "📹 "
            if p_data['audio']:
                status += "🎤 "
            self.participant_list.addItem(f"{username} {status}")
        
        if not (self.screen_share_active and self.current_page == 0):
            self.update_video_display()
    
    def update_video_display(self):
        # (This function is unchanged from your original code)
        while self.video_layout.count():
            item = self.video_layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()
        
        self.video_labels.clear()
        QApplication.processEvents()
        
        participant_list = list(self.participants.keys())
        total_participants = len(participant_list)
        
        if self.screen_share_active:
            if self.current_page == 0:
                return
            participant_page = self.current_page - 1
            total_pages = 1 + max(1, (total_participants - 1) // self.participants_per_page + 1)
        else:
            participant_page = self.current_page
            total_pages = max(1, (total_participants - 1) // self.participants_per_page + 1)
        
        if self.current_page >= total_pages:
            self.current_page = max(0, total_pages - 1)
            participant_page = self.current_page if not self.screen_share_active else self.current_page - 1
        
        start_idx = participant_page * self.participants_per_page
        end_idx = start_idx + self.participants_per_page
        page_participants = participant_list[start_idx:end_idx]
        
        num_participants = len(page_participants)
        if num_participants == 0:
            self.page_label.setText(f"Page {self.current_page + 1}/{total_pages}")
            return
        
        if num_participants == 1: rows, cols = 1, 1
        elif num_participants == 2: rows, cols = 1, 2
        else: rows, cols = 2, 2
        
        for i in range(rows): self.video_layout.setRowStretch(i, 1)
        for i in range(cols): self.video_layout.setColumnStretch(i, 1)
        
        for idx, username in enumerate(page_participants):
            row = idx // cols
            col = idx % cols
            
            cell_widget = QWidget()
            cell_widget.setStyleSheet("""
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a1a2e, stop:1 #16213e);
                border: 2px solid #667eea;
                border-radius: 8px;
            """)
            cell_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            
            cell_layout = QVBoxLayout(cell_widget)
            cell_layout.setContentsMargins(2, 2, 2, 2)
            cell_layout.setSpacing(0)
            
            video_label = VideoLabel()
            video_label.setText(username)
            video_label.setStyleSheet("""
                font-size: 18px;
                color: #ffffff;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a1a2e, stop:1 #16213e);
            """)
            cell_layout.addWidget(video_label, stretch=1)
            
            info_widget = QWidget()
            info_widget.setStyleSheet("""
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
                border-radius: 5px;
            """)
            info_widget.setFixedHeight(35)
            info_layout = QHBoxLayout(info_widget)
            info_layout.setContentsMargins(8, 2, 8, 2)
            
            name_label = QLabel(username)
            name_label.setStyleSheet("color: white; font-weight: bold; font-size: 11px; background: transparent;")
            info_layout.addWidget(name_label)
            
            participant_data = self.participants[username]
            mic_status = "🎤" if participant_data['audio'] else "🔇"
            mic_label = QLabel(mic_status)
            mic_label.setStyleSheet("font-size: 14px; background: transparent;")
            info_layout.addWidget(mic_label)
            
            info_layout.addStretch()
            cell_layout.addWidget(info_widget)
            
            self.video_layout.addWidget(cell_widget, row, col)
            
            self.video_labels[username] = {
                'video_label': video_label,
                'name_label': name_label,
                'mic_label': mic_label,
                'cell_widget': cell_widget
            }
            
            if participant_data['frame'] is not None:
                self.update_video_frame(username, participant_data['frame'])
        
        self.page_label.setText(f"Page {self.current_page + 1}/{total_pages}")
    
    def update_video_frame(self, username, frame):
        # (This function is unchanged from your original code)
        if username in self.video_labels:
            try:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                height, width, channel = frame_rgb.shape
                bytes_per_line = 3 * width
                q_image = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
                
                video_label = self.video_labels[username]['video_label']
                cell_widget = self.video_labels[username]['cell_widget']
                
                cell_size = cell_widget.size()
                available_width = max(cell_size.width() - 10, 100)
                available_height = max(cell_size.height() - 40, 100)
                
                pixmap = QPixmap.fromImage(q_image)
                scaled_pixmap = pixmap.scaled(
                    available_width,
                    available_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                
                video_label.setPixmap(scaled_pixmap)
                video_label.setText("")
            except Exception as e:
                pass
    
    def display_screen_share(self):
        # (This function is unchanged from your original code)
        while self.video_layout.count():
            item = self.video_layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()
        
        self.video_labels.clear()
        QApplication.processEvents()
        
        main_container = QWidget()
        main_container.setStyleSheet("background-color: black;")
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.screen_share_info = QLabel(f"🖥️ Screen shared by: {self.screen_share_user}")
        self.screen_share_info.setStyleSheet("color: white; background-color: #1a1a1a; font-size: 14px; font-weight: bold; padding: 10px;")
        self.screen_share_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen_share_info.setFixedHeight(40)
        main_layout.addWidget(self.screen_share_info)
        
        screen_container = QWidget()
        screen_container.setStyleSheet("background-color: black;")
        screen_container_layout = QStackedLayout(screen_container)
        
        self.screen_share_label = VideoLabel()
        self.screen_share_label.setText("Loading screen share...")
        self.screen_share_label.setStyleSheet("color: gray; font-size: 16px;")
        screen_container_layout.addWidget(self.screen_share_label)
        
        if self.screen_share_user in self.participants:
            overlay_frame = QFrame(screen_container)
            overlay_frame.setStyleSheet("background-color: rgba(0, 0, 0, 180); border: 2px solid #4CAF50; border-radius: 5px;")
            overlay_frame.setFixedSize(200, 150)
            overlay_frame.move(10, 10)
            
            overlay_layout = QVBoxLayout(overlay_frame)
            overlay_layout.setContentsMargins(2, 2, 2, 2)
            overlay_layout.setSpacing(0)
            
            self.presenter_overlay = VideoLabel()
            self.presenter_overlay.setText(self.screen_share_user)
            self.presenter_overlay.setStyleSheet("font-size: 12px; color: white;")
            overlay_layout.addWidget(self.presenter_overlay)
            
            presenter_name = QLabel(self.screen_share_user)
            presenter_name.setStyleSheet("color: white; font-size: 9px; font-weight: bold; background-color: #1a1a1a; padding: 2px;")
            presenter_name.setAlignment(Qt.AlignCenter)
            overlay_layout.addWidget(presenter_name)
            
            def position_overlay():
                if screen_container.isVisible():
                    x = screen_container.width() - overlay_frame.width() - 10
                    y = screen_container.height() - overlay_frame.height() - 10
                    overlay_frame.move(max(10, x), max(10, y))
            
            screen_container.resizeEvent = lambda event: position_overlay()
            overlay_frame.raise_()
        
        main_layout.addWidget(screen_container, stretch=1)
        
        self.video_layout.addWidget(main_container, 0, 0)
        self.video_layout.setRowStretch(0, 1)
        self.video_layout.setColumnStretch(0, 1)
        
        if self.shared_screen_frame is not None:
            self.update_screen_share_display(self.screen_share_user, self.shared_screen_frame)
        
        if self.screen_share_user in self.participants and self.participants[self.screen_share_user]['frame'] is not None:
            self.update_presenter_overlay(self.participants[self.screen_share_user]['frame'])
        
        participant_list = list(self.participants.keys())
        total_pages = 1 + max(1, (len(participant_list) - 1) // self.participants_per_page + 1)
        self.page_label.setText(f"Page 1/{total_pages} - Screen Share")
    
    def update_screen_share_display(self, username, frame):
        # (This function is unchanged from your original code)
        if not self.screen_share_label or username != self.screen_share_user:
            return
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame_rgb.shape
            bytes_per_line = 3 * width
            q_image = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
            
            pixmap = QPixmap.fromImage(q_image)
            scaled_pixmap = pixmap.scaled(self.screen_share_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.screen_share_label.setPixmap(scaled_pixmap)
            self.screen_share_label.setText("")
        except Exception as e:
            pass
    
    def update_presenter_overlay(self, frame):
        # (This function is unchanged from your original code)
        if not self.presenter_overlay: return
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame_rgb.shape
            bytes_per_line = 3 * width
            q_image = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
            
            pixmap = QPixmap.fromImage(q_image)
            scaled_pixmap = pixmap.scaled(196, 130, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.presenter_overlay.setPixmap(scaled_pixmap)
            self.presenter_overlay.setText("")
        except Exception as e:
            pass
    
    def hide_screen_share(self):
        # (This function is unchanged from your original code)
        self.screen_share_label = None
        self.screen_share_info = None
        self.presenter_overlay = None
        self.update_video_display()
    
    def handle_screen_share_start(self, username):
        # (This function is unchanged from your original code)
        self.screen_share_active = True
        self.screen_share_user = username
        self.current_page = 0
        self.shared_screen_frame = None
        self.display_screen_share()
    
    def handle_screen_share_stop(self):
        # (This function is unchanged from your original code)
        self.screen_share_active = False
        self.screen_share_user = None
        self.shared_screen_frame = None
        self.current_page = 0
        self.hide_screen_share()
    
    def prev_page(self):
        # (This function is unchanged from your original code)
        if self.current_page > 0:
            self.current_page -= 1
            if self.screen_share_active and self.current_page == 0:
                self.display_screen_share()
            else:
                self.update_video_display()
    
    def next_page(self):
        # (This function is unchanged from your original code)
        if self.screen_share_active:
            total_pages = 1 + max(1, (len(self.participants) - 1) // self.participants_per_page + 1)
        else:
            total_pages = max(1, (len(self.participants) - 1) // self.participants_per_page + 1)
            
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.update_video_display()
    
    # --- Media Toggles (Updated) ---
    
    def toggle_video(self):
        if not self.video_enabled:
            try:
                # (Platform-specific logic unchanged)
                import platform
                if platform.system() == "Linux":
                    self.cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
                    if not self.cap.isOpened():
                        self.cap = cv2.VideoCapture(0)
                else:
                    self.cap = cv2.VideoCapture(0)
                    if not self.cap.isOpened():
                        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                
                if not self.cap.isOpened():
                    raise Exception("Could not open camera")
                
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                
                self.video_enabled = True
                self.video_btn.setText("📹 Stop Video")
                self.video_btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #eb3349, stop:1 #f45c43);
                        color: white; border: none; border-radius: 10px;
                        padding: 12px; font-weight: bold; font-size: 11px;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #f45c43, stop:1 #eb3349);
                    }
                    QPushButton:pressed { background: #d32f2f; }
                """)
                
                if self.username not in self.participants:
                    self.participants[self.username] = {'video': True, 'audio': self.audio_enabled, 'frame': None}
                else:
                    self.participants[self.username]['video'] = True
                
                self.send_tcp({'type': 'status_update', 'video': True})
                
                video_thread = threading.Thread(target=self.send_video)
                video_thread.daemon = True
                video_thread.start()
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not start video:\n{e}")
        else:
            self.video_enabled = False
            self.video_btn.setText("📹 Start Video")
            self.video_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #56ab2f, stop:1 #a8e063);
                    color: white; border: none; border-radius: 10px;
                    padding: 12px; font-weight: bold; font-size: 11px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #a8e063, stop:1 #56ab2f);
                }
                QPushButton:pressed { background: #4a9626; }
            """)
            
            if self.cap:
                try: self.cap.release()
                except: pass
                self.cap = None
            
            if self.username in self.participants:
                self.participants[self.username]['video'] = False
                self.participants[self.username]['frame'] = None
            
            self.send_tcp({'type': 'status_update', 'video': False})
    
    def toggle_audio(self):
        """Robust audio toggle for Linux compatibility."""
        if not self.audio_enabled:
            try:
                self.audio_in = pyaudio.PyAudio()
                self.stream_in = None
                
                # Try default device first
                try:
                    self.stream_in = self.audio_in.open(
                        format=pyaudio.paInt16, channels=1, rate=16000,
                        input=True, frames_per_buffer=2048
                    )
                    print("Using default audio device.")
                except Exception as e:
                    print(f"Default audio device failed: {e}. Scanning devices...")
                    # If default fails, scan for a working device
                    device_count = self.audio_in.get_device_count()
                    for i in range(device_count):
                        try:
                            info = self.audio_in.get_device_info_by_index(i)
                            if info['maxInputChannels'] > 0:
                                # Found a potential input device
                                print(f"Trying device {i}: {info['name']}...")
                                self.stream_in = self.audio_in.open(
                                    format=pyaudio.paInt16, channels=1, rate=16000,
                                    input=True, frames_per_buffer=2048,
                                    input_device_index=i
                                )
                                print(f"Successfully opened audio device {i}")
                                break # Success
                        except Exception as e:
                            print(f"Device {i} failed: {e}")
                            continue
                    
                    if not self.stream_in:
                        raise Exception("No working audio input device found")
                
                self.audio_enabled = True
                self.audio_btn.setText("🎤 Stop Audio")
                self.audio_btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #eb3349, stop:1 #f45c43);
                        color: white; border: none; border-radius: 10px;
                        padding: 12px; font-weight: bold; font-size: 11px;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #f45c43, stop:1 #eb3349);
                    }
                    QPushButton:pressed { background: #d32f2f; }
                """)
                
                if self.username not in self.participants:
                    self.participants[self.username] = {'video': self.video_enabled, 'audio': True, 'frame': None}
                else:
                    self.participants[self.username]['audio'] = True
                
                self.send_tcp({'type': 'status_update', 'audio': True})
                
                audio_thread = threading.Thread(target=self.send_audio)
                audio_thread.daemon = True
                audio_thread.start()
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not start audio:\n{e}")
                if self.audio_in:
                    try: self.audio_in.terminate()
                    except: pass
                self.audio_in = None
                self.stream_in = None
        else:
            self.audio_enabled = False
            self.audio_btn.setText("🎤 Start Audio")
            self.audio_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #2193b0, stop:1 #6dd5ed);
                    color: white; border: none; border-radius: 10px;
                    padding: 12px; font-weight: bold; font-size: 11px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #6dd5ed, stop:1 #2193b0);
                }
                QPushButton:pressed { background: #1c7d96; }
            """)
            if self.stream_in:
                try:
                    self.stream_in.stop_stream()
                    self.stream_in.close()
                except: pass
            if self.audio_in:
                try: self.audio_in.terminate()
                except: pass
            
            if self.username in self.participants:
                self.participants[self.username]['audio'] = False
            
            self.send_tcp({'type': 'status_update', 'audio': False})
    
    def toggle_screen_share(self):
        if not self.screen_share_enabled:
            self.screen_share_enabled = True
            self.screen_btn.setText("🖥️ Stop Sharing")
            self.screen_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #eb3349, stop:1 #f45c43);
                    color: white; border: none; border-radius: 10px;
                    padding: 12px; font-weight: bold; font-size: 11px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #f45c43, stop:1 #eb3349);
                }
                QPushButton:pressed { background: #d32f2f; }
            """)
            
            self.screen_share_active = True
            self.screen_share_user = self.username
            self.current_page = 0
            self.display_screen_share()
            
            # Send control message as JSON
            message = json.dumps({'type': 'screen_share', 'action': 'start', 'username': self.username})
            self.udp_socket.sendto(message.encode('utf-8'), (self.server_host, self.udp_port))
            
            screen_thread = threading.Thread(target=self.send_screen_share)
            screen_thread.daemon = True
            screen_thread.start()
        else:
            self.screen_share_enabled = False
            self.screen_btn.setText("🖥️ Share Screen")
            self.screen_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #f2994a, stop:1 #f2c94c);
                    color: white; border: none; border-radius: 10px;
                    padding: 12px; font-weight: bold; font-size: 11px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #f2c94c, stop:1 #f2994a);
                }
                QPushButton:pressed { background: #d6843f; }
            """)
            
            # Send control message as JSON
            message = json.dumps({'type': 'screen_share', 'action': 'stop', 'username': self.username})
            self.udp_socket.sendto(message.encode('utf-8'), (self.server_host, self.udp_port))
            
            self.screen_share_active = False
            self.screen_share_user = None
            self.shared_screen_frame = None
            self.current_page = 0
            self.hide_screen_share()
    
    # --- Media Senders (Updated to Binary) ---

    def send_video(self):
        username_bytes = self.username.encode('utf-8')
        username_len = len(username_bytes)
        if username_len > 255: # Sanity check
            print("Username too long for packet header")
            self.toggle_video()
            return
            
        # Pre-pack header info
        # Packet: [TYPE=1] [USERNAME_LEN] [USERNAME] [PAYLOAD]
        header_prefix = struct.pack('!BB', 1, username_len) + username_bytes

        while self.video_enabled and self.running:
            try:
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    time.sleep(0.1)
                    continue
                
                frame_resized = cv2.resize(frame, (320, 240))
                self.participants[self.username]['frame'] = frame_resized
                
                _, buffer = cv2.imencode('.jpg', frame_resized, [cv2.IMWRITE_JPEG_QUALITY, 50])
                frame_data = buffer.tobytes()
                
                packet = header_prefix + frame_data
                
                self.udp_socket.sendto(packet, (self.server_host, self.udp_port))
                self.video_frame_signal.emit(self.username, frame_resized)
                
                time.sleep(0.033) # ~30 FPS
            except Exception as e:
                print(f"Send video error: {e}")
                time.sleep(0.1)
    
    def send_audio(self):
        username_bytes = self.username.encode('utf-8')
        username_len = len(username_bytes)
        if username_len > 255:
            print("Username too long for packet header")
            self.toggle_audio()
            return

        # Packet: [TYPE=2] [USERNAME_LEN] [USERNAME] [PAYLOAD]
        header_prefix = struct.pack('!BB', 2, username_len) + username_bytes

        while self.audio_enabled and self.running:
            try:
                data = self.stream_in.read(2048, exception_on_overflow=False)
                packet = header_prefix + data
                self.udp_socket.sendto(packet, (self.server_host, self.udp_port))
            except Exception as e:
                print(f"Audio capture/send error: {e}")
                # Post a function call to the main thread to safely stop audio
                QTimer.singleShot(0, self.toggle_audio)
                break
    
    def send_screen_share(self):
        username_bytes = self.username.encode('utf-8')
        username_len = len(username_bytes)
        if username_len > 255:
            print("Username too long for packet header")
            self.toggle_screen_share()
            return
            
        # Packet: [TYPE=3] [USERNAME_LEN] [USERNAME] [PAYLOAD]
        header_prefix = struct.pack('!BB', 3, username_len) + username_bytes

        try:
            import platform
            system = platform.system()
            
            if system == "Linux":
                app = QApplication.instance() or QApplication(sys.argv)
                screen = app.primaryScreen()
                
                while self.screen_share_enabled and self.running:
                    try:
                        pixmap = screen.grabWindow(0)
                        qimage = pixmap.toImage()
                        width, height = qimage.width(), qimage.height()
                        
                        ptr = qimage.bits()
                        ptr.setsize(qimage.byteCount())
                        arr = np.array(ptr).reshape(height, width, 4)
                        
                        frame = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
                        frame_resized = cv2.resize(frame, (800, 450))
                        
                        self.shared_screen_frame = frame_resized.copy()
                        if self.current_page == 0:
                            self.screen_share_frame_signal.emit(self.username, frame_resized.copy())
                        
                        _, buffer = cv2.imencode('.jpg', frame_resized, [cv2.IMWRITE_JPEG_QUALITY, 30])
                        frame_data = buffer.tobytes()
                        
                        packet = header_prefix + frame_data
                        if len(packet) < 65500: # Avoid oversized UDP packets
                            self.udp_socket.sendto(packet, (self.server_host, self.udp_port))
                        
                        time.sleep(0.1) # ~10 FPS for screen share
                    except Exception as e:
                        print(f"Linux screen error: {e}")
                        break
            else:
                # Windows/Mac with mss
                with mss() as sct:
                    monitor = sct.monitors[1]
                    while self.screen_share_enabled and self.running:
                        try:
                            screenshot = sct.grab(monitor)
                            frame = np.array(screenshot)
                            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                            frame_resized = cv2.resize(frame_bgr, (800, 600))
                            
                            self.shared_screen_frame = frame_resized.copy()
                            if self.current_page == 0:
                                self.screen_share_frame_signal.emit(self.username, frame_resized.copy())
                            
                            _, buffer = cv2.imencode('.jpg', frame_resized, [cv2.IMWRITE_JPEG_QUALITY, 25])
                            frame_data = buffer.tobytes()
                            
                            packet = header_prefix + frame_data
                            if len(packet) < 65500: # Avoid oversized UDP packets
                                self.udp_socket.sendto(packet, (self.server_host, self.udp_port))
                            
                            time.sleep(0.1)
                        except Exception as e:
                            print(f"Screen error: {e}")
                            break
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Screen share failed:\n{e}")
            self.screen_share_enabled = False
    
    # --- Chat and File Transfer (Updated) ---
    
    def open_chat(self):
        # (This function is unchanged from your original code, but uses send_tcp)
        chat_dialog = QDialog(self)
        chat_dialog.setWindowTitle("💬 Chat")
        chat_dialog.setGeometry(200, 200, 500, 600)
        chat_dialog.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0f0c29, stop:0.5 #302b63, stop:1 #24243e);
            }
        """)
        
        layout = QVBoxLayout(chat_dialog)
        
        recipient_label = QLabel("📤 Send to:")
        recipient_label.setStyleSheet("font-weight: bold; font-size: 12px; color: white;")
        layout.addWidget(recipient_label)
        
        recipient_group = QWidget()
        recipient_group.setStyleSheet("background: transparent;")
        recipient_layout = QVBoxLayout(recipient_group)
        recipient_layout.setContentsMargins(20, 0, 0, 0)
        
        button_group = QButtonGroup(chat_dialog)
        
        everyone_radio = QRadioButton("👥 Everyone")
        everyone_radio.setChecked(True)
        everyone_radio.setStyleSheet("color: white; font-size: 11px;")
        button_group.addButton(everyone_radio)
        recipient_layout.addWidget(everyone_radio)
        
        recipient_buttons = {'everyone': everyone_radio}
        
        for username in self.participants.keys():
            if username != self.username:
                radio = QRadioButton(f"👤 {username}")
                radio.setStyleSheet("color: white; font-size: 11px;")
                button_group.addButton(radio)
                recipient_layout.addWidget(radio)
                recipient_buttons[username] = radio
        
        layout.addWidget(recipient_group)
        
        chat_display = QTextEdit()
        chat_display.setReadOnly(True)
        chat_display.setStyleSheet("""
            QTextEdit {
                background: rgba(255, 255, 255, 0.1);
                color: white;
                border: 2px solid rgba(102, 126, 234, 0.5);
                border-radius: 8px;
                padding: 10px;
                font-size: 11px;
            }
        """)
        
        for msg in self.chat_history:
            chat_display.append(msg.strip())
        
        layout.addWidget(chat_display)
        
        message_frame = QWidget()
        message_frame.setStyleSheet("background: transparent;")
        message_layout = QHBoxLayout(message_frame)
        
        message_entry = QLineEdit()
        message_entry.setPlaceholderText("Type your message...")
        message_entry.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.15);
                color: white;
                border: 2px solid rgba(102, 126, 234, 0.5);
                border-radius: 8px;
                padding: 10px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border: 2px solid #667eea;
            }
        """)
        message_layout.addWidget(message_entry)
        
        def send_chat():
            msg = message_entry.text().strip()
            if msg:
                recipient = None
                for name, radio in recipient_buttons.items():
                    if radio.isChecked():
                        recipient = name
                        break
                
                if recipient:
                    self.send_tcp({
                        'type': 'chat',
                        'recipient': recipient,
                        'message': msg
                    })
                    message_entry.clear()
        
        send_btn = QPushButton("📤 Send")
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.setStyleSheet(self.prev_btn.styleSheet()) # Reuse style
        send_btn.clicked.connect(send_chat)
        message_layout.addWidget(send_btn)
        
        message_entry.returnPressed.connect(send_chat)
        layout.addWidget(message_frame)
        
        self.chat_windows.append(chat_display)
        chat_dialog.finished.connect(lambda: self.chat_windows.remove(chat_display) if chat_display in self.chat_windows else None)
        chat_dialog.exec()
    
    def handle_chat_message(self, message):
        # (This function is unchanged from your original code)
        from_user = message.get('from', 'Unknown')
        msg_text = message.get('message', '')
        recipient = message.get('recipient', 'everyone')
        timestamp = time.strftime('%H:%M:%S', time.localtime(message.get('timestamp', time.time())))
        
        if recipient == 'everyone':
            chat_msg = f"[{timestamp}] {from_user}: {msg_text}"
        else:
            if from_user == self.username:
                chat_msg = f"[{timestamp}] You (to {recipient}): {msg_text}"
            else:
                chat_msg = f"[{timestamp}] {from_user} (private): {msg_text}"
        
        self.chat_history.append(chat_msg + "\n")
        
        for chat_display in self.chat_windows:
            try:
                chat_display.append(chat_msg)
            except:
                pass
    
    def open_file_transfer(self):
        """Sends a file *offer* instead of the whole file."""
        filepath, _ = QFileDialog.getOpenFileName(self, "Select file to send")
        if not filepath:
            return
        
        try:
            filename = os.path.basename(filepath)
            filesize = os.path.getsize(filepath)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not read file: {e}")
            return
            
        file_dialog = QDialog(self)
        file_dialog.setWindowTitle("Send File")
        layout = QVBoxLayout(file_dialog)
        layout.addWidget(QLabel(f"File: {filename} ({filesize // 1024} KB)"))
        layout.addWidget(QLabel("Send to:"))
        
        button_group = QButtonGroup(file_dialog)
        everyone_radio = QRadioButton("Everyone")
        everyone_radio.setChecked(True)
        button_group.addButton(everyone_radio)
        layout.addWidget(everyone_radio)
        
        recipient_buttons = {'everyone': everyone_radio}
        for username in self.participants.keys():
            if username != self.username:
                radio = QRadioButton(username)
                button_group.addButton(radio)
                layout.addWidget(radio)
                recipient_buttons[username] = radio
        
        def send_offer():
            recipient = None
            for name, radio in recipient_buttons.items():
                if radio.isChecked():
                    recipient = name
                    break
            
            if recipient:
                # Store for when we get 'file_accept'
                self.pending_transfers[filename] = filepath
                
                # Send the OFFER
                self.send_tcp({
                    'type': 'file_offer',
                    'recipient': recipient,
                    'filename': filename,
                    'size': filesize
                })
                QMessageBox.information(self, "File Transfer", "File offer has been sent.")
                file_dialog.accept()
        
        send_btn = QPushButton("Send Offer")
        send_btn.clicked.connect(send_offer)
        layout.addWidget(send_btn)
        file_dialog.exec()

    @pyqtSlot(dict)
    def handle_file_offer(self, message):
        """Handles an incoming file offer."""
        from_user = message.get('from', 'Unknown')
        filename = message.get('filename', 'file')
        filesize = message.get('size', 0)
        
        reply = QMessageBox.question(self, "File Transfer",
            f"Accept file '{filename}' ({filesize // 1024} KB) from {from_user}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
        if reply == QMessageBox.StandardButton.Yes:
            save_path, _ = QFileDialog.getSaveFileName(self, "Save file", filename)
            if save_path:
                try:
                    f = open(save_path, 'wb')
                    self.incoming_files[filename] = f
                    
                    self.send_tcp({
                        'type': 'file_accept',
                        'recipient': from_user, # Send back to original sender
                        'filename': filename
                    })
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Could not open file for writing: {e}")
            else:
                # User cancelled save dialog, implicitly reject
                pass
    
    @pyqtSlot(dict)
    def handle_file_accept(self, message):
        """Called when a recipient accepts our file offer. Starts the upload thread."""
        filename = message.get('filename')
        recipient = message.get('from') # The user who accepted
        
        filepath = self.pending_transfers.get(filename)
        
        if filepath and recipient:
            print(f"User {recipient} accepted file {filename}. Starting upload thread...")
            # Start the transfer in a new thread to avoid blocking the GUI
            transfer_thread = threading.Thread(
                target=self.stream_file_chunks,
                args=(filepath, recipient, filename)
            )
            transfer_thread.daemon = True
            transfer_thread.start()
        else:
            print(f"Could not find pending transfer for {filename}")

    def stream_file_chunks(self, filepath, recipient, filename):
        """Reads file in chunks and sends them. Runs in a thread."""
        try:
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(32768) # 32KB chunks
                    if not chunk:
                        break # End of file
                    
                    self.send_tcp({
                        'type': 'file_chunk',
                        'recipient': recipient,
                        'filename': filename,
                        'data': base64.b64encode(chunk).decode('utf-8')
                    })
                    time.sleep(0.01) # Small sleep to yield
            
            # Send end message
            self.send_tcp({
                'type': 'file_end',
                'recipient': recipient,
                'filename': filename
            })
            print(f"Finished sending {filename} to {recipient}")
            
        except Exception as e:
            print(f"Error during file stream: {e}")
        finally:
            if filename in self.pending_transfers:
                del self.pending_transfers[filename]

    @pyqtSlot(dict)
    def handle_file_chunk(self, message):
        """Receives a file chunk and writes it to disk."""
        filename = message.get('filename')
        if filename in self.incoming_files:
            try:
                file_data = base64.b64decode(message['data'])
                self.incoming_files[filename].write(file_data)
            except Exception as e:
                print(f"Error writing file chunk: {e}")
                self.incoming_files[filename].close()
                del self.incoming_files[filename]

    @pyqtSlot(dict)
    def handle_file_end(self, message):
        """Finishes a file transfer."""
        filename = message.get('filename')
        if filename in self.incoming_files:
            self.incoming_files[filename].close()
            del self.incoming_files[filename]
            QMessageBox.information(self, "File Transfer", f"File '{filename}' received successfully!")
            
    def closeEvent(self, event):
        # (This function is unchanged from your original code)
        self.running = False
        
        if self.cap: self.cap.release()
        
        if self.stream_in:
            try:
                self.stream_in.stop_stream()
                self.stream_in.close()
            except: pass
        if self.audio_in:
            try: self.audio_in.terminate()
            except: pass
            
        if self.stream_out:
            try:
                self.stream_out.stop_stream()
                self.stream_out.close()
            except: pass
        if self.audio_out:
            try: self.audio_out.terminate()
            except: pass
            
        if self.tcp_socket:
            try: self.tcp_socket.close()
            except: pass
        if self.udp_socket:
            try: self.udp_socket.close()
            except: pass
        
        cv2.destroyAllWindows()
        event.accept()

# --- Login Dialog (CSS warnings removed) ---
class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎥 Join Conference")
        self.setFixedSize(450, 350)
        self.result_data = None
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0f0c29, stop:0.5 #302b63, stop:1 #24243e);
            }
            QLabel {
                color: white;
            }
            QLineEdit {
                background: rgba(255, 255, 255, 0.15);
                color: white;
                border: 2px solid rgba(102, 126, 234, 0.5);
                border-radius: 8px;
                padding: 10px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 2px solid #667eea;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        title = QLabel("🎥 Conference Login")
        title.setStyleSheet("""
            font-size: 22px;
            font-weight: bold;
            color: white; /* Fallback color */
            background: transparent; /* No background */
            padding: 15px;
        """)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # --- THIS IS THE FIX ---
        # We must set a fixed width for the label *before* creating the
        # gradient, so the gradient knows how wide to be.
        title.setFixedWidth(420) 
        
        # 1. Create a QLinearGradient
        #    (x1, y1, x2, y2) -> We want a horizontal gradient across the label
        gradient = QLinearGradient(0, 0, title.width(), 0)
        gradient.setColorAt(0.0, QColor("#667eea")) # Start color
        gradient.setColorAt(1.0, QColor("#764ba2")) # End color
        
        # 2. Get the label's palette
        palette = title.palette()
        
        # 3. Set the 'WindowText' (foreground/text) color role 
        #    to use our gradient brush
        palette.setBrush(QPalette.ColorRole.WindowText, QBrush(gradient))
        
        # 4. Apply the new palette to the label
        title.setPalette(palette)
        # --- END OF FIX ---
        
        layout.addWidget(title)
        
        layout.addWidget(QLabel("🌐 Server IP:"))
        self.server_entry = QLineEdit("127.0.0.1")
        layout.addWidget(self.server_entry)
        
        layout.addWidget(QLabel("🔌 Server Port:"))
        self.port_entry = QLineEdit("5555")
        layout.addWidget(self.port_entry)
        
        layout.addWidget(QLabel("👤 Username:"))
        self.username_entry = QLineEdit()
        self.username_entry.setPlaceholderText("Enter your name...")
        self.username_entry.returnPressed.connect(self.connect)
        layout.addWidget(self.username_entry)
        
        connect_btn = QPushButton("🚀 Connect")
        connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        connect_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
                color: white;
                border: none;
                border-radius: 10px;
                padding: 15px;
                font-weight: bold;
                font-size: 14px;
                margin-top: 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #764ba2, stop:1 #667eea);
            }
            QPushButton:pressed {
                background: #5a4b8a;
            }
        """)
        connect_btn.clicked.connect(self.connect)
        layout.addWidget(connect_btn)
    
    def connect(self):
        # (This function is unchanged from your original code)
        server = self.server_entry.text().strip()
        port = self.port_entry.text().strip()
        username = self.username_entry.text().strip()
        
        if server and port and username:
            try:
                self.result_data = {'server': server, 'port': int(port), 'username': username}
                self.accept()
            except ValueError:
                QMessageBox.critical(self, "Error", "Invalid port")
        else:
            QMessageBox.warning(self, "Warning", "Fill all fields")

def main():
    # (This function is unchanged from your original code)
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(palette)
    
    login = LoginDialog()
    if login.exec() == QDialog.DialogCode.Accepted and login.result_data:
        client = ConferenceClient(
            login.result_data['server'],
            login.result_data['port'],
            login.result_data['username']
        )
        
        if client.connect():
            client.show()
            sys.exit(app.exec())
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()