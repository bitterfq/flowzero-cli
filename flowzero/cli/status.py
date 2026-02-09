"""Order status checking commands with parallel downloads."""
import io
from pathlib import Path
from collections import defaultdict

import click
import requests

from flowzero.config import config
from flowzero.cli.common import (
    console,
    get_database,
    get_planet_client,
    get_s3_client,
    get_downloader,
)
from flowzero.utils.dates import extract_date_from_filename, extract_scene_id, get_week_start_date
from flowzero.utils.geometry import normalize_aoi_name


@click.command(name="check-order-status")
@click.argument("order_id")
@click.option("--api-key", default=None, help="Planet API Key (default: from env)")
@click.option("--output", default="s3", help="Output location: 's3' or local directory path")
@click.option("--overwrite", is_flag=True, help="Re-download even if files already exist")
def check_order_status(order_id, api_key, output, overwrite):
    """Check order status and download completed files."""
    db = get_database()
    planet = get_planet_client(api_key)

    # Get order from database
    order = db.get_order(order_id)
    if order:
        console.print(f"[bold]Order found in database:[/bold] {order.aoi_name}")
        console.print(f"[bold]Current status:[/bold] {order.status or 'unknown'}")
    else:
        console.print(f"[yellow]Order not in database, checking Planet API...[/yellow]")

    # Check status from Planet
    try:
        order_info = planet.get_order_status(order_id)
    except Exception as e:
        console.print(f"[red]Error checking order status: {e}[/red]")
        return

    order_state = order_info["state"]
    console.print(f"[bold]Planet API Status:[/bold] {order_state}")

    # Update database
    db.update_order_status(order_id, order_state)

    # Handle different states
    if order_state == "success":
        console.print("[green]Order complete! Downloading files...[/green]")
    elif order_state == "partial":
        console.print(
            "[yellow]Order is partial - some files may have failed. Downloading available files...[/yellow]"
        )
    elif order_state == "failed":
        error_hints = order_info.get("error_hints", [])
        console.print(f"[red]Order failed permanently.[/red]")
        if error_hints:
            console.print(f"[red]Error hints: {', '.join(error_hints)}[/red]")
        return
    elif order_state == "cancelled":
        console.print("[red]Order was cancelled and will not be completed.[/red]")
        return
    elif order_state in ("queued", "running"):
        console.print(f"[yellow]Order is {order_state}. Try again later.[/yellow]")
        return
    else:
        console.print(f"[yellow]Unknown order state: {order_state}[/yellow]")
        return

    # Get metadata from database or order info
    if order:
        aoi_name = normalize_aoi_name(order.aoi_name)
        order_type = order.order_type
    else:
        aoi_name = "UnknownAOI"
        order_type = "PSScope"

    is_basemap = "source_type" in order_info and order_info["source_type"] == "basemaps"
    download_links = order_info["_links"].get("results", [])

    if not download_links:
        console.print("[yellow]No downloadable files found.[/yellow]")
        return

    # Determine output location
    use_s3 = output.lower() == "s3"
    if use_s3:
        s3_client = get_s3_client()
        console.print(f"[bold]Uploading to S3 bucket:[/bold] {config.s3_bucket}")
    else:
        s3_client = None
        local_output_dir = Path(output)
        local_output_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"[bold]Downloading to:[/bold] {local_output_dir}")

    # Download files
    if order_type == "PSScope" or not is_basemap:
        _download_psscope_order(
            download_links, aoi_name, use_s3, s3_client, local_output_dir if not use_s3 else None, overwrite
        )
    elif is_basemap:
        _download_basemap_order(
            download_links,
            aoi_name,
            order.mosaic_name if order else "unknown_mosaic",
            use_s3,
            s3_client,
            local_output_dir if not use_s3 else None,
            overwrite,
        )

    console.print("[green]Order processing complete![/green]")


