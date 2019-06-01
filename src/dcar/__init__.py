"""D-Car main API.

This should normally be enough for implementing message bus clients.
"""

__version__ = '0.0.4'

# flake8: noqa

import os
import logging
from collections import namedtuple

from . import errors
from .bus import Bus
from .errors import *
from .router import MatchRule

__all__ = [
    'Bus',
    'MatchRule',
    'Variant',
    'UnixFD',
] + errors.__all__

logging.getLogger(__name__).addHandler(logging.NullHandler())

Variant = namedtuple('Variant', 'signature value')
Variant.__doc__ += '\nA D-Bus Variant.'
Variant.signature.__doc__ = 'D-Bus type signature'
Variant.value.__doc__ = 'value of the Variant'


class UnixFD:
    """Wrapper for a unix file descriptor.

    The file descriptor will be :func:`duplicated <os.dup>`. The caller is
    responsible for closing the original file descriptor.

    :param f: file descriptor or object that has a ``fileno()`` method which
              returns an :class:`int`
    :type f: int or file-like object
    :param bool close: if set to ``True`` the original file descriptor will be
                       closed after duplicating it
    """

    def __init__(self, f, close=False):
        if isinstance(f, int):
            self._fd = os.dup(f)
            if close:
                os.close(f)
        else:
            self._fd = os.dup(f.fileno())
            if close:
                f.close()

    def fileno(self):
        """Return the file descriptor.

        :returns: file descriptor
        :rtype: int
        """
        return self._fd
