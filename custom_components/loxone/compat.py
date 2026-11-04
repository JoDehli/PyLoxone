"""Home Assistant feature boundaries shared by platform setup and unload."""

from importlib import import_module

from homeassistant.const import MAJOR_VERSION, MINOR_VERSION, Platform
from homeassistant.helpers.device_registry import DeviceRegistry

from .const import LOXONE_PLATFORMS


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
