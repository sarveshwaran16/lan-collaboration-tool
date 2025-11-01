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
    participant_list_signal = pyqtSignal(list)
    video_frame_signal = pyqtSignal(str, object)
    screen_share_start_signal = pyqtSignal(str)
    screen_share_stop_signal = pyqtSignal()
    screen_share_frame_signal = pyqtSignal(object)
    chat_message_signal = pyqtSignal(dict)
    file_transfer_signal = pyqtSignal(dict)
    file_available_signal = pyqtSignal(dict)
    
    def __init__(self, server_host, server_port, username):
        super().__init__()
        self.server_host = server_host
        self.tcp_port = server_port
        self.udp_port = None
        self.username = username
        
        self.tcp_socket = None
        self.udp_socket = None
        self.running = False
        
        self.video_enabled = False
        self.audio_enabled = False
        self.screen_share_enabled = False
        self.screen_share_active = False
        self.screen_share_user = None
        
        self.cap = None
        self.audio_in = None
        self.stream_in = None
        self.audio_out = None
        self.stream_out = None
        
        self.participants = {}
        self.previous_participants = set()
        self.current_page = 0
        self.participants_per_page = 4
        self.chat_windows = []
        self.chat_history = []
        self.shared_screen_frame = None
        
        self.video_labels = {}
        self.screen_share_label = None
        self.screen_share_info = None
        self.presenter_overlay = None
        
        self.participant_list_signal.connect(self.update_participant_list)
        self.video_frame_signal.connect(self.update_video_frame)
        self.screen_share_start_signal.connect(self.handle_screen_share_start)
        self.screen_share_stop_signal.connect(self.handle_screen_share_stop)
        self.screen_share_frame_signal.connect(self.update_screen_share_display)
        self.chat_message_signal.connect(self.handle_chat_message)
        self.file_transfer_signal.connect(self.handle_file_transfer)
        self.file_available_signal.connect(self.handle_file_available)
        
        self.setup_gui()
        
    def _open_camera_windows(self):
        """Try multiple backends and indices; always release failed handles so the camera isn't left locked."""
        preferred_backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, 0]  # 0 = default
        for backend in preferred_backends:
            for index in range(0, 4):
                try:
                    cap = cv2.VideoCapture(index, backend) if backend != 0 else cv2.VideoCapture(index)
                    if not cap.isOpened():
                        try:
                            cap.release()
                        except:
                            pass
                        continue
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.size > 0:
                        self.cap = cap
                        return True
                    try:
                        cap.release()
                    except:
                        pass
                except Exception:
                    try:
                        cap.release()
                    except:
                        pass
                    continue
        return False

    def setup_gui(self):
        self.setWindowTitle(f"🎥 Conference - {self.username}")
        self.setGeometry(100, 100, 1400, 800)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
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
        self.next_btn.setStyleSheet("""
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
        nav_layout.addWidget(self.next_btn)
        
        left_layout.addWidget(nav_widget)
        
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
        right_layout.setSpacing(10)
        
        # Participants section
        participants_label = QLabel("👥 Participants")
        participants_label.setStyleSheet("""
            font-size: 14px;
            font-weight: bold;
            color: white;
            background: transparent;
            padding: 5px;
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
                font-size: 11px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 6px;
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
        right_layout.addWidget(self.participant_list, stretch=1)
        
        # Activity log section
        activity_label = QLabel("📋 Activity Log")
        activity_label.setStyleSheet("""
            font-size: 14px;
            font-weight: bold;
            color: white;
            background: transparent;
            padding: 5px;
        """)
        activity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(activity_label)
        
        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setStyleSheet("""
            QTextEdit {
                background: rgba(255, 255, 255, 0.1);
                color: #a0a0a0;
                border: 2px solid rgba(255, 255, 255, 0.2);
                border-radius: 8px;
                font-size: 10px;
                padding: 5px;
            }
        """)
        self.activity_log.setMaximumHeight(200)
        right_layout.addWidget(self.activity_log, stretch=1)
        
        main_layout.addWidget(right_widget, stretch=1)
        
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
        
    def _encode_frame_for_udp(self, frame_bgr, max_bytes=50000):
        """Return (resized_bgr_frame, base64_jpeg) maximizing quality under UDP datagram size.
        Tries higher resolutions and qualities first, backing off until size fits.
        """
        # Attempt a range of resolutions and JPEG qualities
        candidate_resolutions = [
            (1280, 720), (1120, 630), (960, 540), (854, 480), (800, 450), (720, 405), (640, 360)
        ]
        candidate_qualities = [85, 80, 75, 70, 65, 60, 55, 50]
        for width, height in candidate_resolutions:
            resized = cv2.resize(frame_bgr, (width, height))
            for quality in candidate_qualities:
                ok, buffer = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, quality])
                if not ok:
                    continue
                b64 = base64.b64encode(buffer).decode('utf-8')
                if len(b64) <= max_bytes:
                    return resized, b64
        # Fallback
        fallback = cv2.resize(frame_bgr, (640, 360))
        ok, buffer = cv2.imencode('.jpg', fallback, [cv2.IMWRITE_JPEG_QUALITY, 50])
        b64 = base64.b64encode(buffer).decode('utf-8')
        return fallback, b64

    def connect(self):
        try:
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                # Enable TCP keepalive to reduce idle disconnects
                self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except Exception:
                pass
            self.tcp_socket.connect((self.server_host, self.tcp_port))
            
            message = json.dumps({'username': self.username})
            try:
                self.tcp_socket.send(message.encode('utf-8'))
            except Exception:
                pass
            
            data = self.tcp_socket.recv(4096).decode('utf-8')
            msg = json.loads(data)
            self.udp_port = msg.get('udp_port', 5556)
            
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2097152)
            self.udp_socket.bind(('', 0))
            
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
            except:
                pass
            self.audio_out = None
            self.stream_out = None
            return False
            
    def receive_tcp(self):
        buffer = ""
        while self.running:
            try:
                data = self.tcp_socket.recv(65536)
                if not data:
                    break
                
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
                        elif msg_type == 'file_available':
                            self.file_available_signal.emit(message)
                        elif msg_type == 'ping':
                            try:
                                self.tcp_socket.send(json.dumps({'type': 'pong'}).encode('utf-8'))
                            except Exception:
                                pass
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
                        break
                        
            except Exception as e:
                if self.running:
                    print(f"TCP error: {e}")
                break
    
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

            if not self.stream_out:
                ok = self.init_audio_output()
                if not ok:
                    return

            if self.stream_out and self.stream_out.is_active():
                try:
                    self.stream_out.write(audio_data)
                except Exception as e:
                    print(f"Audio playback error: {e}")
                    try:
                        self.stream_out.stop_stream()
                        self.stream_out.close()
                    except:
                        pass
                    try:
                        if self.audio_out:
                            self.audio_out.terminate()
                    except:
                        pass
                    self.stream_out = None
                    self.audio_out = None
        except Exception as e:
            print(f"Audio frame handling error: {e}")
            return
    
    def handle_screen_share_frame(self, message):
        try:
            frame_data = base64.b64decode(message['frame'])
            frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
            self.shared_screen_frame = frame
            
            if self.current_page == 0 and self.screen_share_active:
                self.screen_share_frame_signal.emit(frame)
        except Exception as e:
            pass
    
    def log_activity(self, message):
        """Add a message to the activity log"""
        timestamp = time.strftime('%H:%M:%S')
        formatted_msg = f"[{timestamp}] {message}\n"
        self.activity_log.append(formatted_msg)
    
    def update_participant_list(self, participants):
        current_usernames = set(p['username'] for p in participants)
        
        # Detect joins
        for username in current_usernames:
            if username not in self.previous_participants and username != self.username:
                self.log_activity(f"👤 {username} joined")
        
        # Detect leaves
        for username in self.previous_participants:
            if username not in current_usernames and username != self.username:
                self.log_activity(f"👋 {username} left")
        
        self.previous_participants = current_usernames.copy()
        
        for p in participants:
            username = p['username']
            if username not in self.participants:
                self.participants[username] = {
                    'video': p['video'],
                    'audio': p['audio'],
                    'frame': None
                }
            else:
                old_video_status = self.participants[username]['video']
                new_video_status = p['video']
                
                self.participants[username]['video'] = new_video_status
                self.participants[username]['audio'] = p['audio']
                
                if old_video_status and not new_video_status:
                    self.participants[username]['frame'] = None
                    if username in self.video_labels:
                        self.clear_user_video(username)
        
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
    
    def clear_user_video(self, username):
        try:
            if username in self.video_labels:
                video_label = self.video_labels[username]['video_label']
                video_label.setPixmap(QPixmap())
                video_label.setText(username)
        except Exception as e:
            pass
    
    def update_video_display(self):
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
        
        if num_participants == 1:
            rows, cols = 1, 1
        elif num_participants == 2:
            rows, cols = 1, 2
        elif num_participants == 3:
            rows, cols = 2, 2
        elif num_participants == 4:
            rows, cols = 2, 2
        else:
            rows, cols = 2, 2
        
        for i in range(rows):
            self.video_layout.setRowStretch(i, 1)
        for i in range(cols):
            self.video_layout.setColumnStretch(i, 1)
        
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
        # Lock the screen-share label to current video area size to avoid sliding/growing
        area_size = self.video_frame.size()
        if area_size.width() > 0 and area_size.height() > 0:
            self.screen_share_label.setFixedSize(area_size)
        self.screen_share_label.setScaledContents(True)
        screen_container_layout.addWidget(self.screen_share_label)
        
        # Presenter overlay removed per UX request
        
        main_layout.addWidget(screen_container, stretch=1)
        
        # Lock containers to the same size as video area to keep layout static while sharing
        area_size = self.video_frame.size()
        if area_size.width() > 0 and area_size.height() > 0:
            main_container.setFixedSize(area_size)
            screen_container.setFixedSize(area_size)
        
        self.video_layout.addWidget(main_container, 0, 0)
        self.video_layout.setRowStretch(0, 1)
        self.video_layout.setColumnStretch(0, 1)
        
        if self.shared_screen_frame is not None:
            self.update_screen_share_display(self.shared_screen_frame)
        
        # Presenter overlay removed - no overlay to update
        
        participant_list = list(self.participants.keys())
        total_pages = 1 + max(1, (len(participant_list) - 1) // self.participants_per_page + 1)
        self.page_label.setText(f"Page 1/{total_pages} - Screen Share")
    
    def update_screen_share_display(self, frame):
        try:
            if not self.screen_share_label:
                return
                
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame_rgb.shape
            bytes_per_line = 3 * width
            q_image = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
            
            pixmap = QPixmap.fromImage(q_image)
            target_size = self.video_frame.size()
            if target_size.width() <= 0 or target_size.height() <= 0:
                target_size = self.screen_share_label.size()
            scaled_pixmap = pixmap.scaled(target_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.screen_share_label.setPixmap(scaled_pixmap)
            self.screen_share_label.setText("")
        except Exception as e:
            pass
    
    def update_presenter_overlay(self, frame):
        try:
            if not self.presenter_overlay:
                return
            
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
        self.screen_share_label = None
        self.screen_share_info = None
        self.presenter_overlay = None
        self.update_video_display()
    
    def handle_screen_share_start(self, username):
        self.screen_share_active = True
        self.screen_share_user = username
        self.current_page = 0
        self.shared_screen_frame = None
        if username != self.username:
            self.log_activity(f"🖥️ {username} started screen sharing")
        self.display_screen_share()
    
    def handle_screen_share_stop(self):
        username = self.screen_share_user
        self.screen_share_active = False
        self.screen_share_user = None
        self.shared_screen_frame = None
        self.current_page = 0
        if username and username != self.username:
            self.log_activity(f"🖥️ {username} stopped screen sharing")
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
                import platform
                if platform.system() == "Linux":
                    self.cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
                    if not self.cap.isOpened():
                        self.cap = cv2.VideoCapture(0)
                else:
                    # Robust open on Windows: try several backends/indices and ensure we don't leave the camera locked
                    if self.cap:
                        try:
                            self.cap.release()
                        except:
                            pass
                        self.cap = None
                    ok = self._open_camera_windows()
                    if not ok:
                        QMessageBox.critical(self, "Error", "Could not open camera (in use or not found)")
                        return
                
                if not self.cap.isOpened():
                    QMessageBox.critical(self, "Error", "Could not open camera")
                    return
                
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                
                self.video_enabled = True
                self.video_btn.setText("📹 Stop Video")
                self.video_btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #eb3349, stop:1 #f45c43);
                        color: white;
                        border: none;
                        border-radius: 10px;
                        padding: 12px;
                        font-weight: bold;
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #f45c43, stop:1 #eb3349);
                    }
                    QPushButton:pressed {
                        background: #d32f2f;
                    }
                """)
                
                if self.username not in self.participants:
                    self.participants[self.username] = {'video': True, 'audio': self.audio_enabled, 'frame': None}
                else:
                    self.participants[self.username]['video'] = True
                
                message = json.dumps({'type': 'status_update', 'video': True})
                try:
                    self.tcp_socket.send(message.encode('utf-8'))
                except Exception:
                    pass
                
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
            try:
                self.tcp_socket.send(message.encode('utf-8'))
            except Exception:
                pass
            
            if self.username in self.video_labels:
                video_label = self.video_labels[self.username]['video_label']
                video_label.setPixmap(QPixmap())
                video_label.setText(self.username)
    
    def toggle_audio(self):
        if not self.audio_enabled:
            try:
                self.audio_in = pyaudio.PyAudio()
                
                try:
                    self.stream_in = self.audio_in.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=16000,
                        input=True,
                        frames_per_buffer=2048
                    )
                except OSError as e:
                    print(f"Default audio device failed: {e}")
                    device_count = self.audio_in.get_device_count()
                    for i in range(device_count):
                        try:
                            self.stream_in = self.audio_in.open(
                                format=pyaudio.paInt16,
                                channels=1,
                                rate=16000,
                                input=True,
                                frames_per_buffer=2048,
                                input_device_index=i
                            )
                            print(f"Using audio device {i}")
                            break
                        except:
                            continue
                    else:
                        raise Exception("No working audio device found")
                
                self.audio_enabled = True
                self.audio_btn.setText("🎤 Stop Audio")
                self.audio_btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #eb3349, stop:1 #f45c43);
                        color: white;
                        border: none;
                        border-radius: 10px;
                        padding: 12px;
                        font-weight: bold;
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #f45c43, stop:1 #eb3349);
                    }
                    QPushButton:pressed {
                        background: #d32f2f;
                    }
                """)
                
                if self.username not in self.participants:
                    self.participants[self.username] = {'video': self.video_enabled, 'audio': True, 'frame': None}
                else:
                    self.participants[self.username]['audio'] = True
                
                message = json.dumps({'type': 'status_update', 'audio': True})
                try:
                    self.tcp_socket.send(message.encode('utf-8'))
                except Exception:
                    pass
                
                audio_thread = threading.Thread(target=self.send_audio)
                audio_thread.daemon = True
                audio_thread.start()
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not start audio:\n{e}")
        else:
            self.audio_enabled = False
            self.audio_btn.setText("🎤 Start Audio")
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
            if self.stream_in:
                self.stream_in.stop_stream()
                self.stream_in.close()
            if self.audio_in:
                self.audio_in.terminate()
            
            if self.username in self.participants:
                self.participants[self.username]['audio'] = False
            
            message = json.dumps({'type': 'status_update', 'audio': False})
            try:
                self.tcp_socket.send(message.encode('utf-8'))
            except Exception:
                pass
    
    def toggle_screen_share(self):
        if not self.screen_share_enabled:
            self.screen_share_enabled = True
            self.screen_btn.setText("🖥️ Stop Sharing")
            self.screen_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #eb3349, stop:1 #f45c43);
                    color: white;
                    border: none;
                    border-radius: 10px;
                    padding: 12px;
                    font-weight: bold;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #f45c43, stop:1 #eb3349);
                }
                QPushButton:pressed {
                    background: #d32f2f;
                }
            """)
            
            self.screen_share_active = True
            self.screen_share_user = self.username
            self.current_page = 0
            self.display_screen_share()
            
            message = json.dumps({'type': 'screen_share', 'action': 'start', 'username': self.username})
            try:
                self.tcp_socket.send(message.encode('utf-8'))
            except Exception:
                pass
            
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
            
            message = json.dumps({'type': 'screen_share', 'action': 'stop', 'username': self.username})
            try:
                self.tcp_socket.send(message.encode('utf-8'))
            except Exception:
                pass
            
            self.screen_share_active = False
            self.screen_share_user = None
            self.shared_screen_frame = None
            self.current_page = 0
            self.hide_screen_share()
    
    def send_video(self):
        while self.video_enabled and self.running:
            try:
                ret, frame = self.cap.read()
                if not ret or frame is None or frame.size == 0:
                    time.sleep(0.1)
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
            except Exception as e:
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
                print(f"Audio capture/send error: {e}")
                self.audio_enabled = False
                try:
                    if self.stream_in:
                        self.stream_in.stop_stream()
                        self.stream_in.close()
                        self.stream_in = None
                except:
                    pass
                try:
                    if self.audio_in:
                        self.audio_in.terminate()
                        self.audio_in = None
                except:
                    pass
                break
    
    def send_screen_share(self):
        try:
            import platform
            system = platform.system()
            
            print(f"[{self.username}] Starting screen share on {system}")
            
            if system == "Linux":
                try:
                    from PIL import ImageGrab
                    print(f"[{self.username}] Using PIL ImageGrab for Linux")
                    
                    frame_count = 0
                    
                    while self.screen_share_enabled and self.running:
                        try:
                            screenshot = ImageGrab.grab()
                            frame = np.array(screenshot)
                            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                            # Higher quality for TCP relay
                            frame = cv2.resize(frame, (1280, 720))
                            display_frame = frame.copy()
                            self.shared_screen_frame = display_frame

                            if self.current_page == 0:
                                self.screen_share_frame_signal.emit(display_frame)

                            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                            frame_data = base64.b64encode(buffer).decode('utf-8')
                            
                            message = json.dumps({
                                'type': 'screen_share',
                                'action': 'frame',
                                'username': self.username,
                                'frame': frame_data
                            })
                            
                            try:
                                self.tcp_socket.send(message.encode('utf-8'))
                                frame_count += 1
                                
                                if frame_count % 50 == 0:
                                    print(f"[INFO] Sent {frame_count} frames via TCP")
                                    
                            except socket.error as e:
                                print(f"[ERROR] TCP send failed: {e}")
                                break
                            
                            time.sleep(0.1)
                            
                        except Exception as e:
                            print(f"[ERROR] PIL screen capture error: {e}")
                            QMessageBox.critical(self, "Screen Share Error", 
                                f"Linux screen capture failed: {e}\n\nTry: pip install pillow\nOr run: xhost +local:")
                            self.screen_share_enabled = False
                            break
                    
                    print(f"[INFO] Screen share stopped. Sent {frame_count} frames")
                            
                except Exception as e:
                    print(f"[ERROR] Linux screen share init failed: {e}")
                    QMessageBox.critical(self, "Error", f"Screen capture failed:\n{e}")
                    self.screen_share_enabled = False
                    return
                    
            else:
                print(f"[{self.username}] Using mss for screen capture")
                
                with mss() as sct:
                    try:
                        monitor = sct.monitors[1]
                    except:
                        monitor = sct.monitors[0]
                    
                    frame_count = 0
                    
                    print(f"[INFO] Capturing monitor: {monitor}")
                    
                    while self.screen_share_enabled and self.running:
                        try:
                            screenshot = sct.grab(monitor)
                            frame = np.array(screenshot)
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                            # Higher quality for TCP relay
                            frame = cv2.resize(frame, (1280, 720))

                            self.shared_screen_frame = frame.copy()
                            if self.current_page == 0:
                                self.screen_share_frame_signal.emit(frame.copy())

                            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                            frame_data = base64.b64encode(buffer).decode('utf-8')
                            
                            message = json.dumps({
                                'type': 'screen_share',
                                'action': 'frame',
                                'username': self.username,
                                'frame': frame_data
                            })
                            
                            try:
                                self.tcp_socket.send(message.encode('utf-8'))
                                frame_count += 1
                                
                                if frame_count % 50 == 0:
                                    print(f"[INFO] Sent {frame_count} frames via TCP")
                                    
                            except socket.error as e:
                                print(f"[ERROR] TCP send failed: {e}")
                                break
                            
                            time.sleep(0.1)
                            
                        except Exception as e:
                            print(f"[ERROR] Screen share error: {e}")
                            time.sleep(0.5)
                            continue
                    
                    print(f"[INFO] Screen share stopped. Sent {frame_count} frames")
                        
        except Exception as e:
            print(f"[FATAL] Screen share failed: {e}")
            
            def show_error():
                QMessageBox.critical(self, "Error", f"Screen share failed:\n{e}")
                
            QTimer.singleShot(0, show_error)
            self.screen_share_enabled = False
    
    def open_chat(self):
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
                    message = json.dumps({
                        'type': 'chat',
                        'recipient': recipient,
                        'message': msg
                    })
                    try:
                        self.tcp_socket.send(message.encode('utf-8'))
                        message_entry.clear()
                    except Exception as e:
                        QMessageBox.critical(self, "Error", str(e))
        
        send_btn = QPushButton("📤 Send")
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #764ba2, stop:1 #667eea);
            }
            QPushButton:pressed {
                background: #5a4b8a;
            }
        """)
        send_btn.clicked.connect(send_chat)
        message_layout.addWidget(send_btn)
        
        message_entry.returnPressed.connect(send_chat)
        layout.addWidget(message_frame)
        
        self.chat_windows.append(chat_display)
        chat_dialog.finished.connect(lambda: self.chat_windows.remove(chat_display) if chat_display in self.chat_windows else None)
        chat_dialog.exec()
    
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
        filepath, _ = QFileDialog.getOpenFileName(self, "Select file")
        if not filepath:
            return
        
        try:
            import os
            if os.path.getsize(filepath) > 10 * 1024 * 1024:
                QMessageBox.warning(self, "Warning", "File too large! Max 10MB")
                return
        except:
            pass
        
        file_dialog = QDialog(self)
        file_dialog.setWindowTitle("Share File")
        file_dialog.setGeometry(300, 300, 400, 300)
        
        layout = QVBoxLayout(file_dialog)
        
        filename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath)
        size_mb = file_size / (1024 * 1024)
        
        file_info = QLabel(f"File: {filename} ({size_mb:.2f} MB)")
        file_info.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(file_info)
        
        recipient_label = QLabel("Share with:")
        recipient_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(recipient_label)
        
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
        
        def send_file():
            try:
                with open(filepath, 'rb') as f:
                    file_data = f.read()
                
                recipient = None
                for name, radio in recipient_buttons.items():
                    if radio.isChecked():
                        recipient = name
                        break
                
                # Always upload to server with recipient info
                message = json.dumps({
                    'type': 'file_upload',
                    'recipient': recipient,
                    'filename': filename,
                    'size': file_size,
                    'data': base64.b64encode(file_data).decode('utf-8')
                })
                
                self.tcp_socket.send(message.encode('utf-8'))
                
                # Log activity
                if recipient == 'everyone':
                    self.log_activity(f"📁 Shared {filename} with everyone")
                else:
                    self.log_activity(f"📁 Shared {filename} with {recipient}")
                
                QMessageBox.information(self, "Success", f"File shared with {recipient}!")
                file_dialog.accept()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
        
        button_layout = QHBoxLayout()
        send_btn = QPushButton("Share")
        send_btn.clicked.connect(send_file)
        button_layout.addWidget(send_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(file_dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        file_dialog.exec()
    
    def handle_file_transfer(self, message):
        from_user = message.get('from', 'Unknown')
        filename = message.get('filename', 'file')
        
        # Auto-accept and show save dialog
        try:
            file_data = base64.b64decode(message['data'])
            save_path, _ = QFileDialog.getSaveFileName(self, f"Save file from {from_user}", filename)
            
            if save_path:
                with open(save_path, 'wb') as f:
                    f.write(file_data)
                QMessageBox.information(self, "Success", f"File saved!")
                self.log_activity(f"📥 Downloaded {filename} from {from_user}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
    
    def handle_file_available(self, message):
        from_user = message.get('from', 'Unknown')
        filename = message.get('filename', 'file')
        file_size = message.get('size', 0)
        size_mb = file_size / (1024 * 1024)
        
        # Log to activity
        self.log_activity(f"📁 {from_user} shared {filename} ({size_mb:.2f} MB)")
        
        # Show download dialog
        reply = QMessageBox.question(
            self,
            "📁 File Available",
            f"{from_user} shared: {filename}\n\nSize: {size_mb:.2f} MB\n\nDownload now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Request download from server
            download_msg = json.dumps({
                'type': 'file_download',
                'filename': filename
            })
            try:
                self.tcp_socket.send(download_msg.encode('utf-8'))
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not request file: {e}")
    
    def closeEvent(self, event):
        self.running = False
        
        if self.cap:
            self.cap.release()
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

class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎥 Join Conference")
        # Open at an optimal medium size so all text fields are clearly visible
        self.resize(700, 520)
        self.setMinimumSize(500, 380)
        self.setSizeGripEnabled(True)
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
            color: white;
            padding: 15px;
        """)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
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