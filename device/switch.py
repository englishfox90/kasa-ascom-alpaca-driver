# --------------------
# Imports
# --------------------
import asyncio
import keyring
from kasa import Discover, SmartPlug
from datetime import datetime, timezone
import sys
import threading
import time
import logging
try:
    from tzlocal import get_localzone
    TZLOCAL_AVAILABLE = True
except ImportError:
    TZLOCAL_AVAILABLE = False
from falcon import Request, Response, HTTPBadRequest, before
from .shr import PropertyResponse, MethodResponse, PreProcessRequest, StateValue, get_request_field, to_bool
from .exceptions import *

# --------------------
# Globals and Metadata
# --------------------

logger: Logger = None
if logger is None:
    logger = logging.getLogger("kasa-alpaca")
    if not logger.hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s %(levelname)s [%(filename)s:%(lineno)d] %(message)s'
        )

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
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()
        self.email = None
        self.password = None
        self._load_credentials()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _load_credentials(self):
        self.email = keyring.get_password('kasa-alpaca', 'email')
        self.password = keyring.get_password('kasa-alpaca', 'password')
        if not self.email or not self.password:
            self._prompt_and_store_credentials()

    def _prompt_and_store_credentials(self):
        import getpass
        email = input('Enter Kasa account email: ')
        password = getpass.getpass('Password: ')
        keyring.set_password('kasa-alpaca', 'email', email)
        keyring.set_password('kasa-alpaca', 'password', password)
        self.email = email
        self.password = password

    def update_credentials(self):
        self._prompt_and_store_credentials()

    def connect(self):
        import time as _time
        if logger:
            logger.info(f"connect() called. Event loop closed? {self.loop.is_closed()}")
        global maxdev
        with self.lock:
            # Ensure the event loop is set as current for this thread
            if self.loop.is_closed():
                logger.info("Event loop was closed, creating new event loop.")
                self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            logger.info(f"connect() using event loop: {self.loop}")
            # Add a short delay to allow OS resources to settle after disconnect
            _time.sleep(0.5)
            start = time.time()
            try:
                fut = asyncio.run_coroutine_threadsafe(self._get_device_list(), self.loop)
                self.device_list, self.device_objs = fut.result()
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
                    logger.info(f"Device list loaded in {elapsed:.2f}s: {self.device_list}")
            except Exception as ex:
                self.connected = False
                if logger:
                    logger.error(f"Connect failed after {time.time()-start:.2f}s: {ex}")
                raise DriverException(0x500, f"python-kasa devicelist failed: {ex}")

    def disconnect(self):
        import gc
        with self.lock:
            logger.info(f"disconnect() called. Event loop running? {self.loop.is_running()} closed? {self.loop.is_closed()}")
            self.connected = False
            self.device_list = []
            self.device_objs = []
            # Gracefully close asyncio event loop if running
            try:
                if self.loop.is_running():
                    self.loop.call_soon_threadsafe(self.loop.stop)
                if hasattr(self, '_loop_thread') and self._loop_thread.is_alive():
                    self._loop_thread.join(timeout=2)
                if not self.loop.is_closed():
                    self.loop.close()
                logger.info("Graceful disconnect: asyncio event loop closed and thread joined.")
            except Exception as ex:
                logger.error(f"Graceful disconnect: error closing event loop: {ex}")
            # Recreate a new event loop for future connections
            self.loop = asyncio.new_event_loop()
            # Start the new event loop in a background thread
            self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
            self._loop_thread.start()
            logger.info(f"disconnect() created new event loop: {self.loop}")
            # Force garbage collection to clean up sockets/resources
            gc.collect()

    def is_connected(self):
        return self.connected

    async def _get_device_list(self):
        devices = []
        device_objs = []
        try:
            found = await Discover.discover()
            logger.info(f"Discover.discover() returned: {found}")
            if not found:
                logger.warning("No devices discovered.")
                return devices, device_objs
            for addr, dev in found.items():
                try:
                    await dev.update()
                    logger.info(f"Device updated: {getattr(dev, 'alias', addr)}")
                    devices.append(dev.alias)
                    device_objs.append(dev)
                except Exception as ex:
                    logger.error(f"Device update failed for {getattr(dev, 'alias', addr)}: {ex}")
            if logger:
                logger.info(f"Discovered devices: {devices}")
            return devices, device_objs
        except Exception as ex:
            logger.error(f"Device discovery failed: {ex}")
            return devices, device_objs

    def _safe_async(self, coro):
        """Run an async coroutine safely from sync context using the dedicated event loop."""
        # Always use run_coroutine_threadsafe for self.loop
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return fut.result()

    def get_switch(self, id=0):
        name = self._resolve_id(id)
        idx = self.device_list.index(name)
        # Cloud Connection readonly switch: return True if cloud connected, else False
        if hasattr(self, 'cloud_switch_map') and idx in self.cloud_switch_map:
            parent_idx = self.cloud_switch_map[idx]
            dev = self.device_objs[parent_idx]
            try:
                self._safe_async(dev.update())
            except Exception as update_ex:
                import types
                if isinstance(update_ex, types.CoroutineType):
                    logger.error(f"get_switch: update failed for {getattr(dev, 'alias', dev)}: coroutine was never awaited")
                else:
                    logger.error(f"get_switch: update failed for {getattr(dev, 'alias', dev)}: {update_ex}")
            cloudstatus = dev.features.get('cloud_connection')
            status = cloudstatus.value
            return bool(status)
        # Power (On Since) readonly switch: always ON
        if hasattr(self, 'readonly_switches') and idx in self.readonly_switches and (not hasattr(self, 'cloud_switch_map') or idx not in self.cloud_switch_map):
            dev = self.device_objs[idx]
            try:
                self._safe_async(dev.update())
            except Exception as update_ex:
                import types
                if isinstance(update_ex, types.CoroutineType):
                    logger.error(f"get_switch: update failed for {getattr(dev, 'alias', dev)}: coroutine was never awaited")
                else:
                    logger.error(f"get_switch: update failed for {getattr(dev, 'alias', dev)}: {update_ex}")
            return True
        dev = self.device_objs[idx]
        if hasattr(self, 'child_map') and idx in self.child_map:
            dev_idx, cidx = self.child_map[idx]
            child = dev.children[cidx]
            logger.debug(f"get_switch: Updating child {child.alias} of {dev.alias}")
            try:
                self._safe_async(child.update())
            except Exception as update_ex:
                import types
                if isinstance(update_ex, types.CoroutineType):
                    logger.error(f"get_switch: update failed for child {child.alias} of {dev.alias}: coroutine was never awaited")
                else:
                    logger.error(f"get_switch: update failed for child {child.alias} of {dev.alias}: {update_ex}")
            logger.debug(f"get_switch: {dev.alias} - {child.alias} is_on={child.is_on}")
            return child.is_on
        else:
            logger.debug(f"get_switch: Updating device {dev.alias}")
            try:
                self._safe_async(dev.update())
            except Exception as update_ex:
                import types
                if isinstance(update_ex, types.CoroutineType):
                    logger.error(f"get_switch: update failed for {getattr(dev, 'alias', dev)}: coroutine was never awaited")
                else:
                    logger.error(f"get_switch: update failed for {getattr(dev, 'alias', dev)}: {update_ex}")
            logger.debug(f"get_switch: {dev.alias} is_on={dev.is_on}")
            return dev.is_on

    def set_switch(self, state, id=0):
        import time as _time
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
                logger.info(f"set_switch: Setting child {child.alias} of {dev.alias} to {'ON' if state else 'OFF'} (attempt {attempt+1})")
                fut = asyncio.run_coroutine_threadsafe(child.turn_on() if state else child.turn_off(), self.loop)
                fut.result()
                _time.sleep(delay)
                fut_update = asyncio.run_coroutine_threadsafe(dev.update(), self.loop)
                fut_update.result()
                child = dev.children[cidx]
                logger.info(f"set_switch: {dev.alias} - {child.alias} is now {'ON' if child.is_on else 'OFF'} (expected {'ON' if state else 'OFF'})")
                if child.is_on == state:
                    return
            logger.error(f"set_switch: State mismatch after {max_retries} attempts for {child.alias} of {dev.alias}: expected {state}, got {child.is_on}")
            raise DriverException(0x501, f"Failed to set switch state for {child.alias} of {dev.alias}")
        else:
            for attempt in range(max_retries):
                logger.info(f"set_switch: Setting {dev.alias} to {'ON' if state else 'OFF'} (attempt {attempt+1})")
                fut = asyncio.run_coroutine_threadsafe(dev.turn_on() if state else dev.turn_off(), self.loop)
                fut.result()
                _time.sleep(delay)
                fut_update = asyncio.run_coroutine_threadsafe(dev.update(), self.loop)
                fut_update.result()
                logger.info(f"set_switch: {dev.alias} is now {'ON' if dev.is_on else 'OFF'} (expected {'ON' if state else 'OFF'})")
                if dev.is_on == state:
                    return
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

