"""Input switching backends for Linux, macOS and Windows."""
import sys
from .devices import command
from . import ddc


def switch_input(settings, value):
    backend = settings.get('backend', {'darwin': 'm1ddc', 'win32': 'windows'}.get(sys.platform, 'ddcutil'))
    if backend == 'disabled':
        return 'Monitor control disabled on this computer'
    if backend == 'ddcutil':
        monitors = [m for m in ddc.detect() if
                    (not settings.get('serial') or m.serial == settings['serial'])]
        if len(monitors) != 1:
            raise RuntimeError('Select exactly one Dell monitor with monitor.serial; none or multiple found')
        ddc.switch(monitors[0], value)
    elif backend == 'm1ddc':
        command([settings.get('executable', 'm1ddc'), 'display', str(settings.get('display', '1')),
                 'set', 'input', str(value)], timeout=20)
    elif backend == 'betterdisplay':
        command([settings.get('executable', '/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay'),
                 'set', f'-name={settings["display"]}', '-feature=ddc', '-vcp=0x60',
                 f'-value={value}'], timeout=20)
    elif backend == 'windows':
        windows_switch(settings.get('display', 1), value)
    else:
        raise ValueError(f'Unknown monitor backend: {backend}')
    return 'Monitor input command sent'


def windows_switch(index, value):
    import ctypes as c
    from ctypes import wintypes as w
    if sys.platform != 'win32':
        raise RuntimeError('Windows monitor backend requires Windows')
    class Physical(c.Structure):
        _fields_ = [('handle', w.HANDLE), ('description', w.WCHAR * 128)]
    user = c.WinDLL('user32', use_last_error=True)
    dxva = c.WinDLL('dxva2', use_last_error=True)
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HANDLE, w.HDC, c.POINTER(w.RECT), w.LPARAM)
    user.EnumDisplayMonitors.argtypes = [w.HDC, c.POINTER(w.RECT), callback_type, w.LPARAM]
    user.EnumDisplayMonitors.restype = w.BOOL
    dxva.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [w.HANDLE, c.POINTER(w.DWORD)]
    dxva.GetNumberOfPhysicalMonitorsFromHMONITOR.restype = w.BOOL
    dxva.GetPhysicalMonitorsFromHMONITOR.argtypes = [w.HANDLE, w.DWORD, c.POINTER(Physical)]
    dxva.GetPhysicalMonitorsFromHMONITOR.restype = w.BOOL
    dxva.SetVCPFeature.argtypes = [w.HANDLE, w.BYTE, w.DWORD]
    dxva.SetVCPFeature.restype = w.BOOL
    dxva.DestroyPhysicalMonitors.argtypes = [w.DWORD, c.POINTER(Physical)]
    dxva.DestroyPhysicalMonitors.restype = w.BOOL
    handles = []
    @callback_type
    def collect(handle, _hdc, _rect, _data):
        handles.append(handle)
        return True
    if not user.EnumDisplayMonitors(None, None, collect, 0):
        raise c.WinError(c.get_last_error())
    found = 0
    for handle in handles:
        count = w.DWORD()
        if not dxva.GetNumberOfPhysicalMonitorsFromHMONITOR(handle, c.byref(count)):
            continue
        monitors = (Physical * count.value)()
        if not dxva.GetPhysicalMonitorsFromHMONITOR(handle, count, monitors):
            continue
        try:
            for monitor in monitors:
                found += 1
                if found == int(index):
                    if not dxva.SetVCPFeature(monitor.handle, 0x60, value):
                        raise c.WinError(c.get_last_error())
                    return
        finally:
            dxva.DestroyPhysicalMonitors(count, monitors)
    raise RuntimeError(f'Physical display {index} not found')
