"""Menu-based Amazon S3 file manager using Boto3's S3 resource directly.

Run: python main.py --profile PROFILE_NAME
Credentials come from the normal AWS CLI/Boto3 credential chain, never source code.
"""

import argparse
from pathlib import Path
from typing import Any

import boto3
from boto3.exceptions import Boto3Error
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, ProfileNotFound


BUCKET_NAME = "s3-practice-payment"
REGION = "us-east-2"

MENU = """
================ S3 File Manager ================
1. Create (upload) an object
2. Read (list) objects
3. Read (download) an object
4. Update (replace) an object
5. Delete an object
0. Exit
==================================================
"""


class S3Error(RuntimeError):
    """User-readable error for S3 operations."""


def aws_error(action: str, error: Exception) -> S3Error:
    """Turn AWS and credential errors into a short actionable message."""
    if isinstance(error, NoCredentialsError):
        return S3Error(
            f"{action} failed: no AWS credentials found. Sign in with AWS CLI or choose a configured profile. "
            "Never put access keys in this file."
        )
    if isinstance(error, ClientError):
        details = error.response.get("Error", {})
        return S3Error(
            f"{action} failed ({details.get('Code', 'Unknown')}): "
            f"{details.get('Message', str(error))}"
        )
    return S3Error(f"{action} failed: {error}")


def connect(bucket: Any) -> None:
    """Use the S3 bucket resource to make a read-only bucket access check."""
    try:
        bucket.load()
    except (ClientError, BotoCoreError) as error:
        raise aws_error("S3 bucket check", error) from error


def object_exists(s3: Any, bucket_name: str, key: str) -> bool:
    """Check object metadata; a 404 means absent, other errors are not hidden."""
    validate_key(key)
    try:
        s3.Object(bucket_name, key).load()
        return True
    except ClientError as error:
        # Only a not-found response means the key is absent; permission failures must surface.
        code = error.response.get("Error", {}).get("Code", "")
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return False
        raise aws_error(f"Checking {key!r}", error) from error
    except BotoCoreError as error:
        raise aws_error(f"Checking {key!r}", error) from error


def validate_key(key: str) -> str:
    """Reject blank keys before sending a request to AWS."""
    if not key or not key.strip():
        raise ValueError("S3 object key cannot be empty.")
    return key


def upload_file(bucket: Any, file_path: str | Path, key: str) -> dict[str, str]:
    """Upload one local file with the bucket resource's transfer helper."""
    source = Path(file_path).expanduser()
    key = validate_key(key)
    if not source.is_file():
        raise FileNotFoundError(f"Local file does not exist: {source}")
    try:
        # Boto3 manages multipart transfers automatically for large files.
        bucket.upload_file(str(source), key)
        return {"bucket": bucket.name, "key": key, "source": str(source)}
    except (ClientError, BotoCoreError, Boto3Error) as error:
        raise aws_error(f"Uploading {source}", error) from error


def list_objects(bucket: Any, prefix: str = "") -> list[dict[str, Any]]:
    """List objects by prefix; the Boto3 collection handles pagination."""
    try:
        # Convert each resource object to a small dictionary used by the CLI.
        return [
            {"Key": item.key, "Size": item.size, "LastModified": item.last_modified}
            for item in bucket.objects.filter(Prefix=prefix)
        ]
    except (ClientError, BotoCoreError) as error:
        raise aws_error(f"Listing prefix {prefix!r}", error) from error


def download_file(bucket: Any, key: str, destination: str | Path) -> Path:
    """Download one object to disk using the bucket resource."""
    key = validate_key(key)
    target = Path(destination).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        bucket.download_file(key, str(target))
        return target
    except (ClientError, BotoCoreError, Boto3Error, OSError) as error:
        raise aws_error(f"Downloading {key!r}", error) from error


def delete_object(s3: Any, bucket_name: str, key: str) -> dict[str, Any]:
    """Delete an object by key; the menu asks for confirmation before this call."""
    key = validate_key(key)
    try:
        return s3.Object(bucket_name, key).delete()
    except (ClientError, BotoCoreError) as error:
        raise aws_error(f"Deleting {key!r}", error) from error


