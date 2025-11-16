"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""

import hashlib
import logging
from hmac import HMAC

from Crypto.Hash import HMAC, SHA1, SHA256

_LOGGER = logging.getLogger(__name__)

hash_algorithms = {"SHA1": SHA1, "SHA256": SHA256}


def hash_token(key: str, string_to_hash: str, hash_alg: str = "SHA1") -> str | None:
    """Hash token with the given algorithm and key."""
    if hash_alg == "SHA1":
        hash_module = SHA1
    elif hash_alg == "SHA256":
        hash_module = SHA256
    else:
        _LOGGER.error(f"Unrecognised hash algorithm: {hash_alg}")
        return None
    digester = HMAC.new(bytes.fromhex(key), string_to_hash.encode("utf-8"), hash_module)
    return digester.hexdigest()


def generate_hmac(data: str, hash_alg: str) -> str | None:
    """Generate HMAC hash."""
    if hash_alg == "SHA1":
        m = hashlib.sha1()
    elif hash_alg == "SHA256":
        m = hashlib.sha256()
    else:
        _LOGGER.error(f"Unrecognised hash algorithm: {hash_alg}")
        return None

    m.update(data.encode("utf-8"))
    return m.hexdigest().upper()
