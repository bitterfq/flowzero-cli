"""Data models for orders."""
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Order:
    """Represents a Planet Labs order."""

    order_id: str
    aoi_name: str
    order_type: str  # "PSScope" or "Basemap (Composite)"
    start_date: str
    end_date: str
    num_bands: Optional[str] = None
    product_bundle: Optional[str] = None
    product_bundle_order: Optional[str] = None
    clipped: bool = True
    aoi_area_sqkm: Optional[float] = None
    scenes_selected: Optional[int] = None
    scenes_found: Optional[int] = None
    quota_hectares: Optional[float] = None
    batch_order: bool = False
    batch_id: Optional[str] = None
    mosaic_name: Optional[str] = None
    status: Optional[str] = None  # queued, running, success, partial, failed, cancelled
    timestamp: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        """Create Order from dictionary."""
        return cls(**data)
