"""Convert neutral library catalogue values at their owning HA callers."""
from __future__ import annotations

from homeassistant.components.media_player import BrowseMedia, SearchMedia
from homeassistant.components.media_player.const import MediaClass
from pyloxone_audio.models import MediaNode, SearchResult


def to_ha_browse(node: MediaNode) -> BrowseMedia:
    """Preserve every existing browser field and convert children recursively."""
    return BrowseMedia(
        media_class=MediaClass(node.media_class),
        media_content_id=node.media_content_id,
        media_content_type=node.media_content_type,
        title=node.title,
        can_play=node.can_play,
        can_expand=node.can_expand,
        children=[to_ha_browse(child) for child in node.children] if node.children is not None else None,
        children_media_class=MediaClass(node.children_media_class) if node.children_media_class is not None else None,
        thumbnail=node.thumbnail,
        not_shown=node.not_shown,
        can_search=node.can_search,
        search_media_classes=[MediaClass(kind) for kind in node.search_media_classes]
        if node.search_media_classes is not None else None,
    )


def to_ha_search(result: SearchResult) -> SearchMedia:
    """Keep the host's supported search schema and real BrowseMedia instances."""
    return SearchMedia(version=result.version, result=[to_ha_browse(node) for node in result.result])
