"""Offline tests for direct Boto3 resource helpers and CLI safety."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from botocore.exceptions import ClientError

import main


def client_error(code: str, status: int) -> ClientError:
    """Build an AWS-style error response for offline tests."""
    return ClientError(
        {
            "Error": {"Code": code, "Message": "mock failure"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "UnitTest",
    )


class TestS3Helpers(unittest.TestCase):
    """Exercise object helpers using mocks rather than AWS credentials/network."""

    def setUp(self) -> None:
        self.s3 = MagicMock()
        self.bucket = MagicMock()
        self.bucket.name = "s3-practice-payment"

    def test_connect_uses_bucket_resource(self) -> None:
        main.connect(self.bucket)
        self.bucket.load.assert_called_once_with()

    def test_connect_turns_403_into_readable_error(self) -> None:
        self.bucket.load.side_effect = client_error("403", 403)
        with self.assertRaisesRegex(main.S3Error, "403"):
            main.connect(self.bucket)

    def test_object_exists_true_and_not_found(self) -> None:
        obj = self.s3.Object.return_value
        self.assertTrue(main.object_exists(self.s3, self.bucket.name, "a.txt"))
        obj.load.side_effect = client_error("404", 404)
        self.assertFalse(main.object_exists(self.s3, self.bucket.name, "missing.txt"))

    def test_object_exists_propagates_access_denied_as_s3_error(self) -> None:
        self.s3.Object.return_value.load.side_effect = client_error("403", 403)
        with self.assertRaisesRegex(main.S3Error, "403"):
            main.object_exists(self.s3, self.bucket.name, "private.txt")

    def test_blank_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            main.object_exists(self.s3, self.bucket.name, " ")

    def test_upload_requires_local_file_and_uses_bucket_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "sample.txt"
            source.write_text("example", encoding="utf-8")
            result = main.upload_file(self.bucket, source, "folder/sample.txt")
            self.assertEqual(result["key"], "folder/sample.txt")
            self.bucket.upload_file.assert_called_once_with(str(source), "folder/sample.txt")
            with self.assertRaises(FileNotFoundError):
                main.upload_file(self.bucket, Path(temp_dir) / "missing.txt", "missing.txt")

    def test_list_objects_converts_resource_objects_to_display_rows(self) -> None:
        self.bucket.objects.filter.return_value = [
            Mock(key="folder/a.txt", size=4, last_modified="date-a"),
            Mock(key="folder/b.txt", size=8, last_modified="date-b"),
        ]
        rows = main.list_objects(self.bucket, "folder/")
        self.assertEqual(rows[0], {"Key": "folder/a.txt", "Size": 4, "LastModified": "date-a"})
        self.assertEqual(len(rows), 2)
        self.bucket.objects.filter.assert_called_once_with(Prefix="folder/")

    def test_download_creates_parent_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "child" / "file.txt"
            result = main.download_file(self.bucket, "file.txt", destination)
            self.assertEqual(result, destination)
            self.assertTrue(destination.parent.is_dir())
            self.bucket.download_file.assert_called_once_with("file.txt", str(destination))

    def test_delete_uses_object_resource(self) -> None:
        response = {"ResponseMetadata": {"HTTPStatusCode": 204}}
        self.s3.Object.return_value.delete.return_value = response
        self.assertEqual(main.delete_object(self.s3, self.bucket.name, "file.txt"), response)
        self.s3.Object.assert_called_once_with(self.bucket.name, "file.txt")

    def test_empty_search_prefix_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty prefix"):
            main.search_by_prefix(self.bucket, "")

    def test_batch_upload_skips_existing_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "existing.txt"
            file_path.write_text("data", encoding="utf-8")
            with patch("main.object_exists", return_value=True), patch("main.upload_file") as upload:
                results = main.batch_upload(self.s3, self.bucket, [file_path], "batch/")
            self.assertEqual(results[0]["status"], "skipped")
            upload.assert_not_called()

    def test_batch_upload_reports_a_failure_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "one.txt"
            second = Path(temp_dir) / "two.txt"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            with patch("main.object_exists", return_value=False), patch(
                "main.upload_file", side_effect=[main.S3Error("failed"), {}]
            ):
                results = main.batch_upload(self.s3, self.bucket, [first, second])
            self.assertEqual([item["status"] for item in results], ["failed", "uploaded"])

    def test_safe_download_path_blocks_parent_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "Unsafe S3 key"):
                main.safe_download_path(Path(temp_dir), "../outside.txt", "")

    def test_batch_delete_continues_after_failure(self) -> None:
        with patch("main.delete_object", side_effect=[main.S3Error("denied"), {}]):
            results = main.batch_delete(self.s3, self.bucket.name, ["one.txt", "two.txt"])
        self.assertEqual([item["status"] for item in results], ["failed", "deleted"])


class TestMenuSafety(unittest.TestCase):
    """Ensure destructive menu operations require explicit confirmation."""

    def test_delete_declined_does_not_call_aws(self) -> None:
        s3, bucket = Mock(), Mock()
        with patch("builtins.input", side_effect=["6", "x.txt", "n", "0"]), redirect_stdout(io.StringIO()):
            main.run_menu(s3, bucket)
        s3.Object.return_value.delete.assert_not_called()

    def test_end_of_input_exits_without_traceback(self) -> None:
        output = io.StringIO()
        with patch("builtins.input", side_effect=EOFError), redirect_stdout(output):
            main.run_menu(Mock(), Mock())
        self.assertIn("Input ended. Exiting", output.getvalue())


if __name__ == "__main__":
    unittest.main()
