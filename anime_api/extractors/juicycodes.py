"""JuicyCodes decoder (ported from the RareAnimesIndia extension's
``JuicyCodes.kt``).

The Argon player pages embed their config inside a ``_juicycodes("...")``
payload.  :func:`decode_from_html` finds that payload in a page's HTML and
decodes it to the plain config string (which then contains e.g.
``"file": "https://...m3u8"``).

Algorithm (exactly as in the extension):

* ``_juicycodes("...")`` — the payload's last 3 chars are the *salt*;
  ``offset`` is the concatenation of ``(ord(char) - 100)`` for each salt
  char, read as a long.
* The rest of the payload is base64url-ish: ``_`` -> ``+``, ``-`` -> ``/``,
  padded with ``=`` to a multiple of 4, decoded as ISO-8859-1.
* Each decoded char maps through the symbol table
  ``"`%-+*$!_^="`` to a digit 0-9 (index in the table).
* Every 4 digits form a quad; the output char is
  ``chr((quad % 1000) - offset)`` and is kept only when it falls in the
  valid range 9-126.
"""

import base64
import re

# Symbol table: index 0-9 maps to digit 0-9.  (The report renders the
# table space-separated as "` % - + * $ ! _ ^ =".)
_SYMBOLS = "`%-+*$!_^="
_SYMBOL_TO_DIGIT = {ch: str(i) for i, ch in enumerate(_SYMBOLS)}

_JUICY_RE = re.compile(r'_juicycodes\("([^"]+)"\)')


def decode_payload(payload):
    """Decode one raw ``_juicycodes(...)`` payload string; None on failure."""
    if not payload or len(payload) <= 3:
        return None
    salt = payload[-3:]
    try:
        offset = int("".join(str(ord(c) - 100) for c in salt))
    except ValueError:
        return None
    body = payload[:-3]
    # base64url-ish -> standard base64, padded.
    b64 = body.replace("_", "+").replace("-", "/")
    b64 += "=" * (-len(b64) % 4)
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return None
    text = raw.decode("iso-8859-1")
    digits = []
    for ch in text:
        digit = _SYMBOL_TO_DIGIT.get(ch)
        if digit is None:
            # Unknown symbol: the payload is corrupt for our purposes.
            return None
        digits.append(digit)
    out = []
    for i in range(0, len(digits) - 3, 4):
        quad = int("".join(digits[i:i + 4]))
        code = (quad % 1000) - offset
        if 9 <= code <= 126:
            out.append(chr(code))
    return "".join(out) if out else None


def decode_from_html(html):
    """Find ``_juicycodes("...")`` in ``html`` and decode it.

    Returns the decoded config string, or ``None`` when no payload is
    present or it cannot be decoded.
    """
    if not html:
        return None
    match = _JUICY_RE.search(html)
    if not match:
        return None
    return decode_payload(match.group(1))
