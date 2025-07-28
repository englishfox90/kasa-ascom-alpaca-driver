# --------------------
# Imports
# --------------------
import asyncio
import keyring
from kasa import Discover, SmartPlug
import threading
import time
from falcon import Request, Response, HTTPBadRequest, before
from logging import Logger
from .shr import PropertyResponse, MethodResponse, PreProcessRequest, StateValue, get_request_field, to_bool
from .exceptions import *

# --------------------
# Globals and Metadata
# --------------------

logger: Logger = None
if logger is None:
    import logging
    logger = logging.getLogger("kasa-alpaca")
    if not logger.hasHandlers():
        logging.basicConfig(level=logging.INFO)

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
    """Manages Kasa switches via python-kasa library."""
    def __init__(self):
        self.connected = False
        self.device_list = []
        self.device_objs = []
        self.lock = threading.RLock()
        self.loop = asyncio.new_event_loop()
        self.email = None
        self.password = None
        self._load_credentials()

    def _load_credentials(self):
        self.email = keyring.get_password('kasa-alpaca', 'email')
        self.password = keyring.get_password('kasa-alpaca', 'password')
        if not self.email or not self.password:
            self._prompt_and_store_credentials()

    def _prompt_and_store_credentials(self):
        import getpass
        print('Enter Kasa account email:')
        email = input('Email: ')
        password = getpass.getpass('Password: ')
        keyring.set_password('kasa-alpaca', 'email', email)
        keyring.set_password('kasa-alpaca', 'password', password)
        self.email = email
        self.password = password

    def update_credentials(self):
        self._prompt_and_store_credentials()

    def connect(self):
        if logger:
            logger.info("connect() called. Logger is active.")
        global maxdev
        with self.lock:
            start = time.time()
            try:
                self.device_list, self.device_objs = self.loop.run_until_complete(self._get_device_list())
                self.child_map = {}  # Map device_list index to (dev_idx, child_idx)
                new_device_list = []
                new_device_objs = []
                self.readonly_switches = set()  # Track readonly switches (parent devices)
                self.cloud_switch_map = {}  # Map: index -> parent idx for cloud connection switches
                for idx, dev in enumerate(self.device_objs):
                    # Add Power (On Since) as a readonly switch for the parent
                    new_device_list.append("Power")
                    new_device_objs.append(dev)
                    self.readonly_switches.add(len(new_device_list)-1)
                    parent_idx = len(new_device_list)-1
                    # Add Cloud Connection as a readonly switch for the parent
                    new_device_list.append("Cloud Connection")
                    new_device_objs.append(dev)
                    self.readonly_switches.add(len(new_device_list)-1)
                    self.cloud_switch_map[len(new_device_list)-1] = parent_idx
                    if hasattr(dev, 'children') and dev.children:
                        for cidx, child in enumerate(dev.children):
                            name = f"{child.alias}"
                            new_device_list.append(name)
                            self.child_map[len(new_device_list)-1] = (idx, cidx)
                            new_device_objs.append(dev)
                self.device_list = new_device_list
                self.device_objs = new_device_objs
                self.connected = True
                maxdev = len(self.device_list)
                SwitchMetadata.MaxDeviceNumber = maxdev
                elapsed = time.time() - start
                if logger:
                    logger.info(f"Kasa connect: device list loaded in {elapsed:.2f}s: {self.device_list}")
            except Exception as ex:
                self.connected = False
                if logger:
                    logger.error(f"Kasa connect failed after {time.time()-start:.2f}s: {ex}")
                raise DriverException(0x500, f"python-kasa devicelist failed: {ex}")

    def disconnect(self):
        with self.lock:
            self.connected = False
            self.device_list = []
            self.device_objs = []

    def is_connected(self):
        return self.connected

    async def _get_device_list(self):
        devices = []
        device_objs = []
        found = await Discover.discover()
        for addr, dev in found.items():
            await dev.update()
            devices.append(dev.alias)
            device_objs.append(dev)
        if logger:
            logger.info(f"python-kasa discovered devices: {devices}")
        return devices, device_objs

    def get_switch(self, id=0):
        name = self._resolve_id(id)
        idx = self.device_list.index(name)
        # Cloud Connection readonly switch: return True if cloud connected, else False
        if hasattr(self, 'cloud_switch_map') and idx in self.cloud_switch_map:
            parent_idx = self.cloud_switch_map[idx]
            dev = self.device_objs[parent_idx]
            # Use dev.has_cloud_connection and dev.is_cloud_connected per python-kasa docs
            if hasattr(dev, 'has_cloud_connection') and dev.has_cloud_connection:
                return bool(getattr(dev, 'is_cloud_connected', False))
            return False
        # Power (On Since) readonly switch: always ON
        if hasattr(self, 'readonly_switches') and idx in self.readonly_switches and (not hasattr(self, 'cloud_switch_map') or idx not in self.cloud_switch_map):
            return True
        dev = self.device_objs[idx]
        if hasattr(self, 'child_map') and idx in self.child_map:
            dev_idx, cidx = self.child_map[idx]
            child = dev.children[cidx]
            if logger:
                logger.debug(f"get_switch: Updating child {child.alias} of {dev.alias}")
            self.loop.run_until_complete(child.update())
            if logger:
                logger.debug(f"get_switch: {dev.alias} - {child.alias} is_on={child.is_on}")
            return child.is_on
        else:
            if logger:
                logger.debug(f"get_switch: Updating device {dev.alias}")
            self.loop.run_until_complete(dev.update())
            if logger:
                logger.debug(f"get_switch: {dev.alias} is_on={dev.is_on}")
            return dev.is_on

    def set_switch(self, state, id=0):
        name = self._resolve_id(id)
        idx = self.device_list.index(name)
        # Prevent setting state for readonly (parent) and cloud switches
        if (hasattr(self, 'readonly_switches') and idx in self.readonly_switches):
            raise DriverException(0x502, f"Switch {name} is read-only.")
        dev = self.device_objs[idx]
        max_retries = 3
        delay = 1.2  # seconds
        if hasattr(self, 'child_map') and idx in self.child_map:
            dev_idx, cidx = self.child_map[idx]
            dev = self.device_objs[dev_idx]
            for attempt in range(max_retries):
                child = dev.children[cidx]
                if logger:
                    logger.info(f"set_switch: Setting child {child.alias} of {dev.alias} to {'ON' if state else 'OFF'} (attempt {attempt+1})")
                self.loop.run_until_complete(child.turn_on() if state else child.turn_off())
                import time as _time
                _time.sleep(delay)
                self.loop.run_until_complete(dev.update())
                child = dev.children[cidx]
                if logger:
                    logger.info(f"set_switch: {dev.alias} - {child.alias} is now {'ON' if child.is_on else 'OFF'} (expected {'ON' if state else 'OFF'})")
                if child.is_on == state:
                    return
            if logger:
                logger.error(f"set_switch: State mismatch after {max_retries} attempts for {child.alias} of {dev.alias}: expected {state}, got {child.is_on}")
            raise DriverException(0x501, f"Failed to set switch state for {child.alias} of {dev.alias}")
        else:
            for attempt in range(max_retries):
                if logger:
                    logger.info(f"set_switch: Setting {dev.alias} to {'ON' if state else 'OFF'} (attempt {attempt+1})")
                self.loop.run_until_complete(dev.turn_on() if state else dev.turn_off())
                import time as _time
                _time.sleep(delay)
                self.loop.run_until_complete(dev.update())
                if logger:
                    logger.info(f"set_switch: {dev.alias} is now {'ON' if dev.is_on else 'OFF'} (expected {'ON' if state else 'OFF'})")
                if dev.is_on == state:
                    return
            if logger:
                logger.error(f"set_switch: State mismatch after {max_retries} attempts for {dev.alias}: expected {state}, got {dev.is_on}")
            raise DriverException(0x501, f"Failed to set switch state for {dev.alias}")

    def _resolve_id(self, id):
        if not self.device_list:
            self.device_list, self.device_objs = self.loop.run_until_complete(self._get_device_list())
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
        idstr = get_request_field('Id', req)
        try:
            id = int(idstr)
        except:
            resp.text = PropertyResponse(1, req).json
            return
        # For Power (readonly) switch, set max value to 1 (toggle)
        if hasattr(device, 'readonly_switches') and id in device.readonly_switches and (not hasattr(device, 'cloud_switch_map') or id not in device.cloud_switch_map):
            resp.text = PropertyResponse(1, req).json
        else:
            resp.text = PropertyResponse(1, req).json

