# MonitorMan

A small status bar / system tray utility to switch Dell monitor inputs over DDC/CI. An independent keyboard-follow helper supports Linux, macOS, and Windows; see [cross-platform setup](FOLLOW.md). The original Linux monitor-only app also remains available. The display connected during development identifies as a **Dell S2725QC**. Inputs are discovered from the monitor, rather than guessed from its model. Multiple Dell displays get separate entries.

## Configure with the GUI

Quit the previous MonitorMan instance, then install the GUI dependencies and launch:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m monitorman --settings
```

On Windows use `.venv\Scripts\python` for the interpreter. Use the same commands on macOS as on Linux.

The settings window opens automatically on first launch. Click **Find paired devices and Dell monitors**, choose your Keychron, select the MX Vertical channel paired to each computer, and choose each monitor input. Set the other computer's name, test the keyboard connection and switch commands, then **Save and apply**. Changes take effect immediately. The **Start MonitorMan when I log in** checkbox manages login startup.

Open the window again from the tray's **Settings…** menu or by clicking its icon. Each computer has independent settings. Automatic following is initially paused because keyboard sleep and a slot switch both look like a disconnect. See [keyboard-follow setup and behavior](FOLLOW.md) for platform dependencies and limitations.

The GUI stores settings in `~/.config/MonitorMan/settings.json` on Linux (or under `XDG_CONFIG_HOME`), `~/Library/Application Support/MonitorMan/settings.json` on macOS, and `%APPDATA%\MonitorMan\settings.json` on Windows. Existing files can be opened with `--config /path/to/settings.json --settings`.

PySide6 provides the shared tray and settings window. On Linux, if Qt reports a missing xcb cursor library, install `libxcb-cursor0`. The legacy GTK monitor-only tray is still available with `--monitor-only`.

## Setup (Ubuntu / Debian)

Enable **DDC/CI** in the monitor's on-screen settings, then install:

```sh
sudo apt install ddcutil python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
sudo modprobe i2c-dev
```

Check access as your normal user:

```sh
ddcutil detect --brief
```

If access is denied, use the distribution's ddcutil I²C permissions setup. On systems using the `i2c` group:

```sh
sudo usermod -aG i2c "$USER"
```

Log out and back in after changing groups. Do not run the app as root. If `/dev/i2c-*` disappears after reboot, make the module persistent:

```sh
printf 'i2c-dev\n' | sudo tee /etc/modules-load.d/monitorman.conf
```

GNOME needs AppIndicator support (Ubuntu normally includes it). If the tray icon is missing, enable Ubuntu AppIndicators in the Extensions app; install `gnome-shell-extension-appindicator` if absent.

## Legacy monitor-only tray

From this folder:

```sh
/usr/bin/python3 -m monitorman --monitor-only
```

Click the monitor icon, then an input. A check mark indicates the input read during the last scan. **Rescan monitors** updates displays, inputs, and current state. Only one command runs at a time, keeping the menu responsive. Starting a second monitor-only instance activates the existing instance.

Switching away may disconnect DDC/CI from this computer. Use the other computer's utility or the monitor's buttons to switch back if necessary. “Input command sent” indicates command delivery; it does not verify that the monitor switched. Docks and adapters may block DDC/CI. The monitor-only mode does not switch USB peripherals. The optional [keyboard-follow mode](FOLLOW.md) can also switch an MX Vertical between its Bluetooth slots.

If input discovery fails, the app shows the error instead of guessing input codes. You can inspect the monitor's responses with `ddcutil capabilities` and `ddcutil getvcp 60`.

## Launcher and optional login startup

Run the following from this folder to create a launcher (it refers to this checkout, so keep the folder in place):

```sh
python3 install_launcher.py
```

To also start at login:

```sh
python3 install_launcher.py --autostart
```

Remove `~/.local/share/applications/monitorman.desktop` and `~/.config/autostart/monitorman.desktop` to uninstall the launchers.

## Development

The Linux monitor-only mode needs no pip packages; GTK and Ayatana bindings come from the system packages above. The shared GUI/tray/follow mode uses requirements.txt.

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q monitorman install_launcher.py
```

Backend tests cover discovery, capability parsing, input selection, and failure handling. Hardware input switching and tray rendering need testing on a desktop with the dependencies installed.

DDC command behavior follows the upstream [detect](https://www.ddcutil.com/command_detect/), [capabilities](https://www.ddcutil.com/command_capabilities/), and [setvcp](https://www.ddcutil.com/command_setvcp/) documentation.
