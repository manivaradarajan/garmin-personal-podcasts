"""RSS 2.0 feed builder — pure function, no I/O."""

from __future__ import annotations

import calendar
from datetime import datetime
from email.utils import formatdate
from xml.etree.ElementTree import Element, SubElement, tostring

from podcast.models import ManifestEntry

__all__ = ["build_rss_xml", "canonical_mime_type", "default_description"]

_ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
_ITUNES_CATEGORY = "Education"

# Drive reports some MIME types that are not registered IANA types
# (notably audio/mp3 for uppercase .MP3 files). Normalise enclosure
# types to canonical equivalents so strict feed validators accept them.
_CANONICAL_MIME_TYPES = {
    "audio/mp3": "audio/mpeg",
    "audio/x-m4a": "audio/mp4",
    "audio/x-m4b": "audio/mp4",
}


def canonical_mime_type(mime_type: str) -> str:
    """Map a Drive-reported MIME type to its canonical enclosure type.

    Args:
        mime_type: MIME type as reported by Drive (may include params).

    Returns:
        Canonical IANA media type for use in RSS enclosures.
    """
    base = mime_type.lower().split(";")[0].strip()
    return _CANONICAL_MIME_TYPES.get(base, base)


def build_rss_xml(
    entries: list[ManifestEntry],
    title: str,
    feed_url: str,
    base_url: str,
    description: str | None = None,
) -> str:
    """Build an RSS 2.0 feed XML string from manifest entries.

    Entries are sorted newest-first by published_at. The result is a valid
    RSS 2.0 document with itunes: namespace elements for Garmin compatibility.
    Output is deterministic for a given manifest: lastBuildDate tracks the
    newest episode, so validators and crawlers see stable bytes.

    Args:
        entries: Manifest entries representing synced audio files.
        title: Podcast channel title.
        feed_url: Absolute URL of this feed (used as channel link and self).
        base_url: Base URL of the application.
        description: Channel description; falls back to a generated one
            long enough for validator minimums.

    Returns:
        UTF-8 encoded RSS 2.0 XML document as a string.
    """
    rss = Element("rss", {"version": "2.0", "xmlns:itunes": _ITUNES_NS})
    channel = SubElement(rss, "channel")

    sorted_entries = sorted(
        entries,
        key=lambda e: e.published_at,
        reverse=True,
    )
    if sorted_entries:
        last_build = _iso_to_rfc2822(sorted_entries[0].published_at)
    else:
        last_build = _rfc2822_now()
    _add_channel_metadata(
        channel,
        title,
        feed_url,
        base_url,
        description or default_description(title),
        last_build,
    )
    cover_url = f"{base_url}/cover.png"
    for entry in sorted_entries:
        _add_item(channel, entry, title, cover_url)

    xml_bytes = tostring(rss, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes


def default_description(title: str) -> str:
    """Return a validator-safe channel description for a title.

    Args:
        title: Podcast channel title.

    Returns:
        Description string exceeding common 50-character minimums.
    """
    return f"{title} — private personal podcast feed, synced from Google Drive"


def _add_channel_metadata(
    channel: Element,
    title: str,
    feed_url: str,
    base_url: str,
    description: str,
    last_build: str,
) -> None:
    """Populate RSS channel-level metadata elements.

    Args:
        channel: The <channel> XML element to populate.
        title: Podcast channel title.
        feed_url: Absolute URL of this feed.
        base_url: Base URL of the application.
        description: Channel description text.
        last_build: Preformatted RFC 2822 build timestamp.
    """
    SubElement(channel, "title").text = title
    SubElement(channel, "link").text = base_url
    SubElement(channel, "description").text = description
    SubElement(channel, "language").text = "en"
    SubElement(channel, "itunes:author").text = title
    SubElement(channel, "itunes:explicit").text = "false"
    SubElement(channel, "itunes:image", {"href": f"{base_url}/cover.png"})
    SubElement(channel, "itunes:category", {"text": _ITUNES_CATEGORY})
    SubElement(channel, "lastBuildDate").text = last_build
    SubElement(
        channel,
        "atom:link",
        {
            "href": feed_url,
            "rel": "self",
            "type": "application/rss+xml",
            "xmlns:atom": "http://www.w3.org/2005/Atom",
        },
    )


def _add_item(
    channel: Element, entry: ManifestEntry, author: str, cover_url: str
) -> None:
    """Append a single <item> element to the channel.

    Args:
        channel: The <channel> XML element to append to.
        entry: ManifestEntry representing the audio episode.
        author: Podcast author name for itunes:author.
        cover_url: Absolute cover art URL for itunes:image.
    """
    item = SubElement(channel, "item")
    SubElement(item, "title").text = entry.name
    SubElement(item, "description").text = entry.name
    SubElement(item, "itunes:author").text = author
    SubElement(item, "itunes:subtitle").text = entry.name
    SubElement(item, "itunes:image", {"href": cover_url})
    SubElement(item, "itunes:explicit").text = "false"
    SubElement(item, "itunes:episodeType").text = "full"
    guid = SubElement(item, "guid", {"isPermaLink": "false"})
    guid.text = entry.drive_file_id
    SubElement(item, "pubDate").text = _iso_to_rfc2822(entry.published_at)
    if entry.duration_sec is not None:
        SubElement(item, "itunes:duration").text = str(entry.duration_sec)
    SubElement(
        item,
        "enclosure",
        {
            "url": entry.blob_url,
            "length": str(entry.size_bytes),
            "type": canonical_mime_type(entry.mime_type),
        },
    )


# ---


def _rfc2822_now() -> str:
    """Return the current UTC time as an RFC 2822 string.

    Returns:
        Current UTC timestamp in RFC 2822 format.
    """
    return formatdate(usegmt=True)


def _iso_to_rfc2822(iso: str) -> str:
    """Convert an ISO 8601 UTC timestamp string to RFC 2822 format.

    Args:
        iso: ISO 8601 timestamp string (e.g. "2026-09-05T12:00:00Z").

    Returns:
        RFC 2822 formatted date string.
    """
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        timestamp = calendar.timegm(dt.utctimetuple())
        return formatdate(timestamp, usegmt=True)
    except ValueError, AttributeError:
        return formatdate(usegmt=True)
