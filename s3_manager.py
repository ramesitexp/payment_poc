"""Small, reusable S3 operations for the command-line application.

Credentials are deliberately not stored here. Boto3 uses its normal credential
chain, including credentials and profiles created by the AWS CLI.
"""

from pathlib import Path, PurePosixPath
from typing import Any

import boto3
from boto3.exceptions import Boto3Error
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, ProfileNotFound


class S3OperationError(RuntimeError):
    """Readable error raised when an AWS operation cannot be completed."""


class S3Manager:
    """Perform file and object operations against one S3 bucket."""

    def __init__(
        self,
        bucket_name: str = "s3-practice-payment",
        region: str = "us-east-2",
        profile_name: str | None = None,
    ) -> None:
        # A session reads AWS_PROFILE, AWS_SHARED_CREDENTIALS_FILE, environment
        # credentials, and other standard AWS credential-chain sources.
        # Remember the target bucket and region for later API calls.
        self.bucket_name = bucket_name
        self.region = region
        # A profile name selects credentials stored by AWS CLI; None uses Boto3's default chain.
        self.profile_name = profile_name
        # A session creates service clients using standard Boto3 credentials.
        try:
            self.session = boto3.Session(profile_name=profile_name, region_name=region)
        except ProfileNotFound as error:
            # Give a direct hint when --profile names a profile not configured yet.
            raise S3OperationError(
                f"AWS profile {profile_name!r} was not found. Configure it with AWS CLI first."
            ) from error
        # The S3 client performs the bucket and object operations used by this app.
        self.s3 = self.session.client("s3")

    @staticmethod
    def _aws_error(action: str, error: Exception) -> S3OperationError:
        """Convert low-level AWS errors into an actionable message."""
        if isinstance(error, NoCredentialsError):
            # Explain how to sign in without encouraging credentials in source code.
            return S3OperationError(
                f"{action} failed: no AWS credentials found. Sign in with AWS CLI `aws login` "
                "or configure your organization's SSO/profile, then restart the app. "
                "Never paste access keys into this Python file."
            )
        if isinstance(error, ClientError):
            # ClientError includes a structured AWS error code and message.
            detail = error.response.get("Error", {})
            code = detail.get("Code", "Unknown")
            message = detail.get("Message", str(error))
            return S3OperationError(f"{action} failed ({code}): {message}")
        return S3OperationError(f"{action} failed: {error}")

    @staticmethod
    def _validate_key(key: str) -> str:
        """Reject empty object names while preserving valid S3 key characters."""
        if not key or not key.strip():
            raise ValueError("S3 object key cannot be empty.")
        # Return the original key; S3 key names can include spaces and punctuation.
        return key

    def connect(self) -> dict[str, str]:
        """Verify access to the configured S3 bucket without fetching account identity."""
        try:
            # HeadBucket is read-only and confirms the current credentials can reach this bucket.
            self.s3.head_bucket(Bucket=self.bucket_name)
            return {
                "bucket": self.bucket_name,
                "region": self.region,
            }
        except (ClientError, BotoCoreError) as error:
            raise self._aws_error("AWS connection or bucket check", error) from error

    def object_exists(self, key: str) -> bool:
        """Return whether an object exists; surface access and network errors."""
        key = self._validate_key(key)
        try:
            # HEAD reads object metadata only; it does not download the object's body.
            self.s3.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                return False
            raise self._aws_error(f"Checking object {key!r}", error) from error
        except BotoCoreError as error:
            raise self._aws_error(f"Checking object {key!r}", error) from error

    def upload_file(self, file_path: str | Path, key: str) -> dict[str, str]:
        """Upload a local file to the given S3 key (an existing key is replaced)."""
        source = Path(file_path).expanduser()
        key = self._validate_key(key)
        if not source.is_file():
            raise FileNotFoundError(f"Local file does not exist: {source}")
        try:
            # upload_file manages multipart uploads for larger files automatically.
            self.s3.upload_file(str(source), self.bucket_name, key)
            return {"bucket": self.bucket_name, "key": key, "source": str(source)}
        except (ClientError, BotoCoreError, Boto3Error) as error:
            raise self._aws_error(f"Uploading {source}", error) from error

    def list_objects(self, prefix: str = "") -> list[dict[str, Any]]:
        """List every object whose key begins with prefix, handling pagination."""
        try:
            # Ask Boto3 for a paginator so more than one response page is handled.
            paginator = self.s3.get_paginator("list_objects_v2")
            # Accumulate each page's Contents entries into one result list.
            objects: list[dict[str, Any]] = []
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                objects.extend(page.get("Contents", []))
            return objects
        except (ClientError, BotoCoreError) as error:
            raise self._aws_error(f"Listing objects with prefix {prefix!r}", error) from error

    def download_file(self, key: str, destination: str | Path) -> Path:
        """Download an S3 object to a local destination path."""
        key = self._validate_key(key)
        target = Path(destination).expanduser()
        try:
            # Create missing local folders before saving the downloaded file.
            target.parent.mkdir(parents=True, exist_ok=True)
            # download_file streams the object to disk rather than holding it all in memory.
            self.s3.download_file(self.bucket_name, key, str(target))
            return target
        except (ClientError, BotoCoreError, Boto3Error, OSError) as error:
            raise self._aws_error(f"Downloading {key!r}", error) from error

    def delete_object(self, key: str) -> dict[str, Any]:
        """Delete one S3 object. The CLI asks for confirmation before calling this."""
        key = self._validate_key(key)
        try:
            # The response is returned to the caller; callers should confirm first.
            return self.s3.delete_object(Bucket=self.bucket_name, Key=key)
        except (ClientError, BotoCoreError) as error:
            raise self._aws_error(f"Deleting {key!r}", error) from error

    def search_by_prefix(self, prefix: str) -> list[dict[str, Any]]:
        """Find objects whose full S3 keys start with the supplied prefix."""
        if not prefix:
            raise ValueError("Enter a non-empty prefix for search.")
        # S3 lists keys beginning with Prefix; no separate search API is required.
        return self.list_objects(prefix=prefix)

    def batch_upload(
        self, file_paths: list[str | Path], prefix: str = "", overwrite: bool = False
    ) -> list[dict[str, str]]:
        """Upload multiple files, preserving each filename below the S3 prefix."""
        results: list[dict[str, str]] = []
        # Avoid leading/trailing slashes when composing prefix/filename keys.
        clean_prefix = prefix.strip("/")
        for file_path in file_paths:
            source = Path(file_path).expanduser()
            key = f"{clean_prefix}/{source.name}" if clean_prefix else source.name
            try:
                if self.object_exists(key) and not overwrite:
                    results.append({"status": "skipped", "key": key, "message": "Already exists"})
                    continue
                self.upload_file(source, key)
                results.append({"status": "uploaded", "key": key, "message": "Upload complete"})
            except (S3OperationError, OSError, ValueError) as error:
                results.append({"status": "failed", "key": key, "message": str(error)})
        return results

    @staticmethod
    def _safe_batch_target(root: Path, key: str, prefix: str) -> Path:
        """Map an S3 key beneath root and block keys that escape that directory."""
        relative_key = key[len(prefix):].lstrip("/") if prefix and key.startswith(prefix) else key
        # Treat S3's slash-separated key as portable POSIX path components.
        parts = PurePosixPath(relative_key).parts
        if not parts or any(part in {"..", "."} for part in parts):
            raise ValueError(f"Unsafe S3 key cannot be mapped locally: {key}")
        resolved_root = root.resolve()
        target = resolved_root.joinpath(*parts).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError(f"S3 key would write outside the download folder: {key}") from error
        return target

    def batch_download(
        self, prefix: str, destination_dir: str | Path, overwrite: bool = False
    ) -> list[dict[str, str]]:
        """Download all objects under a prefix, preserving their relative paths."""
        root = Path(destination_dir).expanduser()
        # Keep one outcome per item so a failed object doesn't hide successful ones.
        results: list[dict[str, str]] = []
        for item in self.list_objects(prefix=prefix):
            key = item["Key"]
            try:
                target = self._safe_batch_target(root, key, prefix)
                if target.exists() and not overwrite:
                    results.append({"status": "skipped", "key": key, "message": f"Already exists: {target}"})
                    continue
                self.download_file(key, target)
                results.append({"status": "downloaded", "key": key, "message": str(target)})
            except (S3OperationError, OSError, ValueError) as error:
                results.append({"status": "failed", "key": key, "message": str(error)})
        return results

    def batch_delete(self, keys: list[str]) -> list[dict[str, str]]:
        """Delete multiple keys; the CLI confirms the full batch before calling."""
        results: list[dict[str, str]] = []
        # Attempt each already-confirmed key and record failures individually.
        for key in keys:
            try:
                self.delete_object(key)
                results.append({"status": "deleted", "key": key, "message": "Delete request sent"})
            except (S3OperationError, ValueError) as error:
                results.append({"status": "failed", "key": key, "message": str(error)})
        return results