device = KasaSwitchController()
try:
    device.connect()
except Exception as ex:
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
        # For Power and Cloud Connection (readonly) switches, set max value to 1 (toggle)
        if hasattr(device, 'readonly_switches') and id in device.readonly_switches:
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
        # For Power and Cloud Connection (readonly) switches, set min value to 0 (toggle)
        if hasattr(device, 'readonly_switches') and id in device.readonly_switches:
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
        # For Power and Cloud Connection (readonly) switches, step is 1
        if hasattr(device, 'readonly_switches') and id in device.readonly_switches:
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
                    # Ensure update is awaited
                    try:
                        device._safe_async(parent_dev.update())
                    except Exception as update_ex:
                        logger.error(f"getswitchdescription: update failed for {getattr(parent_dev, 'alias', parent_dev)}: {update_ex}")
                    cloudstatus = parent_dev.features.get('cloud_connection')
                    status_bool = cloudstatus.value
                    desc = f"Status: {'Connected' if status_bool else 'Disconnected'}"
                # Power (On Since) readonly switch description
                elif hasattr(device, 'readonly_switches') and id in device.readonly_switches and (not hasattr(device, 'cloud_switch_map') or id not in device.cloud_switch_map):
                    on_since = getattr(dev, 'on_since', None) if dev else None
                    # Format with robust local timezone handling, fallback to UTC/US
                    if on_since and isinstance(on_since, datetime):
                        try:
                            # Convert to local timezone if possible
                            if TZLOCAL_AVAILABLE:
                                local_tz = get_localzone()
                                local_dt = on_since.replace(tzinfo=timezone.utc).astimezone(local_tz)
                                formatted = local_dt.strftime('%c %Z')
                            else:
                                # Fallback to UTC
                                formatted = on_since.replace(tzinfo=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                        except Exception as ex:
                            # Fallback to US format
                            try:
                                formatted = on_since.strftime('%m/%d/%Y %I:%M:%S %p UTC')
                            except Exception:
                                formatted = str(on_since)
                        desc = f"On since: {formatted}"
                    else:
                        desc = "On since: Unknown"
                else:
                    # Child or other switch
                    desc = f"{getattr(dev, 'alias', name)} - {name}"
                resp.text = PropertyResponse(desc, req).json
            else:
                resp.text = PropertyResponse(None, req, InvalidValueException(f'Switch id {id} not found.')).json
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
        import os
        try:
            if conn:
                if not device.is_connected():
                    device.connect()
                resp.status = "200 OK"
                resp.content_type = "application/json"
                resp.text = MethodResponse(req).json
                if logger:
                    logger.info(f"PUT /connected response: {resp.text}")
                else:
                    print(f"PUT /connected response: {resp.text}")
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
                logger.info("Connected endpoint: shutting down Python process after disconnect.")
                os._exit(0)
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
        import os
        try:
            device.disconnect()
            resp.text = MethodResponse(req).json
            logger.info("Disconnect endpoint: shutting down Python process.")
            os._exit(0)
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

