#!/usr/bin/env python3
"""
Seed the DataLens DynamoDB usage-stats table with mock data.

Usage
-----
# Seed using table name from SAM stack output:
python scripts/seed_dynamodb.py --table datalens-prod-usage-stats

# Seed using explicit AWS region:
python scripts/seed_dynamodb.py --table datalens-prod-usage-stats --region eu-west-1

# Dry-run (print items without writing):
python scripts/seed_dynamodb.py --table datalens-prod-usage-stats --dry-run

# Override a single product (useful for CI or demo prep):
python scripts/seed_dynamodb.py --table datalens-prod-usage-stats --only creditpulse_pro

Notes
-----
- Safe to re-run: uses put_item (upsert), so existing items are overwritten.
- AWS credentials: uses standard boto3 chain (AWS_PROFILE, instance role, etc.)
- The table name is printed by `sam deploy` as the `UsageTableName` stack output.
  You can also look it up with:
      aws cloudformation describe-stacks \\
          --stack-name <stack-name> \\
          --query "Stacks[0].Outputs[?OutputKey=='UsageTableName'].OutputValue" \\
          --output text
"""

import argparse
import json
import sys
import os
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

# Allow running from the backend/ root or from backend/scripts/
_this_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(_this_dir)
sys.path.insert(0, _backend_dir)

from mock_data.data import USAGE_STATS


def _to_decimal(obj):
    """Recursively convert floats to Decimal (DynamoDB requirement)."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(i) for i in obj]
    return obj


def seed(table_name: str, region: str, dry_run: bool, only: str | None) -> None:
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    items_to_seed = {
        k: v for k, v in USAGE_STATS.items()
        if only is None or k == only
    }

    if not items_to_seed:
        print(f"No items matched filter --only={only!r}. Available keys:")
        for k in USAGE_STATS:
            print(f"  {k}")
        sys.exit(1)

    print(f"Seeding {len(items_to_seed)} item(s) into table '{table_name}' "
          f"(region: {region}){' [DRY RUN]' if dry_run else ''}\n")

    success = 0
    errors = 0

    for product_id, stats in items_to_seed.items():
        item = {"product_id": product_id, **_to_decimal(stats)}

        if dry_run:
            # Pretty-print what would be written
            printable = {"product_id": product_id, **stats}
            print(f"  [DRY RUN] Would write: {json.dumps(printable, indent=4)}\n")
            success += 1
            continue

        try:
            table.put_item(Item=item)
            print(f"  ✓ {product_id}")
            success += 1
        except ClientError as e:
            print(f"  ✗ {product_id}: {e.response['Error']['Message']}", file=sys.stderr)
            errors += 1

    print(f"\nDone — {success} written, {errors} errors.")
    if errors:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed DataLens DynamoDB usage-stats table from mock data."
    )
    parser.add_argument(
        "--table",
        required=True,
        help="DynamoDB table name (UsageTableName output from sam deploy)",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", "us-east-1"),
        help="AWS region (default: AWS_REGION env var or us-east-1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print items without writing to DynamoDB",
    )
    parser.add_argument(
        "--only",
        default=None,
        metavar="PRODUCT_ID",
        help="Seed only a single product_id (e.g. creditpulse_pro)",
    )
    args = parser.parse_args()

    try:
        seed(args.table, args.region, args.dry_run, args.only)
    except NoCredentialsError:
        print(
            "ERROR: No AWS credentials found.\n"
            "Run `aws configure` or set AWS_PROFILE / AWS_ACCESS_KEY_ID.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
