"""Errors module."""

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
    """Base class."""


class AddressError(Error):
    """Raised for errors in server addresses."""


class AuthenticationError(Error):
    """Raised when authentication failed."""


class TransportError(Error):
    """Raised for transport related errors."""


class ValidationError(Error):
    """Raised when validation failed."""


class RegisterError(Error):
    """Raised when a signal or method could not be registered."""


class MessageError(Error):
    """Raised for errors in messages."""


class DBusError(MessageError):
    """Raised for errors from ERROR messages."""


class SignatureError(MessageError):
    """Raised for errors in signatures."""


class TooLongError(MessageError):
    """Raised when a message, an array, a name etc. is too long."""
