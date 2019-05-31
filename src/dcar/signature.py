"""
dcar.signature
--------------
"""
from collections import Counter

from . import marshal
from .const import MAX_SIGNATURE_LEN, MAX_NESTING_DEPTH
from .errors import SignatureError

__all__ = ['Signature']


class Signature:
    def __init__(self, sig):
        if not isinstance(sig, str):
            raise SignatureError('must be of type str, not %s' %
                                 sig.__class__.__name__)
        if len(sig) > MAX_SIGNATURE_LEN:
            raise SignatureError('too long: %d > %d' %
                                 (len(sig), MAX_SIGNATURE_LEN))
        self._string = sig
        counter = Counter()
        self._data = _parse_signature(list(sig), counter)
        if counter['r'] or counter['e']:
            raise SignatureError('unclosed: struct %d, dict entry %d' %
                                 (counter['r'], counter['e']))

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __str__(self):
        return self._string

    def __repr__(self):
        return repr(self._data)


def _parse_signature(sig, counter, container=None):
    if counter['a'] > MAX_NESTING_DEPTH or counter['r'] > MAX_NESTING_DEPTH:
        raise SignatureError('depth: array %d, struct %d' %
                             (counter['a'], counter['r']))
    ct_lst = []  # list of complete types
    while sig:
        token = sig.pop(0)
        if token == '(':
            counter['r'] += 1
            lst = _parse_signature(sig, counter, 'r')
            if not lst:
                raise SignatureError('struct must have at least 1 element')
            ct_lst.append(('r', lst))
        elif token == '{':
            if container != 'a':
                raise SignatureError('dict entry outside array')
            counter['e'] += 1
            lst = _parse_signature(sig, counter, 'e')
            if len(lst) != 2:
                raise SignatureError('dict entry must have 2 elements')
            if lst[0][1] is not None:
                raise SignatureError('dict entry key must be basic type')
            ct_lst.append(('e', lst))
        elif token == 'a':
            counter['a'] += 1
            lst = _parse_signature(sig, counter, 'a')
            if not lst:
                raise SignatureError('array without element type')
            ct_lst.append((token, lst))
        elif token == 'v':
            ct_lst.append((token, []))
        elif token in marshal.type_codes:
            ct_lst.append((token, None))
        elif container == 'r' and token == ')':
            counter['r'] -= 1
            break
        elif container == 'e' and token == '}':
            counter['e'] -= 1
            break
        else:
            raise SignatureError('unexpected token: %r (%r %r)' %
                                 (token, sig, ct_lst))
        if container == 'a':
            counter['a'] -= 1
            break
    return ct_lst
