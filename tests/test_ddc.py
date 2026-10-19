import subprocess
import unittest
from unittest.mock import patch
from monitorman import ddc


class BackendTests(unittest.TestCase):
    def test_only_valid_dell_displays_are_selected(self):
        output = '''Display 1
 I2C bus: /dev/i2c-7
 Monitor: DEL:DELL S2725QC:ABC123
Invalid display
 I2C bus: /dev/i2c-8
 Monitor: DEL:DELL S2725QC:PHANTOM
Display 2
 I2C bus: /dev/i2c-9
 Monitor: ACR:Other:OTHER
Display 3
 I2C bus: /dev/i2c-10
 Monitor: DEL:DELL U2720Q:
'''
        self.assertEqual(ddc.parse_monitors(output), [
            ddc.Monitor(7, 'DELL S2725QC', 'ABC123'),
            ddc.Monitor(10, 'DELL U2720Q', '')])

    def test_inputs_do_not_include_other_feature_values(self):
        output = '''Model: S2725QC
  Feature: 60 (Input Source)
    Values:
      11: HDMI-1
      12: HDMI-2
      1b: USB-C
  Feature: AA (Screen Orientation)
    Values:
      01: Landscape
'''
        self.assertEqual(ddc.parse_inputs(output), {0x11: 'HDMI-1', 0x12: 'HDMI-2', 0x1b: 'USB-C'})
        self.assertEqual(ddc.parse_inputs('Feature: 10 (Brightness)'), {})

    @patch('monitorman.ddc.run')
    def test_dell_usb_c_label_fallback(self, run):
        monitor = ddc.Monitor(7, 'DELL S2725QC', 'ABC')
        for label in ('Unrecognized value', 'Unrecognized feature value'):
            with self.subTest(label=label):
                run.return_value = f'  Feature: 60 (Input Source)\n    Values:\n      1b: {label}\n      12: HDMI-2\n      ff: Unrecognized value\n'
                self.assertEqual(ddc.inputs(monitor), {
                    0x1b: 'USB-C', 0x12: 'HDMI-2', 0xff: 'Unrecognized value'})
        run.return_value = '  Feature: 60 (Input Source)\n    Values:\n      1b: USB-C (Laptop)\n'
        self.assertEqual(ddc.inputs(monitor), {0x1b: 'USB-C (Laptop)'})

    @patch('monitorman.ddc.run')
    def test_switch_targets_bus_with_hex_value_and_no_readback(self, run):
        ddc.switch(ddc.Monitor(7, 'Dell', 'ABC'), 0x11)
        run.assert_called_once_with('--bus', '7', 'setvcp', '60', '0x11', '--noverify')

    @patch('monitorman.ddc.run', return_value='VCP code 0x60 (Input Source): HDMI-1 (sl=0x11)')
    def test_current_input(self, run):
        self.assertEqual(ddc.current(ddc.Monitor(7, 'Dell', 'ABC')), 0x11)

    @patch('subprocess.run', side_effect=subprocess.TimeoutExpired('ddcutil', 45))
    def test_timeout_is_actionable(self, run):
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            ddc.run('detect')

    @patch('subprocess.run', side_effect=FileNotFoundError)
    def test_missing_dependency(self, run):
        with self.assertRaisesRegex(RuntimeError, 'Install ddcutil'):
            ddc.run('detect')

    @patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'Permission denied'))
    def test_command_errors_are_visible(self, run):
        with self.assertRaisesRegex(RuntimeError, 'Permission denied'):
            ddc.run('detect')


if __name__ == '__main__':
    unittest.main()
