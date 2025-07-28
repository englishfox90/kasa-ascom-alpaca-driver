


# --------------------
# Imports
# --------------------
import subprocess
import threading
from falcon import Request, Response, HTTPBadRequest, before
from logging import Logger
from .shr import PropertyResponse, MethodResponse, PreProcessRequest, StateValue, get_request_field, to_bool
from .exceptions import *

# --------------------
# Globals and Metadata
# --------------------

logger: Logger = None
maxdev = 0  # Single instance

class SwitchMetadata:
    Name = 'Kasa Switch'
    Version = '1.0.0'
    Description = 'ASCOM Alpaca driver for Kasa switches'
    DeviceType = 'Switch'
    DeviceID = 'b7e1e2c2-7e2a-4b7a-9e2e-123456789abc'  # Replace with your own GUID if desired
    Info = 'Kasa Switch Alpaca Device\nImplements ISwitch\nASCOM Initiative'
    MaxDeviceNumber = maxdev
    InterfaceVersion = 1

# --------------------
# KasaSwitchController
# --------------------

class KasaSwitchController:
    """Manages Kasa switches via KasaCmd CLI."""
    def __init__(self):
        self.connected = False
        self.device_list = []
        self.lock = threading.Lock()

    def connect(self):
        import time
        global maxdev
        with self.lock:
            start = time.time()
            try:
                self.device_list = self._get_device_list()
                self.connected = True
                maxdev = len(self.device_list)
                SwitchMetadata.MaxDeviceNumber = maxdev
                elapsed = time.time() - start
                if logger:
                    logger.info(f"Kasa connect: device list loaded in {elapsed:.2f}s: {self.device_list}")
                if logger:
                    logger.info(f"maxdev set to {maxdev}")
            except Exception as ex:
                self.connected = False
                if logger:
                    logger.error(f"Kasa connect failed after {time.time()-start:.2f}s: {ex}")
                raise DriverException(0x500, f"KasaCmd devicelist failed: {ex}")

    def disconnect(self):
        with self.lock:
            self.connected = False
            self.device_list = []

    def is_connected(self):
        return self.connected

    def _get_device_list(self):
        import time
        try:
            start = time.time()
            result = subprocess.check_output(["KasaCmd", "-devicelist"], encoding="utf-8", timeout=10)
            elapsed = time.time() - start
            lines = [line.strip() for line in result.splitlines() if line.strip()]
            devices = []
            for line in lines:
                # Ignore lines that are not actual devices
                if 'retrieving updated list' in line.lower():
                    continue
                if ',' in line:
                    parts = line.split(',')
                    if len(parts) >= 2:
                        devices.append(parts[1])  # Use the friendly name
            if logger:
                logger.info(f"KasaCmd -devicelist parsed device names: {devices} in {elapsed:.2f}s")
            return devices
        except subprocess.TimeoutExpired:
            if logger:
                logger.error("KasaCmd -devicelist timed out after 10s")
            raise DriverException(0x500, "KasaCmd devicelist timed out")
        except Exception as ex:
            if logger:
                logger.error(f"KasaCmd devicelist failed: {ex}")
            raise DriverException(0x500, f"KasaCmd devicelist failed: {ex}")

    def get_switch(self, id=0):
        import time
        import re
        import sys
        name = self._resolve_id(id)
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                start = time.time()
                result = subprocess.check_output(["KasaCmd", "-device", name, "-status"], encoding="utf-8", timeout=5)
                elapsed = time.time() - start
                if logger:
                    logger.info(f"KasaCmd -device {name} -status returned {result.strip()} in {elapsed:.2f}s (attempt {attempt})")
                # If devicelist expired or retrieving updated list, retry once
                if ("devicelist expired" in result.lower() or "retrieving updated list" in result.lower()) and attempt < max_attempts:
                    if logger:
                        logger.warning(f"KasaCmd -device {name} -status: devicelist expired, retrying (attempt {attempt+1})")
                    time.sleep(1)
                    continue
                # Robustly parse 'Relay: 1' or 'Relay: 0' (ignore case, whitespace)
                m = re.search(r"Relay:\s*([01])", result, re.IGNORECASE)
                if m:
                    return m.group(1) == "1"
                # fallback: try to parse last number in string
                digits = [int(s) for s in result.strip().split() if s.isdigit()]
                if digits:
                    return digits[-1] == 1
                return False
            except subprocess.TimeoutExpired:
                if logger:
                    logger.error(f"KasaCmd -device {name} -status timed out after 5s (attempt {attempt})")
                if attempt == max_attempts:
                    raise DriverException(0x500, f"KasaCmd status timed out for {name}")
            except Exception as ex:
                if logger:
                    logger.error(f"KasaCmd status failed for {name} (attempt {attempt}): {ex}")
                if attempt == max_attempts:
                    raise DriverException(0x500, f"KasaCmd status failed: {ex}")

    def set_switch(self, state, id=0):
        import time
        name = self._resolve_id(id)
        if logger:
            logger.info(f"set_switch called: id={id}, resolved_name={name}, state={state}")
        try:
            cmd = ["KasaCmd", "-device", name, "-on" if state else "-off"]
            start = time.time()
            subprocess.run(cmd, check=True, timeout=5)
            elapsed = time.time() - start
            if logger:
                logger.info(f"KasaCmd {' '.join(cmd)} succeeded in {elapsed:.2f}s")
        except subprocess.TimeoutExpired:
            if logger:
                logger.error(f"KasaCmd {' '.join(cmd)} timed out after 5s")
            raise DriverException(0x500, f"KasaCmd set timed out for {name}")
        except Exception as ex:
            if logger:
                logger.error(f"KasaCmd set failed for {name}: {ex}")
            raise DriverException(0x500, f"KasaCmd set failed: {ex}")

    def _resolve_id(self, id):
        # Accept int (index), device name, or GUID (case-insensitive)
        if not self.device_list:
            self.device_list = self._get_device_list()
        if isinstance(id, int):
            if id < 0 or id >= len(self.device_list):
                raise InvalidValueException(f"Switch id {id} out of range.")
            return self.device_list[id]
        elif isinstance(id, str):
            for dev in self.device_list:
                if id.lower() == dev.lower():
                    return dev
            raise InvalidValueException(f"Switch name or GUID '{id}' not found.")
        else:
            raise InvalidValueException(f"Invalid switch id: {id}")

