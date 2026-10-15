"""Beginner-friendly CLI entry point for the S3 file manager.

Run with ``python main.py --profile PROFILE_NAME``. This module handles prompts
and output; S3Manager in s3_manager.py performs the AWS resource operations.
"""

import argparse
from pathlib import Path

from s3_manager import S3Manager, S3OperationError


MENU = """
================ S3 File Manager ================
1. Connect / verify access
2. Upload one file
3. List objects
4. Download one object
5. Update (replace) an object
6. Delete one object
7. Search by prefix
8. Batch upload a folder's files
9. Batch download objects by prefix
10. Batch delete objects by prefix
0. Exit
==================================================
"""


def ask_yes_no(question: str) -> bool:
    """Return True only for an explicit yes; destructive actions default to no."""
    # Show the question and accept only the two explicit yes answers.
    return input(f"{question} [y/N]: ").strip().lower() in {"y", "yes"}


def show_objects(objects: list[dict]) -> None:
    """Print useful fields returned by the S3 list_objects_v2 API."""
    # An empty list means no key matched the requested prefix.
    if not objects:
        print("No matching objects found.")
        return
    # Display the number of results before printing one object per line.
    print(f"Found {len(objects)} object(s):")
    # Each list result has an S3 key, byte size, and last-modified timestamp.
    for item in objects:
        # Display object metadata only; the contents of files are not printed.
        print(f"  {item['Key']} | {item['Size']} bytes | {item['LastModified']}")


def show_batch_results(results: list[dict[str, str]]) -> None:
    """Summarize each success, skip, or failure from a batch operation."""
    # A batch can have no results if its folder or prefix matched nothing.
    if not results:
        print("No files or objects were selected.")
        return
    # Print each result separately so failures and skips are visible.
    for result in results:
        # Status identifies whether this file was processed, skipped, or failed.
        print(f"{result['status'].upper():10} {result['key']} — {result['message']}")
    # Count statuses (uploaded, skipped, failed, etc.) for a quick summary.
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    print("Summary: " + ", ".join(f"{name}={count}" for name, count in counts.items()))


