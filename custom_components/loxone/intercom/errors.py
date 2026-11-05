"""User-safe errors; never include a token, SDP or a device's raw payload."""


class IntercomError(RuntimeError):
    """A signalling error with a safe frontend error code."""

    code = "intercom_negotiation_failed"


class IntercomAuthenticationError(IntercomError):
    """The device rejected this session's dedicated token."""

    code = "intercom_authentication_failed"


class IntercomBusyError(IntercomError):
    """Another session owns the audio call."""

    code = "intercom_busy"


class IntercomProtocolError(IntercomError):
    """The peer sent an invalid signalling message."""

    code = "intercom_protocol_error"


class IntercomSDPError(IntercomProtocolError):
    """The offer or answer cannot be translated safely."""

    code = "intercom_invalid_sdp"


class IntercomConnectionError(IntercomError):
    """The signalling connection ended unexpectedly."""

    code = "intercom_connection_lost"


class IntercomIceError(IntercomError):
    """The peer could not establish the media connection."""

    code = "intercom_ice_failed"
