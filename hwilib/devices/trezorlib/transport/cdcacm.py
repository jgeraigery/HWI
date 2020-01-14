# Copyright (C) 2019 Bob McElrath
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License version 3
# as published by the Free Software Foundation.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the License along with this library.
# If not, see <https://www.gnu.org/licenses/lgpl-3.0.html>.

import atexit
import logging
import sys
import time
from typing import Iterable, Optional

# FIXME this file uses the usb library while the upstream code uses the usb1
# library. This means that the device object is different for the different
# transport methods.
import usb.core
import usb.util
import usb.control
import array

from . import DEV_STM32F4, UDEV_RULES_STR, TransportException
from .protocol import ProtocolBasedTransport, ProtocolV1

LOG = logging.getLogger(__name__)

try:
    import usb
except Exception as e:
    LOG.warning("CDC ACM transport is disabled: {}".format(e))
    usb = None

INTERFACE = 0
ENDPOINT = 1
DEBUG_INTERFACE = 1
DEBUG_ENDPOINT = 2


class CDCACMHandle:
    def __init__(self, device, debug: bool = False) -> None:
        self.device = device
        self.interface = DEBUG_INTERFACE if debug else INTERFACE
        self.endpoint = DEBUG_ENDPOINT if debug else ENDPOINT
        self.count = 0
        self.readhandle = None
        self.writehandle = None

    def open(self) -> None:
        # Find control endpoint
        for control in self.device.get_active_configuration().interfaces():
            if control.bInterfaceClass == usb.CLASS_COMM:
                if self.device.is_kernel_driver_active(control.index):
                    self.device.detach_kernel_driver(control.index)
                break

        # Find CDC data endpoint: this device also has a vendor specific and
        # mass storage interface which we want to skip over.
        for cdcdata in self.device.get_active_configuration().interfaces():
            if cdcdata.bInterfaceClass == usb.CLASS_DATA:
                if self.device.is_kernel_driver_active(cdcdata.index):
                    self.device.detach_kernel_driver(cdcdata.index)
                for endpoint in cdcdata.endpoints():
                    if usb.util.endpoint_direction(endpoint.bEndpointAddress) == usb.util.ENDPOINT_IN:
                        self.readhandle = endpoint
                    else:
                        self.writehandle = endpoint
                break

        if self.readhandle is None or self.writehandle is None:
            raise IOError("Cannot open STMicroelectronics CDC ACM device")

        try:
            # 0x21 = usb.util.CTRL_TYPE_CLASS | usb.util.CTRL_RECIPIENT_INTERFACE
            # Set 9600 8N1
            self.device.ctrl_transfer(0x21, 0x22, 0x01|0x02, control.index, None)
            # Set (9600, 8N1)
            self.device.ctrl_transfer(0x21, 0x20, 0, control.index,
                    array.array('B', [0x80, 0x25, 0x00, 0x00, 0x00, 0x00, 0x08]))
        except:
            # FIXME we need a way to set 8N1 on MacOSX. Try the serial class
            # (but need to discover the corresponding device in /dev/ and use the
            # operating system's serial interface)
            pass # MacOSX does not let us use ctrl_transfer

    def close(self) -> None:
        pass
        # TODO
        #if self.handle is not None:
        #    self.handle.releaseInterface(self.interface)
        #    self.handle.close()
        #self.handle = None

    def write_chunk(self, chunk: bytes) -> None:
        print("CDCACMHandle.write_chunk(", chunk, ")")
        assert self.writehandle is not None
        if len(chunk) != 64:
            raise TransportException("Unexpected chunk size: %d" % len(chunk))
        #self.writehandle.write("142857\n")
        self.writehandle.write(chunk)

    def read_chunk(self) -> bytes:
        assert self.readhandle is not None
        chunk = b''
        while True:
            chunkchunk = self.readhandle.read(64-len(chunk))
            chunk += chunkchunk
            if len(chunk) < 64:
                time.sleep(0.001)
            elif len(chunk) == 64:
                break
            else:
                raise TransportException("Unexpected chunk size: %d" % len(chunk))
        print("CDCACMHandle.read_chunk() = ", chunk)
        return chunk


class CDCACMTransport(ProtocolBasedTransport):
    """
    CDCACMTransport implements transport over a serial interface.
    """

    PATH_PREFIX = "cdcacm"
    ENABLED = usb is not None
    context = None

    def __init__(
        self, device, handle: CDCACMHandle = None, debug: bool = False
    ) -> None:
        if handle is None:
            handle = CDCACMHandle(device, debug)

        self.device = device
        self.handle = handle
        self.debug = debug

        super().__init__(protocol=ProtocolV1(handle))

    def get_path(self) -> str:
        return "%s:%03i:%03i" % (self.PATH_PREFIX, self.device.bus, self.device.address)

    def get_usb_vendor_id(self) -> int:
        return self.device.idVendor

    @classmethod
    def enumerate(cls) -> Iterable["CDCACMTransport"]:
        devices = []
        # FIXME add smarter way of allowing for multiple types of devices with
        # different idVendor/idProduct but using CDC ACM
        usbdevs = usb.core.find(idVendor=DEV_STM32F4[0], idProduct=DEV_STM32F4[1])
        if usbdevs is not None:
            devices.extend([CDCACMTransport(d.device) for d in usbdevs])
        return devices

    def find_debug(self) -> "CDCACMTransport":
        if self.protocol.VERSION >= 2:
            # TODO test this
            # XXX this is broken right now because sessions don't really work
            # For v2 protocol, use the same WebUSB interface with a different session
            return CDCACMTransport(self.device, self.handle)
        else:
            # For v1 protocol, find debug USB interface for the same serial number
            return CDCACMTransport(self.device, debug=True)

