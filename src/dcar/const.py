"""Some constants from dbus source files."""

MAJOR_PROTOCOL_VERSION = b'\x01'  #: Major protocol version

MIN_HEADER_SIZE = 16  #: Minimum header size

MAX_MESSAGE_LEN = 2 ** 27  #: Maximum message length

MAX_ARRAY_LEN = 2 ** 26  #: Maximum array length

MAX_NAME_LEN = 255  #: Maximum name length

MAX_SIGNATURE_LEN = 255  #: Maximum signature length

MAX_MATCH_RULE_LEN = 1024  #: Maximum match rule length

MAX_MATCH_RULE_ARG_NUM = 63  #: Maximum number of match rule arguments

MAX_NESTING_DEPTH = 32  #: Maximum nesting depth of arrays and structs

MAX_VARIANT_NESTING_DEPTH = 64  #: Maximum nesting depth of variants

MAX_MSG_UNIX_FDS = 2 ** 25  #: Maximum number of unix file descriptors

LOCAL_PATH = '/org/freedesktop/DBus/Local'  #: Reserved local path

LOCAL_INTERFACE = 'org.freedesktop.DBus.Local'  #: Reserved local interface

DEFAULT_TIMEOUT_VALUE = 25.0  #: Default timeout when waiting for a reply
