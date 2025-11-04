#!/usr/bin/env python3
"""
🖥️ LAN Collaboration Tool - Server GUI
A modern, feature-rich server interface with real-time monitoring
"""

import socket
import threading
import json
import time
import sys
import os
from datetime import datetime, timedelta
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from server import ConferenceServer

class ServerGUI(QMainWindow):
    # Signals for thread-safe GUI updates
    connection_update_signal = pyqtSignal(int, list)
    log_message_signal = pyqtSignal(str, str)  # message, level
    stats_update_signal = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        self.server = None
        self.server_thread = None
        self.server_running = False
        
        # Statistics
        self.start_time = None
        self.total_connections = 0
        self.peak_connections = 0
        self.total_data_mb = 0
        self.connection_times = {}  # username -> start_time
        
        # Settings
        self.tcp_port = 5555
        self.udp_port = 5556
        self.max_clients = 50
        
        # Connect signals
        self.connection_update_signal.connect(self.update_connections_display)
        self.log_message_signal.connect(self.add_log_message)
        self.stats_update_signal.connect(self.update_statistics_display)
        
        self.setup_gui()
        self.load_settings()
        self.update_ip_addresses()
        
    def setup_gui(self):
        """Setup the main GUI layout"""
        self.setWindowTitle("🖥️ LAN Collaboration Server")
        self.setGeometry(100, 50, 1200, 900)
        
        # Main widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Set main window gradient background
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0f2027, stop:0.5 #203a43, stop:1 #2c5364);
            }
        """)
        
        # ===== HEADER SECTION =====
        header = self.create_header()
        main_layout.addWidget(header)
        
        # ===== TOP ROW: Status + Network Config =====
        top_row = QHBoxLayout()
        top_row.setSpacing(15)
        
        status_panel = self.create_status_panel()
        top_row.addWidget(status_panel, stretch=1)
        
        network_panel = self.create_network_panel()
        top_row.addWidget(network_panel, stretch=2)
        
        main_layout.addLayout(top_row)
        
        # ===== MIDDLE ROW: Active Connections + Statistics =====
        middle_row = QHBoxLayout()
        middle_row.setSpacing(15)
        
        connections_panel = self.create_connections_panel()
        middle_row.addWidget(connections_panel, stretch=3)
        
        stats_panel = self.create_statistics_panel()
        middle_row.addWidget(stats_panel, stretch=2)
        
        main_layout.addLayout(middle_row)
        
        # ===== ACTIVITY LOG =====
        log_panel = self.create_activity_log_panel()
        main_layout.addWidget(log_panel, stretch=1)
        
        # ===== SETTINGS PANEL =====
        settings_panel = self.create_settings_panel()
        main_layout.addWidget(settings_panel)
        
        # Start update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_statistics)
        self.update_timer.start(1000)  # Update every second
        
    def create_header(self):
        """Create the header with title and logo"""
        header = QLabel("🖥️  LAN Collaboration Server Control Panel")
        header.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
                color: white;
                font-size: 24px;
                font-weight: bold;
                padding: 20px;
                border-radius: 12px;
            }
        """)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return header
        
    def create_status_panel(self):
        """Create server status panel with start/stop buttons"""
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0f0c29, stop:0.5 #302b63, stop:1 #24243e);
                border-radius: 12px;
                border: 2px solid #667eea;
            }
        """)
        panel.setMinimumHeight(250)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Title
        title = QLabel("⚡ SERVER STATUS")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: white; background: transparent; border: none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Status indicator
        self.status_indicator = QLabel("🔴 STOPPED")
        self.status_indicator.setStyleSheet("""
            font-size: 36px;
            font-weight: bold;
            color: #ff4444;
            background: transparent;
            border: none;
            padding: 15px;
        """)
        self.status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_indicator)
        
        # Start button
        self.start_btn = QPushButton("▶️  START SERVER")
        self.start_btn.clicked.connect(self.start_server)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setMinimumHeight(50)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #56ab2f, stop:1 #a8e063);
                color: white;
                border: none;
                border-radius: 10px;
                padding: 12px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #a8e063, stop:1 #56ab2f);
            }
            QPushButton:pressed {
                background: #4a9626;
            }
            QPushButton:disabled {
                background: #555555;
                color: #888888;
            }
        """)
        layout.addWidget(self.start_btn)
        
        # Stop button
        self.stop_btn = QPushButton("⏹️  STOP SERVER")
        self.stop_btn.clicked.connect(self.stop_server)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumHeight(50)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #eb3349, stop:1 #f45c43);
                color: white;
                border: none;
                border-radius: 10px;
                padding: 12px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f45c43, stop:1 #eb3349);
            }
            QPushButton:pressed {
                background: #d32f2f;
            }
            QPushButton:disabled {
                background: #555555;
                color: #888888;
            }
        """)
        layout.addWidget(self.stop_btn)
        
        layout.addStretch()
        
        return panel
        
    def create_network_panel(self):
        """Create network configuration panel"""
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0f0c29, stop:0.5 #302b63, stop:1 #24243e);
                border-radius: 12px;
                border: 2px solid #667eea;
            }
        """)
        panel.setMinimumHeight(250)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Title
        title = QLabel("🌐 NETWORK CONFIGURATION")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: white; background: transparent; border: none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # IP Address (LAN only - big and visible)
        ip_label = QLabel("📡 Server LAN IP:")
        ip_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #aaaaaa; background: transparent; border: none;")
        layout.addWidget(ip_label)
        
        self.ip_display = QLabel("Detecting...")
        self.ip_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ip_display.setStyleSheet("""
            QLabel {
                background: rgba(255, 255, 255, 0.1);
                color: #4ade80;
                border: 2px solid rgba(102, 126, 234, 0.5);
                border-radius: 10px;
                padding: 15px;
                font-size: 24px;
                font-weight: bold;
                font-family: monospace;
            }
        """)
        self.ip_display.setMinimumHeight(70)
        layout.addWidget(self.ip_display)
        
        # Refresh IP button
        refresh_ip_btn = QPushButton("🔄 Refresh IP")
        refresh_ip_btn.clicked.connect(self.update_ip_addresses)
        refresh_ip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_ip_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #764ba2, stop:1 #667eea);
            }
        """)
        layout.addWidget(refresh_ip_btn)
        
        # Port configuration
        port_layout = QHBoxLayout()
        
        # TCP Port
        tcp_layout = QVBoxLayout()
        tcp_label = QLabel("🔌 TCP Port:")
        tcp_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #aaaaaa; background: transparent; border: none;")
        tcp_layout.addWidget(tcp_label)
        
        self.tcp_port_input = QLineEdit(str(self.tcp_port))
        self.tcp_port_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tcp_port_input.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.15);
                color: white;
                border: 2px solid rgba(102, 126, 234, 0.5);
                border-radius: 8px;
                padding: 12px;
                font-size: 18px;
                font-weight: bold;
            }
        """)
        tcp_layout.addWidget(self.tcp_port_input)
        port_layout.addLayout(tcp_layout)
        
        # UDP Port
        udp_layout = QVBoxLayout()
        udp_label = QLabel("🔌 UDP Port:")
        udp_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #aaaaaa; background: transparent; border: none;")
        udp_layout.addWidget(udp_label)
        
        self.udp_port_input = QLineEdit(str(self.udp_port))
        self.udp_port_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.udp_port_input.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.15);
                color: white;
                border: 2px solid rgba(102, 126, 234, 0.5);
                border-radius: 8px;
                padding: 12px;
                font-size: 18px;
                font-weight: bold;
            }
        """)
        udp_layout.addWidget(self.udp_port_input)
        port_layout.addLayout(udp_layout)
        
        layout.addLayout(port_layout)
        
        return panel
        
    def create_connections_panel(self):
        """Create active connections panel"""
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0f0c29, stop:0.5 #302b63, stop:1 #24243e);
                border-radius: 12px;
                border: 2px solid #667eea;
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Title with counter
        header_layout = QHBoxLayout()
        title = QLabel("👥 ACTIVE CONNECTIONS:")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: white; background: transparent; border: none;")
        header_layout.addWidget(title)
        
        self.connection_counter = QLabel("0")
        self.connection_counter.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #888888;
            background: transparent;
            border: none;
        """)
        header_layout.addWidget(self.connection_counter)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        # Connections list table
        self.connections_table = QTableWidget()
        self.connections_table.setColumnCount(5)
        self.connections_table.setHorizontalHeaderLabels(["👤 Username", "📡 IP Address", "⏱️ Duration", "🎥 Video", "🎤 Audio"])
        self.connections_table.horizontalHeader().setStretchLastSection(True)
        self.connections_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.connections_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.connections_table.setStyleSheet("""
            QTableWidget {
                background: rgba(255, 255, 255, 0.05);
                color: white;
                border: 2px solid rgba(102, 126, 234, 0.3);
                border-radius: 8px;
                gridline-color: rgba(102, 126, 234, 0.2);
            }
            QTableWidget::item {
                padding: 8px;
            }
            QTableWidget::item:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
            }
            QHeaderView::section {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
                color: white;
                padding: 8px;
                border: none;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        
        # Set column widths
        header = self.connections_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        
        layout.addWidget(self.connections_table)
        
        return panel
        
    def create_statistics_panel(self):
        """Create statistics panel"""
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0f0c29, stop:0.5 #302b63, stop:1 #24243e);
                border-radius: 12px;
                border: 2px solid #667eea;
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Title
        title = QLabel("📊 STATISTICS")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: white; background: transparent; border: none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Stats grid
        stats_widget = QWidget()
        stats_widget.setStyleSheet("background: transparent; border: none;")
        stats_layout = QGridLayout(stats_widget)
        stats_layout.setSpacing(15)
        
        # Uptime
        self.uptime_label = self.create_stat_item("⏱️ Uptime", "00:00:00")
        stats_layout.addWidget(self.uptime_label, 0, 0)
        
        # Total connections
        self.total_conn_label = self.create_stat_item("📈 Total Sessions", "0")
        stats_layout.addWidget(self.total_conn_label, 0, 1)
        
        # Peak connections
        self.peak_conn_label = self.create_stat_item("🔝 Peak Users", "0")
        stats_layout.addWidget(self.peak_conn_label, 1, 0)
        
        # Data transferred
        self.data_transfer_label = self.create_stat_item("📊 Data Transfer", "0 MB")
        stats_layout.addWidget(self.data_transfer_label, 1, 1)
        
        # Screen sharing
        self.screen_share_label = self.create_stat_item("🖥️ Presenter", "None")
        stats_layout.addWidget(self.screen_share_label, 2, 0, 1, 2)
        
        layout.addWidget(stats_widget)
        layout.addStretch()
        
        return panel
        
    def create_stat_item(self, label_text, value_text):
        """Create a stat display item"""
        widget = QWidget()
        widget.setStyleSheet("""
            QWidget {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(102, 126, 234, 0.3);
                border-radius: 8px;
                padding: 10px;
            }
        """)
        
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        
        label = QLabel(label_text)
        label.setStyleSheet("font-size: 10px; color: #aaaaaa; background: transparent; border: none;")
        layout.addWidget(label)
        
        value = QLabel(value_text)
        value.setStyleSheet("font-size: 16px; font-weight: bold; color: #4ade80; background: transparent; border: none;")
        value.setObjectName("stat_value")
        layout.addWidget(value)
        
        return widget
        
    def create_activity_log_panel(self):
        """Create activity log panel"""
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0f0c29, stop:0.5 #302b63, stop:1 #24243e);
                border-radius: 12px;
                border: 2px solid #667eea;
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Header with buttons
        header_layout = QHBoxLayout()
        
        title = QLabel("📋 ACTIVITY LOG")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: white; background: transparent; border: none;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Clear button
        clear_btn = QPushButton("🗑️ Clear")
        clear_btn.clicked.connect(self.clear_log)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #eb3349, stop:1 #f45c43);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 15px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f45c43, stop:1 #eb3349);
            }
        """)
        header_layout.addWidget(clear_btn)
        
        # Save button
        save_btn = QPushButton("💾 Save")
        save_btn.clicked.connect(self.save_log)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 15px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #764ba2, stop:1 #667eea);
            }
        """)
        header_layout.addWidget(save_btn)
        
        layout.addLayout(header_layout)
        
        # Log display
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setStyleSheet("""
            QTextEdit {
                background: rgba(0, 0, 0, 0.3);
                color: #dddddd;
                border: 2px solid rgba(102, 126, 234, 0.3);
                border-radius: 8px;
                padding: 10px;
                font-size: 11px;
                font-family: monospace;
            }
        """)
        layout.addWidget(self.log_display)
        
        return panel
        
    def create_settings_panel(self):
        """Create settings panel"""
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0f0c29, stop:0.5 #302b63, stop:1 #24243e);
                border-radius: 12px;
                border: 2px solid #667eea;
            }
        """)
        panel.setMaximumHeight(100)
        
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)
        
        # Max clients
        max_label = QLabel("👥 Max Clients:")
        max_label.setStyleSheet("font-size: 12px; color: white; background: transparent; border: none;")
        layout.addWidget(max_label)
        
        self.max_clients_input = QSpinBox()
        self.max_clients_input.setRange(1, 100)
        self.max_clients_input.setValue(self.max_clients)
        self.max_clients_input.setStyleSheet("""
            QSpinBox {
                background: rgba(255, 255, 255, 0.15);
                color: white;
                border: 2px solid rgba(102, 126, 234, 0.5);
                border-radius: 8px;
                padding: 5px;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.max_clients_input)
        
        layout.addStretch()
        
        # Save settings button
        save_settings_btn = QPushButton("💾 Save Settings")
        save_settings_btn.clicked.connect(self.save_settings)
        save_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_settings_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #56ab2f, stop:1 #a8e063);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #a8e063, stop:1 #56ab2f);
            }
        """)
        layout.addWidget(save_settings_btn)
        
        return panel
        
    def update_ip_addresses(self):
        """Get and display LAN IP address only"""
        lan_ip = "Not Found"
        
        try:
            # Try to get LAN IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                # Connect to external address (doesn't actually send data)
                s.connect(('10.255.255.255', 1))
                lan_ip = s.getsockname()[0]
            except:
                # Fallback: try to get from hostname
                try:
                    host_ips = socket.gethostbyname_ex(socket.gethostname())[2]
                    for ip in host_ips:
                        if ip != "127.0.0.1":
                            lan_ip = ip
                            break
                except:
                    pass
            finally:
                s.close()
                
        except Exception as e:
            lan_ip = f"Error: {e}"
        
        # Display only LAN IP in large text
        self.ip_display.setText(lan_ip)
        self.log_message(f"LAN IP: {lan_ip}", "info")
        
    def start_server(self):
        """Start the conference server"""
        if self.server_running:
            return
            
        # Get port values
        try:
            tcp_port = int(self.tcp_port_input.text())
            udp_port = int(self.udp_port_input.text())
        except ValueError:
            QMessageBox.critical(self, "Error", "Invalid port numbers!")
            return
            
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        
        # Create server instance
        self.server = EnhancedConferenceServer(
            tcp_port=self.tcp_port,
            udp_port=self.udp_port,
            gui_callback=self
        )
        
        # Start server in thread
        self.server_thread = threading.Thread(target=self.server.start, daemon=True)
        self.server_thread.start()
        
        # Update UI
        self.server_running = True
        self.start_time = datetime.now()
        self.status_indicator.setText("🟢 RUNNING")
        self.status_indicator.setStyleSheet("""
            font-size: 36px;
            font-weight: bold;
            color: #4ade80;
            background: transparent;
            border: none;
            padding: 15px;
        """)
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.tcp_port_input.setEnabled(False)
        self.udp_port_input.setEnabled(False)
        
        self.log_message(f"✅ Server started on TCP:{self.tcp_port} UDP:{self.udp_port}", "success")
        
    def stop_server(self):
        """Stop the conference server"""
        if not self.server_running:
            return
            
        # Stop server
        if self.server:
            self.server.stop()
            
        # Update UI
        self.server_running = False
        self.status_indicator.setText("🔴 STOPPED")
        self.status_indicator.setStyleSheet("""
            font-size: 36px;
            font-weight: bold;
            color: #ff4444;
            background: transparent;
            border: none;
            padding: 15px;
        """)
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.tcp_port_input.setEnabled(True)
        self.udp_port_input.setEnabled(True)
        
        self.log_message("🛑 Server stopped", "warning")
        
        # Clear connections
        self.connections_table.setRowCount(0)
        self.connection_counter.setText("0")
        self.connection_counter.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #888888;
            background: transparent;
            border: none;
        """)
        
    def update_connections_display(self, count, clients_data):
        """Update the connections display"""
        # Update counter
        self.connection_counter.setText(str(count))
        if count > 0:
            self.connection_counter.setStyleSheet("""
                font-size: 18px;
                font-weight: bold;
                color: #4ade80;
                background: transparent;
                border: none;
            """)
        else:
            self.connection_counter.setStyleSheet("""
                font-size: 18px;
                font-weight: bold;
                color: #888888;
                background: transparent;
                border: none;
            """)
        
        # Update table
        self.connections_table.setRowCount(len(clients_data))
        
        for row, client in enumerate(clients_data):
            # Username
            username_item = QTableWidgetItem(client['username'])
            username_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.connections_table.setItem(row, 0, username_item)
            
            # IP Address
            ip_item = QTableWidgetItem(client['ip'])
            ip_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.connections_table.setItem(row, 1, ip_item)
            
            # Duration
            duration = client.get('duration', '00:00:00')
            duration_item = QTableWidgetItem(duration)
            duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.connections_table.setItem(row, 2, duration_item)
            
            # Video status
            video_status = "🎥" if client.get('video', False) else "❌"
            video_item = QTableWidgetItem(video_status)
            video_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.connections_table.setItem(row, 3, video_item)
            
            # Audio status
            audio_status = "🎤" if client.get('audio', False) else "❌"
            audio_item = QTableWidgetItem(audio_status)
            audio_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.connections_table.setItem(row, 4, audio_item)
        
        # Update statistics
        if count > self.peak_connections:
            self.peak_connections = count
            
    def update_statistics(self):
        """Update statistics display"""
        if not self.server_running or not self.start_time:
            return
            
        # Calculate uptime
        uptime = datetime.now() - self.start_time
        hours = int(uptime.total_seconds() // 3600)
        minutes = int((uptime.total_seconds() % 3600) // 60)
        seconds = int(uptime.total_seconds() % 60)
        uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        # Update stats
        stats = {
            'uptime': uptime_str,
            'total_connections': self.total_connections,
            'peak_connections': self.peak_connections,
            'data_transfer': f"{self.total_data_mb:.1f} MB",
            'presenter': self.server.current_presenter if self.server else "None"
        }
        
        self.stats_update_signal.emit(stats)
        
        # Update connection durations
        if self.server:
            clients_data = []
            for client_socket, info in list(self.server.clients.items()):
                username = info['username']
                
                # Track connection time
                if username not in self.connection_times:
                    self.connection_times[username] = datetime.now()
                
                duration = datetime.now() - self.connection_times[username]
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                seconds = int(duration.total_seconds() % 60)
                duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                
                clients_data.append({
                    'username': username,
                    'ip': info['address'][0],
                    'duration': duration_str,
                    'video': info.get('video', False),
                    'audio': info.get('audio', False)
                })
            
            self.connection_update_signal.emit(len(clients_data), clients_data)
        
    def update_statistics_display(self, stats):
        """Update statistics labels"""
        # Uptime
        uptime_value = self.uptime_label.findChild(QLabel, "stat_value")
        if uptime_value:
            uptime_value.setText(stats['uptime'])
        
        # Total connections
        total_value = self.total_conn_label.findChild(QLabel, "stat_value")
        if total_value:
            total_value.setText(str(stats['total_connections']))
        
        # Peak connections
        peak_value = self.peak_conn_label.findChild(QLabel, "stat_value")
        if peak_value:
            peak_value.setText(str(stats['peak_connections']))
        
        # Data transfer
        data_value = self.data_transfer_label.findChild(QLabel, "stat_value")
        if data_value:
            data_value.setText(stats['data_transfer'])
        
        # Presenter
        presenter_value = self.screen_share_label.findChild(QLabel, "stat_value")
        if presenter_value:
            presenter_text = stats['presenter'] if stats['presenter'] else "None"
            presenter_value.setText(presenter_text)
            if stats['presenter']:
                presenter_value.setStyleSheet("font-size: 16px; font-weight: bold; color: #f2994a; background: transparent; border: none;")
            else:
                presenter_value.setStyleSheet("font-size: 16px; font-weight: bold; color: #4ade80; background: transparent; border: none;")
        
    def add_log_message(self, message, level="info"):
        """Add a message to the activity log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Color based on level
        if level == "error":
            color = "#ff4444"
            icon = "❌"
        elif level == "warning":
            color = "#f2994a"
            icon = "⚠️"
        elif level == "success":
            color = "#4ade80"
            icon = "✅"
        else:
            color = "#dddddd"
            icon = "ℹ️"
        
        formatted_message = f'<span style="color: #888888;">[{timestamp}]</span> <span style="color: {color};">{icon} {message}</span>'
        
        self.log_display.append(formatted_message)
        
        # Auto-scroll to bottom
        scrollbar = self.log_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
    def log_message(self, message, level="info"):
        """Thread-safe log message"""
        self.log_message_signal.emit(message, level)
        
    def clear_log(self):
        """Clear the activity log"""
        reply = QMessageBox.question(
            self,
            "Clear Log",
            "Are you sure you want to clear the activity log?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.log_display.clear()
            self.log_message("Log cleared", "info")
        
    def save_log(self):
        """Save activity log to file"""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Activity Log",
            f"server_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.log_display.toPlainText())
                self.log_message(f"Log saved to {filename}", "success")
                QMessageBox.information(self, "Success", f"Log saved to:\n{filename}")
            except Exception as e:
                self.log_message(f"Error saving log: {e}", "error")
                QMessageBox.critical(self, "Error", f"Could not save log:\n{e}")
        
    def save_settings(self):
        """Save settings to config file"""
        settings = {
            'tcp_port': int(self.tcp_port_input.text()),
            'udp_port': int(self.udp_port_input.text()),
            'max_clients': self.max_clients_input.value()
        }
        
        try:
            with open('server_config.json', 'w') as f:
                json.dump(settings, f, indent=4)
            self.log_message("Settings saved", "success")
            QMessageBox.information(self, "Success", "Settings saved successfully!")
        except Exception as e:
            self.log_message(f"Error saving settings: {e}", "error")
            QMessageBox.critical(self, "Error", f"Could not save settings:\n{e}")
        
    def load_settings(self):
        """Load settings from config file"""
        try:
            if os.path.exists('server_config.json'):
                with open('server_config.json', 'r') as f:
                    settings = json.load(f)
                    
                self.tcp_port = settings.get('tcp_port', 5555)
                self.udp_port = settings.get('udp_port', 5556)
                self.max_clients = settings.get('max_clients', 50)
                
                self.tcp_port_input.setText(str(self.tcp_port))
                self.udp_port_input.setText(str(self.udp_port))
                self.max_clients_input.setValue(self.max_clients)
                
                self.log_message("Settings loaded", "success")
        except Exception as e:
            self.log_message(f"Could not load settings: {e}", "warning")
        
    def closeEvent(self, event):
        """Handle window close"""
        if self.server_running:
            reply = QMessageBox.question(
                self,
                "Confirm Exit",
                "Server is still running. Stop server and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_server()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


class EnhancedConferenceServer(ConferenceServer):
    """Extended ConferenceServer with GUI callbacks"""
    
    def __init__(self, tcp_port=5555, udp_port=5556, gui_callback=None):
        super().__init__(tcp_port, udp_port)
        self.gui = gui_callback
        
    def handle_tcp_client(self, client_socket, address):
        """Override to add GUI logging"""
        username = None
        try:
            result = super().handle_tcp_client(client_socket, address)
            return result
        except Exception as e:
            if self.gui:
                self.gui.log_message(f"Client error: {e}", "error")
            raise
            
    def remove_client(self, client_socket, username):
        """Override to add GUI logging and update connection count"""
        super().remove_client(client_socket, username)
        
        if self.gui and username:
            self.gui.log_message(f"👋 {username} disconnected", "info")
            
            # Remove from connection times
            if username in self.gui.connection_times:
                del self.gui.connection_times[username]
            
    def handle_tcp_client(self, client_socket, address):
        """Override with GUI integration"""
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
            
            # Log to GUI
            if self.gui:
                self.gui.log_message(f"👤 {username} connected from {address[0]}", "success")
                self.gui.total_connections += 1
                self.gui.connection_times[username] = datetime.now()
            
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
                        break
                    
                    buffer += data.decode('utf-8')
                    
                    while True:
                        try:
                            message, idx = json.JSONDecoder().raw_decode(buffer)
                            buffer = buffer[idx:].lstrip()
                            
                            msg_type = message.get('type')
                            
                            if msg_type == 'chat':
                                self.route_chat(client_socket, message)
                                if self.gui:
                                    recipient = message.get('recipient', 'everyone')
                                    self.gui.log_message(f"💬 {username} → {recipient}", "info")
                            elif msg_type == 'file_transfer':
                                self.route_file(client_socket, message)
                            elif msg_type == 'file_upload':
                                self.handle_file_upload(client_socket, message)
                                if self.gui:
                                    filename = message.get('filename', 'file')
                                    self.gui.log_message(f"📁 {username} uploaded {filename}", "info")
                            elif msg_type == 'file_download':
                                self.handle_file_download(client_socket, message)
                            elif msg_type == 'status_update':
                                self.update_status(client_socket, message)
                            elif msg_type == 'screen_share':
                                action = message.get('action')
                                if self.gui and action in ['start', 'stop']:
                                    if action == 'start':
                                        self.gui.log_message(f"🖥️ {username} started screen sharing", "info")
                                    else:
                                        self.gui.log_message(f"🖥️ {username} stopped screen sharing", "info")
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
                        break
                    continue
                except ConnectionResetError:
                    break
                except ConnectionAbortedError:
                    break
                except Exception as e:
                    if self.gui:
                        self.gui.log_message(f"Error from {username}: {e}", "error")
                    break
                    
        except Exception as e:
            if self.gui:
                self.gui.log_message(f"Connection error from {address}: {e}", "error")
        finally:
            self.remove_client(client_socket, username)
            time.sleep(0.2)
            self.broadcast_participant_update()


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Set dark palette
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
    app.setPalette(palette)
    
    # Create and show GUI
    gui = ServerGUI()
    gui.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
