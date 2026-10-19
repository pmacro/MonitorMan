import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from monitorman.follow import ConnectionTracker, Follower, load_config
from monitorman import devices, displays


def config():
    return {'keyboard_address': '11:22:33:44:55:66', 'local_input': 17,
            'away': {'name': 'Mac', 'input': 27, 'mouse_slot': 2},
            'monitor': {}, 'follow': True, 'poll_seconds': 1, 'settle_seconds': 3}


class FollowTests(unittest.TestCase):
    def test_startup_and_transient_disconnect_do_not_switch(self):
        tracker = ConnectionTracker(3)
        self.assertIsNone(tracker.observe(True, 0))
        self.assertIsNone(tracker.observe(False, 1))
        self.assertIsNone(tracker.observe(True, 2))
        self.assertIsNone(tracker.observe(False, 3))
        self.assertIsNone(tracker.observe(False, 5))
        self.assertEqual(tracker.observe(False, 6), 'disconnected')
        self.assertIsNone(tracker.observe(False, 7))
        self.assertIsNone(tracker.observe(True, 8))
        self.assertEqual(tracker.observe(True, 11), 'connected')

    def test_probe_errors_reset_pending_disconnect(self):
        tracker = ConnectionTracker(3)
        tracker.observe(True, 0)
        tracker.observe(False, 1)
        tracker.observe(None, 5)
        self.assertIsNone(tracker.observe(False, 6))
        self.assertEqual(tracker.observe(False, 9), 'disconnected')

    def test_independent_two_way_flow(self):
        probe, mouse, monitor = Mock(return_value=True), Mock(return_value='sent'), Mock(return_value='sent')
        follower = Follower(config(), probe, mouse, monitor)
        follower.poll(0)
        probe.return_value = False
        follower.poll(1)
        follower.poll(4)
        mouse.assert_called_once_with(2, 'MX Vertical', None)
        monitor.assert_called_once_with({}, 27)
        follower.poll(5)
        mouse.assert_called_once()
        probe.return_value = True
        follower.poll(6)
        follower.poll(9)
        self.assertEqual(monitor.call_args.args, ({}, 17))
        mouse.assert_called_once()  # Destination cannot summon a disconnected mouse.

    def test_paused_tracking_does_not_fire_old_edges(self):
        probe, mouse, monitor = Mock(return_value=True), Mock(), Mock()
        settings = config()
        settings['follow'] = False
        follower = Follower(settings, probe, mouse, monitor)
        follower.poll(0)
        probe.return_value = False
        follower.poll(1)
        follower.poll(5)
        follower.toggle()
        follower.poll(6)
        mouse.assert_not_called()
        monitor.assert_not_called()

    def test_detection_failure_never_means_disconnect(self):
        probe = Mock(side_effect=[True, False, RuntimeError('adapter unavailable'), False, False])
        mouse = Mock(return_value='sent')
        follower = Follower(config(), probe, mouse, Mock(return_value='sent'))
        for now in [0, 1, 5, 6]:
            follower.poll(now)
        mouse.assert_not_called()
        follower.poll(9)
        mouse.assert_called_once()

    def test_enabling_follow_discards_a_pending_edge(self):
        probe = Mock(return_value=True)
        mouse = Mock(return_value='sent')
        settings = config()
        settings['follow'] = False
        follower = Follower(settings, probe, mouse, Mock(return_value='sent'))
        follower.poll(0)
        probe.return_value = False
        follower.poll(1)
        follower.toggle()
        follower.poll(5)
        follower.poll(9)
        mouse.assert_not_called()

    def test_partial_failure_still_attempts_monitor(self):
        monitor = Mock(return_value='Monitor sent')
        follower = Follower(config(), Mock(), Mock(side_effect=RuntimeError('no access')), monitor)
        self.assertIn('no access', follower.away())
        monitor.assert_called_once_with({}, 27)

    def test_config_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            settings = config()
            settings['local_input'] = '0x11'
            path.write_text(json.dumps(settings))
            self.assertEqual(load_config(path)['local_input'], 17)
            for value in (0, 4):
                settings['away']['mouse_slot'] = value
                path.write_text(json.dumps(settings))
                with self.assertRaises(ValueError):
                    load_config(path)


