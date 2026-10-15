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
