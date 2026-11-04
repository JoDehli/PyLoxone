"""Translate a browser's combined offer to Loxone's video-first negotiation."""

from .errors import IntercomProtocolError, IntercomSDPError

MAX_SDP_SIZE = 262144


def split_sdp(sdp):
    header, sections = [], []
    for line in sdp.splitlines():
        if line.startswith("m="):
            sections.append([line])
        elif sections:
            sections[-1].append(line)
        else:
            header.append(line)
    return header, sections


def kind(section):
    return section[0].split()[0][2:]


def mid(section):
    mids = [line[6:] for line in section if line.startswith("a=mid:")]
    if len(mids) != 1 or not mids[0] or any(char.isspace() for char in mids[0]):
        raise IntercomSDPError("SDP contains a missing or invalid media ID")
    return mids[0]


def with_mid(section, value):
    return ["a=mid:" + value if line.startswith("a=mid:") else line for line in section]


def serialize(header, sections):
    return "\r\n".join(header + [line for section in sections for line in section]) + "\r\n"


class OfferPlan:
    def __init__(self, sdp):
        if not isinstance(sdp, str) or not sdp or len(sdp) > MAX_SDP_SIZE:
            raise IntercomSDPError("Invalid or oversized browser SDP offer")
        self.header, self.sections = split_sdp(sdp)
        kinds = [kind(section) for section in self.sections]
        if kinds.count("video") != 1 or kinds.count("audio") > 1 or set(kinds) - {"audio", "video"}:
            raise IntercomSDPError("Intercom requires one video and at most one audio section")
        self.order = [kinds.index("video")]
        if "audio" in kinds:
            self.order.append(kinds.index("audio"))
        self.wire_to_browser = dict(enumerate(self.order))
        self.browser_to_wire = {value: key for key, value in self.wire_to_browser.items()}
        self.browser_mids = {index: mid(section) for index, section in enumerate(self.sections)}
        if len(set(self.browser_mids.values())) != len(self.sections):
            raise IntercomSDPError("SDP contains duplicate media IDs")
        for section in self.sections:
            if len(section[0].split()) < 4:
                raise IntercomSDPError("SDP contains an invalid media section")
        origins = [line[2:].split() for line in self.header if line.startswith("o=")]
        if len(origins) != 1 or len(origins[0]) != 6 or not origins[0][2].isdigit():
            raise IntercomSDPError("SDP contains an invalid session origin")
        self.has_audio = "audio" in kinds

    def _candidate_index(self, index, candidate_mid, mids):
        if index is None and candidate_mid is not None:
            index = next((key for key, value in mids.items() if value == str(candidate_mid)), None)
        if not isinstance(index, int) or isinstance(index, bool) or index not in mids:
            raise IntercomProtocolError("ICE candidate has an unknown media target")
        if candidate_mid is not None and str(candidate_mid) != mids[index]:
            raise IntercomProtocolError("ICE candidate media targets do not match")
        return index

    def local_candidate_target(self, index, candidate_mid):
        """Resolve browser index/mid-only candidates without guessing a transport."""
        index = self._candidate_index(index, candidate_mid, self.browser_mids)
        return self.browser_to_wire[index]

    def remote_candidate_target(self, index, candidate_mid):
        """Map a device's wire index/mid back to the original browser media."""
        index = self._candidate_index(index, candidate_mid, {key: str(key) for key in self.wire_to_browser})
        browser_index = self.wire_to_browser[index]
        return browser_index, self.browser_mids[browser_index]

    def _offer(self, count, bootstrap=False):
        header = []
        for line in self.header:
            if line.startswith("a=group:BUNDLE"):
                header.append("a=group:BUNDLE " + " ".join(str(i) for i in range(count)))
            elif bootstrap and line.startswith("o="):
                fields = line[2:].split()
                fields[2] = str(max(0, int(fields[2]) - 1))
                header.append("o=" + " ".join(fields))
            else:
                header.append(line)
        sections = [
            with_mid(self.sections[index], str(wire_index)) for wire_index, index in enumerate(self.order[:count])
        ]
        return serialize(header, sections)

    def video_offer(self):
        return self._offer(1, bootstrap=self.has_audio)

    def combined_offer(self):
        return self._offer(len(self.order))

    def restore_answer(self, answer):
        if not isinstance(answer, str) or not answer or len(answer) > MAX_SDP_SIZE:
            raise IntercomSDPError("Invalid or oversized Intercom SDP answer")
        header, sections = split_sdp(answer)
        expected = [kind(self.sections[index]) for index in self.order]
        if [kind(section) for section in sections] != expected:
            raise IntercomSDPError("Intercom answer omitted media after staged negotiation")
        if [mid(section) for section in sections] != [str(index) for index in range(len(sections))]:
            raise IntercomSDPError("Intercom answer contains unexpected media IDs")
        restored = [None] * len(sections)
        for wire_index, section in enumerate(sections):
            browser_index = self.wire_to_browser[wire_index]
            restored[browser_index] = with_mid(section, self.browser_mids[browser_index])
        mapped_header = []
        for line in header:
            if line.startswith("a=group:BUNDLE"):
                raise IntercomSDPError("Bundled Intercom answers are not supported")
            mapped_header.append(line)
        return serialize(mapped_header, restored)
