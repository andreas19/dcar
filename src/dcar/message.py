"""D-Bus Message.

See: `Message Protocol
<https://dbus.freedesktop.org/doc/dbus-specification.html#message-protocol>`_
"""

import sys
from collections import namedtuple
from contextlib import suppress
from enum import Enum, IntFlag
from threading import Lock

from .const import MAJOR_PROTOCOL_VERSION, MIN_HEADER_SIZE
from .errors import MessageError, DBusError
from .raw import RawData
from .marshal import types, marshal, unmarshal
from .validate import (validate_object_path, validate_interface_name,
                       validate_member_name, validate_error_name,
                       validate_serial, validate_bus_name,
                       validate_signature, validate_unixfds_field)

HEADER_ALIGNMENT = 8

__all__ = [
    'Byteorder',
    'MessageType',
    'HeaderFlag',
    'HeaderField',
    'HeaderFields',
    'Message',
    'MessageInfo',
]


class EnumReprMixin:
    """Mixin class."""

    def __repr__(self):
        return '<%s.%s>' % (self.__class__.__name__, self.name)


class Byteorder(EnumReprMixin, Enum):
    """Enumeration of byteorders."""

    LITTLE = (b'l', '<')
    BIG = (b'B', '>')
    NATIVE = LITTLE if sys.byteorder == 'little' else BIG

    def __new__(cls, dbus_code, struct_code):
        """Create new instance."""
        obj = object.__new__(cls)
        obj._value_ = dbus_code
        obj.code = struct_code
        return obj


class MessageType(EnumReprMixin, Enum):
    """Enumeration of message types."""

    INVALID = b'\x00'
    METHOD_CALL = b'\x01'
    METHOD_RETURN = b'\x02'
    ERROR = b'\x03'
    SIGNAL = b'\x04'


class HeaderFlag(IntFlag):
    """Enumeration of header flags."""

    NONE = 0
    NO_REPLY_EXPECTED = 1
    NO_AUTO_START = 2
    ALLOW_INTERACTIVE_AUTHORIZATION = 4

    @classmethod
    def from_byte(cls, byte):
        """Convert ``byte`` to a header flag."""
        return cls(int.from_bytes(byte, 'little', signed=False))

    def to_byte(self):
        """Convert header flag to a byte."""
        return self.value.to_bytes(1, 'little', signed=False)


class HeaderField(EnumReprMixin, Enum):
    """Enumeration of header fields."""

    PATH = (1, 'o', validate_object_path)
    INTERFACE = (2, 's', validate_interface_name)
    MEMBER = (3, 's', validate_member_name)
    ERROR_NAME = (4, 's', validate_error_name)
    REPLY_SERIAL = (5, 'u', validate_serial)
    DESTINATION = (6, 's', validate_bus_name)
    SENDER = (7, 's', validate_bus_name)
    SIGNATURE = (8, 'g', validate_signature)
    UNIX_FDS = (9, 'u', validate_unixfds_field)

    def __new__(cls, field_code, type_code, validate_func):
        """Create new instance."""
        obj = object.__new__(cls)
        obj._value_ = field_code
        obj.type_code = type_code
        obj.validate_func = validate_func
        return obj


#: mapping from message types to required header fields
required_header_fields = {
    MessageType.INVALID: (),
    MessageType.METHOD_CALL: (HeaderField.PATH, HeaderField.MEMBER),
    MessageType.METHOD_RETURN: (HeaderField.REPLY_SERIAL,),
    MessageType.ERROR: (HeaderField.ERROR_NAME, HeaderField.REPLY_SERIAL),
    MessageType.SIGNAL: (HeaderField.PATH, HeaderField.INTERFACE,
                         HeaderField.MEMBER),
}


