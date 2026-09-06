"""Tests for compute_diff() — pure, critical business logic."""

from __future__ import annotations

from podcast.models import DriveFile, ManifestEntry
from podcast.sync.engine import compute_diff


def _drive(
    fid: str = "id-1", md5: str = "md5-1", name: str = "ep.mp3"
) -> DriveFile:
    """Build a DriveFile with overridable id/md5."""
    return DriveFile(
        id=fid,
        name=name,
        mime_type="audio/mpeg",
        size_bytes=100,
        md5=md5,
    )


def _entry(fid: str = "id-1", md5: str = "md5-1") -> ManifestEntry:
    """Build a ManifestEntry with overridable id/md5."""
    return ManifestEntry(
        drive_file_id=fid,
        drive_md5=md5,
        blob_url=f"https://blob.test/{fid}",
        name=f"{fid}.mp3",
        size_bytes=100,
        mime_type="audio/mpeg",
        published_at="2026-09-05T12:00:00Z",
    )


def test_empty_drive_empty_manifest_no_changes() -> None:
    """Empty inputs produce empty diff and zero unchanged."""
    to_add, to_update, to_delete, unchanged = compute_diff([], [])
    assert to_add == [] and to_update == [] and to_delete == []
    assert unchanged == 0


def test_new_drive_file_appears_in_to_add() -> None:
    """Drive file absent from manifest lands in to_add."""
    to_add, _, _, _ = compute_diff([_drive()], [])
    assert [f.id for f in to_add] == ["id-1"]


def test_manifest_entry_not_in_drive_appears_in_to_delete() -> None:
    """Manifest entry absent from Drive lands in to_delete."""
    _, _, to_delete, _ = compute_diff([], [_entry()])
    assert [e.drive_file_id for e in to_delete] == ["id-1"]


def test_same_file_same_md5_counts_as_unchanged() -> None:
    """Same id and md5 counts as unchanged."""
    _, to_update, to_delete, unchanged = compute_diff([_drive()], [_entry()])
    assert to_update == [] and to_delete == [] and unchanged == 1


def test_same_file_different_md5_appears_in_to_update() -> None:
    """Same id with different md5 lands in to_update."""
    drive = _drive(md5="new")
    _, to_update, _, unchanged = compute_diff([drive], [_entry(md5="old")])
    assert len(to_update) == 1
    assert to_update[0][0] == drive
    assert unchanged == 0


def test_mixed_state_all_categories_at_once() -> None:
    """One add, one delete, one update, one unchanged together."""
    drive = [_drive("add"), _drive("upd", "new"), _drive("same")]
    manifest = [_entry("upd", "old"), _entry("del"), _entry("same")]
    to_add, to_update, to_delete, unchanged = compute_diff(drive, manifest)
    assert [f.id for f in to_add] == ["add"]
    assert [f.id for f, _ in to_update] == ["upd"]
    assert [e.drive_file_id for e in to_delete] == ["del"]
    assert unchanged == 1


def test_published_at_preserved_in_update() -> None:
    """to_update pairs carry the original ManifestEntry."""
    old = _entry()
    _, to_update, _, _ = compute_diff([_drive(md5="new")], [old])
    assert to_update[0][1] == old
    assert to_update[0][1].published_at == "2026-09-05T12:00:00Z"


def test_multiple_files_all_new() -> None:
    """Three drive files with empty manifest all land in to_add."""
    drive = [_drive(f"id-{i}") for i in range(3)]
    to_add, _, _, _ = compute_diff(drive, [])
    assert len(to_add) == 3


def test_multiple_files_all_deleted() -> None:
    """Empty drive with three manifest entries deletes all."""
    manifest = [_entry(f"id-{i}") for i in range(3)]
    _, _, to_delete, _ = compute_diff([], manifest)
    assert len(to_delete) == 3


def test_unchanged_count_is_accurate() -> None:
    """Five unchanged plus one update counts unchanged as five."""
    drive = [_drive(f"id-{i}") for i in range(5)] + [_drive("u", "new")]
    manifest = [_entry(f"id-{i}") for i in range(5)] + [_entry("u", "old")]
    _, to_update, _, unchanged = compute_diff(drive, manifest)
    assert unchanged == 5 and len(to_update) == 1
