"""Offline unit tests for S3Manager; all AWS clients are mocked."""

from pathlib import Path
from contextlib import redirect_stdout
import io
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import ClientError, NoCredentialsError

from s3_manager import S3Manager, S3OperationError
from main import run_menu


BUCKET = "s3-practice-payment"
REGION = "us-east-2"


def make_client_error(code: str, status: int, message: str = "test error") -> ClientError:
    """Create a realistic botocore error without making a network request."""
    response = {
        "Error": {"Code": code, "Message": message},
        "ResponseMetadata": {"HTTPStatusCode": status},
    }
    return ClientError(response, "UnitTest")


class TestS3Manager(unittest.TestCase):
    """Cover successful paths, expected failures, and batch outcomes offline."""

    def setUp(self) -> None:
        # Bypass boto3.Session so every test is guaranteed to avoid AWS/network access.
        self.manager = object.__new__(S3Manager)
        self.manager.bucket_name = BUCKET
        self.manager.region = REGION
        self.manager.profile_name = None
        self.manager.session = None
        self.manager.s3 = MagicMock()

    def test_connect_checks_bucket_without_identity_lookup(self) -> None:
        result = self.manager.connect()

        self.assertEqual(result["bucket"], BUCKET)
        self.assertEqual(result["region"], REGION)
        self.manager.s3.head_bucket.assert_called_once_with(Bucket=BUCKET)

    def test_connect_converts_aws_error(self) -> None:
        self.manager.s3.head_bucket.side_effect = make_client_error("AccessDenied", 403)

        with self.assertRaisesRegex(S3OperationError, "AccessDenied"):
            self.manager.connect()

    def test_missing_credentials_error_gives_secure_login_guidance(self) -> None:
        error = S3Manager._aws_error("Connecting", NoCredentialsError())

        self.assertIn("aws login", str(error))
        self.assertIn("Never paste access keys", str(error))

    def test_object_exists_true_and_missing(self) -> None:
        self.manager.s3.head_object.return_value = {"ContentLength": 10}
        self.assertTrue(self.manager.object_exists("folder/file.txt"))

        self.manager.s3.head_object.side_effect = make_client_error("404", 404, "missing")
        self.assertFalse(self.manager.object_exists("folder/missing.txt"))

    def test_object_exists_does_not_hide_access_denied(self) -> None:
        self.manager.s3.head_object.side_effect = make_client_error("403", 403, "denied")

        with self.assertRaisesRegex(S3OperationError, "403"):
            self.manager.object_exists("private/file.txt")

    def test_empty_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            self.manager.object_exists("   ")

    def test_upload_success_and_missing_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "sample.txt"
            source.write_text("sample", encoding="utf-8")

            result = self.manager.upload_file(source, "incoming/sample.txt")

            self.assertEqual(result["key"], "incoming/sample.txt")
            self.manager.s3.upload_file.assert_called_once_with(str(source), BUCKET, "incoming/sample.txt")
            with self.assertRaises(FileNotFoundError):
                self.manager.upload_file(Path(temp_dir) / "absent.txt", "absent.txt")

    def test_upload_transfer_error_is_converted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "sample.txt"
            source.write_text("sample", encoding="utf-8")
            self.manager.s3.upload_file.side_effect = S3UploadFailedError("transfer failed")

            with self.assertRaisesRegex(S3OperationError, "transfer failed"):
                self.manager.upload_file(source, "sample.txt")

    def test_list_objects_combines_paginated_results(self) -> None:
        first = {"Key": "incoming/a.txt", "Size": 1}
        second = {"Key": "incoming/b.txt", "Size": 2}
        paginator = self.manager.s3.get_paginator.return_value
        paginator.paginate.return_value = [{"Contents": [first]}, {"Contents": [second]}]

        result = self.manager.list_objects(prefix="incoming/")

        self.assertEqual(result, [first, second])
        paginator.paginate.assert_called_once_with(Bucket=BUCKET, Prefix="incoming/")

    def test_list_objects_handles_empty_bucket_page(self) -> None:
        self.manager.s3.get_paginator.return_value.paginate.return_value = [{}]
        self.assertEqual(self.manager.list_objects(), [])

    def test_download_creates_parent_folder_and_returns_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "new-folder" / "sample.txt"

            result = self.manager.download_file("incoming/sample.txt", target)

            self.assertEqual(result, target)
            self.assertTrue(target.parent.is_dir())
            self.manager.s3.download_file.assert_called_once_with(BUCKET, "incoming/sample.txt", str(target))

    def test_delete_returns_s3_response(self) -> None:
        response = {"ResponseMetadata": {"HTTPStatusCode": 204}}
        self.manager.s3.delete_object.return_value = response

        self.assertEqual(self.manager.delete_object("incoming/sample.txt"), response)
        self.manager.s3.delete_object.assert_called_once_with(Bucket=BUCKET, Key="incoming/sample.txt")

    def test_prefix_search_rejects_empty_prefix(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty prefix"):
            self.manager.search_by_prefix("")

    def test_batch_upload_skips_existing_and_uploads_new(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            existing_file = Path(temp_dir) / "existing.txt"
            new_file = Path(temp_dir) / "new.txt"
            existing_file.write_text("old", encoding="utf-8")
            new_file.write_text("new", encoding="utf-8")
            self.manager.object_exists = Mock(side_effect=lambda key: key.endswith("existing.txt"))
            self.manager.upload_file = Mock()

            results = self.manager.batch_upload([existing_file, new_file], "incoming")

            self.assertEqual([item["status"] for item in results], ["skipped", "uploaded"])
            self.manager.upload_file.assert_called_once_with(new_file, "incoming/new.txt")

    def test_batch_upload_can_overwrite_existing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "existing.txt"
            source.write_text("new", encoding="utf-8")
            self.manager.object_exists = Mock(return_value=True)
            self.manager.upload_file = Mock()

            results = self.manager.batch_upload([source], "incoming", overwrite=True)

            self.assertEqual(results[0]["status"], "uploaded")
            self.manager.upload_file.assert_called_once_with(source, "incoming/existing.txt")

    def test_batch_upload_records_each_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "bad.txt"
            source.write_text("data", encoding="utf-8")
            self.manager.object_exists = Mock(return_value=False)
            self.manager.upload_file = Mock(side_effect=S3OperationError("upload failed"))

            results = self.manager.batch_upload([source])

            self.assertEqual(results[0]["status"], "failed")
            self.assertIn("upload failed", results[0]["message"])

    def test_batch_download_downloads_and_reports_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.manager.list_objects = Mock(return_value=[
                {"Key": "incoming/good.txt"},
                {"Key": "incoming/bad.txt"},
            ])
            self.manager.download_file = Mock(side_effect=[None, S3OperationError("download failed")])

            results = self.manager.batch_download("incoming/", temp_dir)

            self.assertEqual([item["status"] for item in results], ["downloaded", "failed"])
            self.assertIn("download failed", results[1]["message"])

    def test_batch_download_skips_existing_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "existing.txt"
            target.write_text("keep", encoding="utf-8")
            self.manager.list_objects = Mock(return_value=[{"Key": "incoming/existing.txt"}])
            self.manager.download_file = Mock()

            results = self.manager.batch_download("incoming/", temp_dir, overwrite=False)

            self.assertEqual(results[0]["status"], "skipped")
            self.manager.download_file.assert_not_called()

    def test_batch_download_blocks_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "Unsafe S3 key"):
                S3Manager._safe_batch_target(Path(temp_dir), "../outside.txt", "")

    def test_batch_delete_records_success_and_failure(self) -> None:
        self.manager.delete_object = Mock(side_effect=[{}, S3OperationError("delete failed")])

        results = self.manager.batch_delete(["one.txt", "two.txt"])

        self.assertEqual([item["status"] for item in results], ["deleted", "failed"])
        self.assertIn("delete failed", results[1]["message"])


class TestMenuSafety(unittest.TestCase):
    """Confirm the interactive CLI does not run destructive actions without approval."""

    def test_single_delete_cancelled_by_default_no(self) -> None:
        manager = Mock()
        user_inputs = ["6", "incoming/file.txt", "n", "0"]

        with patch("builtins.input", side_effect=user_inputs), redirect_stdout(io.StringIO()):
            run_menu(manager)

        manager.delete_object.assert_not_called()

    def test_single_delete_runs_after_explicit_yes(self) -> None:
        manager = Mock()
        user_inputs = ["6", "incoming/file.txt", "yes", "0"]

        with patch("builtins.input", side_effect=user_inputs), redirect_stdout(io.StringIO()):
            run_menu(manager)

        manager.delete_object.assert_called_once_with("incoming/file.txt")

    def test_batch_delete_cancelled_before_delete_calls(self) -> None:
        manager = Mock()
        manager.list_objects.return_value = [{"Key": "temporary/file.txt"}]
        user_inputs = ["10", "temporary/", "n", "0"]

        with patch("builtins.input", side_effect=user_inputs), redirect_stdout(io.StringIO()):
            run_menu(manager)

        manager.batch_delete.assert_not_called()

    def test_existing_upload_cancelled_without_replacement(self) -> None:
        manager = Mock()
        manager.object_exists.return_value = True
        user_inputs = ["2", "C:/files/file.txt", "incoming/file.txt", "n", "0"]

        with patch("builtins.input", side_effect=user_inputs), redirect_stdout(io.StringIO()):
            run_menu(manager)

        manager.upload_file.assert_not_called()

    def test_end_of_input_exits_without_traceback(self) -> None:
        manager = Mock()
        output = io.StringIO()

        with patch("builtins.input", side_effect=EOFError), redirect_stdout(output):
            run_menu(manager)

        self.assertIn("Input ended. Exiting", output.getvalue())
        manager.connect.assert_not_called()
        manager.delete_object.assert_not_called()

if __name__ == "__main__":
    unittest.main()
