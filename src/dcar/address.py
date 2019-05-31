"""
dcar.address
------------
"""

import os
import string
import sys

from .errors import AddressError

__all__ = ['Address']


class Address:
    def __init__(self, address='session'):
        if address.lower() == 'system':
            addr = os.environ.get(
                'DBUS_SYSTEM_BUS_ADDRESS',
                'unix:path=/var/run/dbus/system_bus_socket')
            self._bus_type = 'system'
        elif address.lower() == 'session':
            addr = os.environ.get('DBUS_SESSION_BUS_ADDRESS')
            if not addr:
                raise AddressError('no address found for SESSION bus')
            self._bus_type = 'session'
        elif address.lower() == 'starter':
            addr = os.environ.get('DBUS_STARTER_ADDRESS')
            if not addr:
                raise AddressError('no address found for STARTER bus')
            self._bus_type = os.environ.get('DBUS_STARTER_BUS_TYPE')
        else:
            addr = address
            self._bus_type = None
        self._addrs = addr.split(';')

    @property
    def bus_type(self):
        return self._bus_type

    def __len__(self):
        return len(self._addrs)

    def __iter__(self):
        for addr in self._addrs:
            name, params = addr.split(':')
            yield name, {k: _unescape(v) for k, v in
                         (param.split('=') for param in params.split(','))}

    def __str__(self):
        return ';'.join(self._addrs)


optionally_escaped = (string.ascii_letters + string.digits + '-_/.\\').encode()


def _unescape(s):
    r, i, percent = [], 0, b'%'[0]
    b = s.encode(sys.getfilesystemencoding())
    while i < len(b):
        if b[i] == percent:
            r.append(int(b[i + 1:i + 3], 16))
            i += 3
        elif b[i] in optionally_escaped:
            r.append(b[i])
            i += 1
        else:
            raise AddressError('unescape: unallowed char %r' % chr(b[i]))
    return bytes(r).decode()
