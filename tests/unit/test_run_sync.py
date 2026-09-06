"""Tests for run_sync() end-to-end with stubs."""

from __future__ import annotations

from podcast.drive.client import DriveListError
from podcast.models import DriveFile
from podcast.sync.engine import run_sync
from tests.conftest import InMemoryBlobStore


class _StubDrive:
    """Minimal DriveClient stub with canned listing and streams."""

    def __init__(
        self,
        files: list[DriveFile] | None = None,
        fail_list: bool = False,
        fail_upload_ids: set[str] | None = None,
    ) -> None:
        """Store canned files and failure flags."""
        self._files = files or []
        self._fail_list = fail_list
        self._fail_upload = fail_upload_ids or set()
        self.upload_calls = 0

    def list_audio_files(self) -> list[DriveFile]:
        """Return canned files or raise DriveListError."""
        if self._fail_list:
            raise DriveListError("list failed")
        return list(self._files)

    def stream_file(self, file_id: str):  # type: ignore[no-untyped-def]
        """Yield bytes or raise for flagged ids."""
        if file_id in self._fail_upload:
            raise RuntimeError("upload failed")
        self.upload_calls += 1
        yield b"audio-bytes"


class _StubSettings:
    """Placeholder settings (run_sync keeps it for extensibility)."""

    podcast_title = "Test Cast"


def _drive(fid: str = "id-1", md5: str = "m1") -> DriveFile:
    """Build a DriveFile with overridable id/md5."""
    return DriveFile(
        id=fid,
        name=f"{fid}.mp3",
        mime_type="audio/mpeg",
        size_bytes=10,
        md5=md5,
    )


def test_empty_drive_empty_manifest_returns_zero_counts() -> None:
    """Nothing to do yields all-zero SyncResult."""
    result = run_sync(
        _StubSettings(),
        InMemoryBlobStore(),
        _StubDrive([]),  # type: ignore[arg-type]
    )
    assert (
        result.added,
        result.updated,
        result.deleted,
        result.unchanged,
        result.errors,
    ) == (0, 0, 0, 0, 0)


def test_new_file_is_added_to_manifest() -> None:
    """One drive file with empty manifest is added."""
    store = InMemoryBlobStore()
    result = run_sync(
        _StubSettings(),
        store,
        _StubDrive([_drive()]),  # type: ignore[arg-type]
    )
    assert result.added == 1
    assert [e.drive_file_id for e in store.read_manifest()] == ["id-1"]


def test_deleted_file_is_removed_from_manifest(
    sample_manifest_entry,
) -> None:
    """Manifest entry absent from Drive is deleted."""
    store = InMemoryBlobStore()
    store.write_manifest([sample_manifest_entry])
    result = run_sync(
        _StubSettings(),
        store,
        _StubDrive([]),  # type: ignore[arg-type]
    )
    assert result.deleted == 1
    assert store.read_manifest() == []


def test_changed_file_is_reuploaded_published_at_preserved(
    sample_manifest_entry,
) -> None:
    """Changed md5 re-uploads but keeps published_at."""
    store = InMemoryBlobStore()
    store.write_manifest([sample_manifest_entry])
    changed = DriveFile(
        id="drive-id-1",
        name="ep1.mp3",
        mime_type="audio/mpeg",
        size_bytes=2_000_000,
        md5="different",
    )
    result = run_sync(
        _StubSettings(),
        store,
        _StubDrive([changed]),  # type: ignore[arg-type]
    )
    assert result.updated == 1
    (back,) = store.read_manifest()
    assert back.drive_md5 == "different"
    assert back.published_at == sample_manifest_entry.published_at


def test_unchanged_file_is_not_touched(sample_manifest_entry) -> None:
    """Same md5 performs no upload call."""
    store = InMemoryBlobStore()
    store.write_manifest([sample_manifest_entry])
    drive = _StubDrive(
        [
            DriveFile(
                id="drive-id-1",
                name="ep1.mp3",
                mime_type="audio/mpeg",
                size_bytes=1_000_000,
                md5="abc123",
            )
        ]
    )
    result = run_sync(
        _StubSettings(),
        store,
        drive,  # type: ignore[arg-type]
    )
    assert result.unchanged == 1
    assert drive.upload_calls == 0


def test_drive_list_error_aborts_sync_manifest_untouched(
    sample_manifest_entry,
) -> None:
    """DriveListError propagates and leaves the manifest alone."""
    import pytest

    store = InMemoryBlobStore()
    store.write_manifest([sample_manifest_entry])
    with pytest.raises(DriveListError):
        run_sync(
            _StubSettings(),
            store,
            _StubDrive(fail_list=True),  # type: ignore[arg-type]
        )
    assert store.read_manifest() == [sample_manifest_entry]


def test_upload_failure_increments_errors_continues() -> None:
    """One failed upload counts an error while others succeed."""
    store = InMemoryBlobStore()
    drive = _StubDrive([_drive("bad"), _drive("good")], fail_upload_ids={"bad"})
    result = run_sync(
        _StubSettings(),
        store,
        drive,  # type: ignore[arg-type]
    )
    assert result.errors == 1 and result.added == 1
    assert [e.drive_file_id for e in store.read_manifest()] == ["good"]


def test_manifest_written_incrementally() -> None:
    """Manifest in the store reflects each operation as it happens."""
    store = InMemoryBlobStore()
    seen: list[int] = []
    orig = store.write_manifest
    store.write_manifest = lambda entries: (  # type: ignore[method-assign]
        seen.append(len(entries)),
        orig(entries),
    )
    run_sync(
        _StubSettings(),  # type: ignore[arg-type]
        store,
        _StubDrive([_drive("a"), _drive("b")]),  # type: ignore[arg-type]
    )
    assert seen == [1, 2]


def test_mp3_upload_is_tagged_and_sized() -> None:
    """MP3 uploads gain ID3 tags; manifest records the tagged size."""
    from pathlib import Path

    raw = (
        Path(__file__).parent.parent / "fixtures" / "untagged.mp3"
    ).read_bytes()

    class _Mp3Drive(_StubDrive):
        def stream_file(self, file_id: str):
            yield raw

    store = InMemoryBlobStore()
    result = run_sync(
        _StubSettings(),  # type: ignore[arg-type]
        store,
        _Mp3Drive([_drive("song")]),  # type: ignore[arg-type]
    )
    assert result.added == 1
    (entry,) = store.read_manifest()
    assert entry.size_bytes > len(raw)
    assert entry.size_bytes == len(store._blobs["song.mp3"])
    assert store._blobs["song.mp3"][:3] == b"ID3"
