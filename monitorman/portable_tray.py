"""Compatibility entry point for the shared Qt tray and settings window."""
def run(config=None, config_path=None, show_settings=False, error=None):
    try:
        from .gui import run as gui_run
    except ImportError as exception:
        raise RuntimeError('Install GUI dependencies: python -m pip install -r requirements.txt') from exception
    return gui_run(config, config_path, show_settings, error)
