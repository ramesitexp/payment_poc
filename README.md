# S3 File Manager (Python + Boto3)

A beginner-friendly menu CLI for the existing S3 bucket `s3-practice-payment` in `us-east-2`. It supports connect/check, upload, list, download, update (replace), delete, prefix search, and batch upload/download/delete.

**Credentials are not in the source code.** The app uses Boto3's standard credential chain and supports selecting a named AWS CLI profile with `--profile`.

## 1. Prerequisites

- Python 3.10 or newer (the source uses Python 3.10 union type syntax).
- AWS CLI v2 installed and an AWS account/profile with access to the bucket.
- The bucket `s3-practice-payment` already exists in `us-east-2`.
- A role/user policy and bucket policy that permit the operations you intend to use. Typical S3 permissions include `s3:ListBucket`, `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject`. Follow least privilege; do not grant broad access just to make an error disappear.

This project includes a bucket-scoped IAM policy template in [s3_access_policy.json](s3_access_policy.json). An AWS account administrator can review it and attach it to the specific IAM role/user used by the CLI profile. It permits listing this bucket and reading, uploading, deleting its objects, and aborting failed multipart uploads; it does not grant bucket creation, policy changes, or access to other buckets. Reduce the object ARN to an approved prefix if the app should manage only part of the bucket. If this bucket enforces SSE-KMS with a customer-managed key, the administrator may also need to grant the appropriate KMS key permissions.

## 2. Set up AWS CLI credentials (Windows PowerShell)

Run these commands in your own terminal, not in a chat message. Do not share access keys or session tokens. If your organization uses IAM Identity Center/SSO, use its approved login flow instead of creating long-lived keys.

1. Check whether AWS CLI is installed:

   ```powershell
   aws --version
   ```

   If PowerShell says `aws` is not recognized and Windows Package Manager (`winget`) is available, install AWS CLI v2, then close and reopen the terminal:

   ```powershell
   winget install --id Amazon.AWSCLI --exact
   ```

   Installation adds software to Windows; review any installer prompts before accepting them. If `winget` is unavailable, use the official AWS CLI v2 Windows installer from AWS documentation.

2. **Recommended for supported AWS accounts:** AWS CLI 2.32.0+ supports `aws login`, which uses short-lived credentials:

   ```powershell
   aws login
   ```

   Complete the sign-in in the browser opened by the CLI. For a named profile, use `aws login --profile payment-dev`. The app can then use the matching profile with `python main.py --profile payment-dev`.

   If your organization already uses IAM Identity Center (SSO), continue using its established profile flow:

   ```powershell
   aws configure sso --profile payment-dev
   aws sso login --profile payment-dev
   ```

   If your organization explicitly requires long-term IAM access keys instead, configure them only through the local AWS CLI prompt (never in Python or chat). Long-lived keys are less secure than short-term sign-in credentials and the previously shared key must not be reused:

   ```powershell
   aws configure --profile payment-dev
   ```

   Use region `us-east-2` and output format `json` when prompted. AWS CLI stores profile data under your Windows user directory; do not copy those credentials into this project.

3. Verify the credential identity. This is read-only and does not change AWS resources:

   ```powershell
   aws sts get-caller-identity --profile payment-dev --output json
   ```

   Successful output contains the AWS account number, user/role ID, and ARN. Confirm the account/role is the intended one before continuing.

4. Verify access to the bucket. This is a read-only request:

   ```powershell
   aws s3api head-bucket --bucket s3-practice-payment --region us-east-2 --profile payment-dev
   ```

   A successful response is usually empty (exit code 0). A failure can mean the bucket is absent, the selected account is wrong, or bucket access is denied. Do not create a bucket or change an IAM policy without confirming the account, region, and authorization first.

If the bucket does not exist, ask the AWS account owner whether you should create it. Bucket creation changes AWS resources and can incur charges; this app intentionally does not create buckets.

## 3. Install and start the application

