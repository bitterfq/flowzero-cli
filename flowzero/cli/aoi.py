"""AOI management commands."""
import sys
from pathlib import Path

import click
import geopandas as gpd

from flowzero.cli.common import console

# Add project root to path to import generate_aoi
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from generate_aoi import start_aoi_server
except ImportError:
    def start_aoi_server():
        console.print("[red]Error: generate_aoi.py not found in project root[/red]")
        raise click.Abort()


@click.command(name="generate-aoi")
def generate_aoi():
    """Launch interactive AOI generation web interface."""
    console.print("[green]Launching AOI generation server...[/green]")
    console.print("[bold cyan]Open your browser at http://localhost:5000[/bold cyan]")
    start_aoi_server()


@click.command(name="convert-shp")
@click.option("--shp", required=True, type=click.Path(exists=True), help="Path to input Shapefile")
@click.option("--output", default="./geojsons", help="Directory to save GeoJSONs")
def convert_shp(shp, output):
    """Convert Shapefile to GeoJSON with proper CRS handling."""
    try:
        output_dir = Path(output)
        output_dir.mkdir(parents=True, exist_ok=True)

        shp_path = Path(shp)
        geojson_path = output_dir / f"{shp_path.stem}.geojson"

        console.print(f"[bold]Reading shapefile:[/bold] {shp_path}")

        gdf = gpd.read_file(shp_path)

        # Handle CRS
        if gdf.crs is None or gdf.crs.to_string() == "unknown":
            console.print("[yellow]Warning: No CRS found, assuming EPSG:4326[/yellow]")
            gdf.set_crs(epsg=4326, inplace=True)
        elif gdf.crs.to_epsg() != 4326:
            console.print(f"[dim]Reprojecting from {gdf.crs} to EPSG:4326[/dim]")
            gdf = gdf.to_crs(epsg=4326)

        # Write GeoJSON
        gdf.to_file(geojson_path, driver="GeoJSON")

        console.print(f"[green]Shapefile converted successfully:[/green] {geojson_path}")
        console.print(f"[dim]Features: {len(gdf)}[/dim]")

    except Exception as e:
        console.print(f"[red]Error converting Shapefile: {e}[/red]")
        raise click.Abort()