def run_menu(manager: S3Manager) -> None:
    """Read menu choices and call the matching S3 operation."""
    # Keep showing the menu until the user explicitly selects Exit.
    while True:
        print(MENU)
        try:
            # Strip spaces so entries such as " 3 " work as expected.
            choice = input("Choose an option: ").strip()
            # Exit without making any AWS request.
            if choice == "0":
                print("Goodbye.")
                return
            # Ask S3 to verify access to the configured bucket.
            if choice == "1":
                connection = manager.connect()
                print("S3 bucket access verified.")
                print(f"Bucket: {connection['bucket']} | Region: {connection['region']}")
            # Upload one existing local file to a chosen S3 object key.
            elif choice == "2":
                # Remove surrounding quotes copied from Windows File Explorer.
                source_text = input("Local file path: ").strip().strip('"')
                # Expand a leading ~ into the user's home folder if present.
                source = Path(source_text).expanduser()
                # If no key is typed, use the local file's filename.
                key = input(f"S3 key [default: {source.name}]: ").strip() or source.name
                # Check before upload because uploading an existing key replaces its contents.
                if manager.object_exists(key) and not ask_yes_no(f"{key!r} exists. Replace it?"):
                    print("Upload cancelled; the existing S3 object was left unchanged.")
                    continue
                # Transfer the file and print the summary returned by our manager.
                print(f"Uploaded: {manager.upload_file(source, key)}")
            # List all S3 keys, or only those beginning with the optional prefix.
            elif choice == "3":
                prefix = input("Optional prefix (blank lists all objects): ").strip()
                show_objects(manager.list_objects(prefix))
            # Download one S3 object to a local file path.
            elif choice == "4":
                key = input("S3 object key: ").strip()
                # Use downloads/<filename> if no destination was entered.
                default_path = Path("downloads") / Path(key).name
                destination_text = input(f"Local destination [default: {default_path}]: ").strip().strip('"')
                destination = Path(destination_text).expanduser() if destination_text else default_path
                # Do not silently overwrite a local file.
                if destination.exists() and not ask_yes_no(f"Local file {destination} exists. Replace it?"):
                    print("Download cancelled; the local file was left unchanged.")
                    continue
                # Save the S3 object's bytes at the selected local destination.
                print(f"Downloaded to: {manager.download_file(key, destination)}")
            # Update means upload replacement bytes to the same S3 key.
            elif choice == "5":
                source_text = input("Replacement local file path: ").strip().strip('"')
                source = Path(source_text).expanduser()
                key = input(f"S3 key to update [default: {source.name}]: ").strip() or source.name
                # Tell the user whether this will replace or create the key.
                exists = manager.object_exists(key)
                action = "replace the existing object" if exists else "create this key (it does not exist yet)"
                # Updating changes remote data, so require a clear confirmation.
                if not ask_yes_no(f"Confirm you want to {action}: {key!r}?"):
                    print("Update cancelled.")
                    continue
                # S3 stores one latest object at a key unless versioning is enabled.
                print(f"Updated: {manager.upload_file(source, key)}")
            # Delete one remote object only after an explicit yes.
            elif choice == "6":
                key = input("S3 object key to delete: ").strip()
                # No or an empty answer cancels this destructive request.
                if not ask_yes_no(f"Permanently request deletion of {key!r} from S3?"):
                    print("Delete cancelled.")
                    continue
                # Show the response dictionary returned by the S3 delete API.
                print(f"Delete response: {manager.delete_object(key)}")
            # Search is a list operation restricted to keys starting with a prefix.
            elif choice == "7":
                prefix = input("Key prefix to search for: ").strip()
                show_objects(manager.search_by_prefix(prefix))
            # Upload all direct child files from a local folder.
            elif choice == "8":
                folder = Path(input("Local folder path: ").strip().strip('"')).expanduser()
                # Only files directly inside this folder are selected, not subfolders.
                files = sorted(path for path in folder.iterdir() if path.is_file())
                if not files:
                    print("No files found directly inside that folder.")
                    continue
                prefix = input("Destination S3 prefix (optional): ").strip()
                # Build the exact S3 key for each local file so existing keys can be checked.
                keys = [f"{prefix.strip('/')}/{path.name}" if prefix.strip("/") else path.name for path in files]
                # Identify any remote keys this batch could overwrite.
                existing = [key for key in keys if manager.object_exists(key)]
                # Default to not overwriting existing remote files.
                overwrite = False
                if existing:
                    print("These batch-upload keys already exist:")
                    for key in existing:
                        print(f"  {key}")
                    overwrite = ask_yes_no("Replace all listed existing objects? (No skips those keys)")
                # Run the upload and display per-file status lines.
                show_batch_results(manager.batch_upload(files, prefix, overwrite=overwrite))
            # Download every object under a non-empty prefix.
            elif choice == "9":
                prefix = input("S3 prefix to download (required): ").strip()
                # Block an empty prefix because it could match the whole bucket.
                if not prefix:
                    print("A non-empty prefix is required to avoid downloading the entire bucket.")
                    continue
                destination = Path(input("Local destination folder [downloads]: ").strip() or "downloads").expanduser()
                # Fetch the matches first, so the user knows if anything will happen.
                objects = manager.list_objects(prefix)
                if not objects:
                    print("No matching objects found.")
                    continue
                # Batch downloads never overwrite local files unless confirmed once here.
                # Confirm the batch once; without approval existing local files are skipped.
                overwrite = ask_yes_no(f"Download {len(objects)} object(s) to {destination}? Existing files will be replaced.")
                # Download matching keys while preserving their relative paths.
                show_batch_results(manager.batch_download(prefix, destination, overwrite=overwrite))
            # Delete every remote key beginning with a prefix after listing and confirmation.
            elif choice == "10":
                prefix = input("S3 prefix to delete (required): ").strip()
                # Require a prefix so a typo cannot request deletion of the entire bucket.
                if not prefix:
                    print("A non-empty prefix is required; bucket-wide batch delete is blocked.")
                    continue
                objects = manager.list_objects(prefix)
                if not objects:
                    print("No matching objects found.")
                    continue
                # Display the complete candidate set before asking for approval.
                print(f"This will send delete requests for {len(objects)} object(s):")
                for item in objects:
                    print(f"  {item['Key']}")
                # No confirmation means no delete API calls are made.
                if not ask_yes_no("Confirm deletion of every listed object?"):
                    print("Batch delete cancelled; no objects were deleted.")
                    continue
                # Send one delete request for each displayed key after confirmation.
                show_batch_results(manager.batch_delete([item["Key"] for item in objects]))
            else:
                print("Unknown choice. Enter one of the listed menu numbers.")
        # Convert expected file, input, and AWS failures into readable CLI output.
        except (S3OperationError, OSError, ValueError) as error:
            print(f"ERROR: {error}")
        except (EOFError, KeyboardInterrupt):
            # Exit cleanly if the input stream closes or the user presses Ctrl+C.
            print("\nInput ended. Exiting without starting another operation.")
            return


def main(argv: list[str] | None = None) -> None:
    """Create the manager, attempt a safe connection check, and start the CLI."""
    # Accept a profile name so Boto3 can load credentials outside this source file.
    parser = argparse.ArgumentParser(description="Manage objects in the configured S3 bucket.")
    # If omitted, Boto3 uses its normal default credential chain.
    parser.add_argument("--profile", help="AWS CLI profile name, for example payment-dev")
    # Read command-line options; argv also makes this function easy to test.
    args = parser.parse_args(argv)
    # Bucket and region are fixed as requested; credentials are resolved by Boto3.
    try:
        # Create S3/STS clients using the requested profile or the default chain.
        manager = S3Manager(
            bucket_name="s3-practice-payment",
            region="us-east-2",
            profile_name=args.profile,
        )
    except S3OperationError as error:
        # A missing named profile prevents client creation, so print help and stop.
        print(f"AWS profile setup error: {error}")
        print("Create or sign in to that profile, then run this command again.")
        return
    try:
        # Perform a read-only check before displaying the interactive menu.
        connection = manager.connect()
        print(f"Connected to bucket {connection['bucket']} in {connection['region']}.")
    except S3OperationError as error:
        # Keep the menu available so the user can see the error and fix credentials.
        # Do not close the app; users can correct their profile and retry option 1.
        print(f"Initial AWS check did not succeed: {error}")
        print("Configure an AWS CLI profile, then restart with --profile PROFILE_NAME.")
    run_menu(manager)


if __name__ == "__main__":
    # Run the CLI only when this file is executed directly (not when imported).
    main()
