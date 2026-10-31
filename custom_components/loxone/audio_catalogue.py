"""Compatibility import for portable catalogue/source history ownership.

The existing entity converts neutral catalogue nodes using audio_models before
returning them to HA. Opaque IDs and target types retain their exact identity.
"""
import sys
from pyloxone_audio import catalogue

sys.modules[__name__] = catalogue
