"""Marshal/unmarshal D-Bus Messages.

.. _ref-types-table:

Types:

=============  ===================  ==========
D-Bus          Python IN            Python OUT
=============  ===================  ==========
a              list, array.array    list
()             tuple                tuple
a{}            dict                 dict
v              bus.Variant,         value
               2-tuple (sig,value)
s,o,g          str                  str
d              float                float
b              bool                 bool
y,n,q,i,u,x,t  int                  int
h              bus.UnixFD,          file descriptor
               obj with fileno(),
               file descriptor
=============  ===================  ==========

See:

* `Summary of types
  <https://dbus.freedesktop.org/doc/dbus-specification.html#idm487>`_
* `Marshalling (Wire Format)
  <https://dbus.freedesktop.org/doc/dbus-specification.html
  #message-protocol-marshaling>`_

.. note::
   Instances of the type classes should be used through the
   :data:`types` mapping which uses D-Bus type codes as keys.
"""

import array
import struct

from .const import MAX_ARRAY_LEN
from .errors import TooLongError, MessageError
from .signature import Signature
from .validate import validate_object_path, validate_signature

__all__ = ['types', 'marshal', 'unmarshal']


class Type:
    """Base class.

    :param str name: type name
    """

    def __init__(self, name):
        self.name = name

    def marshal(self, raw, data, signature=None):
        """Marshal an object of this type.

        The data must be of an appropriate type according
        to the column *Python IN* in the :ref:`table above <ref-types-table>`.

        The ``signature`` parameter is only used in the classes
        :class:`Array`, :class:`Struct`, and :class:`DictEntry`.

        :param RawData raw: raw message data
        :param data: data to be marshalled
        :param signature: see :class:`~dcar.signature.Signature`
        :raises ~dcar.MessageError: if the data could not be marshalled
        """
        raise NotImplementedError

    def unmarshal(self, raw, signature=None):
        """Unmarshal an object of this type.

        The returned data will be of a type according
        to the column *Python OUT* in the :ref:`table above <ref-types-table>`.

        The ``signature`` parameter is only used in the classes
        :class:`Array`, :class:`Struct`, and :class:`DictEntry`.

        :param RawData raw: raw message data
        :param signature: see :class:`~dcar.signature.Signature`
        :return: unmarshalled data
        :raises ~dcar.MessageError: if the data could not be unmarshalled
        """
        raise NotImplementedError

    def __repr__(self):
        signature = [k for k in types if types[k] is self][0]
        return '<%s:%s:%r>' % (self.__class__.__name__, self.name, signature)


class Fixed(Type):
    """Class for fixed types.

    :param str name: type name
    :param str struct_code: code from :mod:`struct` module
    """

    def __init__(self, name, struct_code):
        super().__init__(name)
        self.code = struct_code
        self.size = struct.calcsize(struct_code)
        self.alignment = self.size

    def marshal(self, raw, data, signature=None):
        raw.write_padding(self.alignment)
        try:
            raw.write(struct.pack(raw.byteorder.code + self.code, data))
        except struct.error as ex:
            raise MessageError('marshal %s %r: %s' %
                               (self.name, data, ex)) from ex

    def unmarshal(self, raw, signature=None):
        raw.skip_padding(self.alignment)
        try:
            value = raw.read(self.size)
            return struct.unpack(raw.byteorder.code + self.code, value)[0]
        except struct.error as ex:
            raise MessageError('unmarshal %s %r: %s' %
                               (self.name, value, ex)) from ex


class Boolean(Fixed):
    """Class for booleans."""

    def __init__(self):
        super().__init__('BOOLEAN', 'I')

    def marshal(self, raw, data, signature=None):
        if not isinstance(data, bool):
            raise MessageError('marshal %s: %r is not a valid boolean' %
                               (self.name, data))
        super().marshal(raw, data, signature)

    def unmarshal(self, raw, signature=None):
        value = super().unmarshal(raw, signature)
        if value not in (0, 1):
            raise MessageError('unmarshal %s: %r is not a valid boolean' %
                               (self.name, value))
        return bool(value)


