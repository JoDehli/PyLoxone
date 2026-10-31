"""Compatibility import for the extracted native audio implementation.

A module alias deliberately preserves identity for existing integration callers
and transport-level tests; no second parser, transport or protocol is retained.
"""
import sys
from pyloxone_audio import native

sys.modules[__name__] = native
