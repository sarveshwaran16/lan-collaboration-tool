# 🖥️ Server GUI Documentation

## Overview

The LAN Collaboration Tool now includes a comprehensive **Server GUI** that provides real-time monitoring, statistics, and control over your conference server.

## Features

### 🌐 Network Configuration
- **Auto IP Detection**: Automatically detects and displays all network interfaces
  - Localhost (127.0.0.1)
  - LAN IP addresses
  - All available network interfaces
- **Port Configuration**: Set custom TCP and UDP ports before starting
- **Refresh IP**: Update IP addresses on demand

### ⚡ Server Status & Controls
- **Visual Status Indicator**: 
  - 🔴 Red = Stopped
  - 🟢 Green = Running
- **Start Server Button**: Starts the server with configured ports
- **Stop Server Button**: Gracefully stops server and disconnects all clients
- **Port Locking**: Ports cannot be changed while server is running

### 👥 Active Connections Monitor
- **Real-time Client List**: Table showing all connected clients
- **Connection Details**:
  - Username
  - IP Address
  - Connection Duration (HH:MM:SS)
  - Video Status (🎥 or ❌)
  - Audio Status (🎤 or ❌)
- **Connection Counter**: Shows total active connections with color coding
  - Green when clients are connected
  - Gray when no connections

### 📊 Statistics Dashboard
- **Uptime**: Total server running time
- **Total Sessions**: Cumulative connection count since server start
- **Peak Users**: Maximum concurrent connections reached
- **Data Transfer**: Total data transferred (MB/GB)
- **Current Presenter**: Shows who is screen sharing (if any)

### 📋 Activity Log
- **Real-time Event Logging**:
  - ✅ Server start/stop events (green)
  - 👤 Client connections/disconnections (white)
  - 💬 Chat messages
  - 📁 File uploads/downloads
  - 🖥️ Screen sharing events
  - ❌ Errors (red)
  - ⚠️ Warnings (orange)
- **Log Controls**:
  - 🗑️ Clear log
  - 💾 Save log to file (with timestamp)
- **Auto-scroll**: Automatically scrolls to latest events

### ⚙️ Settings Panel
- **Max Clients**: Set maximum allowed concurrent connections (1-100)
- **Save Settings**: Persist configuration to `server_config.json`
- **Auto-load**: Settings automatically load on startup

## How to Use

### Starting the Server GUI

#### Option 1: Using the Launch Script
```bash
./start_server_gui.sh
```

#### Option 2: Direct Python Command
```bash
python3 server_gui.py
```

### Configuration Steps

1. **Set Ports** (Optional - defaults are 5555/5556):
   - Enter TCP port in the "TCP Port" field
   - Enter UDP port in the "UDP Port" field

2. **Review IP Addresses**:
   - Check the "Server IP Addresses" section
   - Click "🔄 Refresh IP" if needed
   - Share the appropriate IP with clients

3. **Configure Settings** (Optional):
   - Set maximum clients limit
   - Click "💾 Save Settings" to persist

4. **Start Server**:
   - Click "▶️ START SERVER"
   - Status will change to 🟢 RUNNING
   - Ports become locked (cannot change while running)

5. **Monitor Connections**:
   - Watch the "Active Connections" table populate as clients join
   - View real-time statistics
   - Check activity log for events

6. **Stop Server**:
   - Click "⏹️ STOP SERVER"
   - All clients will be gracefully disconnected
   - Server returns to STOPPED state

## Visual Design

The Server GUI matches the client's modern gradient theme:

- **Color Scheme**: Purple-blue gradients with accent colors
- **Status Colors**:
  - 🟢 Green: Running/Active/Success
  - 🔴 Red: Stopped/Error
  - 🟡 Yellow/Orange: Warning
  - White/Gray: Info/Neutral
- **Glassmorphism**: Semi-transparent panels with modern aesthetics
- **Gradient Buttons**: Matching the client UI style

