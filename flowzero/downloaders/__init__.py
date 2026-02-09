"""Download modules for parallel and s5cmd-based downloading."""

from flowzero.downloaders.base import BaseDownloader
from flowzero.downloaders.parallel import ParallelDownloader

try:
    from flowzero.downloaders.s5cmd import S5cmdDownloader
    HAS_S5CMD = True
except Exception:
    HAS_S5CMD = False
    S5cmdDownloader = None

__all__ = ["BaseDownloader", "ParallelDownloader", "S5cmdDownloader", "HAS_S5CMD"]