def _download_psscope_order(download_links, aoi_name, use_s3, s3_client, local_output_dir, overwrite):
    """Download PlanetScope order files organized by week."""
    console.print("[bold]Processing PlanetScope Order - Organizing by week...[/bold]")

    # Extract image metadata
    image_metadata = []
    processed_filenames = set()

    for link in download_links:
        filename = Path(link.get("name", "")).name
        if filename in processed_filenames:
            continue
        processed_filenames.add(filename)

        # Skip non-image files
        if not filename.lower().endswith(".tif") or "udm" in filename.lower() or filename.lower().endswith(".xml"):
            continue

        date_str = extract_date_from_filename(filename)
        if not date_str:
            console.print(f"[yellow]Could not extract date from: {filename}[/yellow]")
            continue

        week_start = get_week_start_date(date_str)
        scene_id = extract_scene_id(filename) or "unknown"

        image_metadata.append(
            {
                "filename": filename,
                "date": date_str,
                "week_start": week_start,
                "scene_id": scene_id,
                "url": link.get("location"),
            }
        )

    # Select one image per week
    weeks = {}
    for img in sorted(image_metadata, key=lambda x: (x["week_start"], x["date"])):
        week = img["week_start"]
        if week not in weeks:
            weeks[week] = img

    console.print(f"[bold]Found {len(image_metadata)} images across {len(weeks)} weeks[/bold]")

    # Prepare download tasks
    relative_path = f"planetscope analytic/four_bands/{aoi_name}"
    download_tasks = []

    for week, img in weeks.items():
        target_filename = f"{img['date']}_{img['scene_id']}.tiff"

        if use_s3:
            s3_key = f"{relative_path}/{target_filename}"
            download_tasks.append((img["url"], s3_key))
        else:
            local_path = local_output_dir / relative_path / target_filename
            download_tasks.append((img["url"], str(local_path)))

    # Try s5cmd first for S3 uploads (20-50x faster than boto3)
    if use_s3:
        from flowzero.downloaders.s5cmd import S5cmdDownloader
        try:
            s5cmd_downloader = S5cmdDownloader(s3_bucket=config.s3_bucket)
            if s5cmd_downloader.available:
                console.print(f"[bold cyan]Using s5cmd for ultra-fast S3 uploads[/bold cyan]")
                console.print(f"[bold]Downloading {len(download_tasks)} files...[/bold]")
                results = s5cmd_downloader.download_batch(download_tasks)
                downloaded = sum(1 for success, _ in results if success)
                failed = sum(1 for success, _ in results if not success)
                console.print(f"\n[bold]Summary:[/bold] {downloaded} downloaded, 0 skipped, {failed} failed")
                return
            else:
                console.print("[yellow]s5cmd not available, using boto3 parallel downloader[/yellow]")
        except Exception as e:
            console.print(f"[yellow]s5cmd error: {e}, using boto3 parallel downloader[/yellow]")

    downloader = get_downloader(s3_client=s3_client)
    check_exists_func = s3_client.key_exists if use_s3 else lambda p: Path(p).exists()

    console.print(f"[bold]Downloading {len(download_tasks)} files...[/bold]")

    skipped = 0
    downloaded = 0
    failed = 0

    for success, destination, error in downloader.download_batch(
        download_tasks, is_s3=use_s3, overwrite=overwrite, check_exists_func=check_exists_func
    ):
        if error == "skipped":
            skipped += 1
            console.print(f"[dim]Skipped (exists): {destination}[/dim]")
        elif success:
            downloaded += 1
            console.print(f"[green]Downloaded: {destination}[/green]")
        else:
            failed += 1
            console.print(f"[red]Failed: {destination} - {error}[/red]")

    console.print(f"\n[bold]Summary:[/bold] {downloaded} downloaded, {skipped} skipped, {failed} failed")


