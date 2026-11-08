"""Google Play reviews: DISABLED.

Google offers no public API for third-party app reviews (the Play Developer Reporting/Reply
APIs only cover your own apps) and the Play terms prohibit scraping. Per the master prompt this
adapter is disabled until a terms-compliant method exists.

access_basis: none
terms: https://play.google.com/about/play-terms/
"""

from __future__ import annotations

NAME = "googleplay"
ENABLED = False
ACCESS_BASIS = None
TERMS_URL = "https://play.google.com/about/play-terms/"


def collect(*_args, **_kwargs):
    raise NotImplementedError("Google Play has no terms-compliant review source; disabled")
