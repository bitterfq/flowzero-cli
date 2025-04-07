import sys
import json
import click
import os
import requests
from datetime import datetime
from pathlib import Path
import geopandas as gpd
from generate_aoi import start_aoi_server
from rich.console import Console
from dotenv import load_dotenv
import urllib.parse
import re
import mimetypes

# Load environment variables
load_dotenv()

console = Console()
ORDERS_LOG_FILE = Path("orders.json")
API_URL = "https://api.planet.com/basemaps/v1/mosaics"
DOWNLOAD_DIR = Path("./Data")  # Save downloads locally

# Ensure Data directory exists
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

def normalize_aoi_name(raw_name: str) -> str:
    '''Normalize AOI name by removing prefixes and suffixes.'''
    # Remove "DrySpy_" or "AOI_" or other prefixes
    cleaned = re.sub(r"^(DrySpy_)?AOI_", "", raw_name)
    # Optionally remove known suffixes like _central, _north, etc.
    cleaned = re.sub(r"_(central|north|south|east|west)$", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def log_order(order_data):
    """Append an order log entry with metadata to orders.json."""
    entry = order_data.copy()
    entry["timestamp"] = datetime.now().isoformat()
    if ORDERS_LOG_FILE.exists():
        try:
            with ORDERS_LOG_FILE.open("r") as f:
                orders = json.load(f)
        except json.JSONDecodeError:
            orders = []
    else:
        orders = []
    orders.append(entry)
    with ORDERS_LOG_FILE.open("w") as f:
        json.dump(orders, f, indent=2)

@click.group()
def cli():
    """FlowZero - River Monitoring Tool using Planet Satellite Data"""
    pass

@cli.command()
def generate_aoi():
    """Launch interactive AOI generation web interface."""
    console.print("🌍 Launching AOI generation server...", style="bold green")
    console.print("📝 Open your browser at http://localhost:5000", style="bold blue")
    start_aoi_server()

@cli.command()
@click.option('--shp', required=True, type=click.Path(exists=True), help='Path to input Shapefile')
@click.option("--output", default="./geojsons", help="Directory to save GeoJSONs")
def convert_shp(shp, output):
    """Convert Shapefile to GeoJSON with proper CRS handling."""
    try:
        output_dir = Path(output)
        output_dir.mkdir(parents=True, exist_ok=True)
        shp_path = Path(shp)
        geojson_path = output_dir / f"{shp_path.stem}.geojson"
        gdf = gpd.read_file(shp_path)
        if gdf.crs is None or gdf.crs.to_string() == "unknown":
            gdf.set_crs(epsg=4326, inplace=True)
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
        gdf.to_file(geojson_path, driver="GeoJSON")
        console.print(f"✅ Shapefile converted successfully: {geojson_path}", style="bold green")
    except Exception as e:
        console.print(f"❌ Error converting Shapefile: {str(e)}", style="bold red")
        sys.exit(1)

@cli.command()
@click.option("--geojson", required=True, type=click.Path(exists=True), help="Path to AOI GeoJSON")
@click.option("--start-date", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", required=True, help="End date (YYYY-MM-DD)")
@click.option("--num-bands", type=click.Choice(['four_bands', 'eight_bands']), default='four_bands', help="Choose 4B or 8B imagery")
@click.option("--api-key", default=os.getenv("PL_API_KEY"), help="Planet API Key")
def submit(geojson, start_date, end_date, num_bands, api_key):
    """Submit a new PlanetScope imagery order (PSScope Scenes)."""
    try:
        # Convert dates to ISO 8601 format
        start_date_iso = f"{start_date}T00:00:00Z"
        end_date_iso = f"{end_date}T23:59:59Z"

        # Load AOI geometry from GeoJSON
        gdf = gpd.read_file(geojson)
        aoi = gdf.geometry.union_all().__geo_interface__

        # Select correct product bundle and item type
        if num_bands == "four_bands":
            product_bundle = "analytic_sr_udm2"  # ✅ FIXED
        else:
            product_bundle = "analytic_8b_sr_udm2"  # ✅ FIXED

        item_type = "PSScene"  # ✅ FIXED (Use latest PlanetScope item type)

        # Step 1: Search for available PlanetScope scenes
        search_url = "https://api.planet.com/data/v1/quick-search"
        search_payload = {
            "name": "Scene Search",
            "item_types": [item_type],
            "filter": {
                "type": "AndFilter",
                "config": [
                    {"type": "GeometryFilter", "field_name": "geometry", "config": aoi},
                    {"type": "DateRangeFilter", "field_name": "acquired", "config": {"gte": start_date_iso, "lte": end_date_iso}},
                    {"type": "RangeFilter", "field_name": "cloud_cover", "config": {"lte": 10}}  # Max 10% cloud cover
                ]
            }
        }

        search_headers = {"Content-Type": "application/json"}
        search_response = requests.post(search_url, json=search_payload, auth=(api_key, ""), headers=search_headers)

        if search_response.status_code != 200:
            console.print(f"❌ Failed to search for scenes: {search_response.text}", style="bold red")
            return

        search_results = search_response.json().get("features", [])
        if not search_results:
            console.print("[yellow]No PlanetScope scenes found in this date range and AOI.[/yellow]")
            return

        # Step 2: Extract item IDs
        item_ids = [scene["id"] for scene in search_results]

        # Step 3: Submit the order with item IDs
        order_url = "https://api.planet.com/compute/ops/orders/v2"
        order_payload = {
            "name": f"PSScope Order {Path(geojson).stem}",
            "products": [{
                "item_ids": item_ids,
                "item_type": item_type,
                "product_bundle": product_bundle
            }]
        }

        order_response = requests.post(order_url, json=order_payload, auth=(api_key, ""), headers=search_headers)

        if order_response.status_code == 202:
            order_info = order_response.json()
            order_id = order_info["id"]
            console.print(f"✅ Order submitted successfully! Order ID: {order_id}", style="bold green")

            # Log order
            log_order({
                "order_id": order_id,
                "aoi_name": normalize_aoi_name(Path(geojson).stem),
                "order_type": "PSScope",
                "start_date": start_date,
                "end_date": end_date,
                "num_bands": num_bands,
                "timestamp": datetime.now().isoformat()
            })
        else:
            console.print(f"❌ Order submission failed: {order_response.status_code} - {order_response.text}", style="bold red")
            return

    except Exception as e:
        console.print(f"❌ Error: {str(e)}", style="bold red")
        sys.exit(1)




@cli.command()
@click.option("--mosaic-name", required=True, help="Mosaic name from list_basemaps")
@click.option("--geojson", type=click.Path(exists=True), help="Path to AOI GeoJSON")
@click.option("--api-key", default=os.getenv("PL_API_KEY"), help="Planet API Key")
def order_basemap(mosaic_name, geojson, api_key):
    """Order a Basemap using a given Mosaic name and AOI."""
    if not api_key:
        console.print("[red]Error: API key is missing.[/red]")
        return

    if geojson:
        gdf = gpd.read_file(geojson)
        aoi = gdf.geometry.unary_union.__geo_interface__
    else:
        console.print("[red]Error: A GeoJSON file must be provided.[/red]")
        return

    order_payload = {
        "name": f"Basemap Order {mosaic_name}",
        "source_type": "basemaps",
        "products": [{"mosaic_name": mosaic_name, "geometry": aoi}],
        "tools": [{"clip": {}}]
    }

    response = requests.post("https://api.planet.com/compute/ops/orders/v2", json=order_payload, auth=(api_key, ""))
    if response.status_code == 202:
        order_info = response.json()
        console.print(f"✅ Order submitted successfully! Order ID: {order_info['id']}", style="bold green")
        log_order({
            "order_id": order_info['id'],
            "order_type": "Basemap (Composite)",
            "aoi_name": normalize_aoi_name(Path(geojson).stem),
            "mosaic_name": mosaic_name,
            "start_date": "N/A",
            "end_date": "N/A",
            "timestamp": datetime.now().isoformat()
        })

    else:
        console.print(f"[red]Error submitting order: {response.text}[/red]")
@cli.command()
@click.argument("order_id")
@click.option("--api-key", default=os.getenv("PL_API_KEY"), help="Planet API Key")
def check_order_status(order_id, api_key):
    """Check order status and download if completed."""
    response = requests.get(f"https://api.planet.com/compute/ops/orders/v2/{order_id}", auth=(api_key, ""))

    if response.status_code != 200:
        console.print(f"[❌] Error checking order status: {response.text}", style="bold red")
        return

    order_info = response.json()
    order_state = order_info["state"]
    console.print(f"[✅] Order Status: {order_state}")

    if order_state != "success":
        return

    # Load orders.json and get aoi_name and mosaic_name for this order
    aoi_name = "UnknownAOI"
    mosaic_name = "UnknownMosaic"

    if ORDERS_LOG_FILE.exists():
        with open(ORDERS_LOG_FILE, "r") as f:
            try:
                orders = json.load(f)
                match = next((o for o in orders if o["order_id"] == order_id), {})
                aoi_name_raw = match.get("aoi_name", "UnknownAOI")
                aoi_name = normalize_aoi_name(aoi_name_raw)
                mosaic_name = match.get("mosaic_name", "unknown_mosaic")
            except Exception as e:
                console.print(f"[yellow]⚠️ Could not read orders.json: {e}[/yellow]")

    order_products = order_info.get("products", [])
    is_basemap = "source_type" in order_info and order_info["source_type"] == "basemaps"

    if is_basemap:
        # Extract YYYY_MM from mosaic_name
        mosaic_date = "_".join(mosaic_name.split("_")[2:4])
        save_dir = Path(f"./Data/Basemaps/{aoi_name}/{mosaic_date}")
    else:
        num_bands = "8b" if "analytic_8b" in order_products[0]["product_bundle"] else "4b"
        save_dir = Path(f"./Data/PSScopeScenes/{aoi_name}/{num_bands}")

    save_dir.mkdir(parents=True, exist_ok=True)

    # Download files
    download_links = order_info["_links"].get("results", [])
    if not download_links:
        console.print("[⚠️] No downloadable files found.")
        return

    console.print(f"[⬇️] Downloading {len(download_links)} files to {save_dir}")

    for idx, link in enumerate(download_links):
        file_url = link['location']
        original_filename = Path(link.get("name", f"file_{idx}")).name
        file_path = save_dir / original_filename

        console.print(f"[📥] Downloading: {original_filename}...")
        r = requests.get(file_url, stream=True)
        with open(file_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        console.print(f"[✅] Downloaded {idx+1}/{len(download_links)}: {file_path}")

    # Save metadata
    metadata_path = save_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(order_info, f, indent=2)

    console.print(f"[🎉] Download complete! Files saved in: {save_dir}", style="bold green")



@cli.command()
@click.option("--start-date", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", required=True, help="End date (YYYY-MM-DD)")
@click.option("--api-key", default=os.getenv("PL_API_KEY"), help="Planet API Key")
def list_basemaps(start_date, end_date, api_key):
    """List available basemaps within a date range."""
    if not api_key:
        console.print("[red]Error: API key is missing.[/red]")
        return

    url = "https://api.planet.com/basemaps/v1/mosaics"
    all_mosaics = []

    while url:
        response = requests.get(url, auth=(api_key, ""))
        if response.status_code != 200:
            console.print(f"[red]Error fetching basemaps: {response.text}[/red]")
            return

        data = response.json()
        mosaics = data.get("mosaics", [])
        all_mosaics.extend(mosaics)

        # Handle pagination
        url = data["_links"].get("_next") if "_links" in data else None

    console.print(f"[cyan]Total basemaps found: {len(all_mosaics)}[/cyan]")

    # Correct filtering
    filtered_mosaics = [
        m for m in all_mosaics
        if start_date <= m["first_acquired"][:10] <= end_date
    ]
    console.print(f"[blue]Basemaps count after filtering: {len(filtered_mosaics)}[/blue]")
    if not filtered_mosaics:
        console.print("[yellow]No matching basemaps found.[/yellow]")
        return

    console.print("[green]Matching Basemaps:[/green]")
    for mosaic in filtered_mosaics:
        console.print(f"Mosaic Name: {mosaic['name']} | ID: {mosaic['id']} | Acquired: {mosaic['first_acquired']}")


cli.add_command(convert_shp)
cli.add_command(order_basemap)
cli.add_command(submit)
cli.add_command(check_order_status)
cli.add_command(list_basemaps)
cli.add_command(generate_aoi)

if __name__ == '__main__':
    cli()