# Instantiate controller
device = KasaSwitchController()
try:
    device.connect()
except Exception as ex:
    if logger:
        logger.error(f"Startup device.connect() failed: {ex}")

# --------------------
# Alpaca API Endpoints
# --------------------

# ISwitch maxswitchvalue endpoint
@before(PreProcessRequest(maxdev))
class maxswitchvalue:
    def on_get(self, req: Request, resp: Response, devnum: int):
        resp.text = PropertyResponse(1, req).json

# ISwitch minswitchvalue endpoint
@before(PreProcessRequest(maxdev))
class minswitchvalue:
    def on_get(self, req: Request, resp: Response, devnum: int):
        resp.text = PropertyResponse(0, req).json

# ISwitch switchstep endpoint
@before(PreProcessRequest(maxdev))
class switchstep:
    def on_get(self, req: Request, resp: Response, devnum: int):
        resp.text = PropertyResponse(1, req).json

# ISwitch getswitchvalue endpoint
@before(PreProcessRequest(maxdev))
class getswitchvalue:
    def on_get(self, req: Request, resp: Response, devnum: int):
        if not device.is_connected():
            resp.text = PropertyResponse(None, req, NotConnectedException()).json
            return
        idstr = get_request_field('Id', req)
        try:
            try:
                id = int(idstr)
            except ValueError:
                id = idstr
            val = device.get_switch(id)
            resp.text = PropertyResponse(1 if val else 0, req).json
        except Exception as ex:
            resp.text = PropertyResponse(None, req, DriverException(0x500, 'Switch.GetSwitchValue failed', ex)).json

# ISwitch getswitch endpoint
@before(PreProcessRequest(maxdev))
class getswitch:
    def on_get(self, req: Request, resp: Response, devnum: int):
        if not device.is_connected():
            resp.text = PropertyResponse(None, req, NotConnectedException()).json
            return
        idstr = get_request_field('Id', req)
        try:
            try:
                id = int(idstr)
            except ValueError:
                id = idstr
            val = device.get_switch(id)
            resp.text = PropertyResponse(bool(val), req).json
        except Exception as ex:
            resp.text = PropertyResponse(None, req, DriverException(0x500, 'Switch.Getswitch failed', ex)).json

