"""Compatibility import for portable native radio discovery."""
import sys
from pyloxone_audio import radio

sys.modules[__name__] = radio
