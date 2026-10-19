"""Widget smoke tests; run with QT_QPA_PLATFORM=offscreen when PySide6 is installed."""
import importlib.util
import os
import unittest
from unittest.mock import Mock
from monitorman import settings

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None


@unittest.skipUnless(HAS_QT, 'PySide6 is not installed')
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from monitorman.gui import SettingsWindow
        self.config = settings.defaults()
        self.config['keyboard_address'] = 'AA:BB:CC:DD:EE:FF'
        self.controller = Mock()
        self.window = SettingsWindow(self.controller, self.config)

    def tearDown(self):
        self.window.deleteLater()
        self.app.processEvents()

    def test_channel_three_roundtrip_and_custom_input(self):
        self.window.away_slot.setCurrentIndex(2)
        self.window.away_input.setEditText('0x1b')
        config = self.window.values()
        self.assertEqual(config['away']['mouse_slot'], 3)
        self.assertEqual(config['away']['input'], 27)
        self.assertEqual(config['local_mouse_slot'], 1)

    def test_same_channels_show_validation_error_without_saving(self):
        self.window.away_slot.setCurrentIndex(0)
        self.window.save()
        self.assertIn('different mouse channels', self.window.status.text())
        self.controller.submit.assert_not_called()

    def test_discovered_keyboard_selection_returns_address(self):
        self.window.keyboard.addItem('Keychron K2 — AA:BB:CC:DD:EE:FF', 'AA:BB:CC:DD:EE:FF')
        self.window.keyboard.setCurrentIndex(0)
        self.assertEqual(self.window.values()['keyboard_address'], 'AA:BB:CC:DD:EE:FF')

    def test_discovery_populates_mouse_serial_for_matching_longer_name(self):
        self.window.discover()
        done = self.controller.submit.call_args.args[1]
        done({'keyboards': [], 'mice': [('Logitech MX Vertical Advanced Ergonomic Mouse', 'dd:6d:55:ed:83:65')],
              'monitors': [], 'errors': []})
        self.assertEqual(self.window.mouse_serial.text(), 'dd:6d:55:ed:83:65')
        self.assertEqual(self.window.values()['mouse_name'], 'Logitech MX Vertical Advanced Ergonomic Mouse')

    def test_discovery_keeps_a_manually_entered_serial(self):
        self.window.mouse_serial.setText('keep-this-serial')
        self.window.discover()
        done = self.controller.submit.call_args.args[1]
        done({'keyboards': [], 'mice': [('MX Vertical', 'different')], 'monitors': [], 'errors': []})
        self.assertEqual(self.window.mouse_serial.text(), 'keep-this-serial')

    def test_mouse_check_displays_errors_and_reenables_buttons(self):
        self.window.test_mouse(False)
        failed = self.controller.submit.call_args.args[2]
        failed(RuntimeError('Permission denied for /dev/hidraw1'))
        self.assertIn('Permission denied', self.window.status.text())
        self.assertTrue(self.window.mouse_check_button.isEnabled())
        self.assertTrue(self.window.mouse_test_button.isEnabled())


if __name__ == '__main__':
    unittest.main()