# ISwitch setswitch endpoint
@before(PreProcessRequest(maxdev))
class setswitch:
    def on_put(self, req: Request, resp: Response, devnum: int):
        if not device.is_connected():
            resp.text = PropertyResponse(None, req, NotConnectedException()).json
            return
        idstr = get_request_field('Id', req)
        try:
            try:
                id = int(idstr)
            except ValueError:
                id = idstr
        except:
            resp.text = MethodResponse(req, InvalidValueException(f'Id {idstr} not a valid integer or device name.')).json
            return
        statestr = get_request_field('State', req)
        try:
            if isinstance(statestr, str):
                if statestr.strip() in ('1', 'true', 'True', 'on', 'ON'):
                    state = True
                elif statestr.strip() in ('0', 'false', 'False', 'off', 'OFF'):
                    state = False
                else:
                    raise ValueError
            else:
                state = bool(statestr)
        except:
            resp.text = MethodResponse(req, InvalidValueException(f'State {statestr} not a valid boolean or 0/1.')).json
            return
        if logger:
            logger.info(f"setswitch endpoint called: idstr={idstr}, parsed_id={id}, state={state}")
        else:
            print(f"setswitch endpoint called: idstr={idstr}, parsed_id={id}, state={state}")
        try:
            device.set_switch(state, id)
            resp.text = MethodResponse(req).json
        except Exception as ex:
            if logger:
                logger.error(f"setswitch endpoint: set_switch failed for id={id}, state={state}, ex={ex}")
            else:
                print(f"setswitch endpoint: set_switch failed for id={id}, state={state}, ex={ex}")
            resp.text = MethodResponse(req, DriverException(0x500, 'Switch.Setswitch failed', ex)).json

# ISwitch setswitchvalue endpoint (for Alpaca compliance, digital switches only)
@before(PreProcessRequest(maxdev))
class setswitchvalue:
    def on_put(self, req: Request, resp: Response, devnum: int):
        if not device.is_connected():
            resp.text = PropertyResponse(None, req, NotConnectedException()).json
            return
        idstr = get_request_field('Id', req)
        try:
            try:
                id = int(idstr)
            except ValueError:
                id = idstr
        except:
            resp.text = MethodResponse(req, InvalidValueException(f'Id {idstr} not a valid integer or device name.')).json
            return
        valstr = get_request_field('Value', req)
        try:
            # For digital switches, only 0 or 1 is valid
            value = int(valstr)
            if value not in (0, 1):
                raise ValueError
        except:
            resp.text = MethodResponse(req, InvalidValueException(f'Value {valstr} not a valid digital switch value (0 or 1).')).json
            return
        state = bool(value)
        if logger:
            logger.info(f"setswitchvalue endpoint called: idstr={idstr}, parsed_id={id}, value={value}, state={state}")
        else:
            print(f"setswitchvalue endpoint called: idstr={idstr}, parsed_id={id}, value={value}, state={state}")
        try:
            device.set_switch(state, id)
            resp.text = MethodResponse(req).json
        except Exception as ex:
            if logger:
                logger.error(f"setswitchvalue endpoint: set_switch failed for id={id}, value={value}, ex={ex}")
            else:
                print(f"setswitchvalue endpoint: set_switch failed for id={id}, value={value}, ex={ex}")
            resp.text = MethodResponse(req, DriverException(0x500, 'Switch.SetSwitchValue failed', ex)).json

# ISwitch getswitchname endpoint
@before(PreProcessRequest(maxdev))
class getswitchname:
    def on_get(self, req: Request, resp: Response, devnum: int):
        if not device.is_connected():
            resp.text = PropertyResponse(None, req, NotConnectedException()).json
            return
        idstr = get_request_field('Id', req)
        try:
            id = int(idstr)
        except:
            resp.text = MethodResponse(req, InvalidValueException(f'Id {idstr} not a valid integer.')).json
            return
        try:
            name = device.device_list[id] if 0 <= id < len(device.device_list) else None
            resp.text = PropertyResponse(name, req).json
        except Exception as ex:
            resp.text = PropertyResponse(None, req, DriverException(0x500, 'Switch.Getswitchname failed', ex)).json

