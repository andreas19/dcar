"""
dcar.bus
--------
"""

from .address import Address
from .errors import Error, TransportError
from .message import HeaderField, HeaderFields, HeaderFlag, Message, MessageType
from .router import Router
from .transports import UnixTransport, TcpTransport, NonceTcpTransport

__all__ = ['Bus']

_transports = {
    'unix': UnixTransport,
    'tcp': TcpTransport,
    'nonce-tcp': NonceTcpTransport,
}


class Bus:
    def __init__(self, address='session'):
        self._router = Router(self)
        self._unique_name = None
        self._has_been_disconnected = False
        if isinstance(address, str):
            address = Address(address)
        self._address = address
        for name, params in address:
            transport_class = _transports.get(name)
            if transport_class:
                self._transport = transport_class(params, self._router)
                break
        else:
            raise TransportError('no transport found')

    @property
    def address(self):
        return self._address

    @property
    def connected(self):
        return self._transport.connected

    @property
    def unique_name(self):
        return self._unique_name

    @property
    def guid(self):
        return self._transport.guid

    @property
    def unix_fds_enabled(self):
        return self._transport.unix_fds_enabled

    @property
    def error(self):
        return self._transport.error

    def raise_on_error(self):
        if self._transport.error:
            raise self._transport.error

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    def connect(self):
        if self.connected:
            return
        if self._has_been_disconnected or self.error:
            raise Error('bus cannot be re-connected')
        self._transport.connect()
        self._transport.authenticate()
        self._transport.start_loops()
        reply = self.method_call('/org/freedesktop/DBus',
                                 'org.freedesktop.DBus',
                                 'Hello',
                                 'org.freedesktop.DBus')
        self._unique_name = reply[0]

    def disconnect(self):
        if self.connected:
            self._has_been_disconnected = True
            self._transport.disconnect()

    def block(self):
        self._transport.block()

    # timeout: None no timeout, 0 no reply, > 0 timeout in secs
    def send_message(self, msg, timeout=None):
        if not self.connected:
            raise TransportError('not connected')
        if timeout == 0.0:
            msg.flags |= HeaderFlag.NO_REPLY_EXPECTED
        return self._router.outgoing(msg, timeout)

    def method_call(self, object_path, interface, method_name, destination,
                    sender=None, signature=None, args=(),
                    flags=HeaderFlag.NONE, timeout=None):
        header_fields = HeaderFields()
        header_fields[HeaderField.PATH] = object_path
        header_fields[HeaderField.INTERFACE] = interface
        header_fields[HeaderField.MEMBER] = method_name
        header_fields[HeaderField.DESTINATION] = destination
        header_fields[HeaderField.SENDER] = sender
        header_fields[HeaderField.SIGNATURE] = signature
        msg = Message(MessageType.METHOD_CALL, flags, header_fields, args)
        return self.send_message(msg, timeout)

    def method_return(self, reply_serial, destination, sender=None,
                      signature=None, args=(), flags=HeaderFlag.NONE):
        header_fields = HeaderFields()
        header_fields[HeaderField.REPLY_SERIAL] = reply_serial
        header_fields[HeaderField.DESTINATION] = destination
        header_fields[HeaderField.SENDER] = sender
        header_fields[HeaderField.SIGNATURE] = signature
        msg = Message(MessageType.METHOD_RETURN, flags, header_fields, args)
        return self.send_message(msg)

    def send_error(self, error_name, reply_serial, destination, sender=None,
                   signature=None, args=(), flags=HeaderFlag.NONE):
        header_fields = HeaderFields()
        header_fields[HeaderField.ERROR_NAME] = error_name
        header_fields[HeaderField.REPLY_SERIAL] = reply_serial
        header_fields[HeaderField.DESTINATION] = destination
        header_fields[HeaderField.SENDER] = sender
        header_fields[HeaderField.SIGNATURE] = signature
        msg = Message(MessageType.ERROR, flags, header_fields, args)
        return self.send_message(msg)

    def emit_signal(self, object_path, interface, signal_name,
                    destination=None, sender=None, signature=None,
                    args=(), flags=HeaderFlag.NONE):
        header_fields = HeaderFields()
        header_fields[HeaderField.PATH] = object_path
        header_fields[HeaderField.INTERFACE] = interface
        header_fields[HeaderField.MEMBER] = signal_name
        header_fields[HeaderField.DESTINATION] = destination
        header_fields[HeaderField.SENDER] = sender
        header_fields[HeaderField.SIGNATURE] = signature
        msg = Message(MessageType.SIGNAL, flags, header_fields, args)
        return self.send_message(msg)

    def register_signal(self, rule, handler, timeout=None):
        reg_id = self._router.signals.add(rule, handler)
        if not rule.unicast:
            try:
                self.method_call('/org/freedesktop/DBus',
                                 'org.freedesktop.DBus',
                                 'AddMatch',
                                 'org.freedesktop.DBus',
                                 signature='s', args=(str(rule),),
                                 timeout=timeout)
            except Error:
                self._router.signals.remove(reg_id)
                raise
        return reg_id

    def unregister_signal(self, reg_id, timeout=None):
        rule, handler = self._router.signals.remove(reg_id)
        if rule:
            self.method_call('/org/freedesktop/DBus',
                             'org.freedesktop.DBus',
                             'RemoveMatch',
                             'org.freedesktop.DBus',
                             signature='s', args=(str(rule),),
                             timeout=timeout)
        return handler, rule

    def register_method(self, object_path, interface, method_name,
                        handler, signature=None):
        return self._router.methods.add((object_path, interface,
                                         method_name), handler, signature)

    def unregister_method(self, meth_id):
        return self._router.methods.remove(meth_id)
