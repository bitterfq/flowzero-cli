import sys
import json
import click
import os
import requests
import boto3
from datetime import datetime, timedelta
from pathlib import Path
import geopandas as gpd
from generate_aoi import start_aoi_server
from rich.console import Console
from dotenv import load_dotenv
import urllib.parse
import re
import mimetypes
import io
from itertools import groupby
from operator import itemgetter

# Load environment variables
load_dotenv()

console = Console()
ORDERS_LOG_FILE = Path("orders.json")
API_URL = "https://api.planet.com/basemaps/v1/mosaics"

# Initialize S3 client
s3 = boto3.client(
    's3',
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)
S3_BUCKET = "flowzero"

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
@click.option("--bundle", default=None, help="Override bundle name to use")
def submit(geojson, start_date, end_date, num_bands, api_key, bundle):
    """Submit a new PlanetScope imagery order (PSScope Scenes) with AOI clipping."""
    try:
        # Convert dates to ISO 8601 format
        start_date_iso = f"{start_date}T00:00:00Z"
        end_date_iso = f"{end_date}T23:59:59Z"

        # Load AOI geometry from GeoJSON
        gdf = gpd.read_file(geojson)
        aoi = gdf.geometry.union_all().__geo_interface__

        # Show AOI information
        aoi_area_sqkm = gdf.area.sum() / 1000000  # Convert from sq meters to sq km
        console.print(f"[✓] AOI area: {aoi_area_sqkm:.2f} sq km", style="bold blue")

        # Determine product bundle based on date range and number of bands
        start_year = int(start_date.split('-')[0])
        
        if bundle:
            # Use override if provided
            product_bundle = bundle
            console.print(f"[✅] Using override bundle: {product_bundle}", style="bold blue")
        elif num_bands == "four_bands":
            if start_year < 2022:
                # For historical 4-band data (pre-2022), try a valid bundle type for Orders API
                product_bundle = "analytic_sr_udm2"  # Try this bundle name for 2021 data
                console.print(f"[✅] Using historical 4-band surface reflectance: {product_bundle}", style="bold blue")
            else:
                # For recent 4-band data (2022+), use analytic_sr_udm2
                product_bundle = "analytic_sr_udm2"
                console.print(f"[✅] Using recent 4-band surface reflectance: {product_bundle}", style="bold blue")
        else:
            # 8-band data (only available after April 2022)
            if start_year < 2022:
                product_bundle = "analytic_sr_udm2"  # Try this for 8-band too
                console.print(f"[✅] Using historical 8-band surface reflectance: {product_bundle}", style="bold blue")
            else:
                product_bundle = "analytic_8b_sr_udm2"
                console.print(f"[✅] Using recent 8-band surface reflectance: {product_bundle}", style="bold blue")

        item_type = "PSScene"

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
                    {"type": "RangeFilter", "field_name": "cloud_cover", "config": {"lte": 0.0}}  # 0% cloud cover
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
            console.print("[yellow]No 100% cloud-free PlanetScope scenes found in this date range and AOI.[/yellow]")
            return

        console.print(f"[✅] Found {len(search_results)} cloud-free scenes", style="bold green")

        # Get a sample of up to 100 scenes for ordering (Planet's documented limit)
        if len(search_results) > 100:
            console.print(f"[⚠️] Found {len(search_results)} scenes, but Planet limits orders to 100 scenes", style="bold yellow")
            
            # Organize scenes by week to ensure good temporal distribution
            scenes_by_week = {}
            for scene in search_results:
                # Get the acquisition date
                acq_date = scene["properties"]["acquired"][:10]  # YYYY-MM-DD format
                
                # Convert to datetime and get the week start date (Sunday)
                year, month, day = map(int, acq_date.split('-'))
                date_obj = datetime(year, month, day)
                days_to_sunday = date_obj.weekday() + 1  # +1 because weekday() considers Monday as 0
                if days_to_sunday == 7:  # If it's already Sunday
                    week_start = date_obj
                else:
                    # Get previous Sunday
                    week_start = date_obj - timedelta(days=days_to_sunday)
                
                week_key = week_start.strftime('%Y-%m-%d')
                
                if week_key not in scenes_by_week:
                    scenes_by_week[week_key] = []
                
                scenes_by_week[week_key].append(scene)
            
            # Select one scene per week (the first/earliest for each week)
            selected_scenes = []
            for week, week_scenes in sorted(scenes_by_week.items()):
                # Sort by acquisition date
                sorted_scenes = sorted(week_scenes, key=lambda s: s["properties"]["acquired"])
                selected_scenes.append(sorted_scenes[0])  # Take the first scene of each week
            
            console.print(f"[✓] Selected {len(selected_scenes)} scenes (one per week)", style="bold blue")
            
            # If still too many, take a maximum of 100
            if len(selected_scenes) > 100:
                selected_scenes = selected_scenes[:100]
                console.print(f"[⚠️] Trimmed to 100 scenes (Planet's limit)", style="bold yellow")
                
            sampled_scenes = selected_scenes
        else:
            sampled_scenes = search_results
            console.print(f"[✓] Using all {len(sampled_scenes)} scenes (under Planet's limit of 100)", style="bold blue")
            
        # Extract IDs
        item_ids = [scene["id"] for scene in sampled_scenes]

        # Try different bundle naming variations if needed
        bundle_variations = [
            product_bundle,          # First try the selected bundle
            "analytic_sr_udm2",      # Common for both 4-band and 8-band SR
            "analytic_udm2",         # With UDM2 mask
            "visual"                 # Last resort: visual product
        ]
        
        # Step 2: Try ordering with different bundle names if needed
        order_url = "https://api.planet.com/compute/ops/orders/v2"
        order_success = False
        
        for try_bundle in bundle_variations:
            order_payload = {
                "name": f"PSScope Order {Path(geojson).stem}",
                "products": [{
                    "item_ids": item_ids,
                    "item_type": item_type,
                    "product_bundle": try_bundle
                }],
                "tools": [
                    {
                        "clip": {
                            "aoi": aoi
                        }
                    }
                ]
            }

            console.print(f"[🔍] Trying order with product bundle: {try_bundle} (WITH CLIPPING)", style="bold blue")
            order_response = requests.post(order_url, json=order_payload, auth=(api_key, ""), headers=search_headers)

            if order_response.status_code == 202:
                order_info = order_response.json()
                order_id = order_info["id"]
                console.print(f"✅ Order submitted successfully with bundle '{try_bundle}'! Order ID: {order_id}", style="bold green")
                console.print(f"[✅] AOI clipping ENABLED - output will be clipped to {aoi_area_sqkm:.2f} sq km", style="bold green")
                
                # Log order with successful bundle
                log_order({
                    "order_id": order_id,
                    "aoi_name": normalize_aoi_name(Path(geojson).stem),
                    "order_type": "PSScope",
                    "start_date": start_date,
                    "end_date": end_date,
                    "num_bands": num_bands,
                    "product_bundle": try_bundle,
                    "clipped": True,
                    "aoi_area_sqkm": aoi_area_sqkm,
                    "timestamp": datetime.now().isoformat()
                })
                
                order_success = True
                break
            else:
                console.print(f"[⚠️] Bundle '{try_bundle}' failed: {order_response.status_code} - {order_response.text[:100]}...", style="yellow")
        
        if not order_success:
            console.print(f"❌ Order submission failed with all bundle variations. Try with a different date range or API key.", style="bold red")

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

