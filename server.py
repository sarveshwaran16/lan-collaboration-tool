import socket
import threading
import json
import time
import sys
from datetime import timedelta
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                             QTextEdit, QTableWidget, QTableWidgetItem, QGroupBox,
                             QSpinBox, QGridLayout)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor

class ServerSignals(QObject):
    """Signals for thread-safe GUI updates"""
    log_message = pyqtSignal(str)
    participant_update = pyqtSignal(list)
    activity_log = pyqtSignal(str)
    status_update = pyqtSignal(str)

class ConferenceServer:
    def __init__(self, tcp_port=5555, udp_port=5556, signals=None):
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.signals = signals
        
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        self.clients = {}
        self.username_to_udp = {}
        self.running = True
        self.lock = threading.Lock()
        
        self.files = {}
        self.current_presenter = None
        
    def emit_log(self, message):
        """Thread-safe log emission"""
        if self.signals:
            self.signals.log_message.emit(message)
        else:
            print(message)
    
    def emit_activity(self, message):
        """Thread-safe activity log emission"""
        if self.signals:
            self.signals.activity_log.emit(message)
    
    def emit_participant_update(self):
        """Thread-safe participant update"""
        participants = []
        with self.lock:
            for sock, info in self.clients.items():
                participants.append({
                    'username': info['username'],
                    'video': info['video'],
                    'audio': info['audio']
                })
        if self.signals:
            self.signals.participant_update.emit(participants)
        
    def start(self):
        self.tcp_socket.bind(('0.0.0.0', self.tcp_port))
        self.tcp_socket.listen(10)
        
        self.udp_socket.bind(('0.0.0.0', self.udp_port))
        
        self.emit_log(f"Server started on TCP port {self.tcp_port} and UDP port {self.udp_port}")
        
        udp_thread = threading.Thread(target=self.handle_udp)
        udp_thread.daemon = True
        udp_thread.start()
        
        while self.running:
            try:
                client_socket, address = self.tcp_socket.accept()
                self.emit_log(f"New TCP connection from {address}")
                thread = threading.Thread(target=self.handle_tcp_client, args=(client_socket, address))
                thread.daemon = True
                thread.start()
            except Exception as e:
                if self.running:
                    self.emit_log(f"Error accepting TCP connection: {e}")
    
    def handle_udp(self):
        while self.running:
            try:
                data, addr = self.udp_socket.recvfrom(131072)
                message = json.loads(data.decode('utf-8'))
                msg_type = message.get('type')
                username = message.get('username')
                
                if username:
                    with self.lock:
                        self.username_to_udp[username] = addr
                
                if msg_type in ['video_frame', 'audio_frame']:
                    self.broadcast_udp_exclude_sender(data, addr, username)
                    
            except json.JSONDecodeError:
                continue
            except Exception as e:
                if self.running:
                    self.emit_log(f"UDP error: {e}")
    
    def broadcast_udp_exclude_sender(self, data, sender_addr, sender_username):
        with self.lock:
            for username, udp_addr in list(self.username_to_udp.items()):
                if username != sender_username:
                    try:
                        self.udp_socket.sendto(data, udp_addr)
                    except Exception as e:
                        self.emit_log(f"Error sending UDP to {username}: {e}")
    
    def broadcast_screen_share_udp(self, data, sender_username):
        with self.lock:
            for username, udp_addr in list(self.username_to_udp.items()):
                if username != sender_username:
                    try:
                        self.udp_socket.sendto(data, udp_addr)
                    except Exception as e:
                        self.emit_log(f"Error sending screen share UDP to {username}: {e}")

    def broadcast_screen_share_tcp(self, data, sender_username):
        with self.lock:
            for client_socket, info in list(self.clients.items()):
                if info.get('username') != sender_username:
                    try:
                        client_socket.send(data)
                    except Exception as e:
                        self.emit_log(f"Error sending screen share TCP to {info.get('username')}: {e}")
                
    def handle_tcp_client(self, client_socket, address):
        username = None
        try:
            client_socket.settimeout(60.0)
            
            data = client_socket.recv(4096).decode('utf-8')
            msg = json.loads(data)
            username = msg['username']
            
            with self.lock:
                self.clients[client_socket] = {
                    'username': username,
                    'address': address,
                    'video': False,
                    'audio': False
                }
            
            self.emit_log(f"User {username} connected from {address}")
            
            response = json.dumps({
                'type': 'connection_info',
                'udp_port': self.udp_port
            })
            client_socket.send(response.encode('utf-8'))
            
            time.sleep(0.1)
            
            self.send_participant_list(client_socket)
            self.broadcast_participant_update()
            self.emit_participant_update()
            
            buffer = ""
            
            while self.running:
                try:
                    data = client_socket.recv(65536)
                    if not data:
                        self.emit_log(f"Client {username} disconnected (no data)")
                        break
                    
                    buffer += data.decode('utf-8')
                    
                    while True:
                        try:
                            message, idx = json.JSONDecoder().raw_decode(buffer)
                            buffer = buffer[idx:].lstrip()
                            
                            msg_type = message.get('type')
                            
                            if msg_type == 'chat':
                                self.route_chat(client_socket, message)
                            elif msg_type == 'file_transfer':
                                self.route_file(client_socket, message)
                            elif msg_type == 'file_upload':
                                self.handle_file_upload(client_socket, message)
                            elif msg_type == 'file_download':
                                self.handle_file_download(client_socket, message)
                            elif msg_type == 'status_update':
                                self.update_status(client_socket, message)
                            elif msg_type == 'screen_share':
                                self.handle_screen_share(client_socket, message)
                            elif msg_type == 'ping':
                                try:
                                    client_socket.send(json.dumps({'type': 'pong'}).encode('utf-8'))
                                except:
                                    break
                                    
                        except json.JSONDecodeError:
                            break
                        
                except socket.timeout:
                    try:
                        client_socket.send(json.dumps({'type': 'ping'}).encode('utf-8'))
                    except:
                        self.emit_log(f"Client {username} connection lost (timeout)")
                        break
                    continue
                except ConnectionResetError:
                    self.emit_log(f"Client {username} connection reset")
                    break
                except ConnectionAbortedError:
                    self.emit_log(f"Client {username} connection aborted")
                    break
                except Exception as e:
                    self.emit_log(f"TCP error from {username}: {e}")
                    break
                    
        except Exception as e:
            self.emit_log(f"Error with client {address}: {e}")
        finally:
            self.remove_client(client_socket, username)
            time.sleep(0.2)
            self.broadcast_participant_update()
            self.emit_participant_update()
            
    def handle_screen_share(self, sender_socket, message):
        with self.lock:
            sender_username = self.clients.get(sender_socket, {}).get('username', 'Unknown')
        
        action = message.get('action')
        
        if action == 'start':
            if self.current_presenter is not None and self.current_presenter != sender_username:
                self.emit_log(f"Screen share REJECTED for {sender_username} - {self.current_presenter} is presenting")
                self.emit_activity(f"🚫 Screen share rejected: {sender_username} (presenter: {self.current_presenter})")
                rejection = json.dumps({
                    'type': 'screen_share',
                    'action': 'rejected',
                    'current_presenter': self.current_presenter
                }).encode('utf-8')
                try:
                    sender_socket.send(rejection)
                except:
                    pass
                return
            
            self.current_presenter = sender_username
            self.emit_log(f"Screen share START from {sender_username}")
            self.emit_activity(f"🖥️ Screen share started: {sender_username}")
            data = json.dumps(message).encode('utf-8')
            self.broadcast_screen_share_tcp(data, sender_username)
        
        elif action == 'stop':
            if self.current_presenter == sender_username:
                self.current_presenter = None
            self.emit_log(f"Screen share STOP from {sender_username}")
            self.emit_activity(f"🖥️ Screen share stopped: {sender_username}")
            data = json.dumps(message).encode('utf-8')
            self.broadcast_screen_share_tcp(data, sender_username)
        
        elif action == 'frame':
            data = json.dumps(message).encode('utf-8')
            self.broadcast_screen_share_tcp(data, sender_username)
            
    def send_participant_list(self, client_socket):
        participants = []
        with self.lock:
            for sock, info in self.clients.items():
                participants.append({
                    'username': info['username'],
                    'video': info['video'],
                    'audio': info['audio']
                })
        
        message = json.dumps({
            'type': 'participant_list',
            'participants': participants
        })
        
        try:
            client_socket.send(message.encode('utf-8'))
        except:
            pass
            
    def broadcast_participant_update(self):
        participants = []
        with self.lock:
            for sock, info in self.clients.items():
                participants.append({
                    'username': info['username'],
                    'video': info['video'],
                    'audio': info['audio']
                })
        
        message = json.dumps({
            'type': 'participant_list',
            'participants': participants
        })
        
        with self.lock:
            for client_socket in list(self.clients.keys()):
                try:
                    client_socket.send(message.encode('utf-8'))
                except:
                    pass
                    
    def route_chat(self, sender_socket, message):
        with self.lock:
            sender_username = self.clients.get(sender_socket, {}).get('username', 'Unknown')
        
        recipient = message.get('recipient')
        chat_message = message.get('message')
        
        self.emit_log(f"Chat from {sender_username} to {recipient}: {chat_message}")
        
        response = {
            'type': 'chat',
            'from': sender_username,
            'message': chat_message,
            'recipient': recipient,
            'timestamp': time.time()
        }
        
        data = json.dumps(response).encode('utf-8')
        
        if recipient == 'everyone':
            with self.lock:
                for client_socket in list(self.clients.keys()):
                    try:
                        client_socket.send(data)
                        self.emit_log(f"Sent chat to {self.clients[client_socket]['username']}")
                    except Exception as e:
                        self.emit_log(f"Error sending chat: {e}")
        else:
            with self.lock:
                for client_socket, info in self.clients.items():
                    if info['username'] == recipient or client_socket == sender_socket:
                        try:
                            client_socket.send(data)
                            self.emit_log(f"Sent private chat to {info['username']}")
                        except Exception as e:
                            self.emit_log(f"Error sending private chat: {e}")
                        
    def route_file(self, sender_socket, message):
        with self.lock:
            sender_username = self.clients.get(sender_socket, {}).get('username', 'Unknown')
        
        recipient = message.get('recipient')
        message['from'] = sender_username
        data = json.dumps(message).encode('utf-8')
        
        if recipient == 'everyone':
            with self.lock:
                for client_socket in list(self.clients.keys()):
                    if client_socket != sender_socket:
                        try:
                            client_socket.send(data)
                        except:
                            pass
        else:
            with self.lock:
                for client_socket, info in self.clients.items():
                    if info['username'] == recipient:
                        try:
                            client_socket.send(data)
                        except:
                            pass
    
    def handle_file_upload(self, sender_socket, message):
        import base64
        with self.lock:
            sender_username = self.clients.get(sender_socket, {}).get('username', 'Unknown')
        
        filename = message.get('filename')
        file_size = message.get('size', 0)
        recipient = message.get('recipient', 'everyone')
        
        try:
            file_data = base64.b64decode(message['data'])
            
            with self.lock:
                self.files[filename] = {
                    'data': file_data,
                    'size': file_size,
                    'uploaded_by': sender_username
                }
            
            self.emit_log(f"File {filename} uploaded by {sender_username} for {recipient} ({file_size} bytes)")
            self.emit_activity(f"📁 File uploaded: {filename} ({file_size} bytes) by {sender_username} → {recipient}")
            
            notification = json.dumps({
                'type': 'file_available',
                'from': sender_username,
                'filename': filename,
                'size': file_size
            }).encode('utf-8')
            
            with self.lock:
                if recipient == 'everyone':
                    for client_socket, info in self.clients.items():
                        if info['username'] != sender_username:
                            try:
                                client_socket.send(notification)
                            except:
                                pass
                else:
                    for client_socket, info in self.clients.items():
                        if info['username'] == recipient:
                            try:
                                client_socket.send(notification)
                            except:
                                pass
        except Exception as e:
            self.emit_log(f"Error handling file upload: {e}")
    
    def handle_file_download(self, requester_socket, message):
        import base64
        filename = message.get('filename')
        
        with self.lock:
            requester_username = self.clients.get(requester_socket, {}).get('username', 'Unknown')
            if filename in self.files:
                file_info = self.files[filename]
                file_data = file_info['data']
                
                response = json.dumps({
                    'type': 'file_transfer',
                    'from': 'Server',
                    'filename': filename,
                    'data': base64.b64encode(file_data).decode('utf-8')
                }).encode('utf-8')
                
                try:
                    requester_socket.send(response)
                    self.emit_log(f"File {filename} downloaded by {requester_username}")
                    self.emit_activity(f"⬇️ File downloaded: {filename} by {requester_username}")
                except Exception as e:
                    self.emit_log(f"Error sending file: {e}")
            else:
                self.emit_log(f"File {filename} not found")
    
    def update_status(self, client_socket, message):
        with self.lock:
            if client_socket in self.clients:
                if 'video' in message:
                    self.clients[client_socket]['video'] = message['video']
                if 'audio' in message:
                    self.clients[client_socket]['audio'] = message['audio']
        
        self.broadcast_participant_update()
        self.emit_participant_update()
        
    def remove_client(self, client_socket, username):
        with self.lock:
            if client_socket in self.clients:
                self.emit_log(f"Client {username} disconnected")
                del self.clients[client_socket]
            
            if username and username in self.username_to_udp:
                del self.username_to_udp[username]
            
            if self.current_presenter == username:
                self.current_presenter = None
                self.emit_log(f"Screen share ended - {username} disconnected")
                self.emit_activity(f"🖥️ Screen share ended: {username} disconnected")
        
        try:
            client_socket.close()
        except:
            pass
        
        self.broadcast_participant_update()
            
    def stop(self):
        shutdown_msg = json.dumps({'type': 'server_shutdown'}).encode('utf-8')
        with self.lock:
            for client_socket in list(self.clients.keys()):
                try:
                    client_socket.send(shutdown_msg)
                except:
                    pass
        
        time.sleep(0.5)
        
        self.running = False
        with self.lock:
            for client_socket in list(self.clients.keys()):
                try:
                    client_socket.close()
                except:
                    pass
        try:
            self.tcp_socket.close()
            self.udp_socket.close()
        except:
            pass

class ServerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.server = None
        self.server_thread = None
        self.signals = ServerSignals()
        self.start_time = None
        
        self.init_ui()
        
        # Connect signals
        self.signals.log_message.connect(self.add_log)
        self.signals.participant_update.connect(self.update_participants)
        self.signals.activity_log.connect(self.add_activity)
        self.signals.status_update.connect(self.update_status_bar)
        
        # Timer for uptime
        self.uptime_timer = QTimer()
        self.uptime_timer.timeout.connect(self.update_uptime)
    
    def get_local_ip(self):
        """Get the local IP address of the machine"""
        try:
            # Create a socket to determine the local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            # Connect to a public DNS server (doesn't actually send data)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            # Fallback to localhost if unable to determine
            return "127.0.0.1"
        
    def init_ui(self):
        self.setWindowTitle("Conference Server Control Panel")
        self.setGeometry(100, 100, 1200, 800)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Top controls
        control_group = QGroupBox("Server Controls")
        control_layout = QGridLayout()
        
        # Server IP
        control_layout.addWidget(QLabel("Server IP:"), 0, 0)
        self.ip_input = QLineEdit(self.get_local_ip())
        self.ip_input.setReadOnly(True)
        self.ip_input.setMinimumWidth(150)
        control_layout.addWidget(self.ip_input, 0, 1)
        
        # TCP Port
        control_layout.addWidget(QLabel("TCP Port:"), 0, 2)
        self.tcp_port_input = QSpinBox()
        self.tcp_port_input.setRange(1024, 65535)
        self.tcp_port_input.setValue(5555)
        control_layout.addWidget(self.tcp_port_input, 0, 3)
        
        # UDP Port
        control_layout.addWidget(QLabel("UDP Port:"), 0, 4)
        self.udp_port_input = QSpinBox()
        self.udp_port_input.setRange(1024, 65535)
        self.udp_port_input.setValue(5556)
        control_layout.addWidget(self.udp_port_input, 0, 5)
        
        # Start/Stop button
        self.start_stop_btn = QPushButton("Start Server")
        self.start_stop_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 10px; }")
        self.start_stop_btn.clicked.connect(self.toggle_server)
        control_layout.addWidget(self.start_stop_btn, 1, 0, 1, 6)
        
        control_group.setLayout(control_layout)
        main_layout.addWidget(control_group)
        
        # Status bar
        status_group = QGroupBox("Server Status")
        status_layout = QHBoxLayout()
        
        self.status_label = QLabel("Status: STOPPED")
        self.status_label.setStyleSheet("font-weight: bold; color: red;")
        status_layout.addWidget(self.status_label)
        
        status_layout.addWidget(QLabel(" | "))
        
        self.participants_label = QLabel("Participants: 0")
        self.participants_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.participants_label)
        
        status_layout.addWidget(QLabel(" | "))
        
        self.uptime_label = QLabel("Uptime: 00:00:00")
        self.uptime_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.uptime_label)
        
        status_layout.addStretch()
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)
        
        # Middle section - Participants and Activity
        middle_layout = QHBoxLayout()
        
        # Participants table
        participants_group = QGroupBox("Connected Participants")
        participants_layout = QVBoxLayout()
        
        self.participants_table = QTableWidget()
        self.participants_table.setColumnCount(3)
        self.participants_table.setHorizontalHeaderLabels(["Username", "Video", "Audio"])
        self.participants_table.horizontalHeader().setStretchLastSection(True)
        self.participants_table.setColumnWidth(0, 200)
        self.participants_table.setColumnWidth(1, 80)
        self.participants_table.setColumnWidth(2, 80)
        participants_layout.addWidget(self.participants_table)
        
        participants_group.setLayout(participants_layout)
        middle_layout.addWidget(participants_group, 1)
        
        # Activity Log
        activity_group = QGroupBox("Activity Log (File Transfers & Screen Sharing)")
        activity_layout = QVBoxLayout()
        
        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setMaximumHeight(250)
        activity_layout.addWidget(self.activity_log)
        
        clear_activity_btn = QPushButton("Clear Activity Log")
        clear_activity_btn.clicked.connect(self.activity_log.clear)
        activity_layout.addWidget(clear_activity_btn)
        
        activity_group.setLayout(activity_layout)
        middle_layout.addWidget(activity_group, 1)
        
        main_layout.addLayout(middle_layout)
        
        # Bottom - System Log
        log_group = QGroupBox("System Log")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        
        clear_log_btn = QPushButton("Clear System Log")
        clear_log_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_log_btn)
        
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)
        
    def toggle_server(self):
        if self.server is None or not self.server.running:
            self.start_server()
        else:
            self.stop_server()
    
    def start_server(self):
        tcp_port = self.tcp_port_input.value()
        udp_port = self.udp_port_input.value()
        
        try:
            self.server = ConferenceServer(tcp_port, udp_port, self.signals)
            self.server_thread = threading.Thread(target=self.server.start)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.start_time = time.time()
            self.uptime_timer.start(1000)
            
            self.start_stop_btn.setText("Stop Server")
            self.start_stop_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-weight: bold; padding: 10px; }")
            self.status_label.setText("Status: RUNNING")
            self.status_label.setStyleSheet("font-weight: bold; color: green;")
            
            self.tcp_port_input.setEnabled(False)
            self.udp_port_input.setEnabled(False)
            
            self.add_log("✓ Server started successfully")
            
        except Exception as e:
            self.add_log(f"✗ Error starting server: {e}")
    
    def stop_server(self):
        if self.server:
            self.server.stop()
            self.server = None
            
            self.uptime_timer.stop()
            self.start_time = None
            
            self.start_stop_btn.setText("Start Server")
            self.start_stop_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 10px; }")
            self.status_label.setText("Status: STOPPED")
            self.status_label.setStyleSheet("font-weight: bold; color: red;")
            
            self.tcp_port_input.setEnabled(True)
            self.udp_port_input.setEnabled(True)
            
            self.participants_table.setRowCount(0)
            self.participants_label.setText("Participants: 0")
            self.uptime_label.setText("Uptime: 00:00:00")
            
            self.add_log("✓ Server stopped")
    
    def add_log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    def add_activity(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.activity_log.append(f"[{timestamp}] {message}")
        self.activity_log.verticalScrollBar().setValue(self.activity_log.verticalScrollBar().maximum())
    
    def update_participants(self, participants):
        self.participants_table.setRowCount(len(participants))
        
        for i, p in enumerate(participants):
            self.participants_table.setItem(i, 0, QTableWidgetItem(p['username']))
            
            video_status = "ON" if p['video'] else "OFF"
            video_item = QTableWidgetItem(video_status)
            video_item.setForeground(QColor("green") if p['video'] else QColor("red"))
            self.participants_table.setItem(i, 1, video_item)
            
            audio_status = "ON" if p['audio'] else "OFF"
            audio_item = QTableWidgetItem(audio_status)
            audio_item.setForeground(QColor("green") if p['audio'] else QColor("red"))
            self.participants_table.setItem(i, 2, audio_item)
        
        self.participants_label.setText(f"Participants: {len(participants)}")
    
    def update_uptime(self):
        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            uptime_str = str(timedelta(seconds=elapsed))
            self.uptime_label.setText(f"Uptime: {uptime_str}")
    
    def update_status_bar(self, message):
        self.statusBar().showMessage(message, 3000)
    
    def closeEvent(self, event):
        if self.server and self.server.running:
            self.stop_server()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle('Fusion')
    
    window = ServerGUI()
    window.show()
    
    sys.exit(app.exec())