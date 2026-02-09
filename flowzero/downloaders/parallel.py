"""Parallel downloader using ThreadPoolExecutor."""
import io
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from flowzero.config import config
from flowzero.downloaders.base import BaseDownloader


class ParallelDownloader(BaseDownloader):
    """Download files in parallel using threading."""

    def __init__(self, s3_client=None, max_workers=None):
        """
        Initialize parallel downloader.

        Args:
            s3_client: S3Client instance (optional, for S3 uploads)
            max_workers: Max number of concurrent downloads (default from config)
        """
        self.s3_client = s3_client
        self.max_workers = max_workers or config.max_concurrent_downloads

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(requests.RequestException),
    )
    def _download_file(self, url, timeout=None):
        """Download file with retry logic."""
        timeout = timeout or config.download_timeout
        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()
        return response

    def download(self, url, destination, is_s3=False):
        """
        Download a single file.

        Args:
            url: Source URL
            destination: S3 key or local file path
            is_s3: Whether destination is S3 (True) or local (False)

        Returns:
            True if successful
        """
        try:
            response = self._download_file(url)

            if is_s3 and self.s3_client:
                # Upload to S3
                self.s3_client.upload_fileobj(io.BytesIO(response.content), destination)
            else:
                # Save locally
                dest_path = Path(destination)
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=config.download_chunk_size):
                        if chunk:
                            f.write(chunk)

            return True

        except Exception as e:
            print(f"Error downloading {url}: {e}")
            return False

    def _download_single(self, url, destination, is_s3, overwrite, check_exists_func):
        """
        Download a single file (worker function).

        Returns:
            tuple: (success, destination, error_msg)
        """
        # Check if file exists
        if not overwrite and check_exists_func:
            if check_exists_func(destination):
                return (True, destination, "skipped")

        try:
            success = self.download(url, destination, is_s3)
            return (success, destination, None if success else "download_failed")

        except Exception as e:
            return (False, destination, str(e))

    def download_batch(
        self, url_destination_pairs, is_s3=False, overwrite=False, check_exists_func=None
    ):
        """
        Download multiple files in parallel.

        Args:
            url_destination_pairs: List of (url, destination) tuples
            is_s3: Whether destinations are S3 keys
            overwrite: Whether to overwrite existing files
            check_exists_func: Function to check if file exists (takes destination)

        Yields:
            Tuples of (success, destination, error_msg) as downloads complete
        """
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self._download_single, url, dest, is_s3, overwrite, check_exists_func
                ): (url, dest)
                for url, dest in url_destination_pairs
            }

            for future in as_completed(futures):
                url, dest = futures[future]
                try:
                    result = future.result()
                    yield result
                except Exception as e:
                    yield (False, dest, str(e))
