"""Connection to message bus."""

from .address import Address
from .const import DEFAULT_TIMEOUT_VALUE
from .errors import Error, TransportError
from .message import HeaderField, HeaderFields, HeaderFlag, Message, MessageType
from .router import Router
from .transports import check_for_known_transport, connect

__all__ = ['Bus']


class Bus:
    """Representation of a client's connection to a message bus.

    An instance of this class is the central point for a client to interact
    with a message bus. It can be used as a context manager. On entering the
    runtime context the :meth:`connect` method will be called, on exiting the
    :meth:`disconnect` method.

    :param address: same as for :class:`~dcar.address.Address` or an
                    :class:`~dcar.address.Address` object
    :type address: str or Address
    """

    def __init__(self, address='session'):
        self._router = Router(self)
        self._unique_name = None
        if isinstance(address, str):
            address = Address(address)
        check_for_known_transport(address)
        self._addr = address
        self._transport = None
        self._address = None

    @property
    def address(self):
        """Return the actual address the client is connected to."""
        return self._address

    @property
    def connected(self):
        """Return whether the client is connected."""
        return self._transport.connected if self._transport else False

    @property
    def unique_name(self):
        """Return the unique name of the client's connection."""
        return self._unique_name

    @property
    def guid(self):
        """Return the GUID of the server."""
        return self._transport.guid if self._transport else None

    @property
    def unix_fds_enabled(self):
        """Return whether passing of unix file descriptors is enabled."""
        return self._transport.unix_fds_enabled if self._transport else False

    @property
    def error(self):
        """Return transport error or  ``None``.

        This error is set when the client loses the connection to the message
        bus because of this error.
        """
        return self._transport.error if self._transport else None

    def raise_on_error(self):
        """Re-raises the :attr:`error` or does nothing."""
        if self._transport and self._transport.error:
            raise self._transport.error

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    def connect(self):
        """Connect to message bus.

        :raises ~dcar.AuthenticationError: if authentication failed
        :raises OSError: if connection failed
        """
        if self.connected:
            return
        self._transport, self._address = connect(self._addr, self._router)
        self._transport.authenticate()
        self._transport.start_loops()
        reply = self.method_call('/org/freedesktop/DBus',
                                 'org.freedesktop.DBus',
                                 'Hello',
                                 'org.freedesktop.DBus')
        self._unique_name = reply[0]

    def disconnect(self):
        """Disconnect the client."""
        if self.connected:
            self._transport.disconnect()

    def block(self, timeout=None):
        """Blocks until ``send-loop`` and ``recv-loop``\
           are finished or timeout is reached.

        These threads are started with
        :meth:`dcar.transports.Transport.start_loops`.

        :param float timeout: timeout value in seconds
                              (``None`` means no timeout)

        .. versionchanged:: 0.2.0 Add parameter ``timeout``
        """
        if self._transport:
            self._transport.block(timeout)

    def send_message(self, msg, timeout=None):
        """Send a message.

        Normally :meth:`method_call`, :meth:`method_return`, :meth:`send_error`
        or :meth:`emit_signal` should be used.

        :param Message msg: the message
        :param float timeout: ``None`` = no timeout, ``0`` = no reply expected
                              and ``> 0`` = timeout in seconds
        :returns: return values of the message call if a reply is expected
                  else ``None``
        :rtype: tuple or None
        :raises ~dcar.TransportError: if the message could not be sent
        """
        if not self.connected:
            raise TransportError('not connected')
        if timeout == 0.0:
            msg.flags |= HeaderFlag.NO_REPLY_EXPECTED
        return self._router.outgoing(msg, timeout)

    def method_call(self, object_path, interface, method_name, destination,
                    *, sender=None, signature=None, args=(),
                    timeout=DEFAULT_TIMEOUT_VALUE, no_auto_start=False,
                    allow_interactive_authorization=False):
        """Send a message of type METHOD_CALL.

        :param str object_path: object path (required)
        :param str interface: interface name
        :param str method_name: method name (required)
        :param str destination: name of the destination's connection
        :param str sender: name of the sender's connection
        :param str signature: D-Bus type signatures of the IN arguments
        :param tuple args: the IN arguments
        :param float timeout: timeout in seconds
        :param bool no_auto_start: header flag
        :param bool allow_interactive_authorization: header flag
        :returns: return values of the method call if a reply is expected
                  else ``None``
        :rtype: tuple or None
        :raises ~dcar.TransportError: if the message could not be sent
        """
        header_fields = HeaderFields()
        header_fields[HeaderField.PATH] = object_path
        header_fields[HeaderField.INTERFACE] = interface
        header_fields[HeaderField.MEMBER] = method_name
        header_fields[HeaderField.DESTINATION] = destination
        header_fields[HeaderField.SENDER] = sender
        header_fields[HeaderField.SIGNATURE] = signature
        flags = HeaderFlag.NONE
        if no_auto_start:
            flags |= HeaderFlag.NO_AUTO_START
        if allow_interactive_authorization:
            flags |= HeaderFlag.ALLOW_INTERACTIVE_AUTHORIZATION
        msg = Message(MessageType.METHOD_CALL, flags, header_fields, args)
        return self.send_message(msg, timeout)

    def method_return(self, reply_serial, destination, *, sender=None,
                      signature=None, args=()):
        """Send a message of type METHOD_RETURN.

        :param int reply_serial: serial of the message for which this is
                                 a reply (required)
        :param str destination: name of the destination's connection
        :param str sender: name of the sender's connection
        :param str signature: D-Bus type signatures of the OUT arguments of
                              the called method
        :param tuple args: the OUT arguments of the called method
        :raises ~dcar.TransportError: if the message could not be sent
        """
        header_fields = HeaderFields()
        header_fields[HeaderField.REPLY_SERIAL] = reply_serial
        header_fields[HeaderField.DESTINATION] = destination
        header_fields[HeaderField.SENDER] = sender
        header_fields[HeaderField.SIGNATURE] = signature
        msg = Message(MessageType.METHOD_RETURN, HeaderFlag.NONE,
                      header_fields, args)
        return self.send_message(msg)

    def send_error(self, error_name, reply_serial, destination, *, sender=None,
                   signature=None, args=()):
        """Send a message of type ERROR.

        :param str error_name: error name (required)
        :param int reply_serial: serial of the message for which this is
                                 a reply (required)
        :param str destination: name of the destination's connection
        :param str sender: name of the sender's connection
        :param str signature: D-Bus type signatures of the arguments
        :param tuple args: the arguments
        :raises ~dcar.TransportError: if the message could not be sent
        """
        header_fields = HeaderFields()
        header_fields[HeaderField.ERROR_NAME] = error_name
        header_fields[HeaderField.REPLY_SERIAL] = reply_serial
        header_fields[HeaderField.DESTINATION] = destination
        header_fields[HeaderField.SENDER] = sender
        header_fields[HeaderField.SIGNATURE] = signature
        msg = Message(MessageType.ERROR, HeaderFlag.NONE, header_fields, args)
        return self.send_message(msg)

    def emit_signal(self, object_path, interface, signal_name,
                    destination=None, *, sender=None, signature=None, args=()):
        """Send a message of type SIGNAL.

        :param str object_path: object path (required)
        :param str interface: interface name (required)
        :param str signal_name: signal name (required)
        :param str destination: name of the destination's connection
        :param str sender: name of the sender's connection
        :param str signature: D-Bus type signatures of the arguments
        :param tuple args: the arguments
        :raises ~dcar.TransportError: if the message could not be sent
        """
        header_fields = HeaderFields()
        header_fields[HeaderField.PATH] = object_path
        header_fields[HeaderField.INTERFACE] = interface
        header_fields[HeaderField.MEMBER] = signal_name
        header_fields[HeaderField.DESTINATION] = destination
        header_fields[HeaderField.SENDER] = sender
        header_fields[HeaderField.SIGNATURE] = signature
        msg = Message(MessageType.SIGNAL, HeaderFlag.NONE, header_fields, args)
        return self.send_message(msg)

    def register_signal(self, rule, handler, unicast=False,
                        timeout=DEFAULT_TIMEOUT_VALUE):
        """Register a signal.

        The handler function must take one parameter:
        a :class:`~dcar.message.MessageInfo` object.

        .. note::

           The handler functions for incoming method calls and signals will be
           executed in a separate thread sequentially.

        :param ~dcar.MatchRule rule: the match rule
        :param callable handler: handler function for the signal
        :param bool unicast: if ``True`` this rule applies to a unicast
                             signal and no *AddMatch* message will
                             be sent to the message bus
        :param float timeout: timeout in seconds
        :return: ID of the signal
        :rtype: int
        :raises ~dcar.RegisterError: if the signal could not be registered
        :raises ~dcar.TransportError: if the *AddMatch* message could
                                      not be sent
        """
        reg_id = self._router.signals.add(rule, handler, unicast)
        if not unicast:
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

    def unregister_signal(self, reg_id, timeout=DEFAULT_TIMEOUT_VALUE):
        """Unregister a signal.

        :param int reg_id: ID returned by :meth:`register_signal`
        :param float timeout: timeout in seconds
        :raises ~dcar.TransportError: if RemoveMatch message could not be sent
        """
        rule = self._router.signals.remove(reg_id)
        if rule:
            self.method_call('/org/freedesktop/DBus',
                             'org.freedesktop.DBus',
                             'RemoveMatch',
                             'org.freedesktop.DBus',
                             signature='s', args=(str(rule),),
                             timeout=timeout)

    def register_method(self, object_path, interface, method_name,
                        handler, signature=None):
        """Register a method.

        The handler function must take two parameters:
        a :class:`Bus` object and
        a :class:`~dcar.message.MessageInfo` object.

        .. note::

           The handler functions for incoming method calls and signals will be
           executed in a separate thread sequentially.

        :param str object_path: object path
        :param str interface: interface name
        :param str method_name: method name
        :param str signature: D-Bus type signatures of the arguments
        :return: ID of the method
        :rtype: int
        :raises ~dcar.RegisterError: if the method could not be registered
        """
        return self._router.methods.add((object_path, interface,
                                         method_name), handler, signature)

    def unregister_method(self, meth_id):
        """Unregister a method.

        :param int meth_id: ID returned by :meth:`register_method`
        """
        self._router.methods.remove(meth_id)
