import csv
import hashlib
import io
import json
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import BUCKET, KEY, OUTPUT, SOURCE, StorageConfig


class ObjectStorage:
    def __init__(self):
        self.config = StorageConfig.load()
        self.client = boto3.client(
            "s3",
            endpoint_url=self.config.endpoint,
            aws_access_key_id=self.config.access_key,
            aws_secret_access_key=self.config.secret_key,
            region_name="us-east-1",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def rows(self):
        body = self.client.get_object(Bucket=BUCKET, Key=KEY)["Body"]

        with io.TextIOWrapper(body, encoding="utf-8", newline="") as stream:
            yield from csv.DictReader(stream)

    def prepare(self):
        try:
            self.client.head_bucket(Bucket=BUCKET)
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise

            self.client.create_bucket(Bucket=BUCKET)

        projection = OUTPUT / "input" / "vacancies_core.csv"
        projection.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "vacancy_id",
            "name",
            "role",
            "area",
            "key_skills",
            "salary_from",
            "salary_to",
            "currency",
            "gross",
        ]
        row_count = 0

        with (
            SOURCE.open(encoding="utf-8", newline="") as source,
            projection.open("w", encoding="utf-8", newline="") as target,
        ):
            writer = csv.DictWriter(target, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()

            for row in csv.DictReader(source):
                writer.writerow(row)
                row_count += 1

        with projection.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()

        try:
            existing = self.client.head_object(Bucket=BUCKET, Key=KEY)
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise

            existing = {}

        if existing.get("Metadata", {}).get("sha256") != digest:
            self.client.upload_file(
                str(projection), BUCKET, KEY, ExtraArgs={"Metadata": {"sha256": digest}}
            )

        body = self.client.get_object(Bucket=BUCKET, Key=KEY)["Body"]
        remote_hash = hashlib.sha256()

        try:
            for block in body.iter_chunks(4 * 1024 * 1024):
                remote_hash.update(block)
        finally:
            body.close()

        if remote_hash.hexdigest() != digest:
            raise ValueError("S3 content SHA-256 mismatch")

        with SOURCE.open("rb") as stream:
            original_hash = hashlib.file_digest(stream, "sha256").hexdigest()

        original_key = "hw3/input/it_vacancies_2024.csv"

        try:
            original_head = self.client.head_object(Bucket=BUCKET, Key=original_key)
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise

            original_head = {}

        if original_head.get("Metadata", {}).get("sha256") != original_hash:
            self.client.upload_file(
                str(SOURCE), BUCKET, original_key, ExtraArgs={"Metadata": {"sha256": original_hash}}
            )
            original_body = self.client.get_object(Bucket=BUCKET, Key=original_key)["Body"]
            original_remote_hash = hashlib.sha256()

            try:
                for block in original_body.iter_chunks(4 * 1024 * 1024):
                    original_remote_hash.update(block)
            finally:
                original_body.close()

            if original_remote_hash.hexdigest() != original_hash:
                raise ValueError("Original S3 content SHA-256 mismatch")

            save_json(
                OUTPUT / "original_storage.json",
                {
                    "bucket": BUCKET,
                    "key": original_key,
                    "bytes": SOURCE.stat().st_size,
                    "sha256": original_hash,
                    "s3_sha256": original_remote_hash.hexdigest(),
                },
            )

        return {
            "bucket": BUCKET,
            "key": KEY,
            "bytes": projection.stat().st_size,
            "input_rows": row_count,
            "original_bytes": SOURCE.stat().st_size,
            "original_sha256": original_hash,
            "sha256": digest,
            "s3_sha256": remote_hash.hexdigest(),
            "head": {
                k: str(v)
                for k, v in self.client.head_object(Bucket=BUCKET, Key=KEY).items()
                if k in ("ContentLength", "ETag", "LastModified", "Metadata")
            },
        }

    def upload_results(self, directory: Path):
        objects = []

        for path in sorted(directory.glob("*.csv")):
            key = "hw3/results/" + path.name
            self.client.upload_file(str(path), BUCKET, key)
            objects.append(
                {
                    "key": key,
                    "bytes": self.client.head_object(Bucket=BUCKET, Key=key)["ContentLength"],
                }
            )

        return objects


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