def extract_date_from_filename(filename):
    """Extract the acquisition date from Planet product filename."""
    # Planet filenames typically contain date info in format like yyyymmdd
    pattern = r"(\d{4})(\d{2})(\d{2})_"
    match = re.search(pattern, filename)
    if match:
        year, month, day = match.groups()
        return f"{year}_{month}_{day}"
    return None

def extract_scene_id(filename):
    """Extract scene ID from Planet product filename."""
    # Scene ID typically follows the date and is before an underscore or dot
    pattern = r"\d{8}_(\w+)_"
    match = re.search(pattern, filename)
    if match:
        return match.group(1)
    return None

def get_week_start_date(date_str):
    """Get start of week (Sunday) for a given date string (YYYY_MM_DD)."""
    year, month, day = map(int, date_str.split('_'))
    date_obj = datetime(year, month, day)
    days_to_sunday = date_obj.weekday() + 1  # +1 because weekday() considers Monday as 0
    if days_to_sunday == 7:  # If it's already Sunday
        return date_str
    # Get previous Sunday
    sunday = date_obj - timedelta(days=days_to_sunday)
    return sunday.strftime('%Y_%m_%d')

@cli.command()
@click.argument("order_id")
@click.option("--api-key", default=os.getenv("PL_API_KEY"), help="Planet API Key")
def check_order_status(order_id, api_key):
    """Check order status and upload to S3 if completed."""
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
    order_type = "Unknown"
    num_bands = "four_bands"  # Default
    product_bundle = None

    if ORDERS_LOG_FILE.exists():
        with open(ORDERS_LOG_FILE, "r") as f:
            try:
                orders = json.load(f)
                match = next((o for o in orders if o["order_id"] == order_id), {})
                aoi_name_raw = match.get("aoi_name", "UnknownAOI")
                aoi_name = normalize_aoi_name(aoi_name_raw)
                mosaic_name = match.get("mosaic_name", "unknown_mosaic")
                order_type = match.get("order_type", "Unknown")
                num_bands = match.get("num_bands", "four_bands")
                product_bundle = match.get("product_bundle")
                console.print(f"[✅] Found order metadata: AOI={aoi_name}, Type={order_type}, Bundle={product_bundle}", style="bold green")
            except Exception as e:
                console.print(f"[yellow]⚠️ Could not read orders.json: {e}[/yellow]")

    is_basemap = "source_type" in order_info and order_info["source_type"] == "basemaps"

    # Download links
    download_links = order_info["_links"].get("results", [])
    if not download_links:
        console.print("[⚠️] No downloadable files found.")
        return

    # For PSScope: Process files according to requirements
    if order_type == "PSScope" and num_bands == "four_bands":
        console.print(f"[🔍] Processing PSScope Order - Organizing by week...")
        
        # First pass: collect metadata about each image
        image_metadata = []
        
        # Track files we've already processed to avoid duplicates
        processed_filenames = set()
        
        for link in download_links:
            filename = Path(link.get("name", "")).name
            
            # Skip if already processed
            if filename in processed_filenames:
                continue
                
            processed_filenames.add(filename)
            
            # Skip non-TIFF files, XML files, or UDM files
            if not filename.lower().endswith('.tif') or 'udm' in filename.lower() or filename.lower().endswith('.xml'):
                continue
                
            # Extract date from filename
            date_str = extract_date_from_filename(filename)
            if not date_str:
                console.print(f"[yellow]⚠️ Could not extract date from filename: {filename}[/yellow]")
                continue
                
            # Get week start date (Sunday)
            week_start = get_week_start_date(date_str)
            scene_id = extract_scene_id(filename) or "unknown"
            
            # Extract cloud cover if available in metadata
            cloud_cover = 0  # Assuming 0 for now since we already filtered by cloud cover in the search
            
            image_metadata.append({
                'filename': filename,
                'date': date_str,
                'week_start': week_start, 
                'scene_id': scene_id,
                'cloud_cover': cloud_cover,
                'url': link.get('location'),
                'size': link.get('length', 0)
            })
        
        # Group by week and select best image per week (lowest cloud cover, or first if tied)
        weeks = {}
        for img in sorted(image_metadata, key=lambda x: (x['week_start'], x['cloud_cover'], x['date'])):
            week = img['week_start']
            if week not in weeks:
                weeks[week] = img  # Take first image with lowest cloud cover for each week
        
        console.print(f"[✅] Found {len(image_metadata)} images across {len(weeks)} weeks")
        
        # Upload selected images to S3
        s3_path_prefix = f"planetscope analytic/four_bands/{aoi_name}"
        
        for week, img in weeks.items():
            filename = img['filename']
            s3_key = f"{s3_path_prefix}/{img['date']}_{img['scene_id']}.tiff"
            
            console.print(f"[⬆️] Uploading week {week} image: {filename} -> s3://{S3_BUCKET}/{s3_key}")
            
            # Download and upload directly to S3 without saving locally
            r = requests.get(img['url'], stream=True)
            if r.status_code == 200:
                try:
                    # Upload to S3 using the content from memory
                    s3.upload_fileobj(
                        io.BytesIO(r.content),
                        S3_BUCKET,
                        s3_key
                    )
                    console.print(f"[✅] Successfully uploaded to S3: s3://{S3_BUCKET}/{s3_key}")
                except Exception as e:
                    console.print(f"[❌] Error uploading to S3: {str(e)}", style="bold red")
            else:
                console.print(f"[❌] Failed to download image: {r.status_code}", style="bold red")
                
    # For Basemap: Upload all files to appropriate S3 path
    elif is_basemap or order_type == "Basemap (Composite)":
        # Extract YYYY_MM from mosaic_name (e.g., global_monthly_2024_01_mosaic)
        mosaic_parts = mosaic_name.split("_")
        if len(mosaic_parts) >= 4 and len(mosaic_parts[2]) == 4:  # Assuming YYYY format in position 2
            mosaic_date = f"{mosaic_parts[2]}_{mosaic_parts[3]}"
        else:
            # Fallback if we can't parse the date from mosaic name
            mosaic_date = "unknown_date"
            
        s3_path_prefix = f"basemaps/{aoi_name}/{mosaic_date}"
        console.print(f"[⬆️] Uploading Basemap files to S3 path: s3://{S3_BUCKET}/{s3_path_prefix}")
        
        for link in download_links:
            filename = Path(link.get("name", "")).name
            s3_key = f"{s3_path_prefix}/{filename}"
            
            console.print(f"[⬆️] Downloading and uploading: {filename}")
            r = requests.get(link.get('location'), stream=True)
            if r.status_code == 200:
                try:
                    # Upload to S3 directly from memory
                    s3.upload_fileobj(
                        io.BytesIO(r.content),
                        S3_BUCKET,
                        s3_key
                    )
                    console.print(f"[✅] Successfully uploaded to S3: s3://{S3_BUCKET}/{s3_key}")
                except Exception as e:
                    console.print(f"[❌] Error uploading to S3: {str(e)}", style="bold red")
            else:
                console.print(f"[❌] Failed to download file: {r.status_code}", style="bold red")
    
    # Save order metadata to S3
    try:
        metadata_json = json.dumps(order_info, indent=2)
        s3_metadata_path = ""
        
        if is_basemap or order_type == "Basemap (Composite)":
            s3_metadata_path = f"basemaps/{aoi_name}/{mosaic_date}/metadata.json"
        else:
            s3_metadata_path = f"planetscope analytic/four_bands/{aoi_name}/metadata.json"
            
        s3.put_object(
            Body=metadata_json,
            Bucket=S3_BUCKET,
            Key=s3_metadata_path
        )
        console.print(f"[✅] Order metadata saved to S3: s3://{S3_BUCKET}/{s3_metadata_path}")
    except Exception as e:
        console.print(f"[❌] Error saving metadata to S3: {str(e)}", style="bold red")

    console.print(f"[🎉] Order processing complete! All files uploaded to S3.", style="bold green")


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