# ISwitch getswitchdescription endpoint
@before(PreProcessRequest(maxdev))
class getswitchdescription:
    def on_get(self, req: Request, resp: Response, devnum: int):
        if not device.is_connected():
            resp.text = PropertyResponse(None, req, NotConnectedException()).json
            return
        idstr = get_request_field('Id', req)
        try:
            id = int(idstr)
        except:
            resp.text = MethodResponse(req, InvalidValueException(f'Id {idstr} not a valid integer.')).json
            return
        try:
            if 0 <= id < len(device.device_list):
                name = device.device_list[id]
                # Use a GUID based on the name for reference (or use a hash if not available)
                import uuid
                guid = str(uuid.uuid5(uuid.NAMESPACE_DNS, name))
                desc = f"{name} (GUID: {guid})"
            else:
                desc = f"Switch {id} (Invalid index)"
            resp.text = PropertyResponse(desc, req).json
        except Exception as ex:
            resp.text = PropertyResponse(None, req, DriverException(0x500, 'Switch.GetSwitchDescription failed', ex)).json

# ISwitch canwrite endpoint
@before(PreProcessRequest(maxdev))
class canwrite:
    def on_get(self, req: Request, resp: Response, devnum: int):
        if not device.is_connected():
            resp.text = PropertyResponse(None, req, NotConnectedException()).json
            return
        idstr = get_request_field('Id', req)
        try:
            id = int(idstr)
        except:
            resp.text = MethodResponse(req, InvalidValueException(f'Id {idstr} not a valid integer.')).json
            return
        resp.text = PropertyResponse(True, req).json

# Management endpoints
class connect:
    def on_put(self, req: Request, resp: Response, devnum: int):
        try:
            device.connect()
            resp.text = MethodResponse(req).json
        except Exception as ex:
            resp.text = MethodResponse(req, DriverException(0x500, 'Switch.Connect failed', ex)).json

@before(PreProcessRequest(maxdev))
class connected:
    def on_get(self, req: Request, resp: Response, devnum: int):
        try:
            is_conn = device.is_connected()
            resp.text = PropertyResponse(is_conn, req).json
        except Exception as ex:
            resp.text = MethodResponse(req, DriverException(0x500, 'Switch.Connected failed', ex)).json

    def on_put(self, req: Request, resp: Response, devnum: int):
        conn_str = get_request_field('Connected', req)
        conn = to_bool(conn_str)
        try:
            if conn:
                device.connect()
            else:
                device.disconnect()
            resp.text = MethodResponse(req).json
        except Exception as ex:
            resp.text = MethodResponse(req, DriverException(0x500, 'Switch.Connected failed', ex)).json

@before(PreProcessRequest(maxdev))
class disconnect:
    def on_put(self, req: Request, resp: Response, devnum: int):
        try:
            device.disconnect()
            resp.text = MethodResponse(req).json
        except Exception as ex:
            resp.text = MethodResponse(req, DriverException(0x500, 'Switch.Disconnect failed', ex)).json

# Metadata endpoints
@before(PreProcessRequest(maxdev))
class driverinfo:
    def on_get(self, req: Request, resp: Response, devnum: int):
        resp.text = PropertyResponse(SwitchMetadata.Info, req).json

@before(PreProcessRequest(maxdev))
class interfaceversion:
    def on_get(self, req: Request, resp: Response, devnum: int):
        resp.text = PropertyResponse(SwitchMetadata.InterfaceVersion, req).json

@before(PreProcessRequest(maxdev))
class driverversion:
    def on_get(self, req: Request, resp: Response, devnum: int):
        resp.text = PropertyResponse(SwitchMetadata.Version, req).json

@before(PreProcessRequest(maxdev))
class name:
    def on_get(self, req: Request, resp: Response, devnum: int):
        resp.text = PropertyResponse(SwitchMetadata.Name, req).json

@before(PreProcessRequest(maxdev))
class supportedactions:
    def on_get(self, req: Request, resp: Response, devnum: int):
        resp.text = PropertyResponse([], req).json

@before(PreProcessRequest(maxdev))
class maxswitch:
    def on_get(self, req: Request, resp: Response, devnum: int):
        if not device.is_connected():
            if logger:
                logger.warning("maxswitch: device not connected")
            resp.text = PropertyResponse(None, req, NotConnectedException()).json
            return
        try:
            val = len(device.device_list)
            if logger:
                logger.info(f"maxswitch: returning {val}")
            resp.text = PropertyResponse(val, req).json
        except Exception as ex:
            if logger:
                logger.error(f"maxswitch: failed: {ex}")
            resp.text = PropertyResponse(None, req, DriverException(0x500, 'Switch.Maxswitch failed', ex)).json