Open this project folder in VS Code. In its terminal, create/activate an environment if desired, install the listed dependency, and launch the app with the same profile:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py --profile payment-dev
```

If you use the AWS default profile instead, run `python main.py` without the `--profile` option. The CLI profile controls which AWS identity Boto3 uses; it does not grant permissions by itself.

If PowerShell blocks environment activation, follow your organization's policy; you can also run the virtual environment's Python executable directly without activating it. In VS Code, select that same `.venv` interpreter.

On startup the program makes one read-only S3 check, `HeadBucket`, to confirm access to the configured bucket. The menu still opens if the check fails so credentials/access can be corrected and checked again with option 1. No AWS resource is created during startup.

### Run offline tests

Run `python -m unittest discover -s tests -v` from the project folder. The unit tests mock all AWS clients and use temporary local files, so they do not require credentials and do not change the bucket.

## 4. Menu operations and practical examples

Use local file paths as they appear on your machine. S3 keys are object names, not local filesystem paths. A prefix is a beginning-of-key match, not a folder permission boundary.

| Operation | Example menu flow | Behavior |
| --- | --- | --- |
| Upload | `2` → `C:\\payments\\march.csv` → key `incoming/march.csv` | Sends a local file to S3. If that key already exists, replacement requires confirmation. |
| List | `3` → prefix `incoming/` | Prints every matching key, size, and last-modified timestamp; blank prefix lists all objects. |
| Download | `4` → key `incoming/march.csv` → destination `downloads/march.csv` | Writes the object locally; a pre-existing local destination requires confirmation. |
| Update | `5` → replacement file → key `incoming/march.csv` | Uploads the new bytes to the same key. This replaces the old object only after confirmation. A missing key is created after explicit confirmation. |
| Delete | `6` → key `incoming/march.csv` → confirm `y` | Sends an S3 delete request only after explicit confirmation. |
| Search | `7` → prefix `incoming/2026/` | Returns keys starting with that exact prefix. |
| Batch upload | `8` → local folder → prefix `incoming/` | Uploads direct child files with their filenames. Existing keys are shown; `y` replaces those keys, while `N` skips them. |
| Batch download | `9` → non-empty prefix `incoming/` → destination `downloads/incoming` | Downloads matching objects while preserving relative key paths. Existing local files are replaced only if the one batch confirmation is accepted; otherwise those files are skipped. |
| Batch delete | `10` → non-empty prefix `temp/` → review displayed keys → confirm `y` | Lists the complete target set and sends delete requests only after one explicit confirmation. Empty prefix is blocked to prevent accidental bucket-wide deletion. |

Batch operations report per-item `uploaded`/`downloaded`/`deleted`, `skipped`, or `failed` results; a batch can partially succeed if an individual file or request fails. Review the output before retrying.

### Sample menu runs (illustrative)

The transcripts below show representative prompts and output after you start the app. Names, sizes, timestamps, and response details are examples; actual output depends on your files and S3 responses. Menu operations that access AWS will still return `403 Forbidden` until the selected profile is authorized for this bucket. Do not copy real payment/customer data into practice files.

**Option 0 — exit**

```text
Choose an option: 0
Goodbye.
```

**Option 1 — verify bucket access**

```text
Choose an option: 1
S3 bucket access verified.
Bucket: s3-practice-payment | Region: us-east-2
```

**Option 2 — upload one file**

```text
Choose an option: 2
Local file path: C:\practice\sample.txt
S3 key [default: sample.txt]: practice/sample.txt
Uploaded: {'bucket': 's3-practice-payment', 'key': 'practice/sample.txt', 'source': 'C:\\practice\\sample.txt'}
```

If that key already exists, the app asks `Replace it? [y/N]`; answering `N` cancels without uploading.

**Option 3 — list objects**

```text
Choose an option: 3
Optional prefix (blank lists all objects): practice/
Found 1 object(s):
   practice/sample.txt | 24 bytes | 2026-10-15 12:00:00+00:00
```

**Option 4 — download one object**

```text
Choose an option: 4
S3 object key: practice/sample.txt
Local destination [default: downloads\sample.txt]: downloads\sample-copy.txt
Downloaded to: downloads\sample-copy.txt
```

**Option 5 — update (replace) an object**

```text
Choose an option: 5
Replacement local file path: C:\practice\sample-v2.txt
S3 key to update [default: sample-v2.txt]: practice/sample.txt
Confirm you want to replace the existing object: 'practice/sample.txt'? [y/N]: y
Updated: {'bucket': 's3-practice-payment', 'key': 'practice/sample.txt', 'source': 'C:\\practice\\sample-v2.txt'}
```

**Option 6 — delete one object**

```text
Choose an option: 6
S3 object key to delete: practice/old-sample.txt
Permanently request deletion of 'practice/old-sample.txt' from S3? [y/N]: y
Delete response: {'ResponseMetadata': {'HTTPStatusCode': 204}}
```

The actual delete response fields can vary, and S3 versioning may leave a delete marker rather than permanently erase old versions.

**Option 7 — search by prefix**

```text
Choose an option: 7
Key prefix to search for: practice/2026/
Found 1 object(s):
   practice/2026/sample.txt | 24 bytes | 2026-10-15 12:00:00+00:00
