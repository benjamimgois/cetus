"""Vendor definitions for the Cetus Automation module.

Each vendor entry is a declarative table describing how to recognize the
device prompt, how to detect command errors and how to answer interactive
questions automatically.  The automation workers consume this table; adding
support for a new vendor means adding one entry here and nothing else.

A vendor entry contains:
- ``label``: human readable display name.
- ``prompt``: list of regexes matching an idle prompt (applied to the last
  line of the session output, multiline-tolerant).
- ``errors``: list of regexes flagging vendor error output in a command
  response (applied line by line).
- ``interactive``: list of ``(question_regex, answer)`` pairs used to reply
  to interactive questions automatically.  The literal ``{password}`` inside
  an answer is replaced by the session password at runtime.
- ``telnet_login``: regexes for the login stage prompts (username/password).
"""

import re


__all__ = [
    'VENDORS',
    'VENDOR_MENU',
    'AUTODETECT',
    'get_vendor',
    'detect_vendor',
    'is_prompt',
    'find_interactive_answer',
    'find_vendor_error',
]


AUTODETECT = 'autodetect'

VENDORS = {
    'huawei': {
        'label': 'Huawei VRP',
        'prompt': [
            re.compile(r'<[^<>\s][^<>\r\n]*>\s*$'),            # <SW1>
            re.compile(r'\[[^\[\]\r\n]+\]\s*$'),               # [SW1] / [SW1-GigabitEthernet0/0/1]
        ],
        'errors': [
            re.compile(r'^Error:\s*(Unrecognized|Wrong|Incomplete|Ambiguous|Too many)', re.I),
            re.compile(r'^Error:', re.I),
            re.compile(r'%Error'),
        ],
        'interactive': [
            (re.compile(r'(?i)[\[(]\s*y\s*/\s*n\s*[\])]'), 'Y'),
            (re.compile(r'(?i)continue\s*\?\s*$'), 'Y'),
            (re.compile(r'(?i)overwrite[^:\r\n]*\?\s*$'), 'Y'),
            (re.compile(r'(?i)password\s*:\s*$'), '{password}'),
        ],
        'telnet_login': (re.compile(r'(?i)(username|user\s*name|login)\s*:'), re.compile(r'(?i)password\s*:')),
    },
    'cisco': {
        'label': 'Cisco IOS',
        'prompt': [
            re.compile(r'[^\s\r\n#>]+[#>]\s*$'),               # SW1> / SW1# / SW1(config)#
        ],
        'errors': [
            re.compile(r'^% Invalid input detected', re.I),
            re.compile(r'^% Ambiguous command', re.I),
            re.compile(r'^% Incomplete command', re.I),
            re.compile(r'^% Unknown command', re.I),
            re.compile(r'^%Error'),
        ],
        'interactive': [
            (re.compile(r'\[confirm\]\s*$'), '\r'),
            (re.compile(r'(?i)[\[(]\s*y\s*/\s*n\s*[\])]'), 'Y'),
            (re.compile(r'(?i)continue\s*\?\s*$'), 'Y'),
            (re.compile(r'(?i)password\s*:\s*$'), '{password}'),
        ],
        'telnet_login': (re.compile(r'(?i)(username|user\s*access|login)\s*:'), re.compile(r'(?i)password\s*:')),
    },
    'mikrotik': {
        'label': 'MikroTik RouterOS',
        'prompt': [
            re.compile(r'\[[^\]\r\n]+\]\s*>\s*$'),             # [admin@MikroTik] >
        ],
        'errors': [
            re.compile(r'bad command name', re.I),
            re.compile(r'input does not match any value', re.I),
            re.compile(r'no such item', re.I),
            re.compile(r'unknown parameter', re.I),
            re.compile(r'^failure:', re.I),
        ],
        'interactive': [
            (re.compile(r'(?i)[\[(]\s*y\s*/\s*n\s*[\])]'), 'Y'),
            (re.compile(r'(?i)continue\s*\?\s*$'), 'Y'),
            (re.compile(r'(?i)password\s*:\s*$'), '{password}'),
        ],
        'telnet_login': (re.compile(r'(?i)login\s*:'), re.compile(r'(?i)password\s*:')),
    },
    'juniper': {
        'label': 'Juniper JunOS',
        'prompt': [
            re.compile(r'[^\s\r\n>@]+@[^\s\r\n>@]*>\s*$'),     # user@host>
            re.compile(r'[^\s\r\n>#]+@[^\s\r\n>#]*#\s*$'),     # user@host# (config mode)
        ],
        'errors': [
            re.compile(r'^syntax error', re.I),
            re.compile(r'^error:', re.I),
            re.compile(r'unknown command', re.I),
            re.compile(r'^invalid value', re.I),
        ],
        'interactive': [
            (re.compile(r'(?i)[\[(]\s*yes\s*/\s*no\s*[\])]'), 'yes'),
            (re.compile(r'(?i)password\s*:\s*$'), '{password}'),
        ],
        'telnet_login': (re.compile(r'(?i)(login|username)\s*:'), re.compile(r'(?i)password\s*:')),
    },
    'generic': {
        'label': 'Genérico',
        'prompt': [
            re.compile(r'[^\s\r\n]*[#>$]\s*$'),
        ],
        'errors': [
            re.compile(r'invalid input', re.I),
            re.compile(r'ambiguous command', re.I),
            re.compile(r'incomplete command', re.I),
            re.compile(r'unknown command', re.I),
            re.compile(r'^error[:\s]', re.I | re.M),
        ],
        'interactive': [
            (re.compile(r'(?i)[\[(]\s*y\s*/\s*n\s*[\])]'), 'Y'),
            (re.compile(r'(?i)continue\s*\?\s*$'), 'Y'),
        ],
        'telnet_login': (re.compile(r'(?i)(username|login)\s*:'), re.compile(r'(?i)password\s*:')),
    },
}

