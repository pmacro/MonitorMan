import sys
from concurrent.futures import ThreadPoolExecutor
from . import ddc


def linux_main():
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('AyatanaAppIndicator3', '0.1')
        from gi.repository import Gtk, GLib, Gio, AyatanaAppIndicator3 as Indicator
    except (ImportError, ValueError) as error:
        sys.exit(f'{error}\nInstall python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1. See README.md.')

    class App(Gtk.Application):
        def __init__(self):
            super().__init__(application_id='io.monitorman.InputSwitcher',
                             flags=Gio.ApplicationFlags.FLAGS_NONE)
            self.pool = ThreadPoolExecutor(max_workers=1)
            self.busy = False
            self.indicator = None
            self.monitors = []
            self.message = 'Scanning Dell monitors…'

        def do_activate(self):
            if self.indicator is not None:
                return
            self.hold()
            self.indicator = Indicator.Indicator.new(
                'monitorman', 'video-display', Indicator.IndicatorCategory.HARDWARE)
            self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
            self.scan()

        def item(self, menu, label, callback=None):
            item = Gtk.MenuItem(label=label)
            item.set_sensitive(callback is not None and not self.busy)
            if callback:
                item.connect('activate', callback)
            menu.append(item)
            return item

        def render(self):
            menu = Gtk.Menu()
            self.item(menu, 'MonitorMan')
            if self.message:
                self.item(menu, self.message)
            for monitor, choices, active, error in self.monitors:
                self.item(menu, f'{monitor.model} · {monitor.serial or "no serial"}')
                if error:
                    self.item(menu, 'Input discovery failed')
                for code, label in choices.items():
                    prefix = '✓ ' if code == active else '    '
                    self.item(menu, prefix + label,
                              lambda _, m=monitor, c=code: self.change(m, c))
            menu.append(Gtk.SeparatorMenuItem())
            self.item(menu, 'Rescan monitors', lambda _: self.scan())
            self.item(menu, 'Setup / troubleshooting', lambda _: self.help())
            quit_item = Gtk.MenuItem(label='Quit')
            quit_item.connect('activate', lambda _: self.quit())
            menu.append(quit_item)
            menu.show_all()
            self.indicator.set_menu(menu)

        def work(self, task, done):
            self.busy = True
            self.render()
            future = self.pool.submit(task)
            def finish():
                self.busy = False
                try:
                    result = future.result()
                except Exception as error:
                    self.message = 'Monitor communication failed — rescan to retry'
                    self.dialog(str(error))
                else:
                    done(result)
                self.render()
                return False
            future.add_done_callback(lambda _: GLib.idle_add(finish))

        def scan(self):
            self.message = 'Scanning Dell monitors…'
            def task():
                results = []
                for monitor in ddc.detect():
                    try:
                        choices = ddc.inputs(monitor)
                        try:
                            active = ddc.current(monitor)
                        except RuntimeError:
                            active = None
                        results.append((monitor, choices, active, None))
                    except RuntimeError as error:
                        results.append((monitor, {}, None, str(error)))
                return results
            def done(results):
                self.monitors = results
                self.message = '' if results else 'No controllable Dell monitor found'
                errors = [row[3] for row in results if row[3]]
                if errors:
                    self.dialog('\n\n'.join(errors))
            self.work(task, done)

        def change(self, monitor, code):
            self.message = 'Switching input…'
            def done(_):
                # Acknowledgement means sent, not proof that the new input is active.
                self.message = 'Input command sent · rescan when reconnected'
                self.monitors = [(m, choices, None if m == monitor else active, error)
                                 for m, choices, active, error in self.monitors]
            self.work(lambda: ddc.switch(monitor, code), done)

        def dialog(self, text):
            dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.INFO,
                                       buttons=Gtk.ButtonsType.CLOSE, text='MonitorMan')
            dialog.format_secondary_text(text)
            dialog.connect('response', lambda widget, _: widget.destroy())
            dialog.show_all()

        def help(self):
            self.dialog('Enable DDC/CI in the Dell on-screen menu. Connect with HDMI, DisplayPort or USB-C video.\n\n'
                        'Install: sudo apt install ddcutil python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1\n'
                        'Load I²C: sudo modprobe i2c-dev\n\n'
                        'If access is denied, follow README.md. GNOME needs the AppIndicator extension enabled.\n\n'
                        'After switching to another computer, use that computer or the monitor buttons to switch back if DDC becomes unreachable.')

    app = App()
    try:
        return app.run(sys.argv)
    finally:
        app.pool.shutdown(wait=False, cancel_futures=True)


def main():
    from .cli import entry
    return entry()


if __name__ == '__main__':
    sys.exit(main())
