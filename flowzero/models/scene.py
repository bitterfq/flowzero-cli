"""Data models for scenes."""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Scene:
    """Represents a Planet scene/image."""

    scene_id: str
    acquired_date: datetime
    cloud_cover: float
    coverage_pct: float
    geometry: dict  # GeoJSON geometry

    @property
    def date_str(self):
        """Get date as YYYY-MM-DD string."""
        return self.acquired_date.strftime("%Y-%m-%d")
