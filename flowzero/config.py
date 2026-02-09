"""Configuration management for FlowZero Orders CLI."""
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from config.yaml and environment variables."""

    def __init__(self, config_path=None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"

        with open(config_path) as f:
            self._config = yaml.safe_load(f)

        self._load_env_overrides()

    def _load_env_overrides(self):
        """Load environment variable overrides."""
        self.pl_api_key = os.getenv("PL_API_KEY")
        self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")

    @property
    def planet_base_url(self):
        return self._config["api"]["planet_base_url"]

    @property
    def min_coverage_pct(self):
        return self._config["api"]["min_coverage_pct"]

    @property
    def rate_limit_delay(self):
        return self._config["api"]["rate_limit_delay"]

    @property
    def pagination_delay(self):
        return self._config["api"]["pagination_delay"]

    @property
    def api_timeout(self):
        return self._config["api"]["timeout"]

    @property
    def s3_bucket(self):
        return self._config["s3"]["bucket"]

    @property
    def s3_region(self):
        return self._config["s3"]["region"]

    @property
    def s3_max_pool_connections(self):
        return self._config["s3"]["max_pool_connections"]

    @property
    def s3_retry_attempts(self):
        return self._config["s3"]["retry_attempts"]

    @property
    def download_chunk_size(self):
        return self._config["downloads"]["chunk_size"]

    @property
    def max_concurrent_downloads(self):
        return self._config["downloads"]["max_concurrent_downloads"]

    @property
    def download_timeout(self):
        return self._config["downloads"]["timeout"]

    @property
    def download_retry_attempts(self):
        return self._config["downloads"]["retry_attempts"]

    @property
    def database_path(self):
        return Path(self._config["storage"]["database_path"])

    @property
    def cache_dir(self):
        return Path(self._config["storage"]["cache_dir"])

    @property
    def cache_ttl(self):
        return self._config["storage"]["cache_ttl"]

    @property
    def log_level(self):
        return self._config["logging"]["level"]

    @property
    def log_format(self):
        return self._config["logging"]["format"]


# Global config instance
config = Config()
