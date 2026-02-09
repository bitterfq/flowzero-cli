"""Basemap commands."""
from pathlib import Path

import click
import geopandas as gpd

from flowzero.cli.common import console, get_database, get_planet_client
from flowzero.models.order import Order
from flowzero.utils.geometry import normalize_aoi_name


@click.command(name="list-basemaps")
@click.option("--start-date", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", required=True, help="End date (YYYY-MM-DD)")
@click.option("--api-key", default=None, help="Planet API Key")
def list_basemaps(start_date, end_date, api_key):
    """List available Planet Basemap mosaics within a date range."""
    planet = get_planet_client(api_key)

    console.print(f"[bold]Searching for basemaps from {start_date} to {end_date}...[/bold]")

    try:
        mosaics = planet.list_basemaps(start_date, end_date)
    except Exception as e:
        console.print(f"[red]Error fetching basemaps: {e}[/red]")
        return

    if not mosaics:
        console.print("[yellow]No matching basemaps found.[/yellow]")
        return

    console.print(f"\n[bold cyan]Found {len(mosaics)} basemaps[/bold cyan]\n")

    for mosaic in mosaics:
        console.print(f"[bold]{mosaic['name']}[/bold]")
        console.print(f"  ID: {mosaic['id']}")
        console.print(f"  Acquired: {mosaic.get('first_acquired', 'N/A')}")
        console.print()


@click.command(name="order-basemap")
@click.option("--mosaic-name", required=True, help="Mosaic name from list-basemaps")
@click.option("--geojson", required=True, type=click.Path(exists=True), help="Path to AOI GeoJSON")
@click.option("--api-key", default=None, help="Planet API Key")
def order_basemap(mosaic_name, geojson, api_key):
    """Order a Planet Basemap using a given Mosaic name and AOI."""
    db = get_database()
    planet = get_planet_client(api_key)

    # Load AOI
    gdf = gpd.read_file(geojson)
    gdf = gdf.to_crs(epsg=4326)
    aoi = gdf.geometry.unary_union.__geo_interface__
    aoi_name = normalize_aoi_name(Path(geojson).stem)

    console.print(f"[bold]AOI:[/bold] {aoi_name}")
    console.print(f"[bold]Mosaic:[/bold] {mosaic_name}")

    # Submit order
    try:
        order_response = planet.order_basemap(mosaic_name, aoi)
        order_id = order_response["id"]

        console.print(f"[green]Order submitted successfully![/green]")
        console.print(f"[bold]Order ID:[/bold] {order_id}")

        # Save to database
        order = Order(
            order_id=order_id,
            aoi_name=aoi_name,
            order_type="Basemap (Composite)",
            start_date="N/A",
            end_date="N/A",
            status="queued",
            mosaic_name=mosaic_name,
        )

        db.save_order(order)
        console.print("[dim]Order saved to database[/dim]")

    except Exception as e:
        console.print(f"[red]Error submitting order: {e}[/red]")
