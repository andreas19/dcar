"""Message routing."""

import inspect
import logging
from contextlib import suppress
from dataclasses import dataclass, field, astuple
from functools import partial
from queue import SimpleQueue
from threading import Condition, Lock

from . import validate
from .const import MAX_MATCH_RULE_LEN, MAX_MATCH_RULE_ARG_NUM
from .errors import (Error, TransportError, RegisterError,
                     TooLongError, DBusError)
from .message import HeaderField, MessageType

__all__ = ['Router', 'MatchRule']

_logger = logging.getLogger(__name__)

MATCH_RULE_VALIDATORS = (
    validate.validate_object_path,
    validate.validate_interface_name,
    validate.validate_member_name,
    validate.validate_bus_name,
    validate.validate_object_path,
    partial(validate.validate_bus_name, unique=True),
    partial(validate.validate_bus_name, strict=False),
)


class Router:
    """Class for routing in- and outgoing messages."""

    def __init__(self, bus):
        self._cv = Condition()
        self._replies = {}
        self.signals = Signals()
        self.methods = Methods()
        self.out_queue = SimpleQueue()
        self._bus = bus

    def _check_replies(self, serial):
        if self._bus.connected:
            return self._replies[serial] is not None
        else:
            if self._bus.error:
                return self._bus.error
            return TransportError('disconnected')

    def outgoing(self, msg, timeout):
        """Handle outgoing messages.

        :param ~dcar.message.Message msg: the message
        :param float timeout: timeout in seconds
        :returns: return values of a message call (if a reply is expected)
                  or ``None``
        :rtype: tuple or None
        :raises ~dcar.TransportError: if the message could not be sent
        :raises ~dcar.MessageError: if the message could not be marshalled
        """
        msg_bytes, unix_fds = msg.to_bytes()
        _logger.debug('\n-> %s', msg)
        if unix_fds and not self._bus.unix_fds_enabled:
            raise TransportError('unix fds passing not supported')
        self.out_queue.put((msg_bytes, unix_fds))
        if msg.reply_expected:
            with self._cv:
                self._replies[msg.serial] = None
                result = self._cv.wait_for(partial(self._check_replies,
                                                   msg.serial),
                                           timeout)
                if result:
                    if isinstance(result, Error):
                        raise result
                    reply = self._replies.pop(msg.serial)
                    reply.raise_on_error()
                    return reply.body
                else:
                    del self._replies[msg.serial]
                    raise TransportError('Timeout: %f secs.' % timeout)
        else:
            return None

    def incoming(self, msg):
        """Handle incoming messages.

        :param ~dcar.message.Message msg: the message
        """
        _logger.debug('\n<- %s', msg)
        if msg is None:  # transport disconnected
            with self._cv:
                self.out_queue.put((None, None))  # unblock send-loop
                self._cv.notify_all()
            return
        if msg.message_type is MessageType.INVALID:
            return  # ignore unknown message types
        if msg.message_type in (MessageType.METHOD_RETURN, MessageType.ERROR):
            with self._cv:
                if msg.reply_serial in self._replies:
                    self._replies[msg.reply_serial] = msg
                    self._cv.notify_all()
        elif msg.message_type is MessageType.METHOD_CALL:
            try:
                method = self._find_method(msg)
                method(self._bus, msg.info)
            except DBusError as ex:
                self._send_error(ex, msg.serial, msg.fields[HeaderField.SENDER])
        elif msg.message_type is MessageType.SIGNAL:
            for handler in self.signals.matches(msg, self._bus.unique_name):
                handler(msg.info)

    def _find_method(self, msg):
        method, signature = self.methods.find(msg)
        if not method:
            raise DBusError('org.freedesktop.DBus.Error.UnknownMethod',
                            'Method %r not found in interface %r '
                            'on object path %r' %
                            (msg.fields[HeaderField.MEMBER],
                             msg.fields[HeaderField.INTERFACE],
                             msg.fields[HeaderField.PATH]))
        if not (not signature and not msg.fields[HeaderField.SIGNATURE] or
                signature == msg.fields[HeaderField.SIGNATURE]):
            raise DBusError('org.freedesktop.DBus.Error.InvalidArgs',
                            'the message signature "%s" is not the '
                            'expected "%s"' %
                            (msg.fields[HeaderField.SIGNATURE] or '',
                             signature or ''))
        return method

    def _send_error(self, ex, serial, sender):
        self._bus.send_error(ex.args[0], serial, sender, signature='s',
                             args=ex.args[1:])


