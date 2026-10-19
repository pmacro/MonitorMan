# Independent keyboard follow on Linux, macOS and Windows

Run one local MonitorMan app on each computer. **The normal setup is now graphical:** launch `python -m monitorman --settings`, discover and select devices, choose the MX Vertical channels and monitor inputs, then Save and apply. Reopen Settings from the tray at any time. The JSON examples below remain available for advanced use. There is no network service, pairing between apps, or communication between computers. Both computers must already be paired to the Keychron K2 and MX Vertical using their respective Bluetooth slots.

When you switch the keyboard away, the source app observes a stable Bluetooth disconnect, tells its connected MX Vertical to select the configured other slot, and switches the Dell to the configured other input. When the keyboard reconnects, the destination app selects its own monitor input. The mouse follows because the source computer sent its switch command; a disconnected mouse cannot be summoned from the destination computer.

## What this can detect

The K2 handles its Bluetooth slot shortcuts internally. The app sees connected/disconnected state, not the destination slot. **Independent automatic following therefore uses a fixed two-computer route.** You may run the app on any of the three supported operating systems, but it cannot infer which of two other computers you picked in a three-computer setup.

**Keyboard sleep, powering it off, Bluetooth being disabled, and a real slot switch can look alike.** A stable disconnect can send the mouse and monitor away in all these cases. The three-second delay filters brief drops; it cannot establish the cause. Follow is off by default. Enable it only if this tradeoff fits your workflow; pause from the tray when needed. No action fires just because the app starts with the keyboard absent or present. Reconnecting the keyboard after waking can select the local monitor input again.

## Dependencies

Use Python 3.10 or later. From the project folder, create a virtual environment and install:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

On Windows use `py -3 -m venv .venv` followed by `.venv\Scripts\python -m pip install -r requirements.txt`. The commands below use `python` to mean that environment's interpreter; on Linux/macOS activate with `source .venv/bin/activate`, on PowerShell use `.venv\Scripts\Activate.ps1` or invoke the interpreter directly.

### Linux

Keep the existing `ddcutil` and `i2c-dev` setup from README.md. Keyboard detection uses `bluetoothctl` (package `bluez`). The shared tray and settings window use Qt (PySide6); GNOME needs status icon support. The original `--monitor-only` mode still uses GTK. On Ubuntu:

```sh
sudo apt install ddcutil bluez python3-venv python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
```

The new Qt GUI does not require system GTK bindings in the venv. If you also want the legacy `--monitor-only` mode, create the venv with `--system-site-packages` so it can use GTK.

Mouse commands need access to Logitech hidraw devices. Solaar's distribution package provides standard Logitech udev permissions. If mouse switching reports access denied, install `solaar`, reconnect the mouse and log in again; see [Solaar installation and permissions](https://pwr-solaar.github.io/Solaar/installation). Avoid running two HID control utilities during testing. Do not run MonitorMan as root.

### macOS

