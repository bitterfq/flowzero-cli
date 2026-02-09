"""Shared utilities for CLI commands."""
from rich.console import Console

from flowzero.config import config
from flowzero.storage.database import Database
from flowzero.api.planet import PlanetAPIClient
from flowzero.api.s3 import S3Client
from flowzero.downloaders.parallel import ParallelDownloader

# Global console for consistent output
console = Console()


def get_database():
    """Get initialized database."""
    return Database()


def get_planet_client(api_key=None):
    """Get initialized Planet API client."""
    return PlanetAPIClient(api_key or config.pl_api_key)


def get_s3_client():
    """Get initialized S3 client."""
    return S3Client()


def get_downloader(s3_client=None, max_workers=None):
    """Get initialized parallel downloader."""
    return ParallelDownloader(s3_client=s3_client, max_workers=max_workers)


def print_order_summary(order):
    """Print order details in consistent format."""
    console.print(f"[bold]Order ID:[/bold] {order.order_id}")
    console.print(f"[bold]AOI:[/bold] {order.aoi_name}")
    console.print(f"[bold]Type:[/bold] {order.order_type}")
    console.print(f"[bold]Status:[/bold] {order.status or 'unknown'}")
    console.print(f"[bold]Date Range:[/bold] {order.start_date} to {order.end_date}")
    if order.scenes_selected:
        console.print(f"[bold]Scenes:[/bold] {order.scenes_selected}")
    if order.quota_hectares:
        console.print(f"[bold]Quota:[/bold] {order.quota_hectares:,.0f} hectares")


def print_stats(stats):
    """Print database statistics."""
    console.print("\n[bold cyan]Database Statistics[/bold cyan]")
    console.print("=" * 60)
    console.print(f"Total orders: {stats['total_orders'] or 0}")
    console.print(f"Total batches: {stats['total_batches'] or 0}")
    console.print(f"Total AOIs: {stats['total_aois'] or 0}")
    console.print(f"Total scenes: {stats['total_scenes'] or 0}")

    quota = stats.get('total_quota_ha')
    console.print(f"Total quota: {quota:,.0f} hectares" if quota else "Total quota: 0 hectares")

    console.print(f"\nCompleted orders: {stats.get('completed_orders', 0) or 0}")
    console.print(f"Pending orders: {stats.get('pending_orders', 0) or 0}")
    console.print(f"Failed orders: {stats.get('failed_orders', 0) or 0}")
    console.print("=" * 60)
