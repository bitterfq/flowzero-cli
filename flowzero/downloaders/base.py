"""Base downloader interface."""
from abc import ABC, abstractmethod


class BaseDownloader(ABC):
    """Abstract base class for downloaders."""

    @abstractmethod
    def download(self, url, destination):
        """
        Download a file from URL to destination.

        Args:
            url: Source URL
            destination: Destination (S3 key or local path)

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    def download_batch(self, url_destination_pairs):
        """
        Download multiple files.

        Args:
            url_destination_pairs: List of (url, destination) tuples

        Returns:
            List of (success, destination) tuples
        """
        pass
