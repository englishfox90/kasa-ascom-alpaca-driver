# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# management.py - Management API for  ALpaca device
#
# Part of the AlpycaDevice Alpaca skeleton/template device driver
#
# Author:   Robert B. Denny <rdenny@dc3.com> (rbd)
#
# Python Compatibility: Requires Python 3.7 or later
# GitHub: https://github.com/ASCOMInitiative/AlpycaDevice
#
# -----------------------------------------------------------------------------
# MIT License
#
# Copyright (c) 2022-2024 Bob Denny
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# -----------------------------------------------------------------------------
# Edit History:
# 17-Dec-2022   rbd 0.1 Initial edit for Alpaca sample/template
# 19-Dec-2022   rbd 0.1 Constants in shr.py
# 22-Dec-2022   rbd 0.1 Device metadata, Configuration
# 25-Dec-2022   rbd 0.1 Logging typing for intellisense
# 27-Dec-2022   rbd 0.1 Minimize imports. MIT license and module header.
#               Enhanced logging.
# 23-May-2023   rbd 0.2 Refactoring for  multiple ASCOM device type support
#               GitHub issue #1
#
from falcon import Request, Response
from .shr import PropertyResponse, DeviceMetadata
from .config import Config
from logging import Logger
# For each *type* of device served
from .switch import SwitchMetadata

logger: Logger = None
#logger = None                   # Safe on Python 3.7 but no intellisense in VSCode etc.

def set_management_logger(lgr):
    global logger
    logger = lgr

# -----------
# APIVersions
# -----------
class apiversions:
    def on_get(self, req: Request, resp: Response):
        if logger:
            logger.info("apiversions: handler entry")
        apis = [ 1 ]                            # TODO MAKE CONFIG OR GLOBAL
        resp.text = PropertyResponse(apis, req).json
        if logger:
            logger.info("apiversions: handler exit")

# -------------------------
# Alpaca Server Description
# -------------------------
class description:
    def on_get(self, req: Request, resp: Response):
        if logger:
            logger.info("description: handler entry")
        desc = {
            'ServerName'   : DeviceMetadata.Description,
            'Manufacturer' : DeviceMetadata.Manufacturer,
            'Version'      : DeviceMetadata.Version,
            'Location'     : Config.location
        }
        resp.text = PropertyResponse(desc, req).json
        if logger:
            logger.info("description: handler exit")

# -----------------
# ConfiguredDevices
# -----------------
class configureddevices():
    def on_get(self, req: Request, resp: Response):
        if logger:
            logger.info("configureddevices: handler entry")
        import time
        from .switch import device
        import uuid
        timeout = 5.0  # seconds
        poll = 0.05
        waited = 0.0
        # Wait for device list to be loaded (connected)
        while not device.is_connected() and waited < timeout:
            time.sleep(poll)
            waited += poll
        if not device.is_connected():
            if logger:
                logger.warning("configureddevices: device list not ready after waiting 5s")
            confarray = []
        else:
            confarray = [{
                'DeviceName': SwitchMetadata.Name,
                'DeviceType': SwitchMetadata.DeviceType,
                'DeviceNumber': 0,
                'UniqueID': SwitchMetadata.DeviceID
            }]
            if logger:
                logger.info("configureddevices: returning 1 device (multi-channel switch)")
        resp.text = PropertyResponse(confarray, req).json
        if logger:
            logger.info("configureddevices: handler exit")
