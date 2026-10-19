"""Install a per-user launcher, with optional login startup, on Linux/macOS/Windows."""
import argparse
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys


def desktop_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'


def install(root, config, autostart):
    argv = [sys.executable, str(root / 'run.py')]
    if config:
        argv += ['--config', str(config.resolve())]
    if sys.platform == 'win32':
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        if pythonw.exists():
            argv[0] = str(pythonw)
        command = subprocess.list2cmdline(argv).replace('"', '""')
        script = f'CreateObject("WScript.Shell").Run "{command}", 0, False\n'
        programs = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs'
        destinations = [programs / 'MonitorMan.vbs']
        if autostart:
            destinations.append(programs / 'Startup/MonitorMan.vbs')
        for target in destinations:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(script)
            print(target)
    elif sys.platform == 'darwin':
        app = Path.home() / 'Applications/MonitorMan.app/Contents'
        (app / 'MacOS').mkdir(parents=True, exist_ok=True)
        with (app / 'Info.plist').open('wb') as file:
            plistlib.dump({'CFBundleExecutable': 'MonitorMan', 'CFBundleIdentifier': 'io.monitorman.InputSwitcher',
                          'CFBundleName': 'MonitorMan', 'CFBundlePackageType': 'APPL', 'LSUIElement': True}, file)
        executable = app / 'MacOS/MonitorMan'
        executable.write_text('#!/bin/sh\nexport PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\nexec ' + shlex.join(argv) + '\n')
        executable.chmod(0o755)
        print(app.parent)
        if autostart:
            target = Path.home() / 'Library/LaunchAgents/io.monitorman.InputSwitcher.plist'
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('wb') as file:
                plistlib.dump({'Label': 'io.monitorman.InputSwitcher', 'ProgramArguments': argv,
                              'RunAtLoad': True, 'WorkingDirectory': str(root),
                              'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'},
                              'StandardErrorPath': '/tmp/monitorman-stderr.log',
                              'StandardOutPath': '/tmp/monitorman-stdout.log'}, file)
            print(target)
    else:
        content = ('[Desktop Entry]\nType=Application\nName=MonitorMan\n'
                   'Comment=Switch Dell monitor inputs\nIcon=video-display\n'
                   f'Exec={" ".join(desktop_quote(x) for x in argv)}\n'
                   'Terminal=false\nCategories=Utility;\nStartupNotify=false\n')
        destinations = [Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'applications']
        if autostart:
            destinations.append(Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'autostart')
        for directory in destinations:
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / 'monitorman.desktop'
            target.write_text(content)
            print(target)


def autostart_path():
    if sys.platform == 'win32':
        return Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup/MonitorMan.vbs'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/LaunchAgents/io.monitorman.InputSwitcher.plist'
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'autostart/monitorman.desktop'


def remove_autostart():
    autostart_path().unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--autostart', action='store_true', help='also launch at login')
    parser.add_argument('--config', type=Path, help='keyboard-follow settings')
    args = parser.parse_args()
    if args.config:
        from monitorman.follow import load_config
        load_config(args.config)
    install(Path(__file__).resolve().parent, args.config, args.autostart)


if __name__ == '__main__':
    main()