class HeaderFields:
    """Fields in a message header."""

    signature = 'a(yv)'

    def __init__(self):
        self._fields = {}

    def __setitem__(self, key, value):
        if key in HeaderField:
            self._fields[key] = value
        else:
            raise TypeError('key must be a HeaderField not %r' %
                            key.__class__.__name__)

    def __getitem__(self, key):
        if key in HeaderField:
            return self._fields.get(key)
        raise KeyError(key)

    def __iter__(self):
        return ((e, self._fields[e]) for e in HeaderField
                if e in self._fields and self._fields[e] is not None)

    def to_list(self):
        """Convert the internal dict representation to a list."""
        return [(e.value, (e.type_code, v)) for e, v in self]

    @classmethod
    def from_list(cls, lst):
        """Convert a list to the internal dict representation."""
        obj = cls()
        for key, value in lst:
            with suppress(ValueError):
                obj._fields[HeaderField(key)] = value
        return obj

    def __repr__(self):
        return '<%s: %s>' % (self.__class__.__name__,
                             ', '.join('%s=%r' % (e.name, v) for e, v in self))

    def check(self, message_type):
        """Check if required header fields are present and validate them.

        :param MessageType message_type: the message type
        :raises ~dcar.ValidationError: if validation failed
        :raises ~dcar.MessageError: if required fields are missing
        """
        required = list(required_header_fields[message_type])
        for field, value in self._fields.items():
            if value is not None:
                field.validate_func(value)
                if field in required:
                    required.remove(field)
        if required:
            raise MessageError('required header field(s) missing for %s: %s' %
                               (message_type.name,
                                ', '.join(f.name for f in required)))


def _validate_type(obj, type_, name):
    if not isinstance(obj, type_):
        raise TypeError('%r must be of type %r not %r' %
                        (name, type_.__name__, obj.__class__.__name__))
    return obj


MessageInfo = namedtuple('MessageInfo',
                         ['serial', 'args', 'path', 'interface', 'member',
                          'sender', 'no_reply_expected',
                          'allow_interactive_authorization', 'is_signal'])
MessageInfo.__doc__ += ('\nObjects of this type will be passed to handler'
                        ' functions registered with'
                        ' :meth:`~dcar.Bus.register_signal` and'
                        ' :meth:`~dcar.Bus.register_method`.')
MessageInfo.serial.__doc__ = 'message serial'
MessageInfo.args.__doc__ = 'arguments as a tuple'
MessageInfo.path.__doc__ = 'object path'
MessageInfo.interface.__doc__ = 'interface name'
MessageInfo.member.__doc__ = 'member (signal or method) name'
MessageInfo.sender.__doc__ = "name of the sender's connection"
MessageInfo.no_reply_expected.__doc__ = 'header flag'
MessageInfo.allow_interactive_authorization.__doc__ = 'header flag'
MessageInfo.is_signal.__doc__ = '``True`` if signal'


