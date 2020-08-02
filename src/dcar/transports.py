"""Transports for message bus connections."""

import array
import logging
import socket
import threading
import time
from contextlib import suppress

from .auth import authenticate
from .const import MAX_MESSAGE_LEN, MIN_HEADER_SIZE
from .errors import TransportError, TooLongError
from .message import get_sizes, get_unix_fds_cnt, Message
from .raw import RawData

__all__ = [
    'Transport',
    'UnixTransport',
    'TcpTransport',
    'NonceTcpTransport',
]

_logger = logging.getLogger(__name__)


def check_for_known_transport(addr):
    """Check whether there is a known transport for any address.

    :param ~dcar.address.Address addr: addresses
    :raises TransportError: if no transport was found
    """
    for name, _ in addr:
        if name in _transports:
            return
    raise TransportError('no transport found')


def connect(addr, router):
    """Connect to message bus.

    Tries every address until connection is successful
    or there are no more addresses.

    :param ~dcar.address.Address addr: addresses
    :raises TransportError: if connection failed
    """
    for name, params in addr:
        transport_class = _transports.get(name)
        if transport_class:
            transport = transport_class(params, router)
            try:
                transport.connect()
                return (transport,
                        '%s:%s' % (name,
                                   ','.join('%s=%s' % (k, v)
                                            for k, v in params.items())))
            except Exception:
                _logger.debug('connect failed: %s, %s',
                              name, params, exc_info=True)
    else:
        raise TransportError('connection failed')


class Transport:
    """Base class.

    :param dict params: address parameters
    :param ~dcar.router.Router router: router object
    """

    def __init__(self, params, router):
        self.guid = params.get('guid')
        self.unix_fds_enabled = False
        self.connected = False
        self._router = router
        self._error = None
        self._lock = threading.Lock()

    @property
    def error(self):
        """Return the error which caused disconnection or ``None``."""
        if self._error:
            if isinstance(self._error, TransportError):
                ex = TransportError('connection lost')
                ex.__traceback__ = self._error.__traceback__
            else:
                ex = TransportError('connection lost: %s' % self._error)
                ex.__cause__ = self._error
            return ex

    def _set_error(self, exc):
        if not self._error and self.connected:
            self._error = exc

    def connect(self):
        """Connect to message bus."""
        with self._lock:
            if self.connected:
                return
            self._sock = socket.socket(self._addr_family)
            self._sock.connect(self._address)
            self.connected = True

    def disconnect(self):
        """Disconnect from message bus."""
        with self._lock:
            if not self.connected:
                return
            self.connected = False
            with suppress(OSError):
                self._sock.shutdown(socket.SHUT_RDWR)
            self._sock.close()
            self._router.incoming(None)

    def authenticate(self):
        """Authenticate to message bus."""
        self.guid, self.unix_fds_enabled = authenticate(self._sock,
                                                        self.unix_fds_enabled)

    def start_loops(self):
        """Start threads with ``recv-loop`` and ``send-loop``."""
        self._recv_loop = threading.Thread(target=self._recv_loop,
                                           name='recv-loop', daemon=True)
        self._recv_loop.start()
        self._send_loop = threading.Thread(target=self._send_loop,
                                           name='send-loop', daemon=True)
        self._send_loop.start()

    def block(self, timeout=None):
        """Block until loop threads are finished.

        :param float timeout: timeout value in seconds
                              (``None`` means no timeout)

        .. versionchanged:: 0.2.0 Add parameter ``timeout``
        """
        if timeout is None:
            self._recv_loop.join()
            self._send_loop.join()
        else:
            t = time.time()
            self._recv_loop.join(timeout)
            r = timeout - (time.time() - t)
            if r > 0:
                self._send_loop.join(r)

    def _send_loop(self):
        while self.connected:
            b, fds = self._router.out_queue.get()
            if not b:
                break
            try:
                if self.unix_fds_enabled and fds:
                    self._sock.sendmsg([b], [(socket.SOL_SOCKET,
                                              socket.SCM_RIGHTS,
                                              array.array('i', fds))])
                else:
                    self._sock.sendall(b)
            except Exception as ex:
                _logger.debug('send loop', exc_info=True)
                self._set_error(ex)
                self.disconnect()
                break
        _logger.debug('EXIT send loop')

    def _recv_loop(self):
        try:
            while self.connected:
                b = self._sock.recv(MIN_HEADER_SIZE, socket.MSG_PEEK)
                if not b:
                    raise TransportError()
                total_size, fields_size = get_sizes(RawData(b))
                if total_size > MAX_MESSAGE_LEN:
                    raise TooLongError('message too long: %d bytes' %
                                       total_size)
                raw = RawData(bytearray(total_size))
                view = raw.getbuffer()
                if self.unix_fds_enabled:
                    b = self._sock.recv(MIN_HEADER_SIZE + fields_size,
                                        socket.MSG_PEEK)
                    unix_fds_cnt = get_unix_fds_cnt(RawData(b))
                else:
                    unix_fds_cnt = 0
                if unix_fds_cnt:
                    fds = array.array('i')
                    cnt, anc, _, _ = self._sock.recvmsg_into(
                        [view], socket.CMSG_SPACE(unix_fds_cnt * fds.itemsize))
                    for cmsg_level, cmsg_type, cmsg_data in anc:
                        if (cmsg_level == socket.SOL_SOCKET and
                                cmsg_type == socket.SCM_RIGHTS):
                            fds.frombytes(cmsg_data[:len(cmsg_data) -
                                          (len(cmsg_data) % fds.itemsize)])
                    raw.unix_fds = fds.tolist()
                else:
                    cnt = self._sock.recv_into(view)
                view.release()
                if not cnt:
                    raise TransportError()
                self._router.incoming(Message.from_bytes(raw))
        except Exception as ex:
            _logger.debug('recv loop', exc_info=True)
            self._set_error(ex)
            self.disconnect()
        _logger.debug('EXIT recv loop')


class UnixTransport(Transport):
    """Transport that uses a unix domain socket.

    It supports the passing of file descriptors.
    """

    def __init__(self, params, router):
        super().__init__(params, router)
        self.unix_fds_enabled = True
        self._addr_family = socket.AF_UNIX
        if 'path' in params:
            self._address = params['path']
        else:
            self._address = b'\0' + params['abstract'].encode()


class TcpTransport(Transport):
    """Transport that uses a TCP socket."""

    def __init__(self, params, router):
        super().__init__(params, router)
        self._addr_family = socket.AF_INET
        self._address = (params['host'], int(params['port']))


class NonceTcpTransport(TcpTransport):
    """Transport that uses a nonce-authenticated TCP socket."""

    def __init__(self, params, router):
        super().__init__(params, router)
        self._noncefile = params['noncefile']

    def connect(self):
        """Connect to message bus."""
        super().connect()
        with open(self._noncefile, 'br') as fh:
            self._sock.sendall(fh.read())


_transports = {
    'unix': UnixTransport,
    'tcp': TcpTransport,
    'nonce-tcp': NonceTcpTransport,
}
