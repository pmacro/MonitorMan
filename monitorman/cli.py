"""Cross-platform entry point; the original Linux tray remains available."""
import argparse
import json
import logging
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='MonitorMan: Dell input switching and local Bluetooth follow')
    parser.add_argument('--config', type=Path, help='settings file (default: per-user app settings)')
    parser.add_argument('--settings', action='store_true', help='open the configuration window')
    parser.add_argument('--monitor-only', action='store_true', help='use the original Linux monitor-only tray')
    parser.add_argument('--headless', action='store_true', help='run follow helper without a tray')
    parser.add_argument('--check', action='store_true', help='validate config and read keyboard connection; sends no switches')
    parser.add_argument('--devices', action='store_true', help='list HID names and serials; sends no switches')
    parser.add_argument('--write-example', type=Path, help='write settings template without overwriting an existing file')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.write_example:
        example = {
            'keyboard_address': '00:00:00:00:00:00',
            'mouse_name': 'MX Vertical',
            'monitor': {'backend': {'win32': 'windows', 'darwin': 'm1ddc'}.get(sys.platform, 'ddcutil')},
            'local_input': '0x11',
            'away': {'name': 'Other computer', 'input': '0x1b', 'mouse_slot': 2},
            'follow': False, 'poll_seconds': 1, 'settle_seconds': 3}
        with args.write_example.open('x') as file:
            json.dump(example, file, indent=2)
            file.write('\n')
        print(f'Edit {args.write_example}; follow is paused until enabled.')
        return 0
    if args.devices:
        from .devices import hid_devices
        for info in hid_devices():
            print(f'{info["vendor_id"]:04x}:{info["product_id"]:04x}',
                  info.get('product_string'), 'serial=', info.get('serial_number'))
        return 0
    if args.monitor_only:
        if sys.platform != 'linux':
            parser.error('--monitor-only requires Linux')
        if args.config or args.settings or args.headless or args.check:
            parser.error('--monitor-only cannot be combined with configuration options')
        from .__main__ import linux_main
        # Gtk.Application must not see the arguments consumed above.
        original = sys.argv
        try:
            sys.argv = [sys.argv[0]]
            return linux_main()
        finally:
            sys.argv = original
    from .follow import Follower, load_config
    from .settings import default_path
    path = (args.config or default_path()).expanduser().resolve()
    config, error = None, None
    if path.exists():
        try:
            config = load_config(path)
        except (ValueError, KeyError, OSError) as exception:
            if args.check or args.headless:
                raise
            error = exception
    if args.check or args.headless:
        if config is None:
            parser.error('Save your settings in the GUI first, or supply --config PATH')
    if args.check:
        from .devices import keyboard_connected
        print('Config valid. Keyboard connected:', keyboard_connected(config['keyboard_address']))
        return 0
    from .instance import SingleInstance
    with SingleInstance():
        if args.headless:
            follower = Follower(config)
            try:
                follower.run()
            except KeyboardInterrupt:
                follower.stop()
            return 0
        from .portable_tray import run
        return run(config, path, args.settings, error)


def entry():
    try:
        return main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(f'MonitorMan: {error}', file=sys.stderr)
        return 1