# ISwitch minswitchvalue endpoint
@before(PreProcessRequest(maxdev))
class minswitchvalue:
    def on_get(self, req: Request, resp: Response, devnum: int):
        idstr = get_request_field('Id', req)
        try:
            id = int(idstr)
        except:
            resp.text = PropertyResponse(0, req).json
            return
        # For Power (readonly) switch, set min value to 0 (toggle)
        if hasattr(device, 'readonly_switches') and id in device.readonly_switches and (not hasattr(device, 'cloud_switch_map') or id not in device.cloud_switch_map):
            resp.text = PropertyResponse(0, req).json
        else:
            resp.text = PropertyResponse(0, req).json

# ISwitch switchstep endpoint
@before(PreProcessRequest(maxdev))
class switchstep:
    def on_get(self, req: Request, resp: Response, devnum: int):
        idstr = get_request_field('Id', req)
        try:
            id = int(idstr)
        except:
            resp.text = PropertyResponse(1, req).json
            return
        # For Power (readonly) switch, step is 1
        if hasattr(device, 'readonly_switches') and id in device.readonly_switches and (not hasattr(device, 'cloud_switch_map') or id not in device.cloud_switch_map):
            resp.text = PropertyResponse(1, req).json
        else:
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
        if logger:
            logger.info(f"getswitchname: handler entry (devnum={devnum})")
        if not device.is_connected():
            resp.text = PropertyResponse(None, req, NotConnectedException()).json
            if logger:
                logger.info("getswitchname: handler exit (not connected)")
            return
        idstr = get_request_field('Id', req)
        try:
            id = int(idstr)
        except:
            resp.text = MethodResponse(req, InvalidValueException(f'Id {idstr} not a valid integer.')).json
            if logger:
                logger.info("getswitchname: handler exit (invalid id)")
            return
        try:
            name = device.device_list[id] if 0 <= id < len(device.device_list) else None
            if logger:
                logger.info(f"getswitchname: id={id}, name={name}")
            # Defensive: if name is None, return a clear error
            if name is None:
                resp.text = PropertyResponse(None, req, InvalidValueException(f'Switch id {id} not found.')).json
                if logger:
                    logger.info("getswitchname: handler exit (id not found)")
                return
            resp.text = PropertyResponse(name, req).json
            if logger:
                logger.info("getswitchname: handler exit (success)")
        except Exception as ex:
            resp.text = PropertyResponse(None, req, DriverException(0x500, 'Switch.Getswitchname failed', ex)).json
            if logger:
                logger.error(f"getswitchname: handler exit (exception: {ex})")
            else:
                print(f"getswitchname: handler exit (exception: {ex})")

