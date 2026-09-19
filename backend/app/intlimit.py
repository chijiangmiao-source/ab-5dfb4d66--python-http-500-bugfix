"""Arbitrary-precision JSON integer support around the PEP 682 digit cap.

Python 3.12 (and 3.11.4+) caps decimal<->int string conversions at
``sys.get_int_max_str_digits()`` (4300 digits by default) to limit the cost of
parsing pathological inputs.  The public contract of this service is that
``time`` values are arbitrary-precision integers (see README, "超大毫秒整数"),
so a timestamp with 4301 decimal digits must align and round-trip exactly — it
must never surface as an unstructured HTTP 500.

Three places in the request life cycle perform a throttled conversion:

1. decoding the request body — ``json.loads`` runs ``int(token)`` itself;
   passing ``parse_int=int`` while the cap is lifted keeps every integer
   token as a genuine ``int`` (floats stay ``float``, booleans stay ``bool``)
   without ever routing the digits through a ``str``;
2. formatting validation messages that embed the offending decimal value;
3. encoding the response — ``json.dumps`` reprs every integer back to decimal.

``unlimited_int_strings`` lifts the cap only inside a ``with`` block and then
restores the interpreter default, so the rest of the process keeps Python's
safety threshold intact.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Iterator
from typing import Any

# A cap this large would defeat the purpose of PEP 682; 0 documentedly means
# "unlimited". We only ever set 0 inside ``unlimited_int_strings``.
DISABLED = 0


@contextlib.contextmanager
def unlimited_int_strings() -> Iterator[None]:
    """Temporarily disable the decimal<->int digit limit, then restore it.

    A no-op on interpreters that predate (or build without) the PEP 682
    ``sys.set_int_max_str_digits`` API, where every conversion was already
    unlimited.
    """
    set_limit = getattr(sys, "set_int_max_str_digits", None)
    if set_limit is None:
        yield
        return
    previous = sys.get_int_max_str_digits()
    set_limit(DISABLED)
    try:
        yield
    finally:
        set_limit(previous)


def json_loads_arbitrary_ints(raw: bytes | str) -> Any:
    """Parse JSON keeping integer literals of ANY length as exact ``int``.

    The tokenizer hands each integer token to ``parse_int`` verbatim; with the
    global digit cap lifted inside this call even a 4301-digit token converts
    to an arbitrary-precision ``int`` whose decimal value is unchanged. Float
    literals (handled by ``parse_float``) and ``true``/``false`` are untouched.
    """
    with unlimited_int_strings():
        return json.loads(raw, parse_int=int)


def json_dumps_arbitrary_ints(value: Any) -> str:
    """Serialize to JSON, emitting arbitrarily large ints as exact decimals.

    No timestamp is ever converted to a float: integers go through the normal
    integer encoder with the digit cap lifted, so the response digits equal
    the request digits bit-for-bit.
    """
    with unlimited_int_strings():
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
