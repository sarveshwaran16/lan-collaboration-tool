import socket
import threading
import json
import time

class ConferenceServer:
    def __init__(self, host='0.0.0.0', port=5555):
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients = {}  # {socket: {'username': str, 'address': tuple, 'video': bool, 'audio': bool}}
        self.running = True
        
    def start(self):
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        print(f"Server started on {self.host}:{self.port}")
        
        while self.running:
            try:
                client_socket, address = self.server_socket.accept()
                print(f"New connection from {address}")
                thread = threading.Thread(target=self.handle_client, args=(client_socket, address))
                thread.daemon = True
                thread.start()
            except Exception as e:
                print(f"Error accepting connection: {e}")
                
    def handle_client(self, client_socket, address):
        try:
            # Receive username
            data = client_socket.recv(4096).decode('utf-8')
            username = json.loads(data)['username']
            
            self.clients[client_socket] = {
                'username': username,
                'address': address,
                'video': False,
                'audio': False
            }
            
            # Send current participants list to new client
            self.send_participant_list(client_socket)
            
            # Notify all clients about new participant
            self.broadcast_participant_update()
            
            while self.running:
                try:
                    data = client_socket.recv(65536)
                    if not data:
                        break
                    
                    # Parse message
                    message = json.loads(data.decode('utf-8'))
                    msg_type = message.get('type')
                    
                    if msg_type == 'video_frame':
                        self.broadcast_video_frame(client_socket, message)
                    elif msg_type == 'audio_frame':
                        self.broadcast_audio_frame(client_socket, message)
                    elif msg_type == 'screen_share':
                        self.broadcast_screen_share(client_socket, message)
                    elif msg_type == 'chat':
                        self.handle_chat(client_socket, message)
                    elif msg_type == 'file_transfer':
                        self.handle_file_transfer(client_socket, message)
                    elif msg_type == 'status_update':
                        self.handle_status_update(client_socket, message)
                    elif msg_type == 'request_participants':
                        self.send_participant_list(client_socket)
                        
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    print(f"Error handling message: {e}")
                    break
                    
        except Exception as e:
            print(f"Error with client {address}: {e}")
        finally:
            self.remove_client(client_socket)
            
    def send_participant_list(self, client_socket):
        participants = []
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
        
        for client_socket in list(self.clients.keys()):
            try:
                client_socket.send(message.encode('utf-8'))
            except:
                pass
                
    def broadcast_video_frame(self, sender_socket, message):
        sender_username = self.clients[sender_socket]['username']
        message['username'] = sender_username
        data = json.dumps(message).encode('utf-8')
        
        for client_socket in list(self.clients.keys()):
            if client_socket != sender_socket:
                try:
                    client_socket.send(data)
                except:
                    pass
                    
    def broadcast_audio_frame(self, sender_socket, message):
        sender_username = self.clients[sender_socket]['username']
        message['username'] = sender_username
        data = json.dumps(message).encode('utf-8')
        
        for client_socket in list(self.clients.keys()):
            if client_socket != sender_socket:
                try:
                    client_socket.send(data)
                except:
                    pass
                    
    def broadcast_screen_share(self, sender_socket, message):
        sender_username = self.clients[sender_socket]['username']
        message['username'] = sender_username
        data = json.dumps(message).encode('utf-8')
        
        for client_socket in list(self.clients.keys()):
            if client_socket != sender_socket:
                try:
                    client_socket.send(data)
                except:
                    pass
                    
    def handle_chat(self, sender_socket, message):
        sender_username = self.clients[sender_socket]['username']
        recipient = message.get('recipient')
        chat_message = message.get('message')
        
        response = {
            'type': 'chat',
            'from': sender_username,
            'message': chat_message,
            'timestamp': time.time()
        }
        
        data = json.dumps(response).encode('utf-8')
        
        if recipient == 'everyone':
            for client_socket in list(self.clients.keys()):
                try:
                    client_socket.send(data)
                except:
                    pass
        else:
            # Send to specific user
            for client_socket, info in self.clients.items():
                if info['username'] == recipient or client_socket == sender_socket:
                    try:
                        client_socket.send(data)
                    except:
                        pass
                        
    def handle_file_transfer(self, sender_socket, message):
        sender_username = self.clients[sender_socket]['username']
        recipient = message.get('recipient')
        
        message['from'] = sender_username
        data = json.dumps(message).encode('utf-8')
        
        if recipient == 'everyone':
            for client_socket in list(self.clients.keys()):
                if client_socket != sender_socket:
                    try:
                        client_socket.send(data)
                    except:
                        pass
        else:
            for client_socket, info in self.clients.items():
                if info['username'] == recipient:
                    try:
                        client_socket.send(data)
                    except:
                        pass
                        
    def handle_status_update(self, client_socket, message):
        if 'video' in message:
            self.clients[client_socket]['video'] = message['video']
        if 'audio' in message:
            self.clients[client_socket]['audio'] = message['audio']
        
        self.broadcast_participant_update()
        
    def remove_client(self, client_socket):
        if client_socket in self.clients:
            username = self.clients[client_socket]['username']
            print(f"Client {username} disconnected")
            del self.clients[client_socket]
            client_socket.close()
            self.broadcast_participant_update()
            
    def stop(self):
        self.running = False
        for client_socket in list(self.clients.keys()):
            client_socket.close()
        self.server_socket.close()

if __name__ == "__main__":
    server = ConferenceServer()
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.stop()