class Message:
    """A D-Bus message.

    Objects of this type must be treated as immutable.

    :param MessageType message_type: type of this message
    :param flags: or'ed :class:`HeaderFlags <HeaderFlag>`, ``0``, or ``None``
    :param HeaderFields fields: header fields
    :param tuple body: the data for the body of this message
    :raises ~dcar.ValidationError: if any validation fails
    :raises TypeError: if there is any argument of the wrong type
    """

    _next_serial = 1
    _lock = Lock()

    def __init__(self, message_type, flags, fields, body):
        self.byteorder = Byteorder.NATIVE
        self.message_type = _validate_type(message_type, MessageType,
                                           'message_type')
        if self.message_type == MessageType.INVALID:
            raise ValueError('message type %r not allowed' %
                             MessageType.INVALID.name)
        if not flags:
            self.flags = HeaderFlag.NONE
        else:
            self.flags = _validate_type(flags, HeaderFlag, 'flags')
        self.protocol = MAJOR_PROTOCOL_VERSION
        self.length = -1
        self.fields = _validate_type(fields, HeaderFields, 'fields')
        self.fields.check(self.message_type)
        self.body = _validate_type(body, tuple, 'body')
        with Message._lock:
            self.serial = Message._next_serial
            Message._next_serial += 1
        self.unix_fds_cnt = -1
        self._info = None

    @property
    def info(self):
        """Return a :class:`MessageInfo` object.

        Only available for messages of type METHOD_CALL and SIGNAL.
        """
        return self._info

    @property
    def reply_expected(self):
        """Return ``True`` if a reply is expected."""
        return (self.message_type is MessageType.METHOD_CALL and
                not (self.flags & HeaderFlag.NO_REPLY_EXPECTED))

    @property
    def reply_serial(self):
        """Return the reply serial from the header fields."""
        return self.fields[HeaderField.REPLY_SERIAL]

    @property
    def sender(self):
        """Return the sender from the header fields."""
        return self.fields[HeaderField.SENDER]

    def raise_on_error(self):
        """Raise a :class:`~dcar.DBusError` if this is an ERROR message."""
        if self.message_type is MessageType.ERROR:
            raise DBusError(self.fields[HeaderField.ERROR_NAME], *self.body)

    @classmethod
    def from_bytes(cls, raw):
        """Create a new message object from bytes.

        :param RawData raw: raw message data
        :raises ~dcar.MessageError: if the message could not be created
        """
        raw.seek(0)
        byteorder = Byteorder(raw.read(1))
        raw.byteorder = byteorder
        try:
            message_type = MessageType(raw.read(1))
        except ValueError:
            message_type = MessageType.INVALID
        flags = HeaderFlag.from_byte(raw.read(1))
        protocol = raw.read(1)
        if protocol != MAJOR_PROTOCOL_VERSION:
            raise MessageError('protocol version error: found %r - allowed %r' %
                               (protocol, MAJOR_PROTOCOL_VERSION))
        length = types['u'].unmarshal(raw)
        serial = types['u'].unmarshal(raw)
        if serial == 0:
            raise MessageError('serial == 0 not allowed')
        fields = HeaderFields.from_list(unmarshal(raw,
                                                  HeaderFields.signature)[0])
        fields.check(message_type)
        raw.skip_padding(HEADER_ALIGNMENT)
        body = unmarshal(raw, fields[HeaderField.SIGNATURE])
        b = raw.read()
        if b:
            raise MessageError('too much data: %r' % b)
        obj = super().__new__(cls)
        obj.byteorder = byteorder
        obj.message_type = message_type
        obj.flags = flags
        obj.protocol = protocol
        obj.length = length
        obj.serial = serial
        obj.fields = fields
        obj.body = body
        obj.unix_fds_cnt = len(raw.unix_fds)
        if message_type in (MessageType.METHOD_CALL, MessageType.SIGNAL):
            obj._info = MessageInfo(
                 serial, body, fields[HeaderField.PATH],
                 fields[HeaderField.INTERFACE], fields[HeaderField.MEMBER],
                 fields[HeaderField.SENDER],
                 bool(flags & HeaderFlag.NO_REPLY_EXPECTED),
                 bool(flags & HeaderFlag.ALLOW_INTERACTIVE_AUTHORIZATION),
                 message_type is MessageType.SIGNAL)
        return obj

    def to_bytes(self):
        """Convert this message to bytes.

        :raises ~dcar.MessageError: if the message could not be converted
        """
        signature = self.fields[HeaderField.SIGNATURE]
        if signature and not self.body or not signature and self.body:
            raise MessageError('signature and no body or no signature and body')
        rawhead = RawData()
        rawhead.byteorder = self.byteorder
        rawhead.write(self.byteorder.value)
        rawhead.write(self.message_type.value)
        rawhead.write(self.flags.to_byte())
        rawhead.write(self.protocol)
        rawbody = RawData()
        rawbody.byteorder = self.byteorder
        marshal(rawbody, self.body, signature)
        self.length = len(rawbody.getvalue())
        types['u'].marshal(rawhead, self.length)
        types['u'].marshal(rawhead, self.serial)
        self.unix_fds_cnt = len(rawbody.unix_fds)
        if rawbody.unix_fds:
            self.fields[HeaderField.UNIX_FDS] = self.unix_fds_cnt
        marshal(rawhead, (self.fields.to_list(),), HeaderFields.signature)
        rawhead.write_padding(HEADER_ALIGNMENT)
        return rawhead.getvalue() + rawbody.getvalue(), rawbody.unix_fds

    def __repr__(self):
        args = self.__dict__.copy()
        args['class_name'] = self.__class__.__name__
        return ('<%(class_name)s: %(byteorder)r, %(message_type)r, %(flags)r, '
                '%(protocol)r, length=%(length)r, serial=%(serial)r, '
                '%(fields)r, %(body)r, %(unix_fds_cnt)s>') % args


def get_sizes(raw):
    """Get sizes from raw message data."""
    raw.byteorder = Byteorder(raw.read(1))
    raw.read(3)  # skip bytes
    body_size = types['u'].unmarshal(raw)
    raw.read(4)  # skip bytes
    fields_size = types['u'].unmarshal(raw)
    x = (MIN_HEADER_SIZE + fields_size) % HEADER_ALIGNMENT
    pad = HEADER_ALIGNMENT - x if x else 0
    return MIN_HEADER_SIZE + fields_size + pad + body_size, fields_size


def get_unix_fds_cnt(raw):
    """Get number of unix file descriptors from raw message data."""
    raw.byteorder = Byteorder(raw.read(1))
    raw.read(11)  # skip bytes
    fields = HeaderFields.from_list(unmarshal(raw,
                                              HeaderFields.signature)[0])
    return fields[HeaderField.UNIX_FDS] or 0
