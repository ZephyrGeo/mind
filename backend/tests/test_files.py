from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from backend.file_service import FileService, FileValidationError
from backend.file_storage import GCSFileStorage, LocalFileStorage
from backend.file_store import AttachmentNotFoundError, JsonAttachmentRepository


def _text_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode())
        payload.extend(value)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(payload)


class FileServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.repository = JsonAttachmentRepository(root / "attachments.json")
        self.storage = LocalFileStorage(root / "files")
        self.service = FileService(
            repository=self.repository,
            storage=self.storage,
            max_file_bytes=1_000,
            max_extracted_characters=500,
            max_context_characters=220,
            max_files_per_request=2,
        )

    def test_txt_upload_builds_bounded_context_and_deletes_private_bytes(self) -> None:
        summary = self.service.upload(
            user_id="user-a",
            name="notes.txt",
            media_type="text/plain; charset=utf-8",
            content=("Private project context. " * 20).encode(),
        )

        self.assertEqual(summary.status.value, "ready")
        self.assertNotIn("storage_uri", summary.model_dump())
        file_ids, context = self.service.context_for_ids(
            "user-a",
            [summary.id],
        )
        self.assertEqual(file_ids, [summary.id])
        self.assertIn("notes.txt", context)
        self.assertIn("untrusted reference data", context)
        self.assertLessEqual(len(context), 270)

        attachment = self.repository.get_attachment(summary.id, "user-a")
        stored_path = Path(attachment.storage_uri.removeprefix("file://"))
        self.assertTrue(stored_path.exists())
        with self.assertRaises(AttachmentNotFoundError):
            self.repository.get_attachment(summary.id, "user-b")

        self.service.delete(summary.id, "user-a")
        self.assertFalse(stored_path.exists())
        with self.assertRaises(AttachmentNotFoundError):
            self.repository.get_attachment(summary.id, "user-a")

    def test_rejects_spoofed_unsupported_oversized_and_non_utf8_files(self) -> None:
        cases = [
            ("../notes.txt", "text/plain", b"safe", "invalid_file_name"),
            ("notes.md", "text/plain", b"safe", "file_type_unsupported"),
            ("notes.txt", "text/plain", b"%PDF-not-text", "file_type_mismatch"),
            ("notes.pdf", "application/pdf", b"not-pdf", "file_type_mismatch"),
            ("notes.txt", "text/plain", b"x" * 1_001, "file_too_large"),
            ("notes.txt", "text/plain", b"\xff\xfe", "file_encoding_unsupported"),
        ]
        for name, media_type, content, code in cases:
            with self.subTest(code=code), self.assertRaises(FileValidationError) as raised:
                self.service.upload(
                    user_id="user-a",
                    name=name,
                    media_type=media_type,
                    content=content,
                )
            self.assertEqual(raised.exception.code, code)

    def test_context_rejects_unknown_ids_and_request_limit(self) -> None:
        with self.assertRaises(AttachmentNotFoundError):
            self.service.context_for_ids("user-a", [UUID(int=1)])
        with self.assertRaises(FileValidationError) as raised:
            self.service.context_for_ids(
                "user-a",
                [UUID(int=1), UUID(int=2), UUID(int=3)],
            )
        self.assertEqual(raised.exception.code, "too_many_files")

    def test_pdf_upload_extracts_real_page_text(self) -> None:
        summary = self.service.upload(
            user_id="user-a",
            name="brief.pdf",
            media_type="application/pdf",
            content=_text_pdf("PDF private context"),
        )
        attachment = self.repository.get_attachment(summary.id, "user-a")
        self.assertIn("PDF private context", attachment.extracted_text)

    def test_delete_decodes_unicode_spaces_and_url_characters(self) -> None:
        summary = self.service.upload(
            user_id="user-a",
            name="2026 履歴書 #1.txt",
            media_type="text/plain",
            content=b"Private profile",
        )
        attachment = self.repository.get_attachment(summary.id, "user-a")
        self.assertIn("%20", attachment.storage_uri)
        self.assertIn("%23", attachment.storage_uri)
        stored_path = next((self.storage.root).rglob("2026 履歴書 #1.txt"))
        self.assertTrue(stored_path.exists())

        self.service.delete(summary.id, "user-a")

        self.assertFalse(stored_path.exists())
        with self.assertRaises(AttachmentNotFoundError):
            self.repository.get_attachment(summary.id, "user-a")


class _FakeBlob:
    def __init__(self, name: str) -> None:
        self.name = name
        self.content = b""
        self.content_type = ""
        self.deleted = False

    def upload_from_string(
        self,
        content: bytes,
        *,
        content_type: str,
        if_generation_match: int,
    ) -> None:
        if if_generation_match != 0:
            raise AssertionError("Uploads must reject accidental overwrites.")
        self.content = content
        self.content_type = content_type

    def delete(self) -> None:
        self.deleted = True


class _FakeBucket:
    def __init__(self) -> None:
        self.blobs: dict[str, _FakeBlob] = {}

    def blob(self, name: str) -> _FakeBlob:
        return self.blobs.setdefault(name, _FakeBlob(name))


class _FakeStorageClient:
    def __init__(self) -> None:
        self.bucket_value = _FakeBucket()
        self.list_prefixes: list[str] = []

    def bucket(self, _name: str) -> _FakeBucket:
        return self.bucket_value

    def list_blobs(self, _bucket_name: str, *, prefix: str) -> list[_FakeBlob]:
        self.list_prefixes.append(prefix)
        return [
            blob
            for name, blob in self.bucket_value.blobs.items()
            if name.startswith(prefix)
        ]


class GCSFileStorageTest(unittest.TestCase):
    def test_uses_private_hashed_tenant_paths_and_scoped_cleanup(self) -> None:
        client = _FakeStorageClient()
        storage = GCSFileStorage(bucket_name="private-files", client=client)
        attachment_id = UUID(int=42)

        uri = storage.put(
            user_id="user@example.com",
            attachment_id=attachment_id,
            name="brief.txt",
            media_type="text/plain",
            content=b"private",
        )

        self.assertTrue(uri.startswith("gs://private-files/users/"))
        self.assertNotIn("user@example.com", uri)
        self.assertNotIn("https://", uri)
        object_name = uri.removeprefix("gs://private-files/")
        self.assertEqual(client.bucket_value.blobs[object_name].content, b"private")

        storage.delete_for_user("user@example.com")
        self.assertTrue(client.bucket_value.blobs[object_name].deleted)
        self.assertEqual(len(client.list_prefixes), 1)
        self.assertNotIn("user@example.com", client.list_prefixes[0])


if __name__ == "__main__":
    unittest.main()
