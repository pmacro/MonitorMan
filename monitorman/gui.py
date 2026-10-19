"""Cross-platform Qt tray and configuration window."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QPushButton, QScrollArea, QSpinBox, QSystemTrayIcon, QVBoxLayout, QWidget)

from . import devices, settings
from .follow import Follower, validate_config


class Completion(QObject):
    done = Signal(object, object, object)


def combo(values=(), editable=False):
    box = QComboBox()
    box.setEditable(editable)
    for label, data in values:
        box.addItem(label, data)
    return box


def choose(box, value):
    index = box.findData(value)
    if index >= 0:
        box.setCurrentIndex(index)
    elif box.isEditable():
        box.setEditText(str(value or ''))


def selected(box):
    index = box.currentIndex()
    if index >= 0 and box.currentText() == box.itemText(index):
        return box.currentData()
    return box.currentText().strip()


class SettingsWindow(QMainWindow):
    def __init__(self, controller, config):
        super().__init__()
        self.controller = controller
        self.config = deepcopy(config)
        self.setWindowTitle('MonitorMan Settings')
        self.resize(620, 740)
        self.monitors = []
        body = QWidget()
        layout = QVBoxLayout(body)
        title = QLabel('Make your mouse and monitor follow your keyboard')
        title.setWordWrap(True)
        title.setStyleSheet('font-size: 18px; font-weight: 600; margin-bottom: 8px')
        layout.addWidget(title)
        info = QLabel('Configure this computer, then do the reverse on the other computer. Each app runs independently.')
        info.setWordWrap(True)
        layout.addWidget(info)
        self.discover_button = QPushButton('Find paired devices and Dell monitors')
        self.discover_button.clicked.connect(self.discover)
        layout.addWidget(self.discover_button)
        keyboard = QGroupBox('Keyboard')
        form = QFormLayout(keyboard)
        self.keyboard = combo(editable=True)
        self.keyboard.setPlaceholderText('Choose the Keychron, or enter its Bluetooth address')
        self.keyboard.setEditText(config.get('keyboard_address', ''))
        form.addRow('Bluetooth keyboard', self.keyboard)
        self.check_button = QPushButton('Check connection')
        self.check_button.clicked.connect(self.check_keyboard)
        form.addRow('', self.check_button)
        layout.addWidget(keyboard)
        mouse = QGroupBox('MX Vertical channels')
        form = QFormLayout(mouse)
        self.mouse = combo(editable=True)
        self.mouse.setEditText(config.get('mouse_name', 'MX Vertical'))
        self.mouse_serial = QLineEdit(config.get('mouse_serial', ''))
        self.mouse_serial.setPlaceholderText('Optional; discovery fills this when available')
        self.mouse.currentIndexChanged.connect(self.mouse_selected)
        self.local_slot = combo([(f'Channel {i}', i) for i in (1, 2, 3)])
        self.away_slot = combo([(f'Channel {i}', i) for i in (1, 2, 3)])
        choose(self.local_slot, config.get('local_mouse_slot', 2 if config['away']['mouse_slot'] == 1 else 1))
        choose(self.away_slot, config['away']['mouse_slot'])
        form.addRow('Mouse', self.mouse)
        form.addRow('Mouse serial', self.mouse_serial)
        form.addRow('Channel paired to this computer', self.local_slot)
        form.addRow('Channel paired to other computer', self.away_slot)
        self.mouse_check_button = QPushButton('Check mouse and current channel')
        self.mouse_check_button.clicked.connect(lambda: self.test_mouse(False))
        self.mouse_test_button = QPushButton('Test mouse only → other channel')
        self.mouse_test_button.clicked.connect(lambda: self.test_mouse(True))
        form.addRow(self.mouse_check_button)
        form.addRow(self.mouse_test_button)
        hint = QLabel('Use the channel numbers on the underside of the mouse. The other app should use the reverse mapping.')
        hint.setWordWrap(True)
        form.addRow(hint)
        layout.addWidget(mouse)
        monitor = QGroupBox('Monitor inputs')
        form = QFormLayout(monitor)
        backends = {'linux': [('Dell / ddcutil', 'ddcutil')],
                    'win32': [('Windows monitor control', 'windows')],
                    'darwin': [('m1ddc (Apple Silicon)', 'm1ddc'), ('BetterDisplay (Intel or Apple Silicon)', 'betterdisplay')]}
        self.backend = combo(backends.get(sys.platform, backends['linux']) + [('Do not control the monitor here', 'disabled')])
        choose(self.backend, config['monitor'].get('backend', settings.defaults()['monitor']['backend']))
        self.display = combo([(f'Display {i}', str(i)) for i in range(1, 9)]
                             if sys.platform == 'win32' else [], editable=True)
        choose(self.display, str(config['monitor'].get('serial', config['monitor'].get('display', ''))))
        self.display.currentIndexChanged.connect(self.monitor_selected)
        self.display_label = QLabel()
        self.executable = QLineEdit(config['monitor'].get('executable', ''))
        self.executable.setPlaceholderText('Optional path; leave blank to use the installed tool')
        self.local_input = combo(editable=True)
        self.away_input = combo(editable=True)
        self.set_inputs({}, config['local_input'], config['away']['input'])
        self.away_name = QLineEdit(config['away']['name'])
        form.addRow('Control method', self.backend)
        form.addRow(self.display_label, self.display)
        form.addRow('Tool path', self.executable)
        form.addRow('This computer’s input', self.local_input)
        form.addRow('Other computer’s name', self.away_name)
        form.addRow('Other computer’s input', self.away_input)
        self.backend.currentIndexChanged.connect(self.backend_changed)
        self.backend_changed()
        layout.addWidget(monitor)
        behavior = QGroupBox('Automatic switching')
        form = QFormLayout(behavior)
        self.follow = QCheckBox('Follow keyboard disconnects')
        self.follow.setChecked(config.get('follow', False))
        self.delay = QDoubleSpinBox()
        self.delay.setRange(1, 60)
        self.delay.setSuffix(' seconds')
        self.delay.setValue(config.get('settle_seconds', 3))
        self.poll = QDoubleSpinBox()
        self.poll.setRange(0.25, 60)
        self.poll.setSingleStep(0.25)
        self.poll.setSuffix(' seconds')
        self.poll.setValue(config.get('poll_seconds', 1))
        self.startup = QCheckBox('Start MonitorMan when I log in')
        from install_launcher import autostart_path
        self.startup.setChecked(autostart_path().exists())
        form.addRow(self.follow)
        form.addRow('Wait for a stable disconnect', self.delay)
        form.addRow('Check keyboard every', self.poll)
        form.addRow(self.startup)
        warning = QLabel('Keyboard sleep or powering it off can also trigger a switch. With no communication between apps, the destination is always the “other computer” configured above.')
        warning.setWordWrap(True)
        form.addRow(warning)
        layout.addWidget(behavior)
        tests = QHBoxLayout()
        self.home_button = QPushButton('Test this computer’s monitor input')
        self.home_button.clicked.connect(lambda: self.test(False))
        self.away_button = QPushButton('Test switch to other computer')
        self.away_button.clicked.connect(lambda: self.test(True))
        tests.addWidget(self.home_button)
        tests.addWidget(self.away_button)
        layout.addLayout(tests)
        hint = QLabel('The second test sends the mouse and monitor away immediately. It does not switch the keyboard.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.status = QLabel('Choose your devices, then Save and apply.')
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.save_button = QPushButton('Save and apply')
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save)
        buttons = QHBoxLayout()
        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.close)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.save_button)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.addWidget(scroll)
        outer_layout.addWidget(self.status)
        outer_layout.addLayout(buttons)
        self.setCentralWidget(outer)

    def backend_changed(self):
        backend = self.backend.currentData()
        labels = {'ddcutil': 'Dell serial (blank = only Dell)', 'windows': 'Physical display number',
                  'm1ddc': 'Display number or UUID', 'betterdisplay': 'Exact display name', 'disabled': 'Display'}
        self.display_label.setText(labels[backend])
        self.display.setEnabled(backend != 'disabled')
        self.display.lineEdit().setPlaceholderText('1' if backend in ('windows', 'm1ddc') else '')
        self.executable.setEnabled(backend in ('m1ddc', 'betterdisplay'))

    def set_inputs(self, choices, local, away):
        values = {0x11: 'HDMI 1', 0x12: 'HDMI 2', 0x1b: 'USB-C', 0x0f: 'DisplayPort 1', 0x10: 'DisplayPort 2'}
        values.update(choices)
        for box, value in [(self.local_input, local), (self.away_input, away)]:
            box.clear()
            for code, name in values.items():
                box.addItem(f'{name} (0x{code:02x})', code)
            if box.findData(value) == -1:
                box.addItem(f'Input 0x{value:02x}', value)
            choose(box, value)

    def mouse_selected(self):
        data = self.mouse.currentData()
        if isinstance(data, (tuple, list)):
            self.mouse_serial.setText(data[1])

    def monitor_selected(self):
        serial = selected(self.display)
        for _name, found_serial, choices in self.monitors:
            if serial == found_serial:
                try:
                    local, away = settings.input_code(self.local_input.currentText()), settings.input_code(self.away_input.currentText())
                except ValueError:
                    local, away = self.config['local_input'], self.config['away']['input']
                self.set_inputs(choices, local, away)
                break

    def discover(self):
        self.discover_button.setEnabled(False)
        self.status.setText('Finding devices… You can keep editing while discovery runs.')
        def done(result):
            self.discover_button.setEnabled(True)
            current_keyboard = self.keyboard.currentText()
            try:
                current_address = settings.parse_address(current_keyboard)
            except ValueError:
                current_address = None
            self.keyboard.clear()
            pairs = sorted(result['keyboards'], key=lambda pair: 'keychron' not in pair[0].casefold())
            for name, address in pairs:
                self.keyboard.addItem(f'{name} — {address}', address)
            if current_address:
                choose(self.keyboard, current_address)
            elif not pairs:
                self.keyboard.setEditText(current_keyboard)
            mouse_text, serial_text = self.mouse.currentText(), self.mouse_serial.text()
            self.mouse.blockSignals(True)
            self.mouse.clear()
            for name, serial in result['mice']:
                self.mouse.addItem(name, (name, serial))
            index = next((i for i in range(self.mouse.count())
                          if self.mouse.itemText(i) == mouse_text
                          and (not serial_text or self.mouse.itemData(i)[1] == serial_text)), -1)
            if index < 0 and not serial_text:
                matches = [i for i in range(self.mouse.count()) if mouse_text.casefold() in self.mouse.itemText(i).casefold()]
                if len(matches) == 1:
                    index = matches[0]
            if index >= 0:
                self.mouse.setCurrentIndex(index)
            else:
                self.mouse.setEditText(mouse_text)
            self.mouse.blockSignals(False)
            if index >= 0:
                self.mouse_selected()
            else:
                self.mouse_serial.setText(serial_text)
            self.monitors = result['monitors']
            if self.backend.currentData() == 'ddcutil':
                current = selected(self.display)
                self.display.blockSignals(True)
                self.display.clear()
                for name, serial, _choices in self.monitors:
                    self.display.addItem(f'{name} — {serial or "no serial"}', serial)
                choose(self.display, current)
                self.display.blockSignals(False)
                # Select the sole discovered display on first setup.
                if not current and len(self.monitors) == 1:
                    self.display.setCurrentIndex(0)
                    self.monitor_selected()
            errors = '\n'.join(result['errors'])
            self.status.setText(f'Found {len(pairs)} paired Bluetooth devices, {len(result["mice"])} Logitech devices, {len(self.monitors)} Dell monitors.' + ('\n' + errors if errors else ''))
        self.controller.submit(settings.discover, done,
                               lambda error: (self.discover_button.setEnabled(True), self.error(error)))

    def values(self):
        config = deepcopy(self.config)
        config['keyboard_address'] = settings.parse_address(self.keyboard.currentText())
        mouse = selected(self.mouse)
        config['mouse_name'] = mouse[0] if isinstance(mouse, (tuple, list)) else str(mouse)
        config['mouse_serial'] = self.mouse_serial.text().strip()
        config['local_mouse_slot'] = self.local_slot.currentData()
        config['local_input'] = settings.input_code(self.local_input.currentText())
        config['away'] = {**config['away'], 'name': self.away_name.text().strip(),
                          'input': settings.input_code(self.away_input.currentText()),
                          'mouse_slot': self.away_slot.currentData()}
        backend = self.backend.currentData()
        monitor = deepcopy(config['monitor'])
        monitor['backend'] = backend
        monitor.pop('serial', None)
        monitor.pop('display', None)
        monitor.pop('executable', None)
        display = selected(self.display)
        if backend == 'ddcutil' and display:
            monitor['serial'] = str(display)
        elif backend == 'windows':
            try:
                monitor['display'] = int(display or 1)
            except ValueError:
                raise ValueError('Windows display number must be a positive whole number') from None
            if monitor['display'] < 1:
                raise ValueError('Windows display number must be positive')
        elif backend in ('m1ddc', 'betterdisplay'):
            monitor['display'] = str(display or ('1' if backend == 'm1ddc' else ''))
            if self.executable.text().strip():
                monitor['executable'] = self.executable.text().strip()
        config['monitor'] = monitor
        config.update(follow=self.follow.isChecked(), start_at_login=self.startup.isChecked(),
                      settle_seconds=self.delay.value(), poll_seconds=self.poll.value())
        return validate_config(config)

    def error(self, error):
        self.status.setText(str(error))

    def check_keyboard(self):
        try:
            address = settings.parse_address(self.keyboard.currentText())
        except ValueError as error:
            self.error(error)
            return
        self.check_button.setEnabled(False)
        self.status.setText('Checking keyboard connection…')
        def done(connected):
            self.check_button.setEnabled(True)
            self.status.setText('Keyboard is connected to this computer.' if connected else 'Keyboard is paired but currently disconnected.')
        self.controller.submit(lambda: devices.keyboard_connected(address), done,
                               lambda error: (self.check_button.setEnabled(True), self.error(error)))

    def test_mouse(self, switch):
        mouse = selected(self.mouse)
        name = mouse[0] if isinstance(mouse, (tuple, list)) else str(mouse).strip()
        serial = self.mouse_serial.text().strip()
        slot = self.away_slot.currentData()
        if not name:
            self.error('Choose a mouse first.')
            return
        self.mouse_check_button.setEnabled(False)
        self.mouse_test_button.setEnabled(False)
        self.status.setText(f'Sending mouse to channel {slot}…' if switch else 'Checking mouse access and current channel…')
        def work():
            with self.controller.hardware_lock:
                return devices.switch_mouse(slot, name, serial) if switch else devices.mouse_status(name, serial)
        def done(result):
            self.mouse_check_button.setEnabled(True)
            self.mouse_test_button.setEnabled(True)
            self.status.setText(result)
        self.controller.submit(work, done, lambda error: done(str(error)))

    def test(self, away):
        try:
            config = self.values()
        except (ValueError, KeyError) as error:
            self.error(error)
            return
        self.home_button.setEnabled(False)
        self.away_button.setEnabled(False)
        self.status.setText('Sending switch commands…')
        def work():
            follower = Follower(config)
            follower.action_lock = self.controller.hardware_lock
            return follower.away() if away else follower.home()
        def done(result):
            self.home_button.setEnabled(True)
            self.away_button.setEnabled(True)
            self.status.setText(result)
        self.controller.submit(work, done, lambda error: done(str(error)))

    def save(self):
        try:
            config = self.values()
        except (ValueError, KeyError) as error:
            self.error(error)
            return
        self.save_button.setEnabled(False)
        self.status.setText('Saving settings…')
        def done(result):
            saved, warning = result
            self.config = deepcopy(saved)
            self.save_button.setEnabled(True)
            self.status.setText(warning or 'Saved and applied. You can close this window; MonitorMan stays in the status bar.')
        self.controller.submit(lambda: self.controller.apply(config), done,
                               lambda error: (self.save_button.setEnabled(True), self.error(error)))

    def closeEvent(self, event):
        if self.controller.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            self.controller.quit()
            event.accept()


class Controller:
    def __init__(self, app, path, config=None):
        self.app, self.path = app, Path(path)
        self.config = deepcopy(config or settings.defaults())
        self.hardware_lock = threading.RLock()
        self.service = None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.bridge = Completion()
        self.bridge.done.connect(self.completed, Qt.ConnectionType.QueuedConnection)
        self.closing = False
        self.window = SettingsWindow(self, self.config)
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor('white'), 3))
        painter.setBrush(QColor('#3685cb'))
        painter.drawRoundedRect(5, 8, 54, 38, 5, 5)
        painter.drawLine(32, 46, 32, 56)
        painter.drawLine(20, 57, 44, 57)
        painter.end()
        self.tray = QSystemTrayIcon(QIcon(pixmap), app)
        self.tray.setToolTip('MonitorMan')
        self.menu = QMenu()
        self.status_action = self.menu.addAction('Configure your devices in Settings…')
        self.status_action.setEnabled(False)
        self.menu.addAction('Settings…', self.show_settings)
        self.follow_action = self.menu.addAction('Follow keyboard disconnects')
        self.follow_action.setCheckable(True)
        self.follow_action.triggered.connect(self.toggle)
        self.home_action = self.menu.addAction('Select this computer’s monitor input', lambda: self.action(False))
        self.away_action = self.menu.addAction('Send mouse + monitor to other computer', lambda: self.action(True))
        self.menu.addSeparator()
        self.menu.addAction('Quit', self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(lambda reason: self.show_settings() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        if config:
            self.start_service(config)
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def submit(self, work, done, failed=None):
        future = self.pool.submit(work)
        def finished(result):
            if not self.closing:
                try:
                    self.bridge.done.emit(result, done, failed)
                except RuntimeError:
                    pass  # Qt has already closed while a hardware command finished.
        future.add_done_callback(finished)

    def completed(self, future, done, failed):
        try:
            result = future.result()
        except Exception as error:
            (failed or self.window.error)(error)
        else:
            done(result)

    def start_service(self, config):
        if self.service:
            self.service.configure(config)
        else:
            self.service = Follower(config)
            self.service.action_lock = self.hardware_lock
            self.service.start()
        self.config = deepcopy(config)

    def apply(self, config):
        saved = settings.save_config(self.path, config)
        warning = ''
        try:
            from install_launcher import install, remove_autostart
            if saved.get('start_at_login'):
                install(Path(__file__).resolve().parent.parent, self.path, True)
            else:
                remove_autostart()
        except Exception as error:
            warning = f'Settings saved; login startup could not be updated: {error}'
        self.start_service(saved)
        return saved, warning

    def show_settings(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def toggle(self):
        if self.service:
            self.submit(self.service.toggle, lambda _: self.refresh())

    def action(self, away):
        if self.service:
            self.submit(self.service.away if away else self.service.home, self.window.status.setText)

    def refresh(self):
        service = self.service
        self.follow_action.setEnabled(service is not None)
        self.home_action.setEnabled(service is not None)
        self.away_action.setEnabled(service is not None)
        if service:
            self.status_action.setText(service.status[:180])
            self.tray.setToolTip('MonitorMan · ' + service.status[:120])
            self.follow_action.setChecked(service.enabled)
            self.away_action.setText(f'Send mouse + monitor to {service.config["away"]["name"]}')

    def quit(self):
        if self.service:
            self.service.stop()
        self.timer.stop()
        self.tray.hide()
        self.app.quit()

    def shutdown(self):
        self.closing = True
        if self.service:
            self.service.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)


def run(config=None, config_path=None, show_settings=False, error=None):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName('MonitorMan')
    app.setQuitOnLastWindowClosed(False)
    controller = Controller(app, config_path or settings.default_path(), config)
    if error:
        controller.window.status.setText(f'Could not load settings: {error}. Correct the fields and save.')
    if show_settings or config is None or not controller.tray.isVisible():
        controller.show_settings()
    try:
        return app.exec()
    finally:
        controller.shutdown()
