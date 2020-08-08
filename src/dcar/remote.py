"""Remote module.

.. versionadded:: 0.3.0
"""

from contextlib import suppress

from .bus import Bus
from .router import MatchRule
from .const import DEFAULT_TIMEOUT_VALUE
from .introspection import Data, Method, Property, Signal
from .validate import validate_bus_name, validate_object_path

__all__ = [
    'RemoteObject',
    'DBus',
    'Notifications',
    'PowerManagement',
    'Login1',
    ]


class RemoteObject:
    """An instance of this class is a proxy for an object on the D-Bus.

    Methods, signals, and properties can be accessed as attributes with the
    same names as on the D-Bus. If a name occurs in more than one interface,
    only one  method, signal, or property can be accessed as an attribute.
    To access the shadowed names subscription syntax must be used:
    ``obj['interface name', 'member name']``.

    Calling methods and accessing properties (depending on the `access`
    attribute) is done in the normal way:

      * ``obj.SomeMethod()`` (returns a single value, a tuple or ``None``)
      * ``obj.SomeProperty`` (only with `read` access)
      * ``obj.SomeProperty = value`` (only with `write` access)

    Signal handlers can be set by assigning a function that takes a
    :class:`~dcar.message.MessageInfo` object as its only argument:
    ``obj.SomeSignal = function``. The handler can be removed by assigning
    ``None``.

    See also: :ref:`ref-types-table`

    :param dcar.Bus bus: a connected bus object
    :param str name: bus name
    :param str path: object path
    :param str xml: introspection data (will be loaded from D-Bus if ``None``)
    :raises RuntimeError: if ``bus`` is not a connected :class:`dcar.Bus` object
    :raises ~dcar.ValidationError: if ``name`` or ``path`` are not valid
    """

    def __init__(self, bus, name, path, xml=None):
        if not isinstance(bus, Bus) or not bus.connected:
            raise RuntimeError('bus must be a connected dcar.Bus object')
        self._bus = bus
        self._name = validate_bus_name(name)
        self._path = validate_object_path(path)
        self._data = Data(bus, name, path, xml)
        self._signal_ids = {}
        self._props_cache = {}

    @property
    def xml(self):
        """Return XML data."""
        return self._data.xml

    def __getattr__(self, name):
        with suppress(KeyError):
            if '_data' in self.__dict__:
                return self._get(name)
        raise AttributeError(
            f'{self.__class__.__name__!r} object has no attribute {name!r}')

    def __setattr__(self, name, value):
        with suppress(KeyError):
            if '_data' in self.__dict__:
                self._set(name, value)
                return
        super().__setattr__(name, value)

    def __getitem__(self, key):
        return self._get(key)

    def __setitem__(self, key, value):
        self._set(key, value)

    def _get(self, key):
        member = self._data[key]
        if isinstance(member, Method):
            return self._method(member)
        elif isinstance(member, Property):
            return self._getprop(member)
        elif isinstance(member, Signal):
            raise NotImplementedError('Getting signals is not allowed')

    def _set(self, key, value):
        member = self._data[key]
        if isinstance(member, Method):
            raise NotImplementedError('Setting methods is not allowed')
        elif isinstance(member, Property):
            self._setprop(member, value)
        elif isinstance(member, Signal):
            self._signal(member, value)

    def _method(self, method):
        def m(*args):
            reply = self._bus.method_call(
                self._path,
                method.interface,
                method.name,
                self._name,
                signature=method.in_signature,
                args=args,
                timeout=0.0 if method.no_reply else DEFAULT_TIMEOUT_VALUE)
            if not reply:
                return None
            if len(reply) == 1:
                return reply[0]
            return reply
        return m

    def _getprop(self, prop):
        if prop in self._props_cache:
            return self._props_cache[prop]
        reply = self._bus.method_call(
            self._path,
            'org.freedesktop.DBus.Properties',
            'Get',
            self._name,
            signature='ss',
            args=(prop.interface, prop.name))
        if prop.changed_signal == 'const':
            self._props_cache[prop] = reply[0]
        return reply[0]

    def _setprop(self, prop, value):
        self._bus.method_call(
            self._path,
            'org.freedesktop.DBus.Properties',
            'Set',
            self._name,
            signature='ssv',
            args=(prop.interface, prop.name, (prop.signature, value)))

    def _signal(self, signal, func):
        if func is None:
            if signal in self._signal_ids:
                self._bus.unregister_signal(self._signal_ids[signal])
                del self._signal_ids[signal]
        else:
            self._signal_ids[signal] = self._bus.register_signal(
                MatchRule(self._path, signal.interface, signal.name), func)


class DBus(RemoteObject):
    """Convenience subclass of :class:`RemoteObject`.

    Parameters:
      * name = 'org.freedesktop.DBus'
      * path = '/org/freedesktop/DBus'
    """

    def __init__(self, bus):
        super().__init__(bus,
                         'org.freedesktop.DBus',
                         '/org/freedesktop/DBus')


class Notifications(RemoteObject):
    """Convenience subclass of :class:`RemoteObject`.

    Parameters:
      * name = 'org.freedesktop.Notifications'
      * path = '/org/freedesktop/Notifications'
    """

    def __init__(self, bus):
        super().__init__(bus,
                         'org.freedesktop.Notifications',
                         '/org/freedesktop/Notifications')


class PowerManagement(RemoteObject):
    """Convenience subclass of :class:`RemoteObject`.

    Parameters:
      * name = 'org.freedesktop.PowerManagement'
      * path = '/org/freedesktop/PowerManagement'
    """

    def __init__(self, bus):
        super().__init__(bus,
                         'org.freedesktop.PowerManagement',
                         '/org/freedesktop/PowerManagement')
        self.Inhibit = RemoteObject(bus,
                                    self._name,
                                    f'{self._path}/Inhibit')


class Login1(RemoteObject):
    """Convenience subclass of :class:`RemoteObject`.

    Parameters:
      * name = 'org.freedesktop.login1'
      * path = '/org/freedesktop/login1'
    """

    def __init__(self, bus):
        super().__init__(bus,
                         'org.freedesktop.login1',
                         '/org/freedesktop/login1')
