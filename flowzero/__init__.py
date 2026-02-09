"""FlowZero Orders CLI - Planet Labs satellite imagery ordering tool."""

__version__ = "2.0.0"

try:
    from flowzero.config import config
    __all__ = ["config", "__version__"]
except ImportError:
    # Config might not be available during installation
    __all__ = ["__version__"]
