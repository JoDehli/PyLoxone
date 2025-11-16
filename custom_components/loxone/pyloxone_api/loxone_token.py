"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
import os
import types
from collections import namedtuple
from dataclasses import asdict, dataclass
from typing import Final

LOXONE_EPOCH: Final = datetime.datetime(2009, 1, 1, 0, 0)


class LxJsonKeySalt:
    def __init__(self, key=None, salt=None, hash_alg=None):
        self.key = key
        self.salt = salt
        self.hash_alg = hash_alg or "SHA1"

    def read_user_salt_response(self, reponse):
        js = json.loads(reponse, strict=False)
        value = js["LL"]["value"]
        self.key = value["key"]
        self.salt = value["salt"]
        self.hash_alg = value.get("hashAlg", "SHA1")


Salt = namedtuple("Salt", ["value", "is_new", "previous"])


@dataclass
class LoxoneToken:
    """The LoxoneToken class, used for storing token information"""

    token: str = ""
    valid_until: float = 0  # seconds since 1.1.2009
    key: str = ""
    hash_alg: str = ""
    unsecure_password: bool | None = None

    def __post_init__(self):
        if self.token != "" and self.valid_until != 0:
            return
        self.token = ""
        self.valid_until = -1
        self.key = ""
        self.unsecure_password = False

    def seconds_to_expire(self) -> int:
        """The number of seconds until this token expires."""

        # current number of seconds since epoch
        current_seconds_since_epoch = (
            datetime.datetime.now() - LOXONE_EPOCH
        ).total_seconds()
        # work out how many seconds are left
        if self.valid_until == 0:
            raise ValueError("Cannot have valid_until == 0")
        return int(self.valid_until - current_seconds_since_epoch)
