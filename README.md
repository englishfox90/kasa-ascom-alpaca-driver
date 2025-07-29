# kasa-ascom-alpaca-driver

A Python package that exposes TP-Link Kasa smart plugs as ASCOM Alpaca Switch devices, enabling integration with astronomy automation tools like N.I.N.A. and other Alpaca clients. This project uses the official [python-kasa](https://python-kasa.readthedocs.io/en/latest/) library for device control.

> **This project implements the [ASCOM Alpaca API](https://ascom-standards.org/alpyca/index.html) for Switch devices.**

## Features
- **Expose Kasa smart plugs as ASCOM Alpaca Switches** (on/off control)
- **Credential management** using the Windows keyring, with CLI batch file for easy updating
- **Modern logging** with rotation, logs stored in a dedicated `logs/` directory
- **Background server operation** (no need to keep a command prompt open)
- **No GUI dependencies** (headless operation)

## Plugins and Libraries Used
- [`python-kasa`](https://github.com/python-kasa/python-kasa): Official Python library for controlling Kasa devices
- [`falcon`](https://falcon.readthedocs.io/): High-performance Python web framework for the Alpaca API
- [`keyring`](https://pypi.org/project/keyring/): Secure credential storage in the Windows credential manager
- [`toml`](https://pypi.org/project/toml/): For configuration file parsing
- [`pillow`](https://pypi.org/project/Pillow/): (Required by some dependencies)

## How it Works
- On startup, the app discovers Kasa devices on your network using `python-kasa`.
- Each Kasa device is exposed as an Alpaca Switch (on/off).
- Credentials for Kasa cloud access are securely stored in the Windows keyring. The first run (or via the batch file) will prompt for these.
- The Alpaca server runs in the background.
- Logs are written to a `logs/` directory with rotation.

## Installation & Usage (End User)

### Prerequisites
- **Windows 10 or later**
- **Python 3.7+** (must be installed and available in your PATH)
- **Kasa smart plugs** on your local network

### Quick Start (Recommended for End Users)
1. **Download or clone this repository.**
2. **Open a command prompt** and navigate to the project directory.
3. **To start the Alpaca Switch Manager:**
   - Double-click `run_kasa_switch_manager.bat` 
   - Or run from the command prompt:
     ```bat
     run_kasa_switch_manager.bat
     ```
   - The first run will set up a Python virtual environment and install all required libraries automatically.
   - The server will start and remain running in the command window.

4. **To set or update your Kasa credentials:**
   - Double-click `update_kasa_credentials.bat`
   - Or run from the command prompt:
     ```bat
     update_kasa_credentials.bat
     ```
   - You will be prompted for your Kasa account email and password. These are stored securely in the Windows keyring.

**Note:**
- You only need to update credentials if your Kasa account details change.
- The batch files are safe to run multiple times; they will not create duplicate environments.

### Advanced/Developer Installation
1. Open a command prompt and navigate to the project directory.
2. Install the package and dependencies:
   ```sh
   pip install .
   ```
   This will install all required dependencies.

### Configuration
- Edit `device/config.toml` to change network port, logging options, etc.
- Logs are stored in the `logs/` directory by default.

### Troubleshooting
- If the server does not start, check the logs in the `logs/` directory for errors.
- Ensure your Kasa devices are on the same network as your computer.
- If credentials change or expire, use the credential batch file to update them.
- If you see missing dependencies, re-run the batch file or ensure all requirements are installed.

## Usage in Imaging Sequences

For best results, run the `run_kasa_switch_manager.bat` batch file at the start of your imaging or automation sequence. This will start the Alpaca Switch Manager and make your Kasa devices available to Alpaca clients (e.g., N.I.N.A., ASCOM Switch clients).

- **Start the service before your imaging sequence:**
  - Double-click `run_kasa_switch_manager.bat` or run it from your automation script.
  - The server will remain running and devices will be available for control.

- **Control your Kasa switches as needed during your sequence.**

- **End the session by disconnecting the switch device via Alpaca/ASCOM client:**
  - When you disconnect the switch (using the Alpaca API or your client), the Python service will automatically shut down and the terminal window will close.
  - This ensures all resources are released and the service is ready for the next session.

**Recommended automation:**
- Add a step in your imaging automation to start the batch file before imaging begins.
- Use your Alpaca/ASCOM client to control switches as needed.
- Disconnect the switch at the end of your sequence to close the Python service cleanly.

## License
MIT License. See [LICENSE](LICENSE) for details.

## Credits
- Based on the ASCOM Initiative Alpaca Device template by Bob Denny
- Kasa device control via python-kasa by Tomáš Krajča and contributors
- CLI and integration by Paul Fox-Reeks