@dataclass(frozen=True)
class MatchRule:
    """Match rule for signals.

    Except for ``unicast`` all parameters are explained in the
    `D-Bus specification
    <https://dbus.freedesktop.org/doc/dbus-specification.html
    #message-bus-routing-match-rules>`_.

    If ``unicast=True`` this rule will only apply to unicast signals
    and no *AddMatch* message will be sent to the message bus from
    the :meth:`~dcar.Bus.register_signal` method.
    """

    object_path: str = None
    interface: str = None
    signal_name: str = None
    sender: str = None
    path_namespace: str = None
    destination: str = None
    arg0namespace: str = None
    unicast: bool = False
    args: dict = field(init=False, default_factory=dict)
    argpaths: dict = field(init=False, default_factory=dict)

    def add_arg(self, idx, arg):
        """Add an arg match at idx."""
        _check_index_and_type(idx, arg)
        self.args[idx] = arg
        self._check_length()

    def add_argpath(self, idx, argpath):
        """Add an argpath match at idx."""
        _check_index_and_type(idx, argpath)
        self.argpaths[idx] = argpath
        self._check_length()

    def __post_init__(self):
        for value, validator in zip(astuple(self), MATCH_RULE_VALIDATORS):
            if value is not None:
                validator(value)
        self._check_length()

    def _check_length(self):
        if len(str(self)) > MAX_MATCH_RULE_LEN:
            raise TooLongError('match rule too long: %d bytes' % len(str(self)))

    def __str__(self):
        lst = ["%s='%s'" % (name, value) for name, value in zip(
            ['type', 'sender', 'interface', 'member', 'path', 'path_namespace',
             'destination', 'arg0namespace'],
            ['signal', self.sender, self.interface, self.signal_name,
             self.object_path, self.path_namespace, self.destination,
             self.arg0namespace]) if value]
        if self.args:
            lst.extend(["arg%d='%s'" % (k, v) for k, v in self.args.items()])
        if self.argpaths:
            lst.extend(["arg%dpath='%s'" % (k, v)
                        for k, v in self.argpaths.items()])
        return ','.join(lst)


def _check_index_and_type(idx, arg):
    if idx < 0 or idx > MAX_MATCH_RULE_ARG_NUM:
        raise IndexError('index %d out of range 0..%d' %
                         (idx, MAX_MATCH_RULE_ARG_NUM))
    if not isinstance(arg, str):
        raise TypeError('arg must be type str, not %s' % arg.__class__.__name__)


class Registry:
    """Base class for registries."""

    def __init__(self):
        self._counter = 0
        self._lock = Lock()
        self._data = {}

    def add(self, item, handler, *args):
        """Add an item.

        :param item: depends on type of registry subclass
        :param callable handler: handler function
        :param args: additional arguments
        """
        self._check_handler(handler)
        with self._lock:
            return self._add(item, handler, *args)

    def _add(self, item, handler, *args):
        raise NotImplementedError

    def remove(self, item_id):
        """Remove an item with ID ``item_id``."""
        with self._lock:
            return self._remove(item_id)

    def _remove(self, item_id):
        raise NotImplementedError

    def _check_handler(self, handler):
        if not callable(handler):
            raise TypeError('handler must be callable')
        sig = inspect.signature(handler)
        if len(sig.parameters) != len(self.__class__.params):
            raise TypeError('handler must have %d parameter(s): %r' %
                            (len(self.__class__.params),
                             ', '.join(self.__class__.params)))


