# S3 File Manager

A small interactive Python CLI for creating, reading, updating, and deleting objects in the existing `s3-practice-payment` bucket in `us-east-2`.

## Requirements

- Python 3.10 or newer
- AWS CLI credentials with access to the bucket
- The bucket `s3-practice-payment` already exists in `us-east-2`

The application uses Boto3's normal credential chain and never stores AWS credentials in source code. Configure credentials with your approved AWS CLI login flow, then optionally select a named profile:

```powershell
aws login --profile payment-dev
```

## Install and run

From the project folder:

```powershell
python -m pip install -r requirements.txt
python main.py --profile payment-dev
```

Omit `--profile payment-dev` to use the default AWS credentials. At startup the program checks access to the configured bucket and then opens the menu.

## Operations

| Menu option | Operation |
| --- | --- |
| 1 | Create an object by uploading a local file. Existing keys require confirmation before replacement. |
| 2 | Read objects by listing the bucket, optionally filtered by key prefix. |
| 3 | Read an object by downloading it to a local file. Existing local files require confirmation before replacement. |
| 4 | Update an object by uploading replacement contents to its key, after confirmation. |
| 5 | Delete an object, after confirmation. |
| 0 | Exit. |

The bucket name and region are configured in `main.py`. The included [s3_access_policy.json](s3_access_policy.json) is a bucket-scoped policy template for an administrator to review and assign to the AWS identity used by the CLI.

## Sample operations

These examples show the prompts for each operation. Paths, object names, timestamps, and AWS responses are illustrative; use files and keys that exist in your environment.

### 1. Create (upload) an object

Choose option `1`, enter a local file, then enter the S3 key. If the key already exists, the CLI asks before replacing it.

```text
Choose an option: 1
Local file path: C:\practice\march.csv
S3 key [default: march.csv]: incoming/march.csv
Created: {'bucket': 's3-practice-payment', 'key': 'incoming/march.csv', 'source': 'C:\\practice\\march.csv'}
```

### 2. Read (list) objects

Choose option `2`. Enter a prefix to narrow the results, or leave it blank to list all objects.

```text
Choose an option: 2
Optional prefix (blank lists all): incoming/
Found 1 object(s):
  incoming/march.csv | 2048 bytes | 2026-10-15 09:30:00+00:00
```

### 3. Read (download) an object

Choose option `3`, enter the exact S3 key, and optionally enter a local destination. The default destination is `downloads` plus the object's filename.

```text
Choose an option: 3
S3 object key: incoming/march.csv
Local destination [default: downloads\march.csv]:
Downloaded to: downloads\march.csv
```

If the destination already exists, confirm before the CLI replaces the local file.

### 4. Update (replace) an object

Choose option `4`, provide the replacement local file and the S3 key to update, then confirm the operation.

```text
Choose an option: 4
Replacement local file path: C:\practice\march-revised.csv
S3 key [default: march-revised.csv]: incoming/march.csv
Confirm replace for 'incoming/march.csv'? [y/N]: y
Updated: {'bucket': 's3-practice-payment', 'key': 'incoming/march.csv', 'source': 'C:\\practice\\march-revised.csv'}
```

If the key does not exist, the confirmation asks you to confirm creating it instead.

### 5. Delete an object

Choose option `5`, enter the exact S3 key, and confirm only after checking it carefully.

```text
Choose an option: 5
S3 object key to delete: incoming/march.csv
Request deletion of 'incoming/march.csv' from S3? [y/N]: y
Delete response: {'ResponseMetadata': {'HTTPStatusCode': 204}}
```

Choose `0` at the menu to exit:

```text
Choose an option: 0
Goodbye.
```
