"""Interpreter handoff alignment API package.

The public contract (see README) is that ``time`` is handled as an
arbitrary-precision integer end to end.  CPython caps int<->str conversions
at 4300 decimal digits by default (the CVE-2020-10735 mitigation, present
since 3.10.7 and still the default on 3.12); without intervention a
perfectly legal 4301-digit timestamp would make ``json.loads`` raise
``ValueError`` and the request would surface as an unstructured HTTP 500.

The limit is therefore disabled process-wide at package import, so every
entry point (uvicorn, pytest, scripts) behaves identically regardless of
environment variables, and every conversion path is covered uniformly:

* request parsing — ``json.loads`` of huge integer literals;
* response serialization — ``JSONResponse``/``json.dumps`` of huge ``time``
  and ``cost`` values;
* error-message formatting — f-strings embedding offending values in
  ``main._describe`` and ``validation.validate_anchors``;
* anchor cost computation — ``|Δt|`` results stay exact big integers that
  must also survive serialization.

Values are never converted through floats: precision is preserved
digit-for-digit at any magnitude.
"""

from __future__ import annotations

import sys

# 0 disables the limitation entirely (documented behavior of
# sys.set_int_max_str_digits).  The guard keeps the package importable on
# interpreters older than 3.10.7 that lack the knob altogether.
_set_int_max_str_digits = getattr(sys, "set_int_max_str_digits", None)
if _set_int_max_str_digits is not None:
    _set_int_max_str_digits(0)