class UnixFd(Fixed):
    """Class for unix file descriptors."""

    def __init__(self):
        super().__init__('UNIX_FD', 'I')

    def marshal(self, raw, data, signature=None):
        if isinstance(data, int):
            idx = raw.add_unix_fd(data)
        elif hasattr(data, 'fileno'):
            idx = raw.add_unix_fd(data.fileno())
        else:
            raise MessageError(
                'marshal %s: %r is not a valid file (descriptor)' %
                (self.name, data))
        super().marshal(raw, idx, signature)

    def unmarshal(self, raw, signature=None):
        idx = super().unmarshal(raw, signature)
        if not raw.unix_fds or idx >= len(raw.unix_fds):
            raise MessageError(
                'unmarshal %s: %d is not a valid index for fds' %
                (self.name, idx))
        return raw.unix_fds[idx]


# mapping: dbus type code -> Fixed instance
types = {
    'y': Fixed('BYTE', 'B'),
    'b': Boolean(),
    'n': Fixed('INT16', 'h'),
    'q': Fixed('UINT16', 'H'),
    'i': Fixed('INT32', 'i'),
    'u': Fixed('UINT32', 'I'),
    'x': Fixed('INT64', 'q'),
    't': Fixed('UINT64', 'Q'),
    'd': Fixed('DOUBLE', 'd'),
    'h': UnixFd(),
}


class StringLike(Type):
    """Class for string like types.

    :param str name: type name
    :param str len_type: D-Bus type code for the length field
    :param validate_func: a ``validate_*`` function from the
                          :mod:`validate` module or ``None``
    """

    def __init__(self, name, len_type, validate_func):
        super().__init__(name)
        self.len_type = types[len_type]
        self.alignment = self.len_type.alignment
        self.validate_func = validate_func

    def marshal(self, raw, data, signature=None):
        if self.validate_func:
            self.validate_func(data)
        raw.write_padding(self.alignment)
        pos = raw.tell()
        raw.write_nul_bytes(self.len_type.size)  # placeholder for length
        try:
            # encoding=UTF-8, errors=strict
            d = data.encode()
        except UnicodeError as ex:
            raise MessageError('marshal %s %r: %s' %
                               (self.name, data, ex)) from ex
        raw.write(d)
        raw.write_nul_bytes(1)
        raw.set_value(pos, self.len_type, len(d))  # set length

    def unmarshal(self, raw, signature=None):
        length = self.len_type.unmarshal(raw)
        try:
            # encoding=UTF-8, errors=strict
            value = raw.read(length)
            s = value.decode()
        except UnicodeError as ex:
            raise MessageError('unmarshal %s %r: %s' %
                               (self.name, value, ex)) from ex
        if self.validate_func:
            self.validate_func(s)
        b = raw.read(1)
        if not b or b[0]:
            raise MessageError('no NUL byte after string: %s' % b)
        return s


# mapping: dbus type code -> StringLike instance
types.update({
    's': StringLike('STRING', 'u', None),
    'o': StringLike('OBJECT_PATH', 'u', validate_object_path),
    'g': StringLike('SIGNATURE', 'y', validate_signature),
})


class Container(Type):
    """Base class for container types.

    :param str name: type name
    :param int alignment: the type's alignment
    """

    def __init__(self, name, alignment):
        super().__init__(name)
        self.alignment = alignment

    def __repr__(self):
        signature = [k for k in types if types[k] is self][0]
        return '<Container:%s:%r>' % (self.name, signature)


class Variant(Container):
    """Class for a D-Bus Variant."""

    def __init__(self):
        super().__init__('VARIANT', 1)

    def marshal(self, raw, data, signature=None):
        with raw.nesting_depth():
            if len(data) != 2:
                raise MessageError('variant Python tuple must have 2 elements')
            sig = Signature(data[0])
            if len(sig) != 1:
                raise MessageError(
                    'variant signature must be a single complete type')
            types['g'].marshal(raw, str(sig))
            marshal(raw, (data[1],), sig)

    def unmarshal(self, raw, signature=None):
        with raw.nesting_depth():
            sig = Signature(types['g'].unmarshal(raw))
            if len(sig) != 1:
                raise MessageError(
                    'variant signature must be a single complete type')
            return unmarshal(raw, sig)[0]