## Configuration File

Settings are saved to `server_config.json`:

```json
{
    "tcp_port": 5555,
    "udp_port": 5556,
    "max_clients": 50
}
```

This file is automatically created when you save settings and loaded on startup.

## Activity Log Export

Logs can be exported to a timestamped text file:
- Format: `server_log_YYYYMMDD_HHMMSS.txt`
- Contains plain text version of all log entries
- Useful for debugging and record-keeping

## Statistics Tracking

The GUI tracks:
- **Uptime**: Continuously updated while server is running
- **Total Sessions**: Increments each time a client connects
- **Peak Users**: Highest number of concurrent users
- **Data Transfer**: Estimated based on message size
- **Connection Duration**: Per-client tracking in real-time

## Window Layout

```
┌──────────────────────────────────────────────────┐
│  🖥️  LAN Collaboration Server Control Panel    │
├──────────────────────────────────────────────────┤
│  ┌────────────┐  ┌──────────────────────────┐   │
│  │  STATUS    │  │  NETWORK CONFIG          │   │
│  │  🟢 RUNNING│  │  IPs, Ports             │   │
│  │  [START]   │  │                          │   │
│  │  [STOP]    │  │                          │   │
│  └────────────┘  └──────────────────────────┘   │
│  ┌──────────────────────────────────────────┐   │
│  │  ACTIVE CONNECTIONS: 3                   │   │
│  │  Table with client details...            │   │
│  └──────────────────────────────────────────┘   │
│  ┌─────────────────┐  ┌──────────────────┐     │
│  │  STATISTICS     │  │                   │     │
│  └─────────────────┘  └──────────────────┘     │
│  ┌──────────────────────────────────────────┐   │
│  │  ACTIVITY LOG                            │   │
│  │  [Clear] [Save]                          │   │
│  │  Event messages...                       │   │
│  └──────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────┐   │
│  │  SETTINGS                                │   │
│  └──────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

## Troubleshooting

### GUI Won't Start
- **Check Python**: Ensure Python 3.8+ is installed
- **Check PyQt6**: Run `pip install PyQt6`
- **Check Display**: Ensure X11/Wayland is running

### Ports Already in Use
- Check if another server instance is running
- Try different port numbers
- Use `lsof -i :5555` to see what's using the port

### IP Addresses Not Showing
- Click "🔄 Refresh IP" button
- Check network connection
- Ensure network interfaces are up

### Clients Can't Connect
- Verify server is in RUNNING state (🟢)
- Check firewall settings
- Ensure clients use correct IP and port
- Try localhost (127.0.0.1) for same-machine testing

## Advanced Usage

### Running on Different Ports
1. Stop server if running
2. Change TCP/UDP port values
3. Save settings
4. Start server
5. Update client connections to use new ports

### Monitoring Multiple Sessions
- Activity log shows complete history
- Export logs periodically for record-keeping
- Statistics persist for current server session

### Maximum Performance
- Set max clients based on your hardware
- Monitor the activity log for errors
- Check system resources when many clients connect

## Integration with Existing Server

The GUI wraps the existing `server.py` ConferenceServer class with additional monitoring and logging. The core functionality remains the same, with added benefits:

- Non-intrusive logging
- Thread-safe GUI updates
- Graceful shutdown handling
- Enhanced error reporting

## Tips & Best Practices

1. **Save Settings**: Always save your preferred configuration
2. **Monitor Logs**: Keep an eye on the activity log for issues
3. **Export Logs**: Save logs before clearing for future reference
4. **Check Statistics**: Use statistics to understand usage patterns
5. **Graceful Shutdown**: Always use STOP button, not window close

## Future Enhancements

Potential features for future versions:
- Bandwidth usage graphs
- Per-client data usage
- Ban/whitelist management
- Remote administration
- Multi-server orchestration
- Advanced analytics

---

**Enjoy your professional server management experience! 🎉**
