import csv
import io
import json
import os

import boto3
from botocore.config import Config


class ObjectStorage:
    def __init__(self):
        self.bucket = os.environ.get("S3_BUCKET", "hh-lake")
        self.client = boto3.client(
            "s3",
            endpoint_url=os.environ["S3_ENDPOINT"],
            region_name="us-east-1",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def rows(self, key: str):
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]

        with io.TextIOWrapper(body, encoding="utf-8", newline="") as stream:
            yield from csv.DictReader(stream)

    def put(self, key: str, body: str):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body.encode("utf-8"))

    def put_json(self, key: str, value: dict):
        self.put(key, json.dumps(value, ensure_ascii=False, indent=2))
