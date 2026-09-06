"""RSS 2.0 feed builder — pure function, no I/O."""

from __future__ import annotations

import calendar
from datetime import datetime
from email.utils import formatdate
from xml.etree.ElementTree import Element, SubElement, tostring

from podcast.models import ManifestEntry

__all__ = ["build_rss_xml"]

_ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


def build_rss_xml(
    entries: list[ManifestEntry],
    title: str,
    feed_url: str,
    base_url: str,
) -> str:
    """Build an RSS 2.0 feed XML string from manifest entries.

    Entries are sorted newest-first by published_at. The result is a valid
    RSS 2.0 document with itunes: namespace elements for Garmin compatibility.

    Args:
        entries: Manifest entries representing synced audio files.
        title: Podcast channel title.
        feed_url: Absolute URL of this feed (used as channel link and self).
        base_url: Base URL of the application.

    Returns:
        UTF-8 encoded RSS 2.0 XML document as a string.
    """
    rss = Element("rss", {"version": "2.0", "xmlns:itunes": _ITUNES_NS})
    channel = SubElement(rss, "channel")

    _add_channel_metadata(channel, title, feed_url, base_url)

    sorted_entries = sorted(
        entries,
        key=lambda e: e.published_at,
        reverse=True,
    )
    for entry in sorted_entries:
        _add_item(channel, entry)

    xml_bytes = tostring(rss, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes


def _add_channel_metadata(
    channel: Element,
    title: str,
    feed_url: str,
    base_url: str,
) -> None:
    """Populate RSS channel-level metadata elements.

    Args:
        channel: The <channel> XML element to populate.
        title: Podcast channel title.
        feed_url: Absolute URL of this feed.
        base_url: Base URL of the application.
    """
    SubElement(channel, "title").text = title
    SubElement(channel, "link").text = base_url
    SubElement(channel, "description").text = title
    SubElement(channel, "language").text = "en"
    SubElement(channel, "lastBuildDate").text = _rfc2822_now()
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


def _add_item(channel: Element, entry: ManifestEntry) -> None:
    """Append a single <item> element to the channel.

    Args:
        channel: The <channel> XML element to append to.
        entry: ManifestEntry representing the audio episode.
    """
    item = SubElement(channel, "item")
    SubElement(item, "title").text = entry.name
    guid = SubElement(item, "guid", {"isPermaLink": "false"})
    guid.text = entry.drive_file_id
    SubElement(item, "pubDate").text = _iso_to_rfc2822(entry.published_at)
    SubElement(
        item,
        "enclosure",
        {
            "url": entry.blob_url,
            "length": str(entry.size_bytes),
            "type": entry.mime_type,
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
