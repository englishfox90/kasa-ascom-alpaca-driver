# kasa-ascom-alpaca-driver

A Python package that exposes TP-Link Kasa smart plugs as ASCOM Alpaca Switch devices, enabling integration with astronomy automation tools like N.I.N.A. and other Alpaca clients. This project uses the official [python-kasa](https://python-kasa.readthedocs.io/en/latest/) library for device control and metrics, and provides a user-friendly Windows GUI for setup and management.

## Features
- **Expose Kasa smart plugs as ASCOM Alpaca Switches** (on/off control)
- **Expose Kasa device metrics** (power, voltage, current) as read-only Alpaca switches (gauges) if supported by the device
- **Credential management** using the Windows keyring, with GUI and CLI options
- **Modern logging** with rotation, logs stored in a dedicated `logs/` directory
- **Windows GUI manager** for easy setup, credential management, and server control
- **System tray support** for background running and quick access
- **First-run experience** guides the user through credential setup
- **Background server operation** (no need to keep a command prompt open)

## Plugins and Libraries Used
- [`python-kasa`](https://github.com/python-kasa/python-kasa): Official Python library for controlling Kasa devices and reading metrics
- [`falcon`](https://falcon.readthedocs.io/): High-performance Python web framework for the Alpaca API
- [`keyring`](https://pypi.org/project/keyring/): Secure credential storage in the Windows credential manager
- [`tkinter`](https://docs.python.org/3/library/tkinter.html): Standard Python GUI library (used for the Windows GUI manager)
- [`pystray`](https://pypi.org/project/pystray/): System tray icon support
- [`Pillow`](https://pypi.org/project/Pillow/): Image support for tray icons
- [`toml`](https://pypi.org/project/toml/): For configuration file parsing

## How it Works
- On startup, the app discovers Kasa devices on your network using `python-kasa`.
- Each Kasa device is exposed as an Alpaca Switch (on/off), and if the device supports energy monitoring, additional read-only switches (gauges) are created for metrics like power, voltage, and current.
- Credentials for Kasa cloud access are securely stored in the Windows keyring. The first run (or via the GUI) will prompt for these.
- The Alpaca server runs in the background and can be managed via the Windows GUI or system tray.
- Logs are written to a `logs/` directory with rotation.

## Installation

### Prerequisites
- Windows 10 or later
- Python 3.7+
- Kasa smart plugs on your local network

### Build and Install (Developer/Advanced)
1. Open a command prompt and navigate to the project directory.
2. Install the package and dependencies:
   ```sh
   pip install .
   ```
   This will install all required dependencies, including `pystray` and `Pillow` for tray support.

### Build a Standalone Windows Executable (Recommended for End Users)
1. Install [PyInstaller](https://pyinstaller.org/):
   ```sh
   pip install pyinstaller
   ```
2. Build the GUI manager as a single EXE:
   ```sh
   pyinstaller --noconsole --onefile device/gui_manager.py --name "KasaSwitchManager"
   ```
   The output will be in the `dist/` folder.
3. (Optional) Use [Inno Setup](https://jrsoftware.org/isinfo.php) or [NSIS](https://nsis.sourceforge.io/) to create a Windows installer that:
   - Installs the EXE
   - Creates Start Menu/Desktop shortcuts
   - Optionally launches the GUI after install

#### Example Inno Setup script:
```
[Setup]
AppName=Kasa Alpaca Switch Manager
AppVersion=1.0
DefaultDirName={pf}\\KasaAlpacaSwitch
DefaultGroupName=Kasa Alpaca Switch
OutputBaseFilename=KasaAlpacaSwitchSetup

[Files]
Source: "dist\\KasaSwitchManager.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\\Kasa Switch Manager"; Filename: "{app}\\KasaSwitchManager.exe"
Name: "{userdesktop}\\Kasa Switch Manager"; Filename: "{app}\\KasaSwitchManager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\\KasaSwitchManager.exe"; Description: "Launch Kasa Switch Manager"; Flags: nowait postinstall skipifsilent
```

## Usage
- Launch the app from the Start Menu, Desktop, or by running `kasa-switch-gui` (if installed via pip).
- On first run, you will be prompted to enter your Kasa credentials.
- Use the GUI to start/stop the Alpaca server, view logs, and copy the server URL.
- Minimize the window to send the app to the system tray for background running.
- Use the tray icon to show/hide the window, start/stop the server, or exit.

## Configuration
- Edit `device/config.toml` to change network port, logging options, etc.
- Logs are stored in the `logs/` directory by default.

## Troubleshooting
- If the server does not start, check the logs in the `logs/` directory for errors.
- Ensure your Kasa devices are on the same network as your computer.
- If credentials change or expire, use the GUI to update them.
- If you see missing dependencies, run `pip install .` again or ensure all requirements are installed.

## License
MIT License. See [LICENSE](LICENSE) for details.

## Credits
- Based on the ASCOM Initiative Alpaca Device template by Bob Denny
- Kasa device control via python-kasa by Tomáš Krajča and contributors
- GUI and integration by Paul Fox-Reeks
