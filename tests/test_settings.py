from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from monitorman import settings
from monitorman.follow import Follower, load_config


class SettingsTests(unittest.TestCase):
    def configured(self):
        result = settings.defaults()
        result['keyboard_address'] = 'AA:BB:CC:DD:EE:FF'
        return result

    def test_save_roundtrip_and_validation_preserve_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nested/settings.json'
            config = self.configured()
            settings.save_config(path, config)
            original = path.read_bytes()
            self.assertEqual(load_config(path)['local_mouse_slot'], 1)
            config['away']['mouse_slot'] = 1
            with self.assertRaisesRegex(ValueError, 'different mouse channels'):
                settings.save_config(path, config)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob('.monitorman-*')), [])

    def test_failed_replace_keeps_original_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            settings.save_config(path, self.configured())
            original = path.read_bytes()
            with patch('monitorman.settings.os.replace', side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError):
                    settings.save_config(path, self.configured())
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob('.monitorman-*')), [])

    def test_choosing_other_mouse_channel_is_used_by_switcher(self):
        config = self.configured()
        config['away']['mouse_slot'] = 3
        mouse = Mock(return_value='sent')
        follower = Follower(config, Mock(), mouse, Mock(return_value='sent'))
        follower.away()
        mouse.assert_called_once_with(3, 'MX Vertical', None)

    def test_live_settings_reset_pending_edges_and_change_keyboard_address(self):
        config = self.configured()
        follower = Follower(config, mouse=Mock(), monitor=Mock())
        with patch('monitorman.devices.keyboard_connected', return_value=True) as probe:
            follower.poll(0)
            probe.assert_called_with('AA:BB:CC:DD:EE:FF')
            follower.tracker.observe(False, 1)
            updated = deepcopy(config)
            updated.update(keyboard_address='11:22:33:44:55:66', follow=True)
            follower.configure(updated)
            self.assertIsNone(follower.tracker.stable)
            follower.poll(10)
            probe.assert_called_with('11:22:33:44:55:66')
            self.assertTrue(follower.enabled)
            follower.mouse.assert_not_called()
            follower.monitor.assert_not_called()

    def test_selected_device_addresses_and_input_labels(self):
        self.assertEqual(settings.parse_address('Keychron K2 — aa-bb-cc-dd-ee-ff'), 'AA:BB:CC:DD:EE:FF')
        self.assertEqual(settings.input_code('USB-C (0x1b)'), 27)
        self.assertEqual(settings.input_code('17'), 17)
        for invalid in ('USB-C', '0x100', '-1'):
            with self.assertRaises(ValueError):
                settings.input_code(invalid)

    @patch('monitorman.devices.command')
    def test_paired_device_discovery(self, command):
        with patch('sys.platform', 'linux'):
            command.return_value = 'Device AA:BB:CC:DD:EE:FF Keychron K2\nDevice 11:22:33:44:55:66 MX Vertical\n'
            self.assertEqual(settings.paired_devices()[0], ('Keychron K2', 'AA:BB:CC:DD:EE:FF'))
        with patch('sys.platform', 'darwin'):
            command.return_value = json.dumps([{'name': 'Keychron K2', 'address': 'aa-bb-cc-dd-ee-ff'}])
            self.assertEqual(settings.paired_devices(), [('Keychron K2', 'AA:BB:CC:DD:EE:FF')])

    @patch('monitorman.settings.ddc.detect', side_effect=RuntimeError('No DDC'))
    @patch('monitorman.devices.hid_devices', side_effect=RuntimeError('No HID'))
    @patch('monitorman.settings.paired_devices', return_value=[('Keychron K2', 'AA:BB:CC:DD:EE:FF')])
    def test_partial_discovery_preserves_successful_results(self, paired, hid, ddc):
        with patch('sys.platform', 'linux'):
            result = settings.discover()
        self.assertEqual(len(result['keyboards']), 1)
        self.assertEqual(len(result['errors']), 2)


if __name__ == '__main__':
    unittest.main()
