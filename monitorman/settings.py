"""Settings storage and discovery shared by the GUI and command line."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from . import ddc, devices
from .follow import validate_config


def default_path():
    if sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA', Path.home() / 'AppData/Roaming'))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    return base / 'MonitorMan/settings.json'


def defaults():
    return {'keyboard_address': '', 'mouse_name': 'MX Vertical',
            'local_mouse_slot': 1, 'local_input': 0x11,
            'monitor': {'backend': {'darwin': 'm1ddc', 'win32': 'windows'}.get(sys.platform, 'ddcutil')},
            'away': {'name': 'Other computer', 'input': 0x1b, 'mouse_slot': 2},
            'follow': False, 'start_at_login': False, 'poll_seconds': 1, 'settle_seconds': 3}


def save_config(path, config):
    config = validate_config(deepcopy(config))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.monitorman-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
            json.dump(config, file, indent=2)
            file.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return config


def parse_address(text):
    match = re.search(r'\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b', text)
    address = match[0].replace('-', ':').upper() if match else text.strip()
    devices.address_number(address)
    return address


async def windows_paired():
    from winrt.windows.devices.bluetooth import BluetoothDevice
    from winrt.windows.devices.enumeration import DeviceInformation
    infos = await DeviceInformation.find_all_async(BluetoothDevice.get_device_selector_from_pairing_state(True))
    result = []
    for info in infos:
        device = await BluetoothDevice.from_id_async(info.id)
        if device is not None:
            try:
                address = ':'.join(f'{device.bluetooth_address:012X}'[i:i+2] for i in range(0, 12, 2))
                result.append((info.name, address))
            finally:
                device.close()
    return result


def paired_devices():
    if sys.platform == 'win32':
        return asyncio.run(asyncio.wait_for(windows_paired(), 20))
    if sys.platform == 'darwin':
        items = json.loads(devices.command(['blueutil', '--paired', '--format', 'json']))
        return [(item.get('name') or 'Bluetooth device', parse_address(item['address'])) for item in items]
    output = devices.command(['bluetoothctl', 'devices', 'Paired'])
    return [(name, address) for address, name in re.findall(r'(?m)^Device\s+([\dA-Fa-f:]+)\s+(.+)$', output)]


def discover():
    """Return partial discovery results even if one independent backend fails."""
    results = {'keyboards': [], 'mice': [], 'monitors': [], 'errors': []}
    try:
        results['keyboards'] = paired_devices()
    except Exception as error:
        results['errors'].append(f'Bluetooth: {error}')
    try:
        seen = set()
        for item in devices.hid_devices():
            if item['vendor_id'] == 0x046d:
                name = item.get('product_string') or ''
                serial = item.get('serial_number') or ''
                if name and (name, serial) not in seen:
                    results['mice'].append((name, serial))
                    seen.add((name, serial))
    except Exception as error:
        results['errors'].append(f'Mouse: {error}')
    if sys.platform.startswith('linux'):
        try:
            for monitor in ddc.detect():
                try:
                    choices = ddc.inputs(monitor)
                except RuntimeError as error:
                    choices = {}
                    results['errors'].append(str(error))
                results['monitors'].append((monitor.model, monitor.serial, choices))
        except Exception as error:
            results['errors'].append(f'Monitor: {error}')
    return results


def input_code(text):
    match = re.search(r'0x[0-9a-fA-F]+', text)
    try:
        value = int(match[0], 16) if match else int(text.strip(), 0)
    except ValueError:
        raise ValueError('Choose a monitor input or enter its numeric code, e.g. 0x1b') from None
    if not 0 <= value <= 255:
        raise ValueError('Monitor input must be between 0 and 255')
    return value
