"""
dcar.raw
--------
"""

import io
from contextlib import contextmanager

from .const import MAX_MESSAGE_LEN, MAX_MSG_UNIX_FDS, MAX_VARIANT_NESTING_DEPTH
from .errors import MessageError, TooLongError

__all__ = ['RawData']


class RawData(io.BytesIO):
    def __init__(self, initial_bytes=b''):
        super().__init__(initial_bytes)
        self.byteorder = None
        self._unix_fds = []
        self._nesting_depth = 0

    @property
    def unix_fds(self):
        return self._unix_fds

    @unix_fds.setter
    def unix_fds(self, fds):
        if len(fds) > MAX_MSG_UNIX_FDS:
            raise TooLongError('too many unix fds: %d' % len(fds))
        self._unix_fds = fds

    def write(self, b):
        n = super().write(b)
        if self.tell() > MAX_MESSAGE_LEN:
            raise TooLongError('message too long: %d bytes' % self.tell())
        return n

    def write_nul_bytes(self, n):
        self.write(b'\x00' * n)

    def write_padding(self, alignment):
        self.write_nul_bytes(self._padding_len(alignment))

    def skip_padding(self, alignment):
        b = self.read(self._padding_len(alignment))
        if any(list(b)):
            raise MessageError('none-NUL byte in padding: %s' % b)

    def set_value(self, pos, fixed_type, value):
        self.seek(pos)
        fixed_type.marshal(self, value)
        self.seek(0, io.SEEK_END)

    def add_unix_fd(self, fd):
        if fd in self._unix_fds:
            return self._unix_fds.index(fd)
        else:
            self._unix_fds.append(fd)
            fd_cnt = len(self._unix_fds)
            if fd_cnt > MAX_MSG_UNIX_FDS:
                raise TooLongError('too many unix fds: %d' % fd_cnt)
            return fd_cnt - 1

    def _padding_len(self, alignment):
        x = self.tell() % alignment
        if x:
            return alignment - x
        return 0

    def __repr__(self):
        return '<%s: byteorder=%s>' % (self.__class__.__name__,
                                       self.byteorder.name
                                       if self.byteorder is not None else None)

    @contextmanager
    def nesting_depth(self):
        self._nesting_depth += 1
        if self._nesting_depth > MAX_VARIANT_NESTING_DEPTH:
            raise MessageError('nesting depth > %d' % MAX_VARIANT_NESTING_DEPTH)
        try:
            yield
        finally:
            self._nesting_depth -= 1
