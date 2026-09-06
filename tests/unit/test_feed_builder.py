"""Tests for build_rss_xml() and helpers — pure."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from podcast.feed.builder import _iso_to_rfc2822, build_rss_xml
from podcast.models import ManifestEntry


def _entry(
    fid: str = "drive-id-1",
    published_at: str = "2026-09-05T12:00:00Z",
    name: str = "Episode 1.mp3",
) -> ManifestEntry:
    """Build a ManifestEntry with overridable fields."""
    return ManifestEntry(
        drive_file_id=fid,
        drive_md5="md5",
        blob_url=f"https://blob.test/{fid}.mp3",
        name=name,
        size_bytes=45678901,
        mime_type="audio/mpeg",
        published_at=published_at,
    )


def test_empty_entries_produces_valid_rss() -> None:
    """No items still yields a parseable channel with no items."""
    xml = build_rss_xml([], "T", "https://f/feed", "https://base")
    root = ET.fromstring(xml)
    assert root.tag == "rss"
    assert root.find("channel") is not None
    assert root.findall(".//item") == []


def test_single_entry_produces_one_item() -> None:
    """One entry yields exactly one item element."""
    xml = build_rss_xml([_entry()], "T", "https://f/feed", "https://base")
    assert len(ET.fromstring(xml).findall(".//item")) == 1


def test_enclosure_attributes_are_correct() -> None:
    """Enclosure url, length, and type mirror the entry."""
    xml = build_rss_xml([_entry()], "T", "https://f/feed", "https://base")
    enc = ET.fromstring(xml).find(".//enclosure")
    assert enc is not None
    assert enc.get("url") == "https://blob.test/drive-id-1.mp3"
    assert enc.get("length") == "45678901"
    assert enc.get("type") == "audio/mpeg"


def test_guid_is_drive_file_id_not_permalink() -> None:
    """Guid text is the Drive id with isPermaLink false."""
    xml = build_rss_xml([_entry()], "T", "https://f/feed", "https://base")
    guid = ET.fromstring(xml).find(".//guid")
    assert guid is not None
    assert guid.text == "drive-id-1"
    assert guid.get("isPermaLink") == "false"


def test_items_sorted_newest_first() -> None:
    """Newer published_at appears before older in the XML."""
    old = _entry("old", "2026-09-04T12:00:00Z")
    new = _entry("new", "2026-09-05T12:00:00Z")
    xml = build_rss_xml([old, new], "T", "https://f/feed", "https://base")
    guids = [g.text for g in ET.fromstring(xml).findall(".//guid")]
    assert guids == ["new", "old"]


def test_channel_title_matches_argument() -> None:
    """Channel title element matches the title argument."""
    xml = build_rss_xml([], "My Podcasts", "https://f/feed", "https://base")
    title = ET.fromstring(xml).find("channel/title")
    assert title is not None and title.text == "My Podcasts"


def test_channel_link_matches_base_url() -> None:
    """Channel link element matches the base_url argument."""
    xml = build_rss_xml([], "T", "https://f/feed", "https://mybase.test")
    link = ET.fromstring(xml).find("channel/link")
    assert link is not None and link.text == "https://mybase.test"


def test_itunes_namespace_is_declared() -> None:
    """Root rss element declares the itunes namespace."""
    xml = build_rss_xml([], "T", "https://f/feed", "https://base")
    assert "xmlns:itunes" in xml


def test_xml_declaration_present() -> None:
    """Output starts with an XML declaration."""
    xml = build_rss_xml([], "T", "https://f/feed", "https://base")
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')


def test_iso_to_rfc2822_valid_timestamp() -> None:
    """Valid ISO timestamp converts to RFC 2822 containing Sep 2026."""
    out = _iso_to_rfc2822("2026-09-05T12:00:00Z")
    assert "Sep 2026" in out


def test_iso_to_rfc2822_invalid_falls_back_gracefully() -> None:
    """Garbage input returns a non-empty string without raising."""
    out = _iso_to_rfc2822("not-a-date")
    assert isinstance(out, str) and len(out) > 0


def test_iso_to_rfc2822_z_suffix_handled() -> None:
    """Z suffix is parsed as UTC."""
    out = _iso_to_rfc2822("2026-09-05T12:00:00Z")
    assert "05 Sep 2026 12:00:00" in out