# Combobox entries: (key, label). 'autodetect' first.
VENDOR_MENU = [(AUTODETECT, 'Autodetect')] + [
    (key, VENDORS[key]['label']) for key in ('huawei', 'cisco', 'mikrotik', 'juniper', 'generic')
]

# Detection order: most specific prompt first.
_DETECT_ORDER = ['mikrotik', 'huawei', 'juniper', 'cisco']

_DETECT_REGEXES = [
    ('mikrotik', re.compile(r'\[[^\]\r\n]+\]\s*>\s*$')),
    ('huawei', re.compile(r'<[^<>\s][^<>\r\n]*>\s*$')),
    ('juniper', re.compile(r'[^\s\r\n>@]+@[^\s\r\n>@]+[>#]\s*$')),
    ('cisco', re.compile(r'[^\s\r\n@#>]+[#>]\s*$')),
]


def get_vendor(key):
    """Return the vendor table for *key*, falling back to 'generic'."""
    return VENDORS.get(key, VENDORS['generic'])


def detect_vendor(text):
    """Infer the vendor from session output (last line is expected to be the prompt).

    Returns a vendor key; 'generic' when nothing matches.
    """
    last_line = ''
    for line in reversed(text.splitlines()):
        if line.strip():
            last_line = line
            break
    for key, regex in _DETECT_REGEXES:
        if regex.search(last_line):
            return key
    return 'generic'


def _last_line(text):
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return ''


def is_prompt(text, vendor_key):
    """True when the last non-empty line of *text* is an idle prompt."""
    if not text:
        return False
    line = _last_line(text)
    vendor = get_vendor(vendor_key)
    return any(rx.search(line) for rx in vendor['prompt'])


def find_interactive_answer(text, vendor_key, password=''):
    """Return the automatic answer for an interactive question at the tail
    of *text*, or None when no question is pending."""
    if not text:
        return None
    tail = text[-200:]
    vendor = get_vendor(vendor_key)
    for regex, answer in vendor['interactive']:
        if regex.search(tail):
            return answer.replace('{password}', password or '')
    return None


def find_vendor_error(text, vendor_key, echo_line=''):
    """Search *text* for a vendor error line, skipping the command echo.

    Returns the matched error line, or None.
    """
    if not text:
        return None
    vendor = get_vendor(vendor_key)
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or not stripped[:1].isprintable():
            continue
        if echo_line and stripped.endswith(echo_line.strip()):
            continue
        for regex in vendor['errors']:
            if regex.search(stripped):
                return stripped
    return None