def ask_yes_no(question: str) -> bool:
    """Only explicit y/yes approves an action; the default answer is no."""
    return input(f"{question} [y/N]: ").strip().lower() in {"y", "yes"}


def show_objects(objects: list[dict[str, Any]]) -> None:
    """Print object keys and metadata, never the downloaded file contents."""
    if not objects:
        print("No matching objects found.")
        return
    print(f"Found {len(objects)} object(s):")
    for item in objects:
        print(f"  {item['Key']} | {item['Size']} bytes | {item['LastModified']}")


def run_menu(s3: Any, bucket: Any) -> None:
    """Show the CRUD menu and dispatch each choice to one S3 operation."""
    while True:
        print(MENU)
        try:
            choice = input("Choose an option: ").strip()
            if choice == "0":
                print("Goodbye.")
                return
            if choice == "1":
                source = Path(input("Local file path: ").strip().strip('"')).expanduser()
                key = input(f"S3 key [default: {source.name}]: ").strip() or source.name
                # Creating an existing key overwrites it, so require opt-in first.
                if object_exists(s3, bucket.name, key) and not ask_yes_no(f"{key!r} exists. Replace it?"):
                    print("Create cancelled; the existing object was left unchanged.")
                    continue
                print(f"Created: {upload_file(bucket, source, key)}")
            elif choice == "2":
                # A blank prefix lists the whole bucket; a value narrows results by key.
                show_objects(list_objects(bucket, input("Optional prefix (blank lists all): ").strip()))
            elif choice == "3":
                key = input("S3 object key: ").strip()
                # Keep downloads in a local folder by default, using the S3 key's filename.
                default_path = Path("downloads") / Path(key).name
                entered = input(f"Local destination [default: {default_path}]: ").strip().strip('"')
                target = Path(entered).expanduser() if entered else default_path
                if target.exists() and not ask_yes_no(f"Local file {target} exists. Replace it?"):
                    print("Download cancelled; the local file was left unchanged.")
                    continue
                print(f"Downloaded to: {download_file(bucket, key, target)}")
            elif choice == "4":
                source = Path(input("Replacement local file path: ").strip().strip('"')).expanduser()
                key = input(f"S3 key [default: {source.name}]: ").strip() or source.name
                # Update uses the same upload operation but always confirms create or replace.
                action = "replace" if object_exists(s3, bucket.name, key) else "create"
                if not ask_yes_no(f"Confirm {action} for {key!r}?"):
                    print("Update cancelled.")
                    continue
                print(f"Updated: {upload_file(bucket, source, key)}")
            elif choice == "5":
                key = input("S3 object key to delete: ").strip()
                # Deletion is irreversible from this CLI, so only an explicit yes proceeds.
                if not ask_yes_no(f"Request deletion of {key!r} from S3?"):
                    print("Delete cancelled.")
                    continue
                print(f"Delete response: {delete_object(s3, bucket.name, key)}")
            else:
                print("Unknown choice. Enter one of the listed menu numbers.")
        except (S3Error, OSError, ValueError) as error:
            print(f"ERROR: {error}")
        except (EOFError, KeyboardInterrupt):
            print("\nInput ended. Exiting without starting another operation.")
            return


def main(argv: list[str] | None = None) -> None:
    """Create one Boto3 S3 resource and start the interactive CLI."""
    parser = argparse.ArgumentParser(description="Manage objects in the configured S3 bucket.")
    parser.add_argument("--profile", help="AWS CLI profile name, for example s3-test")
    args = parser.parse_args(argv)

    try:
        # Use one session/resource for all operations; never embed access keys here.
        session = boto3.Session(profile_name=args.profile, region_name=REGION)
        s3 = session.resource("s3")
        bucket = s3.Bucket(BUCKET_NAME)
    except ProfileNotFound as error:
        print(f"AWS profile {args.profile!r} was not found. Configure it with AWS CLI first.")
        return

    try:
        connect(bucket)
        print(f"Connected to bucket {BUCKET_NAME} in {REGION}.")
    except S3Error as error:
        print(f"Initial connection check failed: {error}")
        print("The menu will open; configure credentials or S3 permissions before AWS operations.")

    run_menu(s3, bucket)


if __name__ == "__main__":
    main()
