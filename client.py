import socket
import threading
import json
import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox
import cv2
import pyaudio
import base64
import time
from PIL import Image, ImageTk
import numpy as np
from mss import mss

class ConferenceClient:
    def __init__(self, server_host, server_port, username):
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
        self.participants_per_page = 10
        self.chat_windows = []
        self.chat_history = []
        self.shared_screen_frame = None
        
        # GUI setup
        self.root = tk.Tk()
        self.root.title(f"Conference - {username}")
        self.root.geometry("1200x700")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.setup_gui()
        
    def setup_gui(self):
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left panel - Video
        left_frame = tk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        self.video_frame = tk.Frame(left_frame, bg='black', width=640, height=640)
        self.video_frame.pack(fill=tk.BOTH, expand=True)
        self.video_frame.pack_propagate(False)
        
        # Navigation
        nav_frame = tk.Frame(left_frame)
        nav_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.prev_btn = tk.Button(nav_frame, text="◄ Previous", command=self.prev_page)
        self.prev_btn.pack(side=tk.LEFT, padx=5)
        
        self.page_label = tk.Label(nav_frame, text="Page 1/1")
        self.page_label.pack(side=tk.LEFT, padx=5)
        
        self.next_btn = tk.Button(nav_frame, text="Next ►", command=self.next_page)
        self.next_btn.pack(side=tk.LEFT, padx=5)
        
        # Controls
        control_frame = tk.Frame(left_frame)
        control_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.video_btn = tk.Button(control_frame, text="Start Video", command=self.toggle_video, width=12, bg='#4CAF50', fg='white')
        self.video_btn.pack(side=tk.LEFT, padx=2)
        
        self.audio_btn = tk.Button(control_frame, text="Start Audio", command=self.toggle_audio, width=12, bg='#2196F3', fg='white')
        self.audio_btn.pack(side=tk.LEFT, padx=2)
        
        self.screen_btn = tk.Button(control_frame, text="Share Screen", command=self.toggle_screen_share, width=12, bg='#FF9800', fg='white')
        self.screen_btn.pack(side=tk.LEFT, padx=2)
        
        self.chat_btn = tk.Button(control_frame, text="Chat", command=self.open_chat, width=12, bg='#9C27B0', fg='white')
        self.chat_btn.pack(side=tk.LEFT, padx=2)
        
        self.file_btn = tk.Button(control_frame, text="Share File", command=self.open_file_transfer, width=12, bg='#607D8B', fg='white')
        self.file_btn.pack(side=tk.LEFT, padx=2)
        
        # Right panel - Participants
        right_frame = tk.Frame(main_frame, width=200)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(5, 0))
        right_frame.pack_propagate(False)
        
        tk.Label(right_frame, text="Participants", font=('Arial', 12, 'bold')).pack(pady=5)
        
        list_frame = tk.Frame(right_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.participant_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=('Arial', 10))
        self.participant_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.participant_listbox.yview)
        
        self.video_labels = {}
        self.screen_share_label = None
        self.screen_share_info = None
        
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
            
            # Create UDP socket with larger buffer
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2097152)  # 2MB buffer
            self.udp_socket.bind(('', 0))
            
            # Register with server via UDP
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
                print(f"Audio output setup error: {e}")
            
            # Start receiver threads
            tcp_thread = threading.Thread(target=self.receive_tcp)
            tcp_thread.daemon = True
            tcp_thread.start()
            
            udp_thread = threading.Thread(target=self.receive_udp)
            udp_thread.daemon = True
            udp_thread.start()
            
            return True
        except Exception as e:
            messagebox.showerror("Connection Error", f"Could not connect to server:\n{e}")
            return False
            
    def receive_tcp(self):
        """Receive TCP messages (chat, files, control)"""
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
                            self.root.after(0, self.update_participant_list, message['participants'])
                        elif msg_type == 'chat':
                            self.root.after(0, self.handle_chat_message, message)
                        elif msg_type == 'file_transfer':
                            self.root.after(0, self.handle_file_transfer, message)
                            
                    except json.JSONDecodeError:
                        break
                        
            except Exception as e:
                if self.running:
                    print(f"TCP receive error: {e}")
                break
    
    def receive_udp(self):
        """Receive UDP messages - OPTIMIZED"""
        while self.running:
            try:
                data, addr = self.udp_socket.recvfrom(131072)  # Large buffer for screen share
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
                        self.root.after(0, self.handle_screen_share_start, username)
                    elif action == 'stop':
                        self.root.after(0, self.handle_screen_share_stop)
                    elif action == 'frame':
                        self.handle_screen_share_frame(message)
                    
            except json.JSONDecodeError:
                continue
            except Exception as e:
                if self.running:
                    print(f"UDP receive error: {e}")
    
    def handle_screen_share_start(self, username):
        """Handle screen share start from others"""
        if username == self.username:
            return  # Ignore own start message
            
        self.screen_share_active = True
        self.screen_share_user = username
        self.current_page = 0
        self.shared_screen_frame = None
        self.display_screen_share()
    
    def handle_screen_share_stop(self):
        """Handle screen share stop"""
        self.screen_share_active = False
        self.screen_share_user = None
        self.shared_screen_frame = None
        self.current_page = 0
        self.hide_screen_share()
    
    def handle_screen_share_frame(self, message):
        """Handle incoming screen share frame"""
        try:
            frame_data = base64.b64decode(message['frame'])
            frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
            self.shared_screen_frame = frame
            
            # Update display if on screen share page
            if self.current_page == 0 and self.screen_share_active:
                self.root.after(0, self.update_screen_share_display)
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
        
        self.participant_listbox.delete(0, tk.END)
        for username in self.participants.keys():
            p_data = self.participants[username]
            status = ""
            if p_data['video']:
                status += "📹 "
            if p_data['audio']:
                status += "🎤 "
            self.participant_listbox.insert(tk.END, f"{username} {status}")
        
        # Only update display if not on screen share page
        if not (self.screen_share_active and self.current_page == 0):
            self.update_video_display()
        
    def update_video_display(self):
        """Display participant video grid"""
        for widget in self.video_frame.winfo_children():
            widget.destroy()
        self.video_labels.clear()
        
        participant_list = list(self.participants.keys())
        
        # Calculate page based on screen share status
        if self.screen_share_active:
            if self.current_page == 0:
                return  # Don't rebuild on screen share page
            participant_page = self.current_page - 1
            total_pages = 1 + max(1, (len(participant_list) - 1) // self.participants_per_page + 1)
        else:
            participant_page = self.current_page
            total_pages = max(1, (len(participant_list) - 1) // self.participants_per_page + 1)
        
        start_idx = participant_page * self.participants_per_page
        end_idx = start_idx + self.participants_per_page
        page_participants = participant_list[start_idx:end_idx]
        
        num_participants = len(page_participants)
        if num_participants == 0:
            self.page_label.config(text=f"Page {self.current_page + 1}/{total_pages}")
            return
        
        if num_participants == 1:
            rows, cols = 1, 1
        elif num_participants == 2:
            rows, cols = 1, 2
        elif num_participants <= 4:
            rows, cols = 2, 2
        elif num_participants <= 6:
            rows, cols = 2, 3
        elif num_participants <= 9:
            rows, cols = 3, 3
        else:
            rows, cols = 4, 3
        
        for idx, username in enumerate(page_participants):
            row = idx // cols
            col = idx % cols
            
            cell_frame = tk.Frame(self.video_frame, bg='black', highlightbackground='gray', highlightthickness=1)
            cell_frame.grid(row=row, column=col, sticky='nsew', padx=2, pady=2)
            
            video_label = tk.Label(cell_frame, bg='black', text=username, fg='white', font=('Arial', 16))
            video_label.pack(fill=tk.BOTH, expand=True)
            
            info_frame = tk.Frame(cell_frame, bg='black')
            info_frame.pack(side=tk.BOTTOM, fill=tk.X)
            
            name_label = tk.Label(info_frame, text=username, fg='white', bg='black', font=('Arial', 10, 'bold'))
            name_label.pack(side=tk.LEFT, padx=5, pady=2)
            
            participant_data = self.participants[username]
            mic_status = "🎤" if participant_data['audio'] else "🔇"
            mic_label = tk.Label(info_frame, text=mic_status, fg='white', bg='black', font=('Arial', 12))
            mic_label.pack(side=tk.LEFT, padx=2)
            
            self.video_labels[username] = {
                'video_label': video_label,
                'name_label': name_label,
                'mic_label': mic_label,
                'cell_frame': cell_frame
            }
            
            # Display existing frame
            if participant_data['frame'] is not None:
                self.update_video_frame(username, participant_data['frame'])
        
        for i in range(rows):
            self.video_frame.grid_rowconfigure(i, weight=1)
        for i in range(cols):
            self.video_frame.grid_columnconfigure(i, weight=1)
        
        self.page_label.config(text=f"Page {self.current_page + 1}/{total_pages}")
        
    def display_screen_share(self):
        """Display screen share on page 0"""
        for widget in self.video_frame.winfo_children():
            widget.destroy()
        self.video_labels.clear()
        
        self.screen_share_info = tk.Label(
            self.video_frame, 
            text=f"🖥️ Screen shared by: {self.screen_share_user}", 
            fg='white', 
            bg='#1a1a1a', 
            font=('Arial', 14, 'bold'), 
            pady=10
        )
        self.screen_share_info.pack(side=tk.TOP, fill=tk.X)
        
        self.screen_share_label = tk.Label(
            self.video_frame, 
            bg='black', 
            text="Loading screen share...", 
            fg='gray', 
            font=('Arial', 16)
        )
        self.screen_share_label.pack(fill=tk.BOTH, expand=True)
        
        # Display frame if available
        if self.shared_screen_frame is not None:
            self.update_screen_share_display()
        
        # Update page label
        participant_list = list(self.participants.keys())
        total_pages = 1 + max(1, (len(participant_list) - 1) // self.participants_per_page + 1)
        self.page_label.config(text=f"Page 1/{total_pages} - Screen Share")
    
    def hide_screen_share(self):
        """Hide screen share and return to participants"""
        if self.screen_share_label and self.screen_share_label.winfo_exists():
            self.screen_share_label.destroy()
        if self.screen_share_info and self.screen_share_info.winfo_exists():
            self.screen_share_info.destroy()
        
        self.screen_share_label = None
        self.screen_share_info = None
        self.update_video_display()
    
    def update_screen_share_display(self):
        """Update screen share frame"""
        try:
            if not self.screen_share_label or not self.screen_share_label.winfo_exists():
                return
            if not self.shared_screen_frame is not None:
                return
                
            frame_rgb = cv2.cvtColor(self.shared_screen_frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            
            frame_width = max(self.video_frame.winfo_width() - 20, 100)
            frame_height = max(self.video_frame.winfo_height() - 80, 100)
            
            img.thumbnail((frame_width, frame_height), Image.Resampling.LANCZOS)
            
            photo = ImageTk.PhotoImage(img)
            self.screen_share_label.config(image=photo, text="")
            self.screen_share_label.image = photo
        except Exception as e:
            print(f"Screen display error: {e}")
        
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
                if not self.cap.isOpened():
                    messagebox.showerror("Error", "Could not open camera")
                    return
                
                self.video_enabled = True
                self.video_btn.config(text="Stop Video", bg='#f44336')
                
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
                messagebox.showerror("Error", f"Could not start video:\n{e}")
        else:
            self.video_enabled = False
            self.video_btn.config(text="Start Video", bg='#4CAF50')
            if self.cap:
                self.cap.release()
            
            if self.username in self.participants:
                self.participants[self.username]['video'] = False
                self.participants[self.username]['frame'] = None  # Clear the frame
            
            message = json.dumps({'type': 'status_update', 'video': False})
            self.tcp_socket.send(message.encode('utf-8'))
            
            # Clear own video display
            if self.username in self.video_labels:
                video_label = self.video_labels[self.username]['video_label']
                video_label.config(image='', text=self.username)
                video_label.image = None
            
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
                self.audio_btn.config(text="Stop Audio", bg='#f44336')
                
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
                messagebox.showerror("Error", f"Could not start audio:\n{e}")
        else:
            self.audio_enabled = False
            self.audio_btn.config(text="Start Audio", bg='#2196F3')
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
            self.screen_btn.config(text="Stop Sharing", bg='#f44336')
            
            # Set state immediately for sender
            self.screen_share_active = True
            self.screen_share_user = self.username
            self.current_page = 0
            self.display_screen_share()
            
            # Send start message
            message = json.dumps({'type': 'screen_share', 'action': 'start', 'username': self.username})
            self.udp_socket.sendto(message.encode('utf-8'), (self.server_host, self.udp_port))
            
            # Start capture
            screen_thread = threading.Thread(target=self.send_screen_share)
            screen_thread.daemon = True
            screen_thread.start()
        else:
            self.screen_share_enabled = False
            self.screen_btn.config(text="Share Screen", bg='#FF9800')
            
            # Send stop message
            message = json.dumps({'type': 'screen_share', 'action': 'stop', 'username': self.username})
            self.udp_socket.sendto(message.encode('utf-8'), (self.server_host, self.udp_port))
            
            # Clean up
            self.screen_share_active = False
            self.screen_share_user = None
            self.shared_screen_frame = None
            self.current_page = 0
            self.hide_screen_share()
            
    def send_video(self):
        """Send video - OPTIMIZED"""
        while self.video_enabled and self.running:
            try:
                ret, frame = self.cap.read()
                if ret:
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
                    self.root.after(0, self.update_video_frame, self.username, frame)
                    
                time.sleep(0.033)
            except Exception as e:
                print(f"Video error: {e}")
                break
                
    def send_audio(self):
        """Send audio - OPTIMIZED"""
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
        """Send screen share - Cross-platform with packet size control"""
        try:
            import platform
            system = platform.system()
            
            if system == "Linux":
                # Use scrot for Linux (no visual artifacts)
                import subprocess
                import tempfile
                import os
                
                print(f"[{self.username}] Using scrot for Linux screen capture")
                temp_dir = tempfile.gettempdir()
                
                while self.screen_share_enabled and self.running:
                    try:
                        # Use scrot to capture to file (no visual feedback)
                        temp_file = os.path.join(temp_dir, f"screen_{self.username}.png")
                        subprocess.run(['scrot', '-o', temp_file], 
                                     capture_output=True, 
                                     timeout=1,
                                     check=False)
                        
                        # Read the captured image
                        if os.path.exists(temp_file):
                            frame = cv2.imread(temp_file)
                            os.remove(temp_file)  # Clean up immediately
                            
                            if frame is not None:
                                frame = cv2.resize(frame, (800, 450))  # Smaller resolution
                                
                                # Store for own display
                                self.shared_screen_frame = frame.copy()
                                if self.current_page == 0:
                                    self.root.after(0, self.update_screen_share_display)
                                
                                # Encode with aggressive compression
                                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 30])
                                frame_data = base64.b64encode(buffer).decode('utf-8')
                                
                                message = json.dumps({
                                    'type': 'screen_share',
                                    'action': 'frame',
                                    'username': self.username,
                                    'frame': frame_data
                                })
                                
                                # Check size
                                msg_size = len(message.encode('utf-8'))
                                if msg_size < 60000:  # Only send if under limit
                                    self.udp_socket.sendto(message.encode('utf-8'), 
                                                          (self.server_host, self.udp_port))
                                else:
                                    print(f"Skipping large frame: {msg_size} bytes")
                        
                        time.sleep(0.15)  # 6-7 FPS for Linux
                        
                    except subprocess.TimeoutExpired:
                        print("scrot timeout")
                        continue
                    except Exception as e:
                        print(f"Linux screen capture error: {e}")
                        self.root.after(0, lambda: messagebox.showerror(
                            "Screen Share Error",
                            f"Linux screen capture failed: {e}\n\n"
                            "Please install scrot:\n"
                            "sudo apt-get install scrot"
                        ))
                        self.screen_share_enabled = False
                        self.screen_btn.config(text="Share Screen", bg='#FF9800')
                        break
            else:
                # Windows/Mac - use mss with size control
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
                            
                            # Adaptive resolution based on monitor size
                            height, width = frame.shape[:2]
                            
                            # Scale down to keep packet under 60KB
                            if width > 1920:
                                frame = cv2.resize(frame, (800, 450))  # Very small
                            elif width > 1280:
                                frame = cv2.resize(frame, (960, 540))  # Medium
                            else:
                                frame = cv2.resize(frame, (800, 600))   # Standard
                            
                            # Store for own display
                            self.shared_screen_frame = frame.copy()
                            if self.current_page == 0:
                                self.root.after(0, self.update_screen_share_display)
                            
                            # Aggressive compression for network
                            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 25])
                            frame_data = base64.b64encode(buffer).decode('utf-8')
                            
                            message = json.dumps({
                                'type': 'screen_share',
                                'action': 'frame',
                                'username': self.username,
                                'frame': frame_data
                            })
                            
                            # Check packet size before sending
                            msg_size = len(message.encode('utf-8'))
                            
                            if msg_size < 60000:  # UDP safe limit
                                self.udp_socket.sendto(message.encode('utf-8'), 
                                                      (self.server_host, self.udp_port))
                            else:
                                # Frame too large, skip it
                                print(f"Skipping large frame: {msg_size} bytes")
                            
                            time.sleep(0.1)  # 10 FPS
                            
                        except OSError as e:
                            if "10040" in str(e):
                                print(f"Packet too large, reducing quality...")
                                continue
                            else:
                                print(f"Screen share error: {e}")
                                break
                        except Exception as e:
                            print(f"Screen share error: {e}")
                            break
                        
        except Exception as e:
            print(f"Screen share init error: {e}")
            self.root.after(0, lambda: messagebox.showerror(
                "Screen Share Error",
                f"Could not start screen share: {e}"
            ))
            self.screen_share_enabled = False
            self.screen_btn.config(text="Share Screen", bg='#FF9800')
            
    def handle_video_frame(self, message):
        username = message.get('username')
        if username and username in self.participants:
            try:
                frame_data = base64.b64decode(message['frame'])
                frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
                self.participants[username]['frame'] = frame
                self.root.after(0, self.update_video_frame, username, frame)
            except Exception as e:
                print(f"Video frame error: {e}")
            
    def handle_audio_frame(self, message):
        try:
            audio_data = base64.b64decode(message['audio'])
            if self.stream_out and self.stream_out.is_active():
                self.stream_out.write(audio_data)
        except Exception as e:
            print(f"Audio playback error: {e}")
            
    def update_video_frame(self, username, frame):
        if username in self.video_labels:
            try:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                
                cell_frame = self.video_labels[username]['cell_frame']
                cell_width = max(cell_frame.winfo_width(), 100)
                cell_height = max(cell_frame.winfo_height() - 30, 100)
                
                img.thumbnail((cell_width, cell_height), Image.Resampling.LANCZOS)
                
                photo = ImageTk.PhotoImage(img)
                video_label = self.video_labels[username]['video_label']
                video_label.config(image=photo, text="")
                video_label.image = photo
            except Exception as e:
                print(f"Update frame error: {e}")
        
    def open_chat(self):
        chat_window = tk.Toplevel(self.root)
        chat_window.title("Chat")
        chat_window.geometry("450x550")
        
        tk.Label(chat_window, text="Send to:", font=('Arial', 11, 'bold')).pack(pady=8)
        
        recipient_var = tk.StringVar(value="everyone")
        recipient_frame = tk.Frame(chat_window)
        recipient_frame.pack(pady=5)
        
        tk.Radiobutton(recipient_frame, text="Everyone", variable=recipient_var, value="everyone", font=('Arial', 10)).pack(anchor='w', padx=20)
        
        for username in self.participants.keys():
            if username != self.username:
                tk.Radiobutton(recipient_frame, text=username, variable=recipient_var, value=username, font=('Arial', 10)).pack(anchor='w', padx=20)
        
        chat_display = scrolledtext.ScrolledText(chat_window, height=20, state='disabled', wrap=tk.WORD, font=('Arial', 10))
        chat_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        chat_display.config(state='normal')
        for msg in self.chat_history:
            chat_display.insert(tk.END, msg)
        chat_display.config(state='disabled')
        chat_display.see(tk.END)
        
        message_frame = tk.Frame(chat_window)
        message_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        message_entry = tk.Entry(message_frame, font=('Arial', 10))
        message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        message_entry.focus_set()
        
        def send_chat():
            msg = message_entry.get().strip()
            if msg:
                recipient = recipient_var.get()
                message = json.dumps({
                    'type': 'chat',
                    'recipient': recipient,
                    'message': msg
                })
                try:
                    self.tcp_socket.send(message.encode('utf-8'))
                    message_entry.delete(0, tk.END)
                except Exception as e:
                    messagebox.showerror("Error", f"Could not send message:\n{e}")
        
        send_btn = tk.Button(message_frame, text="Send", command=send_chat, bg='#4CAF50', fg='white', font=('Arial', 10, 'bold'))
        send_btn.pack(side=tk.RIGHT)
        
        message_entry.bind('<Return>', lambda e: send_chat())
        
        self.chat_windows.append(chat_display)
        
        def on_chat_close():
            if chat_display in self.chat_windows:
                self.chat_windows.remove(chat_display)
            chat_window.destroy()
        
        chat_window.protocol("WM_DELETE_WINDOW", on_chat_close)
        
    def handle_chat_message(self, message):
        from_user = message.get('from', 'Unknown')
        msg_text = message.get('message', '')
        recipient = message.get('recipient', 'everyone')
        timestamp = time.strftime('%H:%M:%S', time.localtime(message.get('timestamp', time.time())))
        
        if recipient == 'everyone':
            chat_msg = f"[{timestamp}] {from_user}: {msg_text}\n"
        else:
            if from_user == self.username:
                chat_msg = f"[{timestamp}] You (to {recipient}): {msg_text}\n"
            else:
                chat_msg = f"[{timestamp}] {from_user} (private): {msg_text}\n"
        
        self.chat_history.append(chat_msg)
        
        for chat_display in self.chat_windows:
            try:
                chat_display.config(state='normal')
                chat_display.insert(tk.END, chat_msg)
                chat_display.config(state='disabled')
                chat_display.see(tk.END)
            except:
                pass
                    
    def open_file_transfer(self):
        filepath = filedialog.askopenfilename(title="Select file to share")
        if not filepath:
            return
        
        try:
            import os
            file_size = os.path.getsize(filepath)
            if file_size > 10 * 1024 * 1024:
                messagebox.showwarning("Warning", "File too large! Maximum 10MB")
                return
        except:
            pass
        
        file_window = tk.Toplevel(self.root)
        file_window.title("Send File")
        file_window.geometry("400x250")
        file_window.transient(self.root)
        file_window.grab_set()
        
        filename = filepath.split('/')[-1] if '/' in filepath else filepath.split('\\')[-1]
        
        tk.Label(file_window, text=f"File: {filename}", font=('Arial', 11, 'bold'), wraplength=350).pack(pady=15)
        tk.Label(file_window, text="Send to:", font=('Arial', 10, 'bold')).pack(pady=5)
        
        recipient_var = tk.StringVar(value="everyone")
        recipient_frame = tk.Frame(file_window)
        recipient_frame.pack(pady=10)
        
        tk.Radiobutton(recipient_frame, text="Everyone", variable=recipient_var, value="everyone", font=('Arial', 10)).pack(anchor='w', padx=20)
        
        for username in self.participants.keys():
            if username != self.username:
                tk.Radiobutton(recipient_frame, text=username, variable=recipient_var, value=username, font=('Arial', 10)).pack(anchor='w', padx=20)
        
        def send_file():
            try:
                with open(filepath, 'rb') as f:
                    file_data = f.read()
                
                file_data_b64 = base64.b64encode(file_data).decode('utf-8')
                
                message = json.dumps({
                    'type': 'file_transfer',
                    'recipient': recipient_var.get(),
                    'filename': filename,
                    'data': file_data_b64
                })
                
                self.tcp_socket.send(message.encode('utf-8'))
                messagebox.showinfo("Success", "File sent successfully!")
                file_window.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"Could not send file:\n{e}")
        
        button_frame = tk.Frame(file_window)
        button_frame.pack(pady=15)
        
        tk.Button(button_frame, text="Send", command=send_file, width=12, bg='#4CAF50', fg='white', font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Cancel", command=file_window.destroy, width=12, bg='#f44336', fg='white', font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=5)
        
    def handle_file_transfer(self, message):
        from_user = message.get('from', 'Unknown')
        filename = message.get('filename', 'file')
        
        try:
            file_data = base64.b64decode(message['data'])
            
            save_path = filedialog.asksaveasfilename(
                initialfile=filename,
                title=f"Save file from {from_user}"
            )
            
            if save_path:
                with open(save_path, 'wb') as f:
                    f.write(file_data)
                messagebox.showinfo("Success", f"File saved successfully to:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save file:\n{e}")
                
    def on_closing(self):
        # Confirmation dialog
        result = messagebox.askyesno(
            "Leave Meeting", 
            "Are you sure you want to leave the meeting?",
            icon='warning'
        )
        
        if not result:
            return  # User clicked "No", don't close
        
        # User clicked "Yes", proceed with cleanup
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
        self.root.destroy()
        
    def run(self):
        if self.connect():
            self.root.mainloop()

def main():
    root = tk.Tk()
    root.withdraw()
    
    dialog = tk.Toplevel(root)
    dialog.title("Join Conference")
    dialog.geometry("350x250")
    dialog.resizable(True, True)
    
    tk.Label(dialog, text="Conference Login", font=('Arial', 14, 'bold')).pack(pady=15)
    
    tk.Label(dialog, text="Server IP:", font=('Arial', 10)).pack(pady=5)
    server_entry = tk.Entry(dialog, font=('Arial', 10), width=30)
    server_entry.insert(0, "127.0.0.1")
    server_entry.pack(pady=5)
    
    tk.Label(dialog, text="Server Port:", font=('Arial', 10)).pack(pady=5)
    port_entry = tk.Entry(dialog, font=('Arial', 10), width=30)
    port_entry.insert(0, "5555")
    port_entry.pack(pady=5)
    
    tk.Label(dialog, text="Username:", font=('Arial', 10)).pack(pady=5)
    username_entry = tk.Entry(dialog, font=('Arial', 10), width=30)
    username_entry.pack(pady=5)
    
    result = {'server': None, 'port': None, 'username': None}
    
    def connect():
        server = server_entry.get().strip()
        port = port_entry.get().strip()
        username = username_entry.get().strip()
        
        if server and port and username:
            try:
                result['server'] = server
                result['port'] = int(port)
                result['username'] = username
                dialog.destroy()
                root.destroy()
            except ValueError:
                messagebox.showerror("Error", "Invalid port number")
        else:
            messagebox.showwarning("Warning", "Please fill all fields")
    
    tk.Button(dialog, text="Connect", command=connect, width=15, bg='#4CAF50', fg='white', font=('Arial', 11, 'bold')).pack(pady=15)
    
    username_entry.bind('<Return>', lambda e: connect())
    
    dialog.protocol("WM_DELETE_WINDOW", lambda: (dialog.destroy(), root.destroy()))
    
    root.wait_window(dialog)
    
    if result['server'] and result['port'] and result['username']:
        client = ConferenceClient(result['server'], result['port'], result['username'])
        client.run()

if __name__ == "__main__":
    main()