class Signals(Registry):
    """Signals registry.

    An ``item`` for this type's :meth:`~Registry.add` method is a
    :class:`MatchRule` (see also: :meth:`~dcar.Bus.register_signal`).
    """

    params = ('msginfo',)  #: handler parameters

    def _add(self, rule, handler):
        if not isinstance(rule, MatchRule):
            raise TypeError('first argument must be a MatchRule')
        if (rule, handler) in self._data.values():
            raise RegisterError('rule %r exists with same handler %r' %
                                (str(rule), handler))
        self._counter += 1
        self._data[self._counter] = (rule, handler)
        return self._counter

    def _remove(self, rule_id):
        with suppress(KeyError):
            rule, _ = self._data[rule_id]
            del self._data[rule_id]
            return rule

    def matches(self, msg, unique_name):
        """Match a SIGNAL message to a rule.

        This function is a generator which yields the handler function
        for each matching rule.
        """
        fields = msg.fields
        object_path = fields[HeaderField.PATH]
        interface = fields[HeaderField.INTERFACE]
        signal_name = fields[HeaderField.MEMBER]
        sender = fields[HeaderField.SENDER]
        destination = fields[HeaderField.DESTINATION]
        with self._lock:
            for rule, handler in self._data.values():
                if rule.unicast:
                    rule_destination = unique_name
                else:
                    rule_destination = rule.destination
                if all(((rule.object_path is None or
                         rule.object_path == object_path),
                        rule.interface is None or rule.interface == interface,
                        (rule.signal_name is None or
                         rule.signal_name == signal_name),
                        rule.sender is None or rule.sender == sender,
                        (rule_destination is None or
                         rule_destination == destination),
                        (rule.path_namespace is None or
                         rule.path_namespace == object_path or
                         object_path.startswith(rule.path_namespace + '/')),
                        (rule.arg0namespace is None or
                         msg.body and isinstance(msg.body[0], str) and
                         (rule.arg0namespace == msg.body[0] or
                          msg.body[0].startswith(rule.arg0namespace + '.'))),
                        not rule.args or self._match_args(rule.args, msg.body),
                        (not rule.argpaths or
                         self._match_argpaths(rule.argpaths, msg.body)))):
                    yield handler

    def _match_args(self, args, body):
        if not body or len(body) - 1 < max(args):
            return False
        for idx in args:
            if not isinstance(body[idx], str) or args[idx] != body[idx]:
                return False
        return True

    def _match_argpaths(self, argpaths, body):
        if not body or len(body) - 1 < max(argpaths):
            return False
        for idx in argpaths:
            if not isinstance(body[idx], str):
                return False
            if argpaths[idx] == body[idx]:
                continue
            if (argpaths[idx].endswith('/') and
               body[idx].startswith(argpaths[idx]) or
               body[idx].endswith('/') and
               argpaths[idx].startswith(body[idx])):
                    continue
            return False
        return True


class Methods(Registry):
    """Methods registry.

    An ``item`` for this type's :meth:`~Registry.add` method is a
    tuple ``(object_path, interface, method_name)``
    (see also: :meth:`~dcar.Bus.register_method`).
    """

    params = ('bus', 'msginfo')  #: handler parameters

    def _add(self, tup, handler, signature):
        if len(tup) != 3 or not (all(tup) and handler):
            raise RegisterError('invalid arguments: %r, %r' % (tup, handler))
        if tup in self._data:
            raise RegisterError('a handler for method %r in interface %r '
                                'on object %r already exists' % tup)
        self._counter += 1
        self._data[tup] = (self._counter, handler, signature)
        return self._counter

    def _remove(self, meth_id):
        with suppress(KeyError, IndexError):
            tup = list(filter(lambda x: self._data[x][0] == meth_id,
                              self._data))[0]
            del self._data[tup]

    def find(self, msg):
        """Return handler function and signature for a METHOD_CALL message."""
        fields = msg.fields
        object_path = fields[HeaderField.PATH]
        interface = fields[HeaderField.INTERFACE]
        method_name = fields[HeaderField.MEMBER]
        with self._lock:
            if interface:
                if (object_path, interface, method_name) in self._data:
                    return self._data[(object_path, interface, method_name)][1:]
            else:
                for t in self._data:
                    if t[0] == object_path and t[2] == method_name:
                        return self._data[t][1:]
        return None, None
