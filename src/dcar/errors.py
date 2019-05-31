"""
dcar.errors
-----------
"""

__all__ = [
    'Error',
    'AddressError',
    'AuthenticationError',
    'TransportError',
    'ValidationError',
    'RegisterError',
    'MessageError',
    'DBusError',
    'SignatureError',
    'TooLongError',
]


class Error(Exception):
    pass


class AddressError(Error):
    pass


class AuthenticationError(Error):
    pass


class TransportError(Error):
    pass


class ValidationError(Error):
    pass


class RegisterError(Error):
    pass


class MessageError(Error):
    pass


class DBusError(MessageError):
    pass


class SignatureError(MessageError):
    pass


class TooLongError(MessageError):
    pass
