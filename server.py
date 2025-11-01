import socket
import threading
import json
import time

class ConferenceServer:
    def __init__(self, tcp_port=5555, udp_port=5556):
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        self.clients = {}
        self.username_to_udp = {}
        self.running = True
        self.lock = threading.Lock()
        
        # File storage: {filename: {'data': bytes, 'size': int, 'uploaded_by': str}}
        self.files = {}
        
    def start(self):
        self.tcp_socket.bind(('0.0.0.0', self.tcp_port))
        self.tcp_socket.listen(10)
        
        self.udp_socket.bind(('0.0.0.0', self.udp_port))
        
        print(f"Server started on TCP port {self.tcp_port} and UDP port {self.udp_port}")
        
        udp_thread = threading.Thread(target=self.handle_udp)
        udp_thread.daemon = True
        udp_thread.start()
        
        while self.running:
            try:
                client_socket, address = self.tcp_socket.accept()
                print(f"New TCP connection from {address}")
                thread = threading.Thread(target=self.handle_tcp_client, args=(client_socket, address))
                thread.daemon = True
                thread.start()
            except Exception as e:
                if self.running:
                    print(f"Error accepting TCP connection: {e}")
    
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
                    print(f"UDP error: {e}")
    
    def broadcast_udp_exclude_sender(self, data, sender_addr, sender_username):
        with self.lock:
            for username, udp_addr in list(self.username_to_udp.items()):
                if username != sender_username:
                    try:
                        self.udp_socket.sendto(data, udp_addr)
                    except Exception as e:
                        print(f"Error sending UDP to {username}: {e}")
    
    def broadcast_screen_share_udp(self, data, sender_username):
        with self.lock:
            for username, udp_addr in list(self.username_to_udp.items()):
                if username != sender_username:
                    try:
                        self.udp_socket.sendto(data, udp_addr)
                    except Exception as e:
                        print(f"Error sending screen share UDP to {username}: {e}")

    def broadcast_screen_share_tcp(self, data, sender_username):
        """Relay screen-share messages reliably to all clients over TCP."""
        with self.lock:
            for client_socket, info in list(self.clients.items()):
                if info.get('username') != sender_username:
                    try:
                        client_socket.send(data)
                    except Exception as e:
                        print(f"Error sending screen share TCP to {info.get('username')}: {e}")
                
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
            
            print(f"User {username} connected from {address}")
            
            response = json.dumps({
                'type': 'connection_info',
                'udp_port': self.udp_port
            })
            client_socket.send(response.encode('utf-8'))
            
            time.sleep(0.1)
            
            self.send_participant_list(client_socket)
            self.broadcast_participant_update()
            
            buffer = ""
            
            while self.running:
                try:
                    data = client_socket.recv(65536)
                    if not data:
                        print(f"Client {username} disconnected (no data)")
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
                        print(f"Client {username} connection lost (timeout)")
                        break
                    continue
                except ConnectionResetError:
                    print(f"Client {username} connection reset")
                    break
                except ConnectionAbortedError:
                    print(f"Client {username} connection aborted")
                    break
                except Exception as e:
                    print(f"TCP error from {username}: {e}")
                    break
                    
        except Exception as e:
            print(f"Error with client {address}: {e}")
        finally:
            self.remove_client(client_socket, username)
            time.sleep(0.2)
            self.broadcast_participant_update()
            
    def handle_screen_share(self, sender_socket, message):
        with self.lock:
            sender_username = self.clients.get(sender_socket, {}).get('username', 'Unknown')
        
        action = message.get('action')
        
        if action in ['start', 'stop']:
            print(f"Screen share {action} from {sender_username}")
            data = json.dumps(message).encode('utf-8')
            # Broadcast over TCP for higher reliability and larger frames
            self.broadcast_screen_share_tcp(data, sender_username)
        
        elif action == 'frame':
            data = json.dumps(message).encode('utf-8')
            # Broadcast frames over TCP
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
        
        print(f"Chat from {sender_username} to {recipient}: {chat_message}")
        
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
                        print(f"Sent chat to {self.clients[client_socket]['username']}")
                    except Exception as e:
                        print(f"Error sending chat: {e}")
        else:
            with self.lock:
                for client_socket, info in self.clients.items():
                    if info['username'] == recipient or client_socket == sender_socket:
                        try:
                            client_socket.send(data)
                            print(f"Sent private chat to {info['username']}")
                        except Exception as e:
                            print(f"Error sending private chat: {e}")
                        
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
            
            # Store file
            with self.lock:
                self.files[filename] = {
                    'data': file_data,
                    'size': file_size,
                    'uploaded_by': sender_username
                }
            
            print(f"File {filename} uploaded by {sender_username} for {recipient} ({file_size} bytes)")
            
            # Notify recipients
            notification = json.dumps({
                'type': 'file_available',
                'from': sender_username,
                'filename': filename,
                'size': file_size
            }).encode('utf-8')
            
            with self.lock:
                if recipient == 'everyone':
                    # Notify all except sender
                    for client_socket, info in self.clients.items():
                        if info['username'] != sender_username:
                            try:
                                client_socket.send(notification)
                            except:
                                pass
                else:
                    # Notify only the specified recipient
                    for client_socket, info in self.clients.items():
                        if info['username'] == recipient:
                            try:
                                client_socket.send(notification)
                            except:
                                pass
        except Exception as e:
            print(f"Error handling file upload: {e}")
    
    def handle_file_download(self, requester_socket, message):
        import base64
        filename = message.get('filename')
        
        with self.lock:
            if filename in self.files:
                file_info = self.files[filename]
                file_data = file_info['data']
                
                # Send file to requester
                response = json.dumps({
                    'type': 'file_transfer',
                    'from': 'Server',
                    'filename': filename,
                    'data': base64.b64encode(file_data).decode('utf-8')
                }).encode('utf-8')
                
                try:
                    requester_socket.send(response)
                    print(f"File {filename} downloaded by {self.clients[requester_socket]['username']}")
                except Exception as e:
                    print(f"Error sending file: {e}")
            else:
                print(f"File {filename} not found")
    
    def update_status(self, client_socket, message):
        with self.lock:
            if client_socket in self.clients:
                if 'video' in message:
                    self.clients[client_socket]['video'] = message['video']
                if 'audio' in message:
                    self.clients[client_socket]['audio'] = message['audio']
        
        self.broadcast_participant_update()
        
    def remove_client(self, client_socket, username):
        with self.lock:
            if client_socket in self.clients:
                print(f"Client {username} disconnected")
                del self.clients[client_socket]
            
            if username and username in self.username_to_udp:
                del self.username_to_udp[username]
        
        try:
            client_socket.close()
        except:
            pass
        
        self.broadcast_participant_update()
            
    def stop(self):
        # Notify all clients that the server is shutting down
        shutdown_msg = json.dumps({'type': 'server_shutdown'}).encode('utf-8')
        with self.lock:
            for client_socket in list(self.clients.keys()):
                try:
                    client_socket.send(shutdown_msg)
                except:
                    pass
        
        # Give clients a moment to receive the message
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

if __name__ == "__main__":
    server = ConferenceServer()
    print("\n" + "="*50)
    print("Conference Server Started")
    print("="*50)
    print(f"TCP Port: 5555")
    print(f"UDP Port: 5556")
    print("\nPress Ctrl+C to stop the server")
    print("Or type 'quit' and press Enter")
    print("="*50 + "\n")
    
    server_thread = threading.Thread(target=server.start)
    server_thread.daemon = True
    server_thread.start()
    
    try:
        while True:
            try:
                import sys
                import select
                if sys.platform == 'win32':
                    import msvcrt
                    if msvcrt.kbhit():
                        cmd = input().strip().lower()
                        if cmd in ['quit', 'exit', 'q']:
                            print("\nShutting down server...")
                            break
                else:
                    if select.select([sys.stdin], [], [], 1)[0]:
                        cmd = input().strip().lower()
                        if cmd in ['quit', 'exit', 'q']:
                            print("\nShutting down server...")
                            break
            except:
                pass
            
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\n\nShutting down server...")
    finally:
        server.stop()
        print("Server stopped successfully!")
        print("You can now close this window.\n")