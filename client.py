import socket
import threading
import json
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import cv2
import pyaudio
import base64
import time
from PIL import Image
import numpy as np
from mss import mss
import sys

class VideoLabel(QLabel):
    """Custom label for video display"""
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: black; color: white;")
        self.setScaledContents(False)

class ConferenceClientPyQt5(QMainWindow):
    # Signals for thread-safe GUI updates
    participant_list_signal = pyqtSignal(list)
    video_frame_signal = pyqtSignal(str, object)
    screen_share_start_signal = pyqtSignal(str)
    screen_share_stop_signal = pyqtSignal()
    screen_share_frame_signal = pyqtSignal(object)
    chat_message_signal = pyqtSignal(dict)
    file_transfer_signal = pyqtSignal(dict)
    
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
        self.participants_per_page = 4  # MAX 4 per page
        self.chat_windows = []
        self.chat_history = []
        self.shared_screen_frame = None
        
        # Video display
        self.video_labels = {}
        self.screen_share_label = None
        self.screen_share_info = None
        
        # Connect signals
        self.participant_list_signal.connect(self.update_participant_list)
        self.video_frame_signal.connect(self.update_video_frame)
        self.screen_share_start_signal.connect(self.handle_screen_share_start)
        self.screen_share_stop_signal.connect(self.handle_screen_share_stop)
        self.screen_share_frame_signal.connect(self.update_screen_share_display)
        self.chat_message_signal.connect(self.handle_chat_message)
        self.file_transfer_signal.connect(self.handle_file_transfer)
        
        self.setup_gui()
        
    def setup_gui(self):
        self.setWindowTitle(f"Conference - {self.username}")
        self.setGeometry(100, 100, 1200, 700)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Left panel - Video and controls
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(5)
        
        # Video frame
        self.video_frame = QWidget()
        self.video_frame.setMinimumSize(640, 640)
        self.video_frame.setStyleSheet("background-color: black;")
        self.video_layout = QGridLayout(self.video_frame)
        self.video_layout.setSpacing(2)
        left_layout.addWidget(self.video_frame, stretch=1)
        
        # Navigation
        nav_widget = QWidget()
        nav_layout = QHBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        
        self.prev_btn = QPushButton("◄ Previous")
        self.prev_btn.clicked.connect(self.prev_page)
        self.prev_btn.setFixedWidth(100)
        nav_layout.addWidget(self.prev_btn)
        
        self.page_label = QLabel("Page 1/1")
        self.page_label.setAlignment(Qt.AlignCenter)
        nav_layout.addWidget(self.page_label)
        
        self.next_btn = QPushButton("Next ►")
        self.next_btn.clicked.connect(self.next_page)
        self.next_btn.setFixedWidth(100)
        nav_layout.addWidget(self.next_btn)
        
        left_layout.addWidget(nav_widget)
        
        # Control buttons
        control_widget = QWidget()
        control_layout = QHBoxLayout(control_widget)
        control_layout.setSpacing(5)
        control_layout.setContentsMargins(0, 0, 0, 0)
        
        self.video_btn = QPushButton("Start Video")
        self.video_btn.clicked.connect(self.toggle_video)
        self.video_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px; font-weight: bold;")
        control_layout.addWidget(self.video_btn)
        
        self.audio_btn = QPushButton("Start Audio")
        self.audio_btn.clicked.connect(self.toggle_audio)
        self.audio_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 8px; font-weight: bold;")
        control_layout.addWidget(self.audio_btn)
        
        self.screen_btn = QPushButton("Share Screen")
        self.screen_btn.clicked.connect(self.toggle_screen_share)
        self.screen_btn.setStyleSheet("background-color: #FF9800; color: white; padding: 8px; font-weight: bold;")
        control_layout.addWidget(self.screen_btn)
        
        self.chat_btn = QPushButton("Chat")
        self.chat_btn.clicked.connect(self.open_chat)
        self.chat_btn.setStyleSheet("background-color: #9C27B0; color: white; padding: 8px; font-weight: bold;")
        control_layout.addWidget(self.chat_btn)
        
        self.file_btn = QPushButton("Share File")
        self.file_btn.clicked.connect(self.open_file_transfer)
        self.file_btn.setStyleSheet("background-color: #607D8B; color: white; padding: 8px; font-weight: bold;")
        control_layout.addWidget(self.file_btn)
        
        left_layout.addWidget(control_widget)
        
        main_layout.addWidget(left_widget, stretch=4)
        
        # Right panel - Participants
        right_widget = QWidget()
        right_widget.setMaximumWidth(200)
        right_layout = QVBoxLayout(right_widget)
        
        participants_label = QLabel("Participants")
        participants_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        participants_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(participants_label)
        
        self.participant_list = QListWidget()
        self.participant_list.setStyleSheet("font-size: 11px;")
        right_layout.addWidget(self.participant_list)
        
        main_layout.addWidget(right_widget, stretch=1)
        
        # Apply modern stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2C2C2C;
            }
            QPushButton {
                border-radius: 4px;
                min-height: 35px;
                font-size: 11px;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
            QLabel {
                color: white;
            }
            QListWidget {
                background-color: #3C3C3C;
                color: white;
                border: 1px solid #555;
                border-radius: 4px;
            }
        """)
        
    def connect(self):
        try:
            # Connect TCP
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.connect((self.server_host, self.tcp_port))
            
            # Send username
            message = json.dumps({'username': self.username})
            self.tcp_socket.send(message.encode('utf-8'))
            
            # Receive UDP port info
            data = self.tcp_socket.recv(4096).decode('utf-8')
            msg = json.loads(data)
            self.udp_port = msg.get('udp_port', 5556)
            
            # Create UDP socket
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2097152)
            self.udp_socket.bind(('', 0))
            
            # Register with server
            register_msg = json.dumps({'type': 'register', 'username': self.username})
            self.udp_socket.sendto(register_msg.encode('utf-8'), (self.server_host, self.udp_port))
            
            self.running = True
            
            # Setup audio output
            try:
                self.audio_out = pyaudio.PyAudio()
                self.stream_out = self.audio_out.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    output=True,
                    frames_per_buffer=2048
                )
            except Exception as e:
                print(f"Audio output error: {e}")
            
            # Start threads
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
            
    def receive_tcp(self):
        buffer = ""
        consecutive_errors = 0
        max_errors = 5
        
        while self.running:
            try:
                data = self.tcp_socket.recv(65536)
                if not data:
                    print("TCP connection closed by server")
                    break
                
                consecutive_errors = 0  # Reset error counter on successful receive
                buffer += data.decode('utf-8')
                
                while True:
                    try:
                        message, idx = json.JSONDecoder().raw_decode(buffer)
                        buffer = buffer[idx:].lstrip()
                        
                        msg_type = message.get('type')
                        
                        if msg_type == 'participant_list':
                            self.participant_list_signal.emit(message['participants'])
                        elif msg_type == 'chat':
                            self.chat_message_signal.emit(message)
                        elif msg_type == 'file_transfer':
                            self.file_transfer_signal.emit(message)
                        elif msg_type == 'ping':
                            # Respond to keep-alive
                            try:
                                self.tcp_socket.send(json.dumps({'type': 'pong'}).encode('utf-8'))
                            except:
                                pass
                            
                    except json.JSONDecodeError:
                        break
                        
            except socket.timeout:
                # Send keep-alive
                try:
                    self.tcp_socket.send(json.dumps({'type': 'ping'}).encode('utf-8'))
                except:
                    print("Failed to send keep-alive")
                    consecutive_errors += 1
                    if consecutive_errors >= max_errors:
                        print("Too many errors, disconnecting")
                        break
                continue
            except ConnectionResetError:
                print("Connection reset by peer")
                break
            except Exception as e:
                if self.running:
                    print(f"TCP error: {e}")
                    consecutive_errors += 1
                    if consecutive_errors >= max_errors:
                        print("Too many consecutive errors, disconnecting")
                        break
                    time.sleep(1)  # Wait before retrying
                else:
                    break
        
        # Connection lost - notify user
        if self.running:
            QMessageBox.warning(self, "Connection Lost", "Disconnected from server")
    
    def receive_udp(self):
        while self.running:
            try:
                data, addr = self.udp_socket.recvfrom(131072)
                message = json.loads(data.decode('utf-8'))
                msg_type = message.get('type')
                
                if msg_type == 'video_frame':
                    self.handle_video_frame(message)
                elif msg_type == 'audio_frame':
                    self.handle_audio_frame(message)
                elif msg_type == 'screen_share':
                    action = message.get('action')
                    username = message.get('username')
                    
                    if action == 'start':
                        if username != self.username:
                            self.screen_share_start_signal.emit(username)
                    elif action == 'stop':
                        self.screen_share_stop_signal.emit()
                    elif action == 'frame':
                        self.handle_screen_share_frame(message)
                    
            except json.JSONDecodeError:
                continue
            except Exception as e:
                if self.running:
                    print(f"UDP error: {e}")
    
    def handle_video_frame(self, message):
        username = message.get('username')
        if username and username in self.participants:
            try:
                frame_data = base64.b64decode(message['frame'])
                frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
                self.participants[username]['frame'] = frame
                self.video_frame_signal.emit(username, frame)
            except Exception as e:
                print(f"Video frame error: {e}")
            
    def handle_audio_frame(self, message):
        try:
            audio_data = base64.b64decode(message['audio'])
            if self.stream_out and self.stream_out.is_active():
                self.stream_out.write(audio_data)
        except Exception as e:
            print(f"Audio error: {e}")
    
    def handle_screen_share_frame(self, message):
        try:
            frame_data = base64.b64decode(message['frame'])
            frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
            self.shared_screen_frame = frame
            
            if self.current_page == 0 and self.screen_share_active:
                self.screen_share_frame_signal.emit(frame)
        except Exception as e:
            print(f"Screen frame error: {e}")
    
    def update_participant_list(self, participants):
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
        # Clear existing
        while self.video_layout.count():
            item = self.video_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.video_labels.clear()
        
        participant_list = list(self.participants.keys())
        total_participants = len(participant_list)
        
        # Minimize pages - auto-adjust current page if needed
        if self.screen_share_active:
            max_pages = 1 + ((total_participants - 1) // self.participants_per_page + 1)
        else:
            max_pages = max(1, (total_participants - 1) // self.participants_per_page + 1)
        
        # If current page is now invalid, go to last valid page
        if self.current_page >= max_pages:
            self.current_page = max(0, max_pages - 1)
        
        if self.screen_share_active:
            if self.current_page == 0:
                return
            participant_page = self.current_page - 1
            total_pages = 1 + max(1, (total_participants - 1) // self.participants_per_page + 1)
        else:
            participant_page = self.current_page
            total_pages = max(1, (total_participants - 1) // self.participants_per_page + 1)
        
        start_idx = participant_page * self.participants_per_page
        end_idx = start_idx + self.participants_per_page
        page_participants = participant_list[start_idx:end_idx]
        
        num_participants = len(page_participants)
        if num_participants == 0:
            self.page_label.setText(f"Page {self.current_page + 1}/{total_pages}")
            return
        
        # SMART LAYOUT based on ACTUAL number on THIS page (not total)
        if num_participants == 1:
            # Full screen - 1x1
            rows, cols = 1, 1
            layout_type = "fullscreen"
        elif num_participants == 2:
            # Side by side - 1x2
            rows, cols = 1, 2
            layout_type = "sidebyside"
        elif num_participants == 3:
            # 2 on top, 1 centered at bottom - 2x2 with span
            rows, cols = 2, 2
            layout_type = "three_special"
        elif num_participants == 4:
            # Perfect 2x2 grid
            rows, cols = 2, 2
            layout_type = "grid"
        else:
            rows, cols = 2, 2
            layout_type = "grid"
        
        for idx, username in enumerate(page_participants):
            # Determine position based on layout type
            if layout_type == "fullscreen":
                row, col, rowspan, colspan = 0, 0, 1, 1
            elif layout_type == "sidebyside":
                row, col = 0, idx
                rowspan, colspan = 1, 1
            elif layout_type == "three_special":
                if idx == 0:
                    row, col = 0, 0
                elif idx == 1:
                    row, col = 0, 1
                else:  # idx == 2, center it at bottom spanning both columns
                    row, col, rowspan, colspan = 1, 0, 1, 2
                if idx < 2:
                    rowspan, colspan = 1, 1
            else:  # grid
                row = idx // cols
                col = idx % cols
                rowspan, colspan = 1, 1
            
            cell_widget = QWidget()
            cell_widget.setStyleSheet("background-color: black; border: 1px solid gray;")
            cell_layout = QVBoxLayout(cell_widget)
            cell_layout.setContentsMargins(2, 2, 2, 2)
            cell_layout.setSpacing(0)
            
            video_label = VideoLabel()
            video_label.setText(username)
            video_label.setStyleSheet("font-size: 16px; color: white;")
            video_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            video_label.setScaledContents(False)
            cell_layout.addWidget(video_label, stretch=1)
            
            info_widget = QWidget()
            info_widget.setStyleSheet("background-color: black;")
            info_layout = QHBoxLayout(info_widget)
            info_layout.setContentsMargins(5, 2, 5, 2)
            
            name_label = QLabel(username)
            name_label.setStyleSheet("color: white; font-weight: bold; font-size: 10px;")
            info_layout.addWidget(name_label)
            
            participant_data = self.participants[username]
            mic_status = "🎤" if participant_data['audio'] else "🔇"
            mic_label = QLabel(mic_status)
            mic_label.setStyleSheet("font-size: 12px;")
            info_layout.addWidget(mic_label)
            
            info_layout.addStretch()
            cell_layout.addWidget(info_widget)
            
            # Add to grid with proper span
            self.video_layout.addWidget(cell_widget, row, col, rowspan, colspan)
            
            self.video_labels[username] = {
                'video_label': video_label,
                'name_label': name_label,
                'mic_label': mic_label,
                'cell_widget': cell_widget
            }
            
            if participant_data['frame'] is not None:
                self.update_video_frame(username, participant_data['frame'])
        
        # Configure grid weights for proper sizing
        for i in range(rows):
            self.video_layout.setRowStretch(i, 1)
        for i in range(cols):
            self.video_layout.setColumnStretch(i, 1)
        
        self.page_label.setText(f"Page {self.current_page + 1}/{total_pages}")
    
    def update_video_frame(self, username, frame):
        if username in self.video_labels:
            try:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                height, width, channel = frame_rgb.shape
                bytes_per_line = 3 * width
                q_image = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format_RGB888)
                
                video_label = self.video_labels[username]['video_label']
                cell_widget = self.video_labels[username]['cell_widget']
                
                # Get cell size (not label size) to fit properly
                cell_size = cell_widget.size()
                
                # Account for info bar (approx 30px)
                available_height = cell_size.height() - 35
                available_width = cell_size.width() - 10
                
                pixmap = QPixmap.fromImage(q_image)
                # Scale to fit available space while maintaining aspect ratio
                scaled_pixmap = pixmap.scaled(
                    available_width, 
                    available_height, 
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                )
                
                video_label.setPixmap(scaled_pixmap)
                video_label.setText("")  # Clear text when video shows
            except Exception as e:
                print(f"Update frame error: {e}")
    
    def display_screen_share(self):
        while self.video_layout.count():
            item = self.video_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.video_labels.clear()
        
        # Full screen container - takes entire grid
        container = QWidget()
        container.setStyleSheet("background-color: black;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.screen_share_info = QLabel(f"🖥️ Screen shared by: {self.screen_share_user}")
        self.screen_share_info.setStyleSheet("color: white; background-color: #1a1a1a; font-size: 14px; font-weight: bold; padding: 10px;")
        self.screen_share_info.setAlignment(Qt.AlignCenter)
        self.screen_share_info.setFixedHeight(40)
        layout.addWidget(self.screen_share_info)
        
        self.screen_share_label = VideoLabel()
        self.screen_share_label.setText("Loading screen share...")
        self.screen_share_label.setStyleSheet("color: gray; font-size: 16px;")
        self.screen_share_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.screen_share_label, stretch=1)
        
        # Add to grid spanning ALL rows and columns - FULL PAGE
        self.video_layout.addWidget(container, 0, 0, 2, 2)
        
        # Make grid expand to fill
        self.video_layout.setRowStretch(0, 1)
        self.video_layout.setRowStretch(1, 1)
        self.video_layout.setColumnStretch(0, 1)
        self.video_layout.setColumnStretch(1, 1)
        
        if self.shared_screen_frame is not None:
            self.update_screen_share_display(self.shared_screen_frame)
        
        participant_list = list(self.participants.keys())
        total_pages = 1 + max(1, (len(participant_list) - 1) // self.participants_per_page + 1)
        self.page_label.setText(f"Page 1/{total_pages} - Screen Share")
    
    def hide_screen_share(self):
        self.screen_share_label = None
        self.screen_share_info = None
        self.update_video_display()
    
    def update_screen_share_display(self, frame):
        try:
            if not self.screen_share_label:
                return
                
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame_rgb.shape
            bytes_per_line = 3 * width
            q_image = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format_RGB888)
            
            pixmap = QPixmap.fromImage(q_image)
            scaled_pixmap = pixmap.scaled(self.screen_share_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.screen_share_label.setPixmap(scaled_pixmap)
            self.screen_share_label.setText("")
        except Exception as e:
            print(f"Screen display error: {e}")
    
    def handle_screen_share_start(self, username):
        self.screen_share_active = True
        self.screen_share_user = username
        self.current_page = 0
        self.shared_screen_frame = None
        self.display_screen_share()
    
    def handle_screen_share_stop(self):
        self.screen_share_active = False
        self.screen_share_user = None
        self.shared_screen_frame = None
        self.current_page = 0
        self.hide_screen_share()
    
    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            if self.screen_share_active and self.current_page == 0:
                self.display_screen_share()
            else:
                self.update_video_display()
    
    def next_page(self):
        if self.screen_share_active:
            total_pages = 1 + max(1, (len(self.participants) - 1) // self.participants_per_page + 1)
        else:
            total_pages = max(1, (len(self.participants) - 1) // self.participants_per_page + 1)
            
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.update_video_display()
    
    def toggle_video(self):
        if not self.video_enabled:
            try:
                self.cap = cv2.VideoCapture(0)
                # Set backend explicitly for Windows
                if not self.cap.isOpened():
                    # Try DirectShow backend for Windows
                    self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                
                if not self.cap.isOpened():
                    QMessageBox.critical(self, "Error", "Could not open camera")
                    return
                
                # Set camera properties for stability
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer
                
                self.video_enabled = True
                self.video_btn.setText("Stop Video")
                self.video_btn.setStyleSheet("background-color: #f44336; color: white; padding: 8px; font-weight: bold;")
                
                if self.username not in self.participants:
                    self.participants[self.username] = {'video': True, 'audio': self.audio_enabled, 'frame': None}
                else:
                    self.participants[self.username]['video'] = True
                
                message = json.dumps({'type': 'status_update', 'video': True})
                self.tcp_socket.send(message.encode('utf-8'))
                
                video_thread = threading.Thread(target=self.send_video)
                video_thread.daemon = True
                video_thread.start()
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not start video:\n{e}")
        else:
            self.video_enabled = False
            self.video_btn.setText("Start Video")
            self.video_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px; font-weight: bold;")
            
            if self.cap:
                try:
                    self.cap.release()
                except:
                    pass
                self.cap = None
            
            if self.username in self.participants:
                self.participants[self.username]['video'] = False
                self.participants[self.username]['frame'] = None
            
            message = json.dumps({'type': 'status_update', 'video': False})
            self.tcp_socket.send(message.encode('utf-8'))
            
            if self.username in self.video_labels:
                video_label = self.video_labels[self.username]['video_label']
                video_label.clear()
                video_label.setText(self.username)
    
    def toggle_audio(self):
        if not self.audio_enabled:
            try:
                self.audio_in = pyaudio.PyAudio()
                self.stream_in = self.audio_in.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    frames_per_buffer=2048
                )
                
                self.audio_enabled = True
                self.audio_btn.setText("Stop Audio")
                self.audio_btn.setStyleSheet("background-color: #f44336; color: white; padding: 8px; font-weight: bold;")
                
                if self.username not in self.participants:
                    self.participants[self.username] = {'video': self.video_enabled, 'audio': True, 'frame': None}
                else:
                    self.participants[self.username]['audio'] = True
                
                message = json.dumps({'type': 'status_update', 'audio': True})
                self.tcp_socket.send(message.encode('utf-8'))
                
                audio_thread = threading.Thread(target=self.send_audio)
                audio_thread.daemon = True
                audio_thread.start()
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not start audio:\n{e}")
        else:
            self.audio_enabled = False
            self.audio_btn.setText("Start Audio")
            self.audio_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 8px; font-weight: bold;")
            if self.stream_in:
                self.stream_in.stop_stream()
                self.stream_in.close()
            if self.audio_in:
                self.audio_in.terminate()
            
            if self.username in self.participants:
                self.participants[self.username]['audio'] = False
            
            message = json.dumps({'type': 'status_update', 'audio': False})
            self.tcp_socket.send(message.encode('utf-8'))
    
    def toggle_screen_share(self):
        if not self.screen_share_enabled:
            self.screen_share_enabled = True
            self.screen_btn.setText("Stop Sharing")
            self.screen_btn.setStyleSheet("background-color: #f44336; color: white; padding: 8px; font-weight: bold;")
            
            self.screen_share_active = True
            self.screen_share_user = self.username
            self.current_page = 0
            self.display_screen_share()
            
            message = json.dumps({'type': 'screen_share', 'action': 'start', 'username': self.username})
            self.udp_socket.sendto(message.encode('utf-8'), (self.server_host, self.udp_port))
            
            screen_thread = threading.Thread(target=self.send_screen_share)
            screen_thread.daemon = True
            screen_thread.start()
        else:
            self.screen_share_enabled = False
            self.screen_btn.setText("Share Screen")
            self.screen_btn.setStyleSheet("background-color: #FF9800; color: white; padding: 8px; font-weight: bold;")
            
            message = json.dumps({'type': 'screen_share', 'action': 'stop', 'username': self.username})
            self.udp_socket.sendto(message.encode('utf-8'), (self.server_host, self.udp_port))
            
            self.screen_share_active = False
            self.screen_share_user = None
            self.shared_screen_frame = None
            self.current_page = 0
            self.hide_screen_share()
    
    def send_video(self):
        while self.video_enabled and self.running:
            try:
                ret, frame = self.cap.read()
                if not ret:
                    print("Failed to grab video frame, retrying...")
                    time.sleep(0.1)
                    continue
                    
                if frame is None or frame.size == 0:
                    print("Empty frame received, skipping...")
                    time.sleep(0.033)
                    continue
                
                frame = cv2.resize(frame, (320, 240))
                self.participants[self.username]['frame'] = frame
                
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                frame_data = base64.b64encode(buffer).decode('utf-8')
                
                message = json.dumps({
                    'type': 'video_frame',
                    'username': self.username,
                    'frame': frame_data
                })
                
                self.udp_socket.sendto(message.encode('utf-8'), (self.server_host, self.udp_port))
                self.video_frame_signal.emit(self.username, frame)
                
                time.sleep(0.033)
            except cv2.error as e:
                print(f"OpenCV error: {e}")
                time.sleep(0.1)
                continue
            except Exception as e:
                print(f"Video error: {e}")
                # Don't break, try to continue
                time.sleep(0.1)
                continue
    
    def send_audio(self):
        while self.audio_enabled and self.running:
            try:
                data = self.stream_in.read(2048, exception_on_overflow=False)
                audio_data = base64.b64encode(data).decode('utf-8')
                
                message = json.dumps({
                    'type': 'audio_frame',
                    'username': self.username,
                    'audio': audio_data
                })
                
                self.udp_socket.sendto(message.encode('utf-8'), (self.server_host, self.udp_port))
                time.sleep(0.05)
            except Exception as e:
                print(f"Audio error: {e}")
                break
    
    def send_screen_share(self):
        try:
            import platform
            system = platform.system()
            
            if system == "Linux":
                # PyQt5 for Linux (silent capture)
                try:
                    app = QApplication.instance()
                    if app is None:
                        app = QApplication(sys.argv)
                    
                    screen = app.primaryScreen()
                    
                    while self.screen_share_enabled and self.running:
                        try:
                            pixmap = screen.grabWindow(0)
                            qimage = pixmap.toImage()
                            width = qimage.width()
                            height = qimage.height()
                            
                            ptr = qimage.bits()
                            ptr.setsize(qimage.byteCount())
                            arr = np.array(ptr).reshape(height, width, 4)
                            
                            frame = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
                            frame = cv2.resize(frame, (800, 450))
                            
                            self.shared_screen_frame = frame.copy()
                            if self.current_page == 0:
                                self.screen_share_frame_signal.emit(frame.copy())
                            
                            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 30])
                            frame_data = base64.b64encode(buffer).decode('utf-8')
                            
                            message = json.dumps({
                                'type': 'screen_share',
                                'action': 'frame',
                                'username': self.username,
                                'frame': frame_data
                            })
                            
                            msg_size = len(message.encode('utf-8'))
                            if msg_size < 60000:
                                self.udp_socket.sendto(message.encode('utf-8'), (self.server_host, self.udp_port))
                            else:
                                print(f"Skipping large frame: {msg_size} bytes")
                            
                            time.sleep(0.15)
                            
                        except Exception as e:
                            print(f"Linux screen error: {e}")
                            break
                            
                except ImportError:
                    QMessageBox.critical(self, "Error", "PyQt5 not properly installed")
                    self.screen_share_enabled = False
                    return
                    
            else:
                # Windows/Mac
                with mss() as sct:
                    try:
                        monitor = sct.monitors[1]
                    except:
                        monitor = sct.monitors[0]
                    
                    while self.screen_share_enabled and self.running:
                        try:
                            screenshot = sct.grab(monitor)
                            frame = np.array(screenshot)
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                            
                            height, width = frame.shape[:2]
                            
                            if width > 1920:
                                frame = cv2.resize(frame, (800, 450))
                            elif width > 1280:
                                frame = cv2.resize(frame, (960, 540))
                            else:
                                frame = cv2.resize(frame, (800, 600))
                            
                            self.shared_screen_frame = frame.copy()
                            if self.current_page == 0:
                                self.screen_share_frame_signal.emit(frame.copy())
                            
                            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 25])
                            frame_data = base64.b64encode(buffer).decode('utf-8')
                            
                            message = json.dumps({
                                'type': 'screen_share',
                                'action': 'frame',
                                'username': self.username,
                                'frame': frame_data
                            })
                            
                            msg_size = len(message.encode('utf-8'))
                            
                            if msg_size < 60000:
                                self.udp_socket.sendto(message.encode('utf-8'), (self.server_host, self.udp_port))
                            else:
                                print(f"Skipping large frame: {msg_size} bytes")
                            
                            time.sleep(0.1)
                            
                        except OSError as e:
                            if "10040" in str(e):
                                print(f"Packet too large")
                                continue
                            else:
                                print(f"Screen error: {e}")
                                break
                        except Exception as e:
                            print(f"Screen error: {e}")
                            break
                        
        except Exception as e:
            print(f"Screen init error: {e}")
            QMessageBox.critical(self, "Error", f"Screen share failed:\n{e}")
            self.screen_share_enabled = False
    
    def open_chat(self):
        chat_dialog = QDialog(self)
        chat_dialog.setWindowTitle("Chat")
        chat_dialog.setGeometry(200, 200, 450, 550)
        
        layout = QVBoxLayout(chat_dialog)
        
        # Recipient selection
        recipient_label = QLabel("Send to:")
        recipient_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(recipient_label)
        
        recipient_group = QWidget()
        recipient_layout = QVBoxLayout(recipient_group)
        recipient_layout.setContentsMargins(20, 0, 0, 0)
        
        button_group = QButtonGroup(chat_dialog)
        
        everyone_radio = QRadioButton("Everyone")
        everyone_radio.setChecked(True)
        everyone_radio.setStyleSheet("font-size: 10px;")
        button_group.addButton(everyone_radio)
        recipient_layout.addWidget(everyone_radio)
        
        recipient_buttons = {'everyone': everyone_radio}
        
        for username in self.participants.keys():
            if username != self.username:
                radio = QRadioButton(username)
                radio.setStyleSheet("font-size: 10px;")
                button_group.addButton(radio)
                recipient_layout.addWidget(radio)
                recipient_buttons[username] = radio
        
        layout.addWidget(recipient_group)
        
        # Chat display
        chat_display = QTextEdit()
        chat_display.setReadOnly(True)
        chat_display.setStyleSheet("background-color: #2C2C2C; color: white; border: 1px solid #555; font-size: 10px;")
        
        # Load history
        for msg in self.chat_history:
            chat_display.append(msg.strip())
        
        layout.addWidget(chat_display)
        
        # Message entry
        message_frame = QWidget()
        message_layout = QHBoxLayout(message_frame)
        message_layout.setContentsMargins(0, 0, 0, 0)
        
        message_entry = QLineEdit()
        message_entry.setStyleSheet("background-color: #3C3C3C; color: white; border: 1px solid #555; padding: 5px; font-size: 10px;")
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
                    message = json.dumps({
                        'type': 'chat',
                        'recipient': recipient,
                        'message': msg
                    })
                    try:
                        self.tcp_socket.send(message.encode('utf-8'))
                        message_entry.clear()
                    except Exception as e:
                        QMessageBox.critical(self, "Error", f"Could not send:\n{e}")
        
        send_btn = QPushButton("Send")
        send_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 5px; font-weight: bold;")
        send_btn.clicked.connect(send_chat)
        message_layout.addWidget(send_btn)
        
        message_entry.returnPressed.connect(send_chat)
        
        layout.addWidget(message_frame)
        
        self.chat_windows.append(chat_display)
        
        def on_close():
            if chat_display in self.chat_windows:
                self.chat_windows.remove(chat_display)
            chat_dialog.accept()
        
        chat_dialog.finished.connect(on_close)
        chat_dialog.exec_()
    
    def handle_chat_message(self, message):
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
        filepath, _ = QFileDialog.getOpenFileName(self, "Select file to share")
        if not filepath:
            return
        
        try:
            import os
            file_size = os.path.getsize(filepath)
            if file_size > 10 * 1024 * 1024:
                QMessageBox.warning(self, "Warning", "File too large! Maximum 10MB")
                return
        except:
            pass
        
        file_dialog = QDialog(self)
        file_dialog.setWindowTitle("Send File")
        file_dialog.setGeometry(300, 300, 400, 250)
        
        layout = QVBoxLayout(file_dialog)
        
        filename = os.path.basename(filepath)
        
        file_label = QLabel(f"File: {filename}")
        file_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        file_label.setWordWrap(True)
        layout.addWidget(file_label)
        
        recipient_label = QLabel("Send to:")
        recipient_label.setStyleSheet("font-weight: bold; font-size: 10px;")
        layout.addWidget(recipient_label)
        
        recipient_group = QWidget()
        recipient_layout = QVBoxLayout(recipient_group)
        recipient_layout.setContentsMargins(20, 0, 0, 0)
        
        button_group = QButtonGroup(file_dialog)
        
        everyone_radio = QRadioButton("Everyone")
        everyone_radio.setChecked(True)
        everyone_radio.setStyleSheet("font-size: 10px;")
        button_group.addButton(everyone_radio)
        recipient_layout.addWidget(everyone_radio)
        
        recipient_buttons = {'everyone': everyone_radio}
        
        for username in self.participants.keys():
            if username != self.username:
                radio = QRadioButton(username)
                radio.setStyleSheet("font-size: 10px;")
                button_group.addButton(radio)
                recipient_layout.addWidget(radio)
                recipient_buttons[username] = radio
        
        layout.addWidget(recipient_group)
        
        def send_file():
            try:
                with open(filepath, 'rb') as f:
                    file_data = f.read()
                
                file_data_b64 = base64.b64encode(file_data).decode('utf-8')
                
                recipient = None
                for name, radio in recipient_buttons.items():
                    if radio.isChecked():
                        recipient = name
                        break
                
                message = json.dumps({
                    'type': 'file_transfer',
                    'recipient': recipient,
                    'filename': filename,
                    'data': file_data_b64
                })
                
                self.tcp_socket.send(message.encode('utf-8'))
                QMessageBox.information(self, "Success", "File sent!")
                file_dialog.accept()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not send:\n{e}")
        
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        
        send_btn = QPushButton("Send")
        send_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px; font-weight: bold;")
        send_btn.clicked.connect(send_file)
        button_layout.addWidget(send_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background-color: #f44336; color: white; padding: 8px; font-weight: bold;")
        cancel_btn.clicked.connect(file_dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addWidget(button_frame)
        
        file_dialog.exec_()
    
    def handle_file_transfer(self, message):
        from_user = message.get('from', 'Unknown')
        filename = message.get('filename', 'file')
        
        try:
            file_data = base64.b64decode(message['data'])
            
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                f"Save file from {from_user}",
                filename
            )
            
            if save_path:
                with open(save_path, 'wb') as f:
                    f.write(file_data)
                QMessageBox.information(self, "Success", f"File saved to:\n{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save:\n{e}")
    
    def closeEvent(self, event):
        reply = QMessageBox.question(
            self,
            'Leave Meeting',
            'Are you sure you want to leave the meeting?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.running = False
            
            if self.video_enabled and self.cap:
                self.cap.release()
            
            if self.audio_enabled:
                if self.stream_in:
                    try:
                        self.stream_in.stop_stream()
                        self.stream_in.close()
                    except:
                        pass
                if self.audio_in:
                    try:
                        self.audio_in.terminate()
                    except:
                        pass
            
            if self.stream_out:
                try:
                    self.stream_out.stop_stream()
                    self.stream_out.close()
                except:
                    pass
            if self.audio_out:
                try:
                    self.audio_out.terminate()
                except:
                    pass
            
            if self.tcp_socket:
                try:
                    self.tcp_socket.close()
                except:
                    pass
            
            if self.udp_socket:
                try:
                    self.udp_socket.close()
                except:
                    pass
            
            cv2.destroyAllWindows()
            event.accept()
        else:
            event.ignore()

class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Join Conference")
        self.setFixedSize(400, 300)
        
        # Remove question mark, add minimize/maximize buttons
        self.setWindowFlags(
            Qt.Window |
            Qt.WindowCloseButtonHint |
            Qt.WindowMinimizeButtonHint |
            Qt.WindowMaximizeButtonHint
        )
        
        self.result_data = None
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        title = QLabel("Conference Login")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #2196F3;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Server IP
        ip_label = QLabel("Server IP:")
        ip_label.setStyleSheet("font-size: 11px; font-weight: bold;")
        layout.addWidget(ip_label)
        
        self.server_entry = QLineEdit()
        self.server_entry.setText("127.0.0.1")
        self.server_entry.setStyleSheet("padding: 8px; font-size: 11px; border: 1px solid #ccc; border-radius: 4px;")
        layout.addWidget(self.server_entry)
        
        # Server Port
        port_label = QLabel("Server Port:")
        port_label.setStyleSheet("font-size: 11px; font-weight: bold;")
        layout.addWidget(port_label)
        
        self.port_entry = QLineEdit()
        self.port_entry.setText("5555")
        self.port_entry.setStyleSheet("padding: 8px; font-size: 11px; border: 1px solid #ccc; border-radius: 4px;")
        layout.addWidget(self.port_entry)
        
        # Username
        user_label = QLabel("Username:")
        user_label.setStyleSheet("font-size: 11px; font-weight: bold;")
        layout.addWidget(user_label)
        
        self.username_entry = QLineEdit()
        self.username_entry.setStyleSheet("padding: 8px; font-size: 11px; border: 1px solid #ccc; border-radius: 4px;")
        self.username_entry.returnPressed.connect(self.connect)
        layout.addWidget(self.username_entry)
        
        # Connect button
        connect_btn = QPushButton("Connect")
        connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 10px;
                font-size: 12px;
                font-weight: bold;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        connect_btn.clicked.connect(self.connect)
        layout.addWidget(connect_btn)
        
        self.setStyleSheet("QDialog { background-color: white; }")
    
    def connect(self):
        server = self.server_entry.text().strip()
        port = self.port_entry.text().strip()
        username = self.username_entry.text().strip()
        
        if server and port and username:
            try:
                self.result_data = {
                    'server': server,
                    'port': int(port),
                    'username': username
                }
                self.accept()
            except ValueError:
                QMessageBox.critical(self, "Error", "Invalid port number")
        else:
            QMessageBox.warning(self, "Warning", "Please fill all fields")

def main():
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle('Fusion')
    
    # Login dialog
    login = LoginDialog()
    if login.exec_() == QDialog.Accepted and login.result_data:
        client = ConferenceClientPyQt5(
            login.result_data['server'],
            login.result_data['port'],
            login.result_data['username']
        )
        
        if client.connect():
            client.show()
            sys.exit(app.exec_())
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()