class HardwareProtocolTests(unittest.TestCase):
    def test_linux_prefers_bluetooth_capable_hidraw_backend(self):
        raw_backend, usb_backend = Mock(), Mock()
        with patch('sys.platform', 'linux'), patch.dict('sys.modules', {'hidraw': raw_backend, 'hid': usb_backend}):
            self.assertIs(devices.hid_module(), raw_backend)

    def test_other_platforms_use_native_hid_backend(self):
        raw_backend, native_backend = Mock(), Mock()
        for platform in ('darwin', 'win32'):
            with self.subTest(platform=platform), patch('sys.platform', platform), patch.dict('sys.modules', {'hidraw': raw_backend, 'hid': native_backend}):
                self.assertIs(devices.hid_module(), native_backend)

    def test_hid_reply_matching_and_packet_encoding(self):
        device = Mock()
        device.write.return_value = 20
        device.read.side_effect = [[0x11, 0xff, 2, 0x0d, 1, 2, 3],
                                   [0x11, 0xff, 0, 0x0d, 12, 0, 0]]
        self.assertEqual(devices.request(device, 0, 0, b'\x18\x14')[0], 12)
        self.assertEqual(device.write.call_args.args[0], b'\x11\xff\x00\x0d\x18\x14' + b'\0' * 14)

    def test_hid_error_response_is_not_success(self):
        device = Mock()
        device.write.return_value = 20
        device.read.return_value = [0x11, 0xff, 0xff, 0, 0x0d, 7, 0]
        with self.assertRaisesRegex(RuntimeError, r'HID\+\+ error'):
            devices.request(device, 0, 0)

    @patch('monitorman.devices.hid_module')
    def test_mouse_discovers_feature_and_sends_zero_based_slot(self, hid_module):
        hid = hid_module.return_value
        hid.enumerate.return_value = [{'product_string': 'MX Vertical', 'path': b'mouse', 'serial_number': 'abc', 'product_id': 123}]
        device = hid.device.return_value
        device.write.return_value = 20
        device.read.side_effect = [[0x11, 0xff, 0, 0x0d, 12, 0, 0],
                                   [0x11, 0xff, 12, 0x0d, 3, 0, 0]]
        self.assertEqual(devices.switch_mouse(2), 'Mouse switch command sent')
        self.assertEqual(device.write.call_args.args[0][:5], b'\x11\xff\x0c\x1d\x01')
        self.assertEqual(device.read.call_count, 2)  # No reply needed after changing host.
        device.close.assert_called_once()

    @patch('monitorman.devices.hid_module')
    def test_absent_mouse_has_an_actionable_error(self, hid_module):
        hid_module.return_value.enumerate.return_value = []
        with self.assertRaisesRegex(RuntimeError, 'No accessible mouse matches'):
            devices.switch_mouse(2)

    @patch('monitorman.devices.hid_module')
    def test_mouse_status_reads_current_channel_without_switching(self, hid_module):
        hid = hid_module.return_value
        hid.enumerate.return_value = [{'product_string': 'MX Vertical', 'path': b'mouse',
                                     'serial_number': 'abc', 'product_id': 123}]
        device = hid.device.return_value
        device.write.return_value = 20
        device.read.side_effect = [[0x11, 0xff, 0, 0x0d, 12, 0, 0],
                                   [0x11, 0xff, 12, 0x0d, 3, 2, 0]]
        self.assertIn('current channel 3 of 3', devices.mouse_status())
        self.assertEqual(device.write.call_count, 2)
        self.assertEqual(device.write.call_args.args[0][3], 0x0d)
        device.close.assert_called_once()

    @patch('pathlib.Path.read_text', return_value='HID_UNIQ=aa:bb:cc:dd:ee:ff\nHID_NAME=MX Vertical\n')
    def test_bluetooth_serial_fallback_matches_discovery_and_switching(self, read_text):
        info = {'path': b'/dev/hidraw1', 'serial_number': '', 'product_string': ''}
        with patch('sys.platform', 'linux'):
            result = devices._describe_devices([info])[0]
        self.assertEqual(result['serial_number'], 'aa:bb:cc:dd:ee:ff')
        self.assertEqual(result['product_string'], 'MX Vertical')
        self.assertEqual(info['serial_number'], '')

    @patch('monitorman.displays.command')
    def test_mac_ddc_commands(self, command):
        displays.switch_input({'backend': 'm1ddc', 'display': 'uuid'}, 27)
        command.assert_called_once_with(['m1ddc', 'display', 'uuid', 'set', 'input', '27'], timeout=20)
        command.reset_mock()
        displays.switch_input({'backend': 'betterdisplay', 'display': 'DELL S2725QC'}, 17)
        self.assertIn('-vcp=0x60', command.call_args.args[0])
        self.assertIn('-value=17', command.call_args.args[0])

    @patch('monitorman.devices.command')
    def test_bluetooth_probes(self, command):
        with patch('sys.platform', 'linux'):
            command.return_value = 'Device 11:22:33:44:55:66\n Connected: yes\n'
            self.assertTrue(devices.keyboard_connected('11:22:33:44:55:66'))
            command.return_value = 'Device not found'
            with self.assertRaises(RuntimeError):
                devices.keyboard_connected('11:22:33:44:55:66')
        with patch('sys.platform', 'darwin'):
            command.return_value = '0'
            self.assertFalse(devices.keyboard_connected('11:22:33:44:55:66'))


if __name__ == '__main__':
    unittest.main()
