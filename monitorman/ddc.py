"""DDC/CI backend; independent of the desktop UI."""
import os
import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Monitor:
    bus: int
    model: str
    serial: str


def run(*args):
    try:
        result = subprocess.run(['ddcutil', *args], capture_output=True, text=True,
                                timeout=45, env={**os.environ, 'LC_ALL': 'C'})
    except FileNotFoundError:
        raise RuntimeError('Install ddcutil first. See README.md for setup.') from None
    except subprocess.TimeoutExpired:
        raise RuntimeError('Monitor communication timed out. Check DDC/CI and the cable.') from None
    if result.returncode:
        raise RuntimeError((result.stderr.strip() or result.stdout.strip() or
                            'DDC/CI command failed.')[-2000:])
    return result.stdout


def parse_monitors(output):
    monitors = []
    for block in re.split(r'(?m)^(?=Display \d+|Invalid display)', output):
        if not re.match(r'Display \d+', block):
            continue
        bus = re.search(r'I2C bus:\s*/dev/i2c-(\d+)', block)
        info = re.search(r'Monitor:\s*DEL:([^\n:]+):([^\n]*)', block)
        if bus and info:
            monitors.append(Monitor(int(bus[1]), info[1].strip(), info[2].strip()))
    return monitors


def parse_inputs(output):
    """Parse ddcutil's decoded feature 60 section, preserving vendor labels."""
    section = re.search(r'(?ms)^\s*Feature:\s*60\b(.*?)(?=^\s*Feature:|\Z)', output)
    if not section:
        return {}
    return {int(code, 16): label.strip() for code, label in
            re.findall(r'(?m)^\s+([0-9a-fA-F]{2}):\s*(.+)$', section[1])}


def detect():
    return parse_monitors(run('detect', '--brief'))


def inputs(monitor):
    values = parse_inputs(run('--bus', str(monitor.bus), 'capabilities'))
    # Dell uses the vendor-specific 0x1b for USB-C. Older ddcutil
    # versions cannot name it; retain any explicit label the tool provides.
    if 0x1b in values and 'unrecognized' in values[0x1b].casefold():
        values[0x1b] = 'USB-C'
    if not values:
        raise RuntimeError('The monitor did not report its input choices. Enable DDC/CI in its on-screen menu and rescan.')
    return values


def current(monitor):
    output = run('--bus', str(monitor.bus), 'getvcp', '60')
    match = re.search(r'\(sl=0x([0-9a-fA-F]+)\)', output)
    return int(match[1], 16) if match else None


def switch(monitor, code):
    # Switching away can remove the DDC connection, so do not read back.
    run('--bus', str(monitor.bus), 'setvcp', '60', f'0x{code:02x}', '--noverify')
