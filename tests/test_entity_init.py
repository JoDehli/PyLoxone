"""``LoxoneEntity.__init__`` must survive control attributes it cannot set.

It used to call ``sys.exit(-1)`` on any unexpected exception from
``setattr``, which shut down the whole Home Assistant process because
of one odd control in the structure file.
"""

from __future__ import annotations

import logging

from custom_components.loxone import LoxoneEntity


class _Entity(LoxoneEntity):
    @property
    def broken(self):
        return None

    @broken.setter
    def broken(self, value):
        raise ValueError("cannot take this value")

    @property
    def read_only(self):
        return None


def test_unexpected_setattr_error_is_logged_not_fatal(caplog):
    with caplog.at_level(logging.ERROR):
        entity = _Entity(name="Kitchen", broken=1, uuidAction="uuid-1")

    # The other attributes are still applied.
    assert entity.uuidAction == "uuid-1"
    record = next(r for r in caplog.records if "broken" in r.getMessage())
    assert "Kitchen" in record.getMessage()
    assert record.exc_info is not None


def test_read_only_attribute_is_logged(caplog):
    with caplog.at_level(logging.ERROR):
        _Entity(name="Kitchen", read_only=1)

    assert any(
        "read_only" in r.getMessage() and "Kitchen" in r.getMessage()
        for r in caplog.records
    )
