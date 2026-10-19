"""Per-user file lock. No network sockets and no communication between computers."""
import getpass
import os
import re
import sys
import tempfile
from pathlib import Path


class SingleInstance:
    def __enter__(self):
        user = re.sub(r'[^a-zA-Z0-9_-]', '_', getpass.getuser())
        self.file = (Path(tempfile.gettempdir()) / f'monitorman-{user}.lock').open('a+b')
        try:
            if sys.platform == 'win32':
                import msvcrt
                self.file.seek(0, os.SEEK_END)
                if self.file.tell() == 0:
                    self.file.write(b'0')
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            raise RuntimeError('MonitorMan follow helper is already running for this user') from error
        return self

    def __exit__(self, *_):
        self.file.close()
