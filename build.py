import subprocess
import sys
import os

REQUIREMENTS = 'requirements.txt'
SERVER_SCRIPT = 'server.py'
CLIENT_SCRIPT = 'client.py'

PYINSTALLER_CMD = [sys.executable, '-m', 'pip', 'show', 'pyinstaller']
PYINSTALLER_INSTALL = [sys.executable, '-m', 'pip', 'install', 'pyinstaller']


def install_requirements():
    print('Installing dependencies from requirements.txt...')
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', REQUIREMENTS], check=False)
    if result.returncode != 0:
        print('Failed to install dependencies. Please check your requirements.txt.')
        sys.exit(1)


def ensure_pyinstaller():
    print('Checking for PyInstaller...')
    result = subprocess.run(PYINSTALLER_CMD, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print('PyInstaller is not installed. Installing PyInstaller...')
        result = subprocess.run(PYINSTALLER_INSTALL)
        if result.returncode != 0:
            print('Failed to install PyInstaller.')
            sys.exit(1)


def build_executable(entry_script, name):
    print(f'Building {name}.exe from {entry_script}...')
    # Use --onefile for single exe, --noconfirm to overwrite previous builds, --clean to clean cache
    result = subprocess.run([
        sys.executable, '-m', 'PyInstaller',
        '--onefile', '--noconfirm', '--clean',
        '--windowed' if name == 'client' else '--console',  # windowed for client GUI, console for server
        '--name', name,
        entry_script
    ])
    if result.returncode != 0:
        print(f'Build failed for {entry_script}! Check for errors above.')
        sys.exit(1)
    print(f'Success: {name}.exe generated.')


def main():
    print('========== LAN Conference Tool Builder ==========' )
    install_requirements()
    ensure_pyinstaller()

    # Build server and client
    build_executable(SERVER_SCRIPT, 'server')
    build_executable(CLIENT_SCRIPT, 'client')

    # Let user know where the files are
    dist_dir = os.path.join(os.getcwd(), 'dist')
    server_exe = os.path.join(dist_dir, 'server.exe')
    client_exe = os.path.join(dist_dir, 'client.exe')
    print('\n========== Build Complete ==========' )
    print(f'Server executable: {server_exe}')
    print(f'Client executable: {client_exe}')
    print('Distribute these .exe files for use on any Windows machine on your LAN.')
    print('===================================' )

if __name__ == '__main__':
    main()