def _download_basemap_order(
    download_links, aoi_name, mosaic_name, use_s3, s3_client, local_output_dir, overwrite
):
    """Download basemap order files."""
    console.print("[bold]Processing Basemap Order...[/bold]")

    # Extract date from mosaic name
    mosaic_parts = mosaic_name.split("_")
    if len(mosaic_parts) >= 4 and len(mosaic_parts[2]) == 4:
        mosaic_date = f"{mosaic_parts[2]}_{mosaic_parts[3]}"
    else:
        mosaic_date = "unknown_date"

    relative_path = f"basemaps/{aoi_name}/{mosaic_date}"

    # Prepare download tasks
    download_tasks = []
    for link in download_links:
        filename = Path(link.get("name", "")).name

        if use_s3:
            s3_key = f"{relative_path}/{filename}"
            download_tasks.append((link.get("location"), s3_key))
        else:
            local_path = local_output_dir / relative_path / filename
            download_tasks.append((link.get("location"), str(local_path)))

    # Try s5cmd first for S3 uploads (20-50x faster than boto3)
    if use_s3:
        from flowzero.downloaders.s5cmd import S5cmdDownloader
        try:
            s5cmd_downloader = S5cmdDownloader(s3_bucket=config.s3_bucket)
            if s5cmd_downloader.available:
                console.print(f"[bold cyan]Using s5cmd for ultra-fast S3 uploads[/bold cyan]")
                console.print(f"[bold]Downloading {len(download_tasks)} files...[/bold]")
                results = s5cmd_downloader.download_batch(download_tasks)
                downloaded = sum(1 for success, _ in results if success)
                failed = sum(1 for success, _ in results if not success)
                console.print(f"\n[bold]Summary:[/bold] {downloaded} downloaded, 0 skipped, {failed} failed")
                return
            else:
                console.print("[yellow]s5cmd not available, using boto3 parallel downloader[/yellow]")
        except Exception as e:
            console.print(f"[yellow]s5cmd error: {e}, using boto3 parallel downloader[/yellow]")

    downloader = get_downloader(s3_client=s3_client)
    check_exists_func = s3_client.key_exists if use_s3 else lambda p: Path(p).exists()

    console.print(f"[bold]Downloading {len(download_tasks)} files...[/bold]")

    skipped = 0
    downloaded = 0
    failed = 0

    for success, destination, error in downloader.download_batch(
        download_tasks, is_s3=use_s3, overwrite=overwrite, check_exists_func=check_exists_func
    ):
        if error == "skipped":
            skipped += 1
            console.print(f"[dim]Skipped (exists): {destination}[/dim]")
        elif success:
            downloaded += 1
            console.print(f"[green]Downloaded: {destination}[/green]")
        else:
            failed += 1
            console.print(f"[red]Failed: {destination} - {error}[/red]")

    console.print(f"\n[bold]Summary:[/bold] {downloaded} downloaded, {skipped} skipped, {failed} failed")


