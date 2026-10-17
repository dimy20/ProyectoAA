import boto3
import os

DEFAULT_BUCKET = "proyecto-water-aa"

def get_s3_client():
  aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"]
  aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"]
  region_name=os.environ.get("AWS_REGION", "us-east-1")

  if not aws_access_key_id or not aws_secret_access_key or not region_name:
    raise RuntimeError("Missing AWS credentials")


  s3 = boto3.client(
    "s3",
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    region_name=region_name
  )

  return s3