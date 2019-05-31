"""
dcar.auth
---------
"""

import binascii
import hashlib
import os
import secrets
import stat

from .errors import AuthenticationError

_all_ = ['authenticate']

COOKIE_DIR = os.path.expanduser(b'~/.dbus-keyrings')


def _external(sock):
    sock.sendall(b'AUTH EXTERNAL %b\r\n' % _auth_id())
    return _recv_line(sock)


def _dbus_cookie_sha1(sock):
    mode = os.stat(COOKIE_DIR).st_mode
    if mode & stat.S_IRWXG or mode & stat.S_IRWXO:
        return  # if group/others have permissions don't use it
    sock.sendall(b'AUTH DBUS_COOKIE_SHA1 %b\r\n' % _auth_id())
    reply = _recv_line(sock)
    if reply[0] == b'DATA':
        cookie_ctx, cookie_id, chall_str =\
            bytes.fromhex(reply[1].decode('ascii')).split()
        cookie_file = os.path.join(COOKIE_DIR, cookie_ctx)
        with open(cookie_file, 'br') as fh:
            for id_, _, c in (line.split() for line in fh):
                if id_ == cookie_id:
                    cookie = c
                    break
            else:
                cookie = None
        if cookie:
            client_chall = secrets.token_hex(16).encode('ascii')
            s = b':'.join([chall_str, client_chall, cookie])
            s = hashlib.sha1(s).hexdigest()
            s = b' '.join([client_chall, s.encode('ascii')])
            sock.sendall(b'DATA %b\r\n' % s.hex().encode('ascii'))
            return _recv_line(sock)


def _anonymous(sock):
    sock.sendall(b'AUTH ANONYMOUS\r\n')
    return _recv_line(sock)


auth_mechs = {
    b'EXTERNAL': _external,
    b'DBUS_COOKIE_SHA1': _dbus_cookie_sha1,
    b'ANONYMOUS': _anonymous,
}


def authenticate(sock, unix_fds):
    sock.sendall(b'\0AUTH\r\n')
    auth_reply = _recv_line(sock)
    if auth_reply[0] == b'REJECTED':
        for auth_mech, func in auth_mechs.items():
            if auth_mech not in auth_reply[1:]:
                continue
            reply = func(sock)
            if reply is None:
                sock.sendall(b'CANCEL\r\n')
                _recv_line(sock)  # read REJECTED reply
            if reply and reply[0] == b'OK':
                guid = reply[1]
                if unix_fds:
                    sock.sendall(b'NEGOTIATE_UNIX_FD\r\n')
                    reply = _recv_line(sock)
                    unix_fds = reply[0] == b'AGREE_UNIX_FD'
                sock.sendall(b'BEGIN\r\n')
                return guid.decode(), unix_fds
        else:
            raise AuthenticationError('no supported auth mech in %r' %
                                      b' '.join(reply[1:]))
    raise AuthenticationError('unexpected reply: %r' % b' '.join(auth_reply))


def _recv_line(sock):
    line = b''
    while True:
        line += sock.recv(1024)
        if line.endswith(b'\r\n'):
            break
    return line.split()


def _auth_id():
    return binascii.hexlify(str(os.getuid()).encode())