@click.command(name="batch-check-status")
@click.argument("batch_id")
@click.option("--api-key", default=None, help="Planet API Key (default: from env)")
@click.option("--output", default="s3", help="Output location: 's3' or local directory path")
@click.option("--overwrite", is_flag=True, help="Re-download even if files already exist")
@click.option("--force", is_flag=True, help="Force recheck all orders, even if already completed")
def batch_check_status(batch_id, api_key, output, overwrite, force):
    """Check status and download all orders in a batch."""
    db = get_database()
    planet = get_planet_client(api_key)

    # Get all orders in batch
    orders = db.get_batch_orders(batch_id)

    if not orders:
        console.print(f"[yellow]No orders found with batch_id: {batch_id}[/yellow]")

        # Show available batches
        console.print("\n[dim]Available batch IDs:[/dim]")
        batches = db.list_batches()
        if batches:
            for bid, count in batches:
                console.print(f"  {bid} ({count} orders)")
        return

    console.print(f"[bold cyan]Found {len(orders)} orders in batch: {batch_id}[/bold cyan]\n")

    # Track results
    results = {"success": [], "partial": [], "pending": [], "failed": [], "cancelled": [], "skipped": []}

    for i, order in enumerate(orders, 1):
        console.print(f"[{i}/{len(orders)}] Checking {order.aoi_name} ({order.start_date} to {order.end_date})...")
        console.print(f"  Order ID: {order.order_id}")

        # Skip if already successful (unless force)
        if not force and order.status == "success":
            console.print("  [dim]Skipped (already completed)[/dim]\n")
            results["skipped"].append(order.order_id)
            continue

        # Skip permanently failed/cancelled
        if order.status in ["failed", "cancelled"]:
            console.print(f"  [dim]Skipped (status: {order.status})[/dim]\n")
            results[order.status].append(order.order_id)
            continue

        # Check status
        try:
            order_info = planet.get_order_status(order.order_id)
            order_state = order_info["state"]
            console.print(f"  Status: {order_state}")

            # Update database
            db.update_order_status(order.order_id, order_state)

            # Handle based on state
            if order_state == "success" or order_state == "partial":
                if order_state == "partial":
                    console.print("  [yellow]Partial order - some files may be missing, downloading available files...[/yellow]")
                else:
                    console.print("  [green]Downloading...[/green]")

                # Get download links
                download_links = order_info["_links"].get("results", [])
                if not download_links:
                    console.print("  [yellow]No downloadable files found[/yellow]\n")
                    results["failed"].append(order.order_id)
                    continue

                # Determine output location
                use_s3 = output.lower() == "s3"
                if use_s3:
                    s3_client = get_s3_client()
                else:
                    s3_client = None
                    local_output_dir = Path(output)
                    local_output_dir.mkdir(parents=True, exist_ok=True)

                # Determine order type
                is_basemap = "source_type" in order_info and order_info["source_type"] == "basemaps"
                aoi_name = normalize_aoi_name(order.aoi_name)

                # Download files based on order type
                try:
                    if order.order_type == "PSScope" or not is_basemap:
                        _download_psscope_order(
                            download_links,
                            aoi_name,
                            use_s3,
                            s3_client,
                            local_output_dir if not use_s3 else None,
                            overwrite
                        )
                    elif is_basemap:
                        _download_basemap_order(
                            download_links,
                            aoi_name,
                            order.mosaic_name if order.mosaic_name else "unknown_mosaic",
                            use_s3,
                            s3_client,
                            local_output_dir if not use_s3 else None,
                            overwrite
                        )

                    if order_state == "partial":
                        results["partial"].append(order.order_id)
                    else:
                        results["success"].append(order.order_id)
                    console.print("  [green]Download complete![/green]\n")
                except Exception as download_error:
                    console.print(f"  [red]Download error: {download_error}[/red]\n")
                    results["failed"].append(order.order_id)

            elif order_state in ["queued", "running"]:
                results["pending"].append(order.order_id)

            elif order_state == "failed":
                error_hints = order_info.get("error_hints", [])
                console.print(f"  [red]Failed: {', '.join(error_hints) if error_hints else 'No details'}[/red]")
                results["failed"].append(order.order_id)

            elif order_state == "cancelled":
                console.print("  [red]Cancelled[/red]")
                results["cancelled"].append(order.order_id)

        except Exception as e:
            console.print(f"  [red]Error: {e}[/red]")
            results["failed"].append(order.order_id)

        console.print()

    # Summary
    console.print("\n" + "=" * 60)
    console.print("[bold]Batch Status Check Summary[/bold]")
    console.print("=" * 60)
    console.print(f"[green]Completed & Downloaded: {len(results['success'])}[/green]")

    if results["partial"]:
        console.print(f"[yellow]Partial (some files missing): {len(results['partial'])}[/yellow]")

    if results["skipped"]:
        console.print(f"[dim]Skipped (already complete): {len(results['skipped'])}[/dim]")

    if results["pending"]:
        console.print(f"[yellow]Pending (queued/running): {len(results['pending'])}[/yellow]")

    if results["failed"]:
        console.print(f"[red]Failed: {len(results['failed'])}[/red]")

    if results["cancelled"]:
        console.print(f"[red]Cancelled: {len(results['cancelled'])}[/red]")

    if results["pending"]:
        console.print("\n[yellow]Run again later to check pending orders.[/yellow]")
