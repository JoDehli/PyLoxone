"""Home Assistant compatibility for units and optional camera features."""

from importlib import import_module
from typing import Final

from homeassistant import const as ha_const
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION, Platform
from homeassistant.helpers.device_registry import DeviceRegistry

from .const import LOXONE_PLATFORMS

# HA 2025.2 lacks the hourly flow member and ratio enum. Keep their fallbacks
# here so sensor definitions use named units and newer HA keeps its native enums.
UNIT_LITERS_PER_HOUR: Final[str] = getattr(ha_const.UnitOfVolumeFlowRate, "LITERS_PER_HOUR", "L/h")
UNIT_PARTS_PER_MILLION: Final[str] = (
    ha_const.UnitOfRatio.PARTS_PER_MILLION
    if hasattr(ha_const, "UnitOfRatio")
    else ha_const.CONCENTRATION_PARTS_PER_MILLION
)


def supports_intercom() -> bool:
    """Require the native two-way camera API, including its device registry API."""
    if (MAJOR_VERSION, MINOR_VERSION) < (2026, 11):
        return False
    try:
        camera = import_module("homeassistant.components.camera")
    except ImportError:
        # A minimal HA environment may lack optional camera dependencies.
        # Their absence must not prevent existing Loxone entities loading.
        return False
    capabilities = getattr(camera, "CameraEntityCapabilities", None)
    if capabilities is None:
        return False
    try:
        capabilities(two_way_audio=True)
    except TypeError:
        return False
    return hasattr(DeviceRegistry, "async_get_device_by_identifier") and all(
        hasattr(camera, name)
        for name in (
            "WebRTCAnswer",
            "WebRTCClientConfiguration",
            "WebRTCCandidate",
            "WebRTCError",
        )
    )


def entry_platforms() -> list[Platform]:
    """Select the same supported platforms when setting up and unloading."""
    if supports_intercom():
        return list(LOXONE_PLATFORMS)
    return [platform for platform in LOXONE_PLATFORMS if platform != Platform.CAMERA]