Install [blueutil](https://github.com/toy/blueutil) for connection queries:

```sh
brew install blueutil
```

For Apple Silicon Macs, install [m1ddc](https://github.com/waydabber/m1ddc), e.g. `brew install m1ddc` where available. Run `m1ddc display list` to find the Dell. Configure its UUID instead of an index when possible. The `m1ddc` backend does not support Intel Macs.

For Intel Macs, or unsupported display connections, use the [BetterDisplay CLI](https://github.com/waydabber/BetterDisplay/wiki/Integration-features,-CLI) backend. BetterDisplay must be running, and DDC access enabled for the display:

```json
"monitor": {"backend": "betterdisplay", "display": "DELL S2725QC"}
```

Grant Bluetooth and Input Monitoring permissions to the interpreter/app launching MonitorMan if macOS requests them. HID access and DDC availability vary by OS version and connection. `--check` tests keyboard detection; an actual mouse switch is needed to verify HID writes. Keep the mouse's underside button available during initial testing.

### Windows

Install Python 3.10+ and `requirements.txt` as above. WinRT reads the keyboard's live Bluetooth connection state. Monitor input changes use Windows' native DXVA2 monitor API; no separate DDC program is required. Bluetooth must be enabled, devices paired, and the monitor must support DDC/CI through the current cable/adapter. Allow Bluetooth access if prompted.

## Settings for Linux ↔ Mac

Generate a template independently on each computer:

```sh
python -m monitorman --write-example settings.json
```

This creates a file but starts no automation. Edit it before running. For example, **assuming Linux is HDMI-1 and mouse slot 1, and Mac is USB-C and mouse slot 2**:

Linux:

```json
{
  "keyboard_address": "AA:BB:CC:DD:EE:FF",
  "mouse_name": "MX Vertical",
  "monitor": {"backend": "ddcutil"},
  "local_input": "0x11",
  "away": {"name": "Mac", "input": "0x1b", "mouse_slot": 2},
  "follow": false,
  "poll_seconds": 1,
  "settle_seconds": 3
}
```

Mac:

```json
{
  "keyboard_address": "AA:BB:CC:DD:EE:FF",
  "mouse_name": "MX Vertical",
  "monitor": {"backend": "m1ddc", "display": "1"},
  "local_input": "0x1b",
  "away": {"name": "Linux", "input": "0x11", "mouse_slot": 1},
  "follow": false,
  "poll_seconds": 1,
  "settle_seconds": 3
}
```

Replace the keyboard address with the address shown on each machine. On Linux, use `bluetoothctl devices Paired` and `bluetoothctl info ADDRESS`. On Mac, use `blueutil --paired`. On Windows, find the keyboard's Bluetooth address in Device Manager → Bluetooth → keyboard → Properties → Details → Bluetooth device address (or its Bluetooth device instance path). Use six hex pairs separated by colons. This helper targets classic Bluetooth, as used by the original K2; BLE-only keyboard variants are not covered.

The mouse slot is the number on the mouse, independently of the keyboard's slot number. Dell inputs commonly use `0x11` for HDMI-1, `0x12` for HDMI-2, and `0x1b` for USB-C; use values already verified with your monitor.

On Windows replace `monitor` with `{"backend": "windows", "display": 1}`. This is a one-based physical display index in Windows enumeration order; it can change after reconnecting displays. Test it manually before enabling follow. On Linux, if multiple Dell monitors are connected, set `monitor.serial` to the target's serial from `ddcutil detect --brief`. Set `monitor.backend` to `disabled` on a computer if only the other computer can reach DDC reliably while inactive.

Use `python -m monitorman --devices` to list HID product names and serials if mouse matching fails. Set `mouse_name` to a matching substring; optionally specify `mouse_serial` to disambiguate devices. This implementation targets a directly Bluetooth-connected mouse, not a Unifying/Bolt receiver.

## Run and test

Quit the original MonitorMan tray instance first. Check keyboard detection without sending any switching commands:

```sh
python -m monitorman --config settings.json --check
```

Run the portable tray app:

```sh
python -m monitorman --config settings.json
```

In Settings, first use **Check mouse and current channel** to verify HID access and read its actual channel without switching anything. Discovery fills the selected mouse’s serial when available; a missing serial is optional. Use **Test mouse only → other channel** to isolate mouse switching from monitor control. Results and errors remain visible in the fixed footer. Then test **Send mouse + monitor to …** from each computer while the mouse is connected there. This switches the mouse and monitor, but does not change the keyboard's slot; select the keyboard's destination yourself. Verify both directions. Both target computers must be awake and have Bluetooth enabled.

Then enable **Follow keyboard disconnects** in the tray and use the K2's normal Bluetooth slot shortcut. The tray toggle is for this session; use the saved Follow checkbox in Settings to enable it on subsequent launches. GUI saves apply immediately. Restart after manually editing the JSON file. The app serializes commands, waits for stable state changes, never interprets a failed connection query as a disconnect, and does not automatically retry switches that could take away control. Status reports command delivery, not proof of reconnection at the target.

The portable helper allows one running instance per user. A headless mode is also available:

```sh
python -m monitorman --config settings.json --headless
```

## Login startup

You can manage this with **Start MonitorMan when I log in** in Settings. The command-line alternative follows.

Using the same Python interpreter with the dependencies installed:

```sh
python install_launcher.py --config settings.json --autostart
```

Linux writes the normal desktop launcher/autostart files. macOS writes `~/Applications/MonitorMan.app` and `~/Library/LaunchAgents/io.monitorman.InputSwitcher.plist`. Windows writes `MonitorMan.vbs` to the user's Start Menu Programs folder and Startup subfolder. Startup takes effect at the next login. Keep the checkout, virtual environment, and settings file in place.

Remove the generated launcher and autostart file to uninstall startup. Quit the running app separately. For a loaded macOS LaunchAgent use `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/io.monitorman.InputSwitcher.plist` before removing its plist.

## Validation status

The automated suite exercises disconnect debounce, reconnect handling, paused operation, failed probes, partial device failures, HID++ feature discovery and packet encoding, configuration checks, and backend command construction. Actual Windows/macOS tray rendering, OS permissions, and Bluetooth/DDC switching require testing on those machines; they have not been hardware-verified here.
