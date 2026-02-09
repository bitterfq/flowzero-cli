"""s5cmd downloader for ultra-fast S3 uploads."""
import subprocess
import tempfile
from pathlib import Path

from flowzero.config import config
from flowzero.downloaders.base import BaseDownloader


class S5cmdDownloader(BaseDownloader):
    """Downloader using s5cmd for high-performance S3 uploads."""

    def __init__(self, s3_bucket=None, num_workers=20):
        """
        Initialize s5cmd downloader.

        Args:
            s3_bucket: S3 bucket name
            num_workers: Number of parallel workers for s5cmd
        """
        self.s3_bucket = s3_bucket or config.s3_bucket
        self.num_workers = num_workers
        self._check_s5cmd_available()

    def _check_s5cmd_available(self):
        """Check if s5cmd is installed."""
        try:
            subprocess.run(
                ["s5cmd", "version"], capture_output=True, check=True, timeout=5
            )
            self.available = True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            self.available = False

    def download(self, url, destination):
        """
        Download single file not supported with s5cmd.
        Use download_batch instead.
        """
        return self.download_batch([(url, destination)])[0]

    def download_batch(self, url_destination_pairs):
        """
        Download multiple files using s5cmd.

        Args:
            url_destination_pairs: List of (url, s3_key) tuples
                Note: URLs should be accessible public URLs or pre-signed

        Returns:
            List of (success, destination) tuples
        """
        if not self.available:
            raise RuntimeError("s5cmd is not installed or not in PATH")

        # Create temporary manifest file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            manifest_path = f.name
            for url, s3_key in url_destination_pairs:
                # s5cmd format: source destination
                f.write(f"{url} s3://{self.s3_bucket}/{s3_key}\n")

        try:
            # Run s5cmd with manifest
            result = subprocess.run(
                ["s5cmd", "--numworkers", str(self.num_workers), "run", manifest_path],
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout for large batches
            )

            # Parse results
            # Note: s5cmd doesn't provide per-file success/failure easily
            # If command succeeds, assume all succeeded
            if result.returncode == 0:
                return [(True, dest) for _, dest in url_destination_pairs]
            else:
                print(f"s5cmd error: {result.stderr}")
                return [(False, dest) for _, dest in url_destination_pairs]

        finally:
            # Cleanup manifest file
            Path(manifest_path).unlink(missing_ok=True)
