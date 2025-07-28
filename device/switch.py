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
    METRIC_SUFFIXES = [
        ("_consumption", "Current Consumption (W)"),
        ("_voltage", "Voltage (V)"),
        ("_current", "Current (A)")
    ]

    def __init__(self):
        self.connected = False
        self.device_list = []
        self.device_objs = []
        self.lock = threading.Lock()
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
        global maxdev
        with self.lock:
            start = time.time()
            try:
                self.device_list, self.device_objs = self.loop.run_until_complete(self._get_device_list())
                self.gauge_map = {}
                self.child_map = {}  # Map device_list index to (dev_idx, child_idx)
                new_device_list = []
                new_device_objs = []
                for idx, dev in enumerate(self.device_objs):
                    if hasattr(dev, 'children') and dev.children:
                        for cidx, child in enumerate(dev.children):
                            name = f"{dev.alias} - {child.alias}"
                            new_device_list.append(name)
                            self.child_map[len(new_device_list)-1] = (idx, cidx)
                            new_device_objs.append(dev)
                    else:
                        new_device_list.append(dev.alias)
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

    def is_gauge(self, id):
        # id is int index
        return hasattr(self, 'gauge_map') and id in self.gauge_map

    def get_gauge_value(self, id):
        idx, suffix = self.gauge_map[id]
        dev = self.device_objs[idx]
        if logger:
            logger.debug(f"get_gauge_value: Updating device {dev.alias} for gauge {suffix}")
        self.loop.run_until_complete(dev.update())
        if suffix == "_consumption":
            val = getattr(dev.emeter_realtime, 'power', None)
        elif suffix == "_voltage":
            val = getattr(dev.emeter_realtime, 'voltage', None)
        elif suffix == "_current":
            val = getattr(dev.emeter_realtime, 'current', None)
        else:
            val = None
        if logger:
            logger.debug(f"get_gauge_value: {dev.alias} {suffix} value={val}")
        return val

    def get_gauge_description(self, id):
        idx, suffix = self.gauge_map[id]
        dev = self.device_objs[idx]
        if logger:
            logger.debug(f"get_gauge_description: Updating device {dev.alias} for gauge {suffix}")
        self.loop.run_until_complete(dev.update())
        desc = f"{dev.alias} metric: "
        if suffix == "_consumption":
            desc += f"Current Consumption: {getattr(dev.emeter_realtime, 'power', 'N/A')} W"
        elif suffix == "_voltage":
            desc += f"Voltage: {getattr(dev.emeter_realtime, 'voltage', 'N/A')} V"
        elif suffix == "_current":
            desc += f"Current: {getattr(dev.emeter_realtime, 'current', 'N/A')} A"
        # Add on_since if available
        if hasattr(dev, 'on_since') and dev.on_since:
            desc += f" | On since: {dev.on_since}"
        if logger:
            logger.debug(f"get_gauge_description: {desc}")
        return desc

    def get_switch(self, id=0):
        name = self._resolve_id(id)
        idx = self.device_list.index(name)
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
        dev = self.device_objs[idx]
        if hasattr(self, 'child_map') and idx in self.child_map:
            dev_idx, cidx = self.child_map[idx]
            child = dev.children[cidx]
            if logger:
                logger.debug(f"set_switch: Setting child {child.alias} of {dev.alias} to {'ON' if state else 'OFF'}")
            self.loop.run_until_complete(child.turn_on() if state else child.turn_off())
            if logger:
                logger.debug(f"set_switch: {dev.alias} - {child.alias} set to {'ON' if state else 'OFF'}")
        else:
            if logger:
                logger.debug(f"set_switch: Setting {dev.alias} to {'ON' if state else 'OFF'}")
            self.loop.run_until_complete(dev.turn_on() if state else dev.turn_off())
            if logger:
                logger.debug(f"set_switch: {dev.alias} set to {'ON' if state else 'OFF'}")

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
            if isinstance(id, int) and device.is_gauge(id):
                val = device.get_gauge_value(id)
                resp.text = PropertyResponse(val, req).json
                return
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
            if logger:
                logger.info(f"getswitchname: id={id}, name={name}")
            # Defensive: if name is None, return a clear error
            if name is None:
                resp.text = PropertyResponse(None, req, InvalidValueException(f'Switch id {id} not found.')).json
                return
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
            if device.is_gauge(id):
                desc = device.get_gauge_description(id)
            elif 0 <= id < len(device.device_list):
                name = device.device_list[id]
                import uuid
                guid = str(uuid.uuid5(uuid.NAMESPACE_DNS, name))
                dev_idx = id
                if hasattr(device, 'gauge_map') and id in device.gauge_map:
                    dev_idx = device.gauge_map[id][0]
                dev = device.device_objs[dev_idx] if dev_idx < len(device.device_objs) else None
                on_since = getattr(dev, 'on_since', None) if dev else None
                desc = f"{name} (GUID: {guid})"
                if on_since:
                    desc += f" | On since: {on_since}"
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
        # Gauge switches are read-only
        if device.is_gauge(id):
            resp.text = PropertyResponse(False, req).json
        else:
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

