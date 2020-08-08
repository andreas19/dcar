"""Introspection module.

.. versionadded:: 0.3.0
"""

import xml.etree.ElementTree as ET
from collections import namedtuple, defaultdict

__all__ = [
    'Data',
    'Method',
    'Property',
    'Signal',
    ]

Method = namedtuple('Method',
                    'name interface in_signature out_signature no_reply')
Method.__doc__ = 'Representation of an interface member of type `method`.'
Signal = namedtuple('Signal', 'name interface signature')
Signal.__doc__ = 'Representation of an interface member of type `signal`.'
Property = namedtuple('Property',
                      'name interface signature read write changed_signal')
Property.__doc__ = 'Representation of an interface member of type `property`.'


class Data:
    """Introspection data.

    If not provided, an instance of this class gets the XML data by calling
    `org.freedesktop.DBus.Introspectable.Introspect`.

    The XML data is parsed and a data structure is created with a mapping from
    the names of members of the interfaces to a list of objects of type
    :class:`Method`, :class:`Signal`, or :class:`Property`.

    Access to objects:
      * ``data['member name']``
      * ``data['interface name', 'member name']``

    :param dcar.Bus bus: a connected bus object
    :param str name: bus name
    :param str path: object path
    :param str xml: introspection data (will be loaded from D-Bus if ``None``)
    :raises RuntimeError: if ``bus`` is not a connected :class:`dcar.Bus` object
    :raises ~dcar.ValidationError: if ``name`` or ``path`` are not valid
    """

    def __init__(self, bus, name, path, xml):
        self._bus = bus
        self._name = name
        self._path = path
        if xml:
            self._xml = xml
        else:
            self._xml = self._introspect()
        self._data = _interfaces(ET.fromstring(self._xml))

    def _introspect(self):
        reply = self._bus.method_call(self._path,
                                      'org.freedesktop.DBus.Introspectable',
                                      'Introspect',
                                      self._name)
        return reply[0]

    @property
    def xml(self):
        """Return XML data."""
        return self._xml

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._data[key][-1]
        if len(key) == 2:
            interface, member = key
            for x in self._data[member]:
                if x.interface == interface:
                    return x
        raise KeyError(key)


def _interfaces(root):
    data = defaultdict(list)
    for iface in (elem for elem in _sort(root) if elem.tag == 'interface'):
        elem = iface.find('annotation[@name="org.freedesktop.DBus.Property'
                          '.EmitsChangedSignal"]')
        changed_signal = 'true' if elem is None else elem.get('value')
        for elem in iface:
            if elem.tag == 'method':
                member = _method(elem, iface.get('name'))
            elif elem.tag == 'signal':
                member = _signal(elem, iface.get('name'))
            elif elem.tag == 'property':
                member = _property(elem, iface.get('name'), changed_signal)
            else:
                member = None
            if member:
                data[member.name].append(member)
    data.default_factory = None
    return data


def _method(root, interface):
    in_signature = out_signature = ''
    no_reply = False
    for elem in root:
        if elem.tag == 'arg':
            direction = elem.get('direction', 'in')
            if direction == 'in':
                in_signature += elem.get('type')
            elif direction == 'out':
                out_signature += elem.get('type')
        elif (elem.tag == 'annotation' and
              elem.get('name') == 'org.freedesktop.DBus.Method.NoReply'):
            no_reply = elem.get('value') == 'true'
    return Method(root.get('name'), interface, in_signature,
                  out_signature, no_reply)


def _signal(root, interface):
    signature = ''
    for elem in root:
        if elem.tag == 'arg' and elem.get('direction', 'out') == 'out':
            signature += elem.get('type')
    return Signal(root.get('name'), interface, signature)


def _property(root, interface, changed_signal):
    signature = root.get('type')
    access = root.get('access')
    elem = root.find('annotation[@name="org.freedesktop.DBus.Property'
                     '.EmitsChangedSignal"]')
    return Property(root.get('name'), interface, signature,
                    'read' in access, 'write' in access,
                    changed_signal if elem is None else elem.get('value'))


def _sort(root):
    def f(x):
        if x.tag == 'interface':
            if x.get('name').startswith('org.freedesktop.DBus.'):
                return (0,)
            else:
                return (1, x.get('name'))
        return (2,)
    return sorted(root, key=f)
