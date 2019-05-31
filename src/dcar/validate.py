"""
dcar.validate
-------------
"""

import re
import string

from .const import MAX_NAME_LEN, LOCAL_PATH, LOCAL_INTERFACE
from .errors import ValidationError, SignatureError
from .signature import Signature

_INVALID_CHARS_RE = re.compile('[^a-zA-Z0-9_]')
_INVALID_CHARS_BUS_RE = re.compile(r'[^a-zA-Z0-9_-]')

__all__ = [
    'is_valid_bus_name',
    'is_valid_error_name',
    'is_valid_interface_name',
    'is_valid_member_name',
    'is_valid_object_path',
    'is_valid_serial',
    'is_valid_signature',
    'is_valid_unixfds_field',
    'validate_bus_name',
    'validate_error_name',
    'validate_interface_name',
    'validate_member_name',
    'validate_object_path',
    'validate_serial',
    'validate_signature',
    'validate_unixfds_field',
]


def is_valid_object_path(s):
    if not isinstance(s, str) or not s.startswith('/'):
        return False
    if s == LOCAL_PATH:
        return False
    if s == '/':
        return True
    if s.endswith('/'):
        return False
    for elem in s[1:].split('/'):
        if not elem or _INVALID_CHARS_RE.search(elem):
            return False
    return True


def is_valid_signature(s):
    try:
        Signature(s)
        return True
    except SignatureError:
        return False


def _is_valid_name(s):
    return 0 < len(s) <= MAX_NAME_LEN and isinstance(s, str)


def is_valid_interface_name(s):
    if not _is_valid_name(s):
        return False
    if s == LOCAL_INTERFACE:
        return False
    elems = s.split('.')
    if len(elems) < 2:
        return False
    for elem in elems:
        if (not elem or elem[0] in string.digits or
                _INVALID_CHARS_RE.search(elem)):
            return False
    return True


def is_valid_bus_name(s, unique=False, strict=True):
    if unique and not s.startswith(':'):
        return False
    if not _is_valid_name(s):
        return False
    if s.startswith(':'):
        unique = True
        s = s[1:]
    else:
        unique = False
    elems = s.split('.')
    if not elems[0] or strict and len(elems) < 2:
        return False
    for elem in elems:
        if (not elem or (not unique and elem[0] in string.digits) or
                _INVALID_CHARS_BUS_RE.search(elem)):
            return False
    return True


def is_valid_member_name(s):
    if (not _is_valid_name(s) or '.' in s or s[0] in string.digits or
            _INVALID_CHARS_RE.search(s)):
        return False
    return True


def is_valid_error_name(s):
    return is_valid_interface_name(s)


def is_valid_serial(i):
    return isinstance(i, int) and i > 0


def is_valid_unixfds_field(i):
    return isinstance(i, int) and i >= 0


def validate_object_path(s):
    if not is_valid_object_path(s):
        raise ValidationError('not a valid object path: %r' % s)
    return s


def validate_signature(s):
    try:
        Signature(s)
    except SignatureError as ex:
        raise ValidationError('not a valid signature: %r' % s) from ex
    return s


def validate_interface_name(s):
    if not is_valid_interface_name(s):
        raise ValidationError('not a valid interface name: %r' % s)
    return s


def validate_bus_name(s, unique=False, strict=True):
    if not is_valid_bus_name(s, unique, strict):
        if unique:
            raise ValidationError('not a valid unique name: %r' % s)
        else:
            raise ValidationError('not a valid bus name: %r' % s)
    return s


def validate_member_name(s):
    if not is_valid_member_name(s):
        raise ValidationError('not a valid member name: %r' % s)
    return s


def validate_error_name(s):
    if not is_valid_error_name(s):
        raise ValidationError('not a valid error name: %r' % s)
    return s


def validate_serial(i):
    if not is_valid_serial(i):
        raise ValidationError('serial must be an int > 0 not %r' % i)


def validate_unixfds_field(i):
    if not is_valid_unixfds_field(i):
        raise ValidationError('UNIX_FDS field must be an int >= 0 not %r' % i)
