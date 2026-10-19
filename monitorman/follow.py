"""Independent local keyboard-follow automation. No network service or peers."""
import json
import logging
import math
import threading
import time
from pathlib import Path
from . import devices, displays

LOG = logging.getLogger(__name__)


def number(value):
    return int(value, 0) if isinstance(value, str) else int(value)


def load_config(path):
    return validate_config(json.loads(Path(path).read_text()))


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError('Settings must be a JSON object')
    if not isinstance(config.get('keyboard_address'), str):
        raise ValueError('keyboard_address must be a Bluetooth address string')
    devices.address_number(config['keyboard_address'])
    if not isinstance(config.get('mouse_name', 'MX Vertical'), str) or not config.get('mouse_name', 'MX Vertical').strip():
        raise ValueError('mouse_name must be a nonempty string')
    for field in ('local_input',):
        config[field] = number(config[field])
        if not 0 <= config[field] <= 255:
            raise ValueError(f'{field} must be between 0 and 255')
    away = config['away']
    if not isinstance(away, dict):
        raise ValueError('away must be a JSON object')
    away['input'] = number(away['input'])
    away['mouse_slot'] = number(away['mouse_slot'])
    if not 0 <= away['input'] <= 255 or away['mouse_slot'] not in (1, 2, 3):
        raise ValueError('Invalid away input or mouse slot')
    if not isinstance(away.get('name'), str) or not away['name'].strip():
        raise ValueError('away.name is required')
    monitor = config.setdefault('monitor', {})
    if not isinstance(monitor, dict):
        raise ValueError('monitor must be a JSON object')
    backend = monitor.get('backend')
    if backend not in (None, 'disabled', 'ddcutil', 'windows', 'm1ddc', 'betterdisplay'):
        raise ValueError('Unknown monitor backend')
    if backend == 'betterdisplay' and not monitor.get('display'):
        raise ValueError('BetterDisplay requires monitor.display (exact display name)')
    for key, default, minimum in [('poll_seconds', 1, 0.25), ('settle_seconds', 3, 1)]:
        value = float(config.get(key, default))
        if not math.isfinite(value) or not minimum <= value <= 60:
            raise ValueError(f'{key} must be between {minimum} and 60')
        config[key] = value
    if 'local_mouse_slot' in config:
        config['local_mouse_slot'] = number(config['local_mouse_slot'])
        if config['local_mouse_slot'] not in (1, 2, 3):
            raise ValueError('This computer’s mouse channel must be 1, 2, or 3')
        if config['local_mouse_slot'] == away['mouse_slot']:
            raise ValueError('Choose different mouse channels for the two computers')
    if not isinstance(config.get('follow', False), bool):
        raise ValueError('follow must be true or false')
    return config


class ConnectionTracker:
    """Debounce both edges. Initial state and failed probes never trigger actions."""
    def __init__(self, settle):
        self.settle = settle
        self.stable = None
        self.candidate = None
        self.since = None

    def observe(self, connected, now):
        if connected is None:
            self.candidate = None
            self.since = None
            return None
        if self.stable is None:
            self.stable = connected
            return None
        if connected == self.stable:
            self.candidate = None
            self.since = None
            return None
        if self.candidate != connected:
            self.candidate, self.since = connected, now
        if now - self.since >= self.settle:
            self.stable = connected
            self.candidate, self.since = None, None
            return 'connected' if connected else 'disconnected'
        return None


class Follower:
    def __init__(self, config, probe=None, mouse=None, monitor=None):
        self.config = config
        self.probe = probe or (lambda: devices.keyboard_connected(self.config['keyboard_address']))
        self.mouse = mouse or devices.switch_mouse
        self.monitor = monitor or displays.switch_input
        self.enabled = config.get('follow', False)
        self.status = 'Keyboard follow enabled' if self.enabled else 'Keyboard follow paused'
        self.tracker = ConnectionTracker(config['settle_seconds'])
        self.stop_event = threading.Event()
        self.action_lock = threading.RLock()
        self.thread = None
        self.on_update = lambda: None

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name='keyboard-follow')
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def configure(self, config):
        with self.action_lock:
            self.config = config
            self.enabled = config.get('follow', False)
            self.tracker = ConnectionTracker(config['settle_seconds'])
            self.status = 'Settings applied · ' + ('follow enabled' if self.enabled else 'follow paused')

    def toggle(self):
        with self.action_lock:
            self.enabled = not self.enabled
            # Enabling starts from the current state, not an edge seen while paused.
            self.tracker = ConnectionTracker(self.config['settle_seconds'])
            self.status = 'Keyboard follow enabled' if self.enabled else 'Keyboard follow paused'

    def away(self):
        with self.action_lock:
            away = self.config['away']
            results = []
            for label, action in [
                ('Mouse', lambda: self.mouse(away['mouse_slot'], self.config.get('mouse_name', 'MX Vertical'),
                                             self.config.get('mouse_serial'))),
                ('Monitor', lambda: self.monitor(self.config['monitor'], away['input']))]:
                try:
                    results.append(action())
                except Exception as error:
                    results.append(f'{label}: {error}')
            self.status = ' · '.join(results)
            LOG.info('%s', self.status)
            return self.status

    def home(self):
        with self.action_lock:
            try:
                self.status = self.monitor(self.config['monitor'], self.config['local_input'])
            except Exception as error:
                self.status = f'Monitor: {error}'
            LOG.info('%s', self.status)
            return self.status

    def poll(self, now=None):
        with self.action_lock:
            self._poll(now)

    def _poll(self, now=None):
        try:
            connected = self.probe()
        except Exception as error:
            self.tracker.observe(None, time.monotonic() if now is None else now)
            self.status = f'Keyboard detection: {error}'
            LOG.warning('%s', self.status)
            return
        edge = self.tracker.observe(connected, time.monotonic() if now is None else now)
        if not self.enabled:
            return
        if edge == 'disconnected':
            self.away()
        elif edge == 'connected':
            self.home()

    def run(self):
        while not self.stop_event.is_set():
            self.poll()
            self.on_update()
            self.stop_event.wait(self.config['poll_seconds'])