class Array(Container):
    """Class for a D-Bus Array."""

    def __init__(self):
        super().__init__('ARRAY', types['u'].alignment)
        self.len_type = types['u']

    def marshal(self, raw, data, signature):
        with raw.nesting_depth():
            type_code = signature[0][0]
            if type_code == 'e' and isinstance(data, dict):
                data = list(data.items())
            elif not isinstance(data, (list, array.array)):
                raise MessageError('wrong Python type for array: %r' %
                                   type(data))
            raw.write_padding(self.alignment)
            pos = raw.tell()
            raw.write_nul_bytes(self.len_type.size)  # placeholder for length
            el_type = types[type_code]
            raw.write_padding(el_type.alignment)
            start_pos = raw.tell()
            for v in data:
                el_type.marshal(raw, v, signature[0][1])
            length = raw.tell() - start_pos
            if length > MAX_ARRAY_LEN:
                raise TooLongError('array too long: %d bytes' % length)
            raw.set_value(pos, self.len_type, length)  # set length

    def unmarshal(self, raw, signature):
        with raw.nesting_depth():
            type_code = signature[0][0]
            raw.skip_padding(self.alignment)
            length = self.len_type.unmarshal(raw)
            if length > MAX_ARRAY_LEN:
                raise TooLongError('array too long: %d bytes' % length)
            el_type = types[type_code]
            raw.skip_padding(el_type.alignment)
            end_pos = raw.tell() + length
            lst = []
            while raw.tell() < end_pos:
                lst.append(el_type.unmarshal(raw, signature[0][1]))
            if type_code == 'e':
                return dict(lst)
            return lst


class Struct(Container):
    """Class for a D-Bus Struct."""

    def __init__(self, name='STRUCT'):
        super().__init__(name, 8)

    def marshal(self, raw, data, signature):
        with raw.nesting_depth():
            if not isinstance(data, tuple):
                raise MessageError('tuple expected not %r' % type(data))
            raw.write_padding(self.alignment)
            marshal(raw, data, signature)

    def unmarshal(self, raw, signature):
        with raw.nesting_depth():
            raw.skip_padding(self.alignment)
            return unmarshal(raw, signature)


class DictEntry(Struct):
    """Class for a D-Bus DictEntry."""

    def __init__(self):
        super().__init__('DICT_ENTRY')


# mapping: dbus type code -> Container instance
types.update({'v': Variant(), 'a': Array()})
# dbus type codes for signatures
type_codes = set(types)
# mapping: dbus type code -> Container instance
# (r and e not used in signatures)
types.update({'r': Struct(), 'e': DictEntry()})


def marshal(raw, data, signature):
    """Marshal objects.

    The elements of the data tuple must be of appropriate types according
    to the column *Python IN* in the :ref:`table above <ref-types-table>`.

    :param RawData raw: raw message data
    :param tuple data: tuple of data to be marshalled
    :param signature: see :class:`~dcar.signature.Signature`
    :raises ~dcar.MessageError: if the data could not be marshalled
    """
    signature = _signature(signature)
    if len(signature) != len(data):
        raise MessageError('length: signature %d, args %d' %
                           (len(signature), len(data)))
    for (sig, d) in zip(signature, data):
        t, s = sig
        types[t].marshal(raw, d, s)


def unmarshal(raw, signature):
    """Unmarshal objects.

    The elements of the returned tuple will be of types according
    to the column *Python OUT* in the :ref:`table above <ref-types-table>`.

    :param RawData raw: raw message data
    :param signature: see :class:`~dcar.signature.Signature`
    :return: tuple of unmarshalled data
    :rtype: tuple
    :raises ~dcar.MessageError: if the data could not be unmarshalled
    """
    signature = _signature(signature)
    data = []
    for t, s in signature:
        data.append(types[t].unmarshal(raw, s))
    return tuple(data)


def _signature(signature):
    if isinstance(signature, str):
        return Signature(signature)
    if signature is None:
        return Signature('')
    return signature