```

**Option 8 — batch upload direct files from a folder**

```text
Choose an option: 8
Local folder path: C:\practice\to-upload
Destination S3 prefix (optional): practice/batch/
UPLOADED   practice/batch/one.txt — Upload complete
UPLOADED   practice/batch/two.txt — Upload complete
Summary: uploaded=2
```

S3 keys use `/` even when the local computer is running Windows. If destination keys already exist, the app lists them and asks once whether to replace those objects. Answer `N` to skip existing keys.

**Option 9 — batch download by prefix**

```text
Choose an option: 9
S3 prefix to download (required): practice/batch/
Local destination folder [downloads]: downloads\practice-batch
Download 2 object(s) to downloads\practice-batch? Existing files will be replaced. [y/N]: n
DOWNLOADED practice/batch/one.txt — ...\downloads\practice-batch\one.txt
DOWNLOADED practice/batch/two.txt — ...\downloads\practice-batch\two.txt
Summary: downloaded=2
```

Answering `y` permits replacing any existing local files; answering `N` skips existing local files and downloads the rest.

**Option 10 — batch delete after reviewing the target list**

```text
Choose an option: 10
S3 prefix to delete (required): practice/temp/
This will send delete requests for 2 object(s):
   practice/temp/one.txt
   practice/temp/two.txt
Confirm deletion of every listed object? [y/N]: n
Batch delete cancelled; no objects were deleted.
```

For a real deletion, enter `y` only after checking every displayed key. An empty prefix is rejected to prevent a bucket-wide batch delete.

**Example AWS permission failure**

```text
Choose an option: 1
ERROR: AWS connection or bucket check failed (403): Forbidden
```

This is an AWS authorization response, not a local-path or Python setup problem. Ask the AWS administrator to verify the CLI profile's identity, bucket policy, and required S3 permissions before retrying.

## 5. What the code does

### `s3_manager.py`

- `S3Manager.__init__`: creates a Boto3 `Session` and S3 client for the configured region. It does not accept or store keys; the normal credential chain reads the CLI profile/environment.
- `connect`: calls S3 `head_bucket(Bucket=...)` to test bucket access without retrieving or displaying account identity. `HeadBucket` normally returns an empty success response.
- `object_exists`: calls `head_object(Bucket=..., Key=...)`; a 404 means absent, while access/network errors are reported instead of being mistaken for absence.
- `upload_file`: calls `upload_file(Filename, Bucket, Key)`. This Boto3 high-level transfer handles multipart uploads; it returns no S3 response body, so the app returns a local summary instead.
- `list_objects`: uses a `list_objects_v2` paginator with `Bucket` and `Prefix`. Each page may contain `Contents` entries such as `Key`, `Size`, and `LastModified`; pagination prevents silently missing later pages.
- `download_file`: calls `download_file(Bucket, Key, Filename)` and streams the object to disk. It returns the destination path.
- `delete_object`: calls `delete_object(Bucket, Key)`. S3 returns a response dictionary (often including `DeleteMarker` or `VersionId` when versioning applies). The CLI asks for confirmation first.
- `search_by_prefix`: validates the prefix then delegates to paginated listing.
- `batch_upload`, `batch_download`, `batch_delete`: run the single-item operations in a loop and return one status record per item. Batch download prevents S3 keys from escaping the chosen local directory.
- `_aws_error` and `_validate_key`: convert AWS client/network failures to readable messages and reject blank object keys.

### `main.py`

- `ask_yes_no`: treats only `y`/`yes` as approval, so destructive actions default to no.
- `show_objects` and `show_batch_results`: format API results and per-file outcomes for a beginner-readable terminal view.
- `run_menu`: collects user input, validates risky operations with confirmations, and routes each selection to `S3Manager`.
- `main`: constructs the fixed bucket/region manager, attempts the non-destructive connection check, and starts the menu even when initial credentials are not ready.

AWS error responses are converted to an actionable `ERROR:` message. For `AccessDenied`, verify the active AWS identity, IAM permissions, bucket policy, and region rather than putting credentials into Python.

## 6. Simple Tamil + English flow

1. AWS CLI-la login/profile configure pannunga; keys-ai Python code-la hardcode panna vendam. `AWS_PROFILE` set pannina, Boto3 andha profile-ai use pannum.
2. App start aagumbodhu `HeadBucket` moolama `s3-practice-payment` access irukka-nu read-only-a verify pannum; account identity-ai app retrieve pannaadhu.
3. Menu-la option choose pannunga. Upload/update local file-ai S3 key-ku anuppum; list/search prefix match aana objects-ai paginate panni kaattum; download S3 object-ai local path-ku ezhuthum.
4. Delete, overwrite, batch delete/download overwrite madhiri changes-ku confirmation kekkum. `y` kudutha mattum action proceed aagum; default `N`.
5. Batch-la sila files fail aana, ovvoru item-oda result print aagum. Error vandha AWS identity, region, bucket policy, permissions check pannitu retry pannunga.

## Safety notes

- The CLI never creates buckets, changes bucket policies, or stores credentials.
- Single-object replacement/deletion requires confirmation. Batch deletion shows all matching keys and requires one confirmation. Bucket-wide batch delete is blocked.
- S3 versioning, retention policies, and IAM permissions affect whether deletions are recoverable or allowed; a normal delete request may not mean permanent erasure in a versioned bucket.
- Do not commit AWS credentials, downloaded payment data, or real customer data to source control. Use synthetic data while practicing.