# ISwitch getswitchdescription endpoint
@before(PreProcessRequest(maxdev))
class getswitchdescription:
    def on_get(self, req: Request, resp: Response, devnum: int):
        import locale
        import datetime
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
                dev_idx = id
                dev = device.device_objs[dev_idx] if dev_idx < len(device.device_objs) else None
                # Cloud Connection switch description
                if hasattr(device, 'cloud_switch_map') and id in device.cloud_switch_map:
                    parent_idx = device.cloud_switch_map[id]
                    parent_dev = device.device_objs[parent_idx]
                    status = False
                    if hasattr(parent_dev, 'has_cloud_connection') and parent_dev.has_cloud_connection:
                        status = bool(getattr(parent_dev, 'cloud_connection', False))
                    desc = f"Status: {'Connected' if status else 'Disconnected'}"
                # Power (On Since) readonly switch description
                elif hasattr(device, 'readonly_switches') and id in device.readonly_switches and (not hasattr(device, 'cloud_switch_map') or id not in device.cloud_switch_map):
                    on_since = getattr(dev, 'on_since', None) if dev else None
                    if on_since:
                        try:
                            from dateutil import tz
                            import pytz
                            import datetime as dt
                            if isinstance(on_since, str):
                                on_since_dt = dt.datetime.fromisoformat(on_since)
                            else:
                                on_since_dt = on_since
                            # Localize to system timezone
                            local_tz = tz.tzlocal()
                            local_dt = on_since_dt.astimezone(local_tz)
                            locale.setlocale(locale.LC_TIME, '')
                            formatted = local_dt.strftime('%c')
                            desc = f" On since: {formatted}"
                        except Exception as dt_ex:
                            desc = f"On since: {on_since}"
                else:
                    parent_name = getattr(dev, 'alias', None) if dev else None
                    display_parent = parent_name.replace('_', ' ') if parent_name else None
                    display_name = name.replace('_', ' ') if name else None
                    desc = f"{display_parent} - {display_name}" if display_parent and display_parent != display_name else f"{display_name}"
                resp.text = PropertyResponse(desc, req).json
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
        # Set CanWrite to False for readonly (parent) and cloud switches, True for others
        can_write = True
        if (hasattr(device, 'readonly_switches') and id in device.readonly_switches):
            can_write = False
        if logger:
            logger.info(f"canwrite: returning {can_write} for id={id}")
        resp.text = PropertyResponse(can_write, req).json
        if logger:
            logger.info(f"canwrite: response serialized ({can_write})")

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
            resp.status = "200 OK"
            resp.content_type = "application/json"
            resp.text = PropertyResponse(is_conn, req).json
            if logger:
                logger.info(f"GET /connected response: {resp.text}")
            else:
                print(f"GET /connected response: {resp.text}")
        except Exception as ex:
            resp.status = "200 OK"
            resp.content_type = "application/json"
            resp.text = MethodResponse(req, DriverException(0x500, 'Switch.Connected failed', ex)).json
            if logger:
                logger.error(f"GET /connected error response: {resp.text}")
            else:
                print(f"GET /connected error response: {resp.text}")

    def on_put(self, req: Request, resp: Response, devnum: int):
        conn_str = get_request_field('Connected', req)
        conn = to_bool(conn_str)
        try:
            if conn:
                if not device.is_connected():
                    device.connect()
            else:
                if device.is_connected():
                    device.disconnect()
            resp.status = "200 OK"
            resp.content_type = "application/json"
            resp.text = MethodResponse(req).json
            if logger:
                logger.info(f"PUT /connected response: {resp.text}")
            else:
                print(f"PUT /connected response: {resp.text}")
        except Exception as ex:
            resp.status = "200 OK"
            resp.content_type = "application/json"
            resp.text = MethodResponse(req, DriverException(0x500, 'Switch.Connected failed', ex)).json
            if logger:
                logger.error(f"PUT /connected error response: {resp.text}")
            else:
                print(f"PUT /connected error response: {resp.text}")

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

# CLI for credential management
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Kasa Switch Utility")
    parser.add_argument("credentials", action="store_true", help="Update Kasa credentials in keyring")
    args = parser.parse_args()
    if args.credentials:
        KasaSwitchController().update_credentials()
        print("Credentials updated.")
        exit(0)

