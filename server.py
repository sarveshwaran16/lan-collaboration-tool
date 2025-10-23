import socket
import threading
import json
import time

class ConferenceServer:
    def __init__(self, tcp_port=5555, udp_port=5556):
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        
        # TCP Socket for control messages
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # UDP Socket for media streaming
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        self.clients = {}  # {tcp_socket: {'username': str, 'address': tuple, 'udp_address': tuple, 'video': bool, 'audio': bool}}
        self.username_to_udp = {}  # {username: udp_address}
        self.running = True
        self.lock = threading.Lock()
        
    def start(self):
        self.tcp_socket.bind(('0.0.0.0', self.tcp_port))
        self.tcp_socket.listen(10)
        
        self.udp_socket.bind(('0.0.0.0', self.udp_port))
        
        print(f"Server started on TCP port {self.tcp_port} and UDP port {self.udp_port}")
        
        # Start UDP receiver thread
        udp_thread = threading.Thread(target=self.handle_udp)
        udp_thread.daemon = True
        udp_thread.start()
        
        # Accept TCP connections
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
        """Handle all UDP media packets"""
        while self.running:
            try:
                data, addr = self.udp_socket.recvfrom(65536)
                message = json.loads(data.decode('utf-8'))
                msg_type = message.get('type')
                username = message.get('username')
                
                # Register UDP address for this user
                if username:
                    with self.lock:
                        self.username_to_udp[username] = addr
                
                # Broadcast to all other clients
                if msg_type in ['video_frame', 'audio_frame', 'screen_share']:
                    self.broadcast_udp(data, addr, username)
                    
            except json.JSONDecodeError:
                continue
            except Exception as e:
                if self.running:
                    print(f"UDP error: {e}")
    
    def broadcast_udp(self, data, sender_addr, sender_username):
        """Broadcast UDP packet to all clients except sender"""
        with self.lock:
            for username, udp_addr in self.username_to_udp.items():
                if username != sender_username and udp_addr != sender_addr:
                    try:
                        self.udp_socket.sendto(data, udp_addr)
                    except Exception as e:
                        print(f"Error sending UDP to {username}: {e}")
                
    def handle_tcp_client(self, client_socket, address):
        username = None
        try:
            client_socket.settimeout(60.0)
            
            # Receive username and UDP info
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
            
            # Send UDP port info and current participants
            response = json.dumps({
                'type': 'connection_info',
                'udp_port': self.udp_port
            })
            client_socket.send(response.encode('utf-8'))
            
            time.sleep(0.1)
            
            self.send_participant_list(client_socket)
            self.broadcast_participant_update()
            
            # Handle TCP messages (chat, files, status)
            while self.running:
                try:
                    data = client_socket.recv(65536)
                    if not data:
                        print(f"Client {username} disconnected (no data)")
                        break
                    
                    message = json.loads(data.decode('utf-8'))
                    msg_type = message.get('type')
                    
                    if msg_type == 'chat':
                        self.route_chat(client_socket, message)
                    elif msg_type == 'file_transfer':
                        self.route_file(client_socket, message)
                    elif msg_type == 'status_update':
                        self.update_status(client_socket, message)
                        
                except socket.timeout:
                    continue
                except ConnectionResetError:
                    print(f"Client {username} connection reset")
                    break
                except ConnectionAbortedError:
                    print(f"Client {username} connection aborted")
                    break
                except json.JSONDecodeError as e:
                    print(f"JSON error from {username}: {e}")
                    continue
                except Exception as e:
                    print(f"TCP error from {username}: {e}")
                    break
                    
        except Exception as e:
            print(f"Error with client {address}: {e}")
        finally:
            self.remove_client(client_socket, username)
            
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
            # Broadcast to all clients
            with self.lock:
                for client_socket in list(self.clients.keys()):
                    try:
                        client_socket.send(data)
                        print(f"Sent chat to {self.clients[client_socket]['username']}")
                    except Exception as e:
                        print(f"Error sending chat: {e}")
        else:
            # Send to specific recipient and sender (for confirmation)
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
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.stop()