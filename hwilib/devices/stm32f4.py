# STM32F4 interaction script

from ..errors import DEVICE_NOT_INITIALIZED, DeviceNotReadyError, common_err_msgs, handle_errors
from .trezorlib.transport import enumerate_devices, STM32F4_VENDOR_IDS
from .trezor import TrezorClient
from ..base58 import get_xpub_fingerprint_hex

py_enumerate = enumerate # Need to use the enumerate built-in but there's another function already named that

class STM32F4Client(TrezorClient):
    def __init__(self, path, password=''):
        super(STM32F4Client, self).__init__(path, password)
        self.type = 'stm32f4'

def enumerate(password=''):
    results = []
    for dev in enumerate_devices():
        # enumerate_devices filters to STM32F3 devices
        if dev.get_usb_vendor_id() not in STM32F4_VENDOR_IDS | {-1}:
            continue
        d_data = {}

        d_data['type'] = 'stm32f4'
        d_data['model'] = 'stm32f4' # FIXME get model number?
        d_data['path'] = dev.get_path()

        client = None

        with handle_errors(common_err_msgs["enumerate"], d_data):
            client = STM32F4Client(d_data['path'], password)
            client.client.init_device()
            print(client.client.features.vendor)
            if 'STMicroelectronics' not in client.client.features.vendor:
                continue

            # FIXME everything below is copied from KeepKey
            if d_data['path'] == 'udp:127.0.0.1:21324':
                d_data['model'] += '_simulator'

            d_data['needs_pin_sent'] = client.client.features.pin_protection and not client.client.features.pin_cached
            d_data['needs_passphrase_sent'] = client.client.features.passphrase_protection # always need the passphrase sent for Keepkey if it has passphrase protection enabled
            if d_data['needs_pin_sent']:
                raise DeviceNotReadyError('STM32F4 is locked. Unlock by using \'promptpin\' and then \'sendpin\'.')
            if d_data['needs_passphrase_sent'] and not password:
                raise DeviceNotReadyError("Passphrase needs to be specified before the fingerprint information can be retrieved")
            if client.client.features.initialized:
                master_xpub = client.get_pubkey_at_path('m/0h')['xpub']
                d_data['fingerprint'] = get_xpub_fingerprint_hex(master_xpub)
                d_data['needs_passphrase_sent'] = False # Passphrase is always needed for the above to have worked, so it's already sent
            else:
                d_data['error'] = 'Not initialized'
                d_data['code'] = DEVICE_NOT_INITIALIZED

        if client:
            client.close()

        results.append(d_data)
    return results
