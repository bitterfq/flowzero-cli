"""S3 client with connection pooling and retry logic."""
import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from flowzero.config import config


class S3Client:
    """S3 client with optimized connection pooling."""

    def __init__(self, aws_access_key_id=None, aws_secret_access_key=None, bucket=None):
        self.bucket = bucket or config.s3_bucket

        boto_config = BotoConfig(
            max_pool_connections=config.s3_max_pool_connections,
            retries={"max_attempts": config.s3_retry_attempts, "mode": "adaptive"},
            region_name=config.s3_region,
        )

        self.client = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key_id or config.aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key or config.aws_secret_access_key,
            config=boto_config,
        )

    def key_exists(self, key):
        """Check if a key exists in S3."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(ClientError),
    )
    def upload_fileobj(self, fileobj, key):
        """Upload a file object to S3 with retry logic."""
        self.client.upload_fileobj(fileobj, self.bucket, key)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(ClientError),
    )
    def put_object(self, body, key):
        """Put an object to S3 with retry logic."""
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body)

    def upload_stream(self, stream, key, chunk_size=None):
        """
        Upload a stream to S3 using multipart upload for better memory efficiency.

        Args:
            stream: Iterable that yields chunks of data
            key: S3 key
            chunk_size: Size of each chunk (default from config)
        """
        chunk_size = chunk_size or config.download_chunk_size

        # Initialize multipart upload
        mpu = self.client.create_multipart_upload(Bucket=self.bucket, Key=key)
        upload_id = mpu["UploadId"]

        parts = []
        part_num = 1

        try:
            for chunk in stream:
                if not chunk:
                    continue

                part = self.client.upload_part(
                    Bucket=self.bucket,
                    Key=key,
                    PartNumber=part_num,
                    UploadId=upload_id,
                    Body=chunk,
                )

                parts.append({"PartNumber": part_num, "ETag": part["ETag"]})
                part_num += 1

            # Complete multipart upload
            self.client.complete_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )

        except Exception as e:
            # Abort multipart upload on error
            self.client.abort_multipart_upload(
                Bucket=self.bucket, Key=key, UploadId=upload_id
            )
            raise e
