"""Bluetooth connection state and Logitech HID++ host switching."""
import asyncio
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def command(argv, timeout=10):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                env={**os.environ, 'LC_ALL': 'C'})
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f'{argv[0]}: {error}') from error
    if result.returncode:
        raise RuntimeError(f'{argv[0]}: {result.stderr.strip() or result.stdout.strip()}')
    return result.stdout.strip()


def address_number(address):
    compact = re.sub('[:-]', '', address)
    if not re.fullmatch('[0-9a-fA-F]{12}', compact):
        raise ValueError('Bluetooth address must contain six hexadecimal pairs')
    return int(compact, 16)


async def windows_connected(address):
    try:
        from winrt.windows.devices.bluetooth import BluetoothDevice, BluetoothConnectionStatus
    except ImportError as error:
        raise RuntimeError('Install winrt-runtime and winrt-Windows.Devices.Bluetooth on Windows') from error
    device = await BluetoothDevice.from_bluetooth_address_async(address_number(address))
    if device is None:
        raise RuntimeError('Keyboard not found or Bluetooth permission denied')
    try:
        return device.connection_status == BluetoothConnectionStatus.CONNECTED
    finally:
        device.close()


def keyboard_connected(address):
    address_number(address)
    if sys.platform == 'win32':
        return asyncio.run(asyncio.wait_for(windows_connected(address), 10))
    if sys.platform == 'darwin':
        output = command(['blueutil', '--is-connected', address])
        if output not in ('0', '1'):
            raise RuntimeError(f'Unexpected blueutil response: {output}')
        return output == '1'
    output = command(['bluetoothctl', 'info', address])
    match = re.search(r'Connected:\s*(yes|no)', output)
    if not match:
        raise RuntimeError('Cannot determine keyboard connection; check the paired Bluetooth address')
    return match[1] == 'yes'


def hid_module():
    # Linux wheels can ship both backends: `hid` uses libusb and cannot see
    # Bluetooth peripherals, while `hidraw` supports Bluetooth as well as USB.
    if sys.platform.startswith('linux'):
        try:
            import hidraw
            return hidraw
        except ImportError:
            pass  # Older/distro builds expose the hidraw backend as `hid`.
    try:
        import hid
    except ImportError as error:
        raise RuntimeError('Install the hidapi Python package for mouse switching') from error
    return hid


def hid_devices():
    return _describe_devices(hid_module().enumerate())


def _describe_devices(items):
    """Use Bluetooth HID_UNIQ when hidapi omits a Linux device's serial."""
    result = []
    for original in items:
        item = dict(original)
        path = os.fsdecode(item.get('path', b''))
        if sys.platform.startswith('linux') and path.startswith('/dev/hidraw'):
            try:
                info = (Path('/sys/class/hidraw') / Path(path).name / 'device/uevent').read_text()
                fields = dict(line.split('=', 1) for line in info.splitlines() if '=' in line)
                if not item.get('serial_number'):
                    item['serial_number'] = fields.get('HID_UNIQ', '')
                if not item.get('product_string'):
                    item['product_string'] = fields.get('HID_NAME', '')
            except OSError:
                pass
        result.append(item)
    return result


def request(device, feature, function, params=b'', wait=True):
    # Long HID++ report, direct Bluetooth device, software ID 0x0d.
    header = bytes([0x11, 0xff, feature, (function << 4) | 0x0d])
    packet = (header + params).ljust(20, b'\0')
    if device.write(packet) != len(packet):
        raise RuntimeError('Could not write complete HID++ report')
    if not wait:
        return None  # A host switch can drop the connection before a reply.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        reply = bytes(device.read(64, 200))
        if len(reply) < 7 or reply[1] != 0xff:
            continue
        if reply[2] in (0x8f, 0xff) and reply[3:5] == header[2:4]:
            raise RuntimeError(f'HID++ error 0x{reply[5]:02x}')
        if reply[:4] == header:
            return reply[4:]
    raise RuntimeError('Mouse did not answer HID++ query; check HID permissions and Bluetooth connection')


def mouse_status(name='MX Vertical', serial=None):
    return _mouse_operation(None, name, serial)


def switch_mouse(slot, name='MX Vertical', serial=None):
    if slot not in (1, 2, 3):
        raise ValueError('Mouse slot must be 1, 2, or 3')
    return _mouse_operation(slot, name, serial)


def _mouse_operation(slot, name, serial):
    hid = hid_module()
    matches = [d for d in _describe_devices(hid.enumerate(0x046d, 0))
               if name.casefold() in (d.get('product_string') or '').casefold()
               and (not serial or d.get('serial_number') == serial)]
    if not matches:
        detail = ''
        if sys.platform.startswith('linux'):
            for path in Path('/sys/class/hidraw').glob('*'):
                try:
                    info = (path / 'device/uevent').read_text()
                except OSError:
                    continue
                if '046D' in info and name.casefold() in info.casefold():
                    node = Path('/dev') / path.name
                    detail = (f' Linux sees the mouse at {node}, but the HID library cannot access it.'
                              ' Check hidraw device permissions (Solaar provides Logitech udev rules), then reconnect the mouse.')
                    break
        raise RuntimeError(f'No accessible mouse matches “{name}”'
                           + (f' with serial “{serial}”' if serial else '')
                           + '. Wake the mouse and check that it is connected here by Bluetooth.' + detail)
    # One mouse can expose several HID collections. Refuse multiple physical mice.
    identities = {(d.get('product_id'), d.get('serial_number')) for d in matches}
    if len(identities) > 1:
        raise RuntimeError('Multiple matching mice; configure mouse_serial')
    failures = []
    for info in matches:
        device = hid.device()
        try:
            device.open_path(info['path'])
            # Discover CHANGE_HOST dynamically via IRoot.getFeature(0x1814).
            feature = request(device, 0, 0, bytes([0x18, 0x14]))[0]
            if not feature:
                raise RuntimeError('Mouse does not expose CHANGE_HOST')
            hosts = request(device, feature, 0)
            if slot is None:
                return (f'{info.get("product_string") or name}: connected, current channel '
                        f'{hosts[1] + 1} of {hosts[0]}. Serial: {info.get("serial_number") or "not reported (optional)"}.')
            if slot > hosts[0]:
                raise RuntimeError('Requested slot exceeds mouse host count')
            if hosts[1] == slot - 1:
                return 'Mouse already on target slot'
            request(device, feature, 1, bytes([slot - 1]), wait=False)
            return 'Mouse switch command sent'
        except (OSError, RuntimeError) as error:
            detail = str(error)
            if isinstance(error, OSError) and sys.platform.startswith('linux'):
                detail += ' Check read/write access to the mouse hidraw device; install Solaar udev permissions and reconnect the mouse.'
            failures.append(detail)
        finally:
            device.close()
    raise RuntimeError('; '.join(dict.fromkeys(failures)))
