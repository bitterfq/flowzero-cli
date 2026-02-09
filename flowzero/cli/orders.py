"""Order submission commands with duplicate checking."""
import uuid
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import click
import geopandas as gpd

from flowzero.config import config
from flowzero.cli.common import console, get_database, get_planet_client
from flowzero.models.order import Order
from flowzero.utils.geometry import load_geojson, calculate_coverage, normalize_aoi_name
from flowzero.utils.dates import subdivide_date_range, get_interval_key


def select_scenes_by_cadence(features, aoi_geom, cadence, min_coverage_pct=None):
    """
    Select best scenes based on cadence.

    Returns:
        List of (feature, coverage_pct, date) tuples
    """
    min_coverage_pct = min_coverage_pct or config.min_coverage_pct

    scene_groups = defaultdict(list)

    for feature in features:
        props = feature["properties"]
        coverage_pct = calculate_coverage(feature["geometry"], aoi_geom)

        # Skip if coverage too low
        if coverage_pct < min_coverage_pct:
            continue

        date_str = props["acquired"][:10]
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        key = get_interval_key(date_obj, cadence)
        scene_groups[key].append((coverage_pct, date_obj, feature))

    # Sort each group by coverage descending, then date ascending; select first
    selected = []
    for group in scene_groups.values():
        group.sort(key=lambda x: (-x[0], x[1]))  # coverage desc, date asc
        coverage_pct, date, f = group[0]
        selected.append((f, coverage_pct, date))

    return selected


@click.command(name="submit")
@click.option("--geojson", required=True, type=click.Path(exists=True), help="Path to AOI GeoJSON")
@click.option("--start-date", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", required=True, help="End date (YYYY-MM-DD)")
@click.option(
    "--num-bands",
    type=click.Choice(["four_bands", "eight_bands"]),
    default="four_bands",
    help="Choose 4B or 8B imagery",
)
@click.option("--api-key", default=None, help="Planet API Key (default: from env)")
@click.option("--bundle", default=None, help="Override bundle name to use")
@click.option(
    "--cadence",
    type=click.Choice(["daily", "weekly", "monthly"]),
    default="weekly",
    help="Scene selection cadence",
)
@click.option("--skip-if-exists", is_flag=True, help="Skip if order already exists for this AOI/date range")
def submit(geojson, start_date, end_date, num_bands, api_key, bundle, cadence, skip_if_exists):
    """Submit a new PlanetScope imagery order."""
    db = get_database()
    planet = get_planet_client(api_key)

    # Load AOI
    aoi_geom, aoi_geojson, area_sqkm = load_geojson(geojson)
    aoi_name = normalize_aoi_name(Path(geojson).stem)

    console.print(f"[bold]AOI:[/bold] {aoi_name}")
    console.print(f"[bold]Area:[/bold] {area_sqkm:.2f} sq km")
    console.print(f"[bold]Date Range:[/bold] {start_date} to {end_date}")

    # Check for existing order
    if skip_if_exists:
        if db.has_completed_order(aoi_name, start_date, end_date):
            console.print("[yellow]Order already completed for this AOI/date range. Skipping.[/yellow]")
            existing = db.find_existing_order(aoi_name, start_date, end_date)
            console.print(f"[yellow]Existing order ID: {existing.order_id}[/yellow]")
            return

        existing = db.find_existing_order(aoi_name, start_date, end_date)
        if existing and existing.status in ["queued", "running"]:
            console.print(f"[yellow]Order already pending: {existing.order_id}[/yellow]")
            console.print(f"[yellow]Status: {existing.status}[/yellow]")
            return

    # Determine product bundle
    start_year = int(start_date.split("-")[0])
    if bundle:
        product_bundle = bundle
        console.print(f"[bold]Using override bundle:[/bold] {product_bundle}")
    elif num_bands == "four_bands":
        product_bundle = "ortho_analytic_4b_sr"
        console.print(f"[bold]Using 4-band surface reflectance:[/bold] {product_bundle}")
    else:
        product_bundle = "ortho_analytic_8b_sr" if start_year >= 2021 else "ortho_analytic_4b_sr"
        console.print(f"[bold]Using 8-band surface reflectance:[/bold] {product_bundle}")

    # Cross walk product bundle for ordering
    if product_bundle == "ortho_analytic_4b_sr":
        product_bundle_order = "analytic_sr_udm2"
    elif product_bundle == "ortho_analytic_8b_sr":
        product_bundle_order = "analytic_8b_sr_udm2"
    else:
        product_bundle_order = product_bundle

    # Search for scenes
    console.print("\n[bold]Searching for scenes...[/bold]")
    try:
        features = planet.search_scenes(
            aoi_geojson, f"{start_date}T00:00:00Z", f"{end_date}T23:59:59Z", product_bundle
        )
    except Exception as e:
        console.print(f"[red]Failed to search for scenes: {e}[/red]")
        return

    if not features:
        console.print("[yellow]No cloud-free PlanetScope scenes found.[/yellow]")
        return

    console.print(f"[bold]Found {len(features)} scenes matching initial criteria[/bold]")

    # Filter and select by cadence
    selected = select_scenes_by_cadence(features, aoi_geom, cadence)

    if not selected:
        console.print("[yellow]No full-coverage scenes matched filter.[/yellow]")
        return

    console.print(f"[green]Selected {len(selected)} best scenes ({cadence})[/green]")

    # Show selection
    for f, cov, dt in selected[:10]:  # Show first 10
        console.print(f"  {dt.date()} | ID: {f['id']} | Coverage: {cov:.2f}%")

    if len(selected) > 10:
        console.print(f"  ... and {len(selected) - 10} more")

    # Calculate quota
    quota_sqkm = area_sqkm * len(selected)
    quota_hectares = quota_sqkm * 100

    console.print(f"\n[bold cyan]Total quota:[/bold cyan] {quota_hectares:,.0f} hectares")

    # Confirm
    if not click.confirm("Proceed with order?"):
        console.print("[yellow]Order cancelled by user.[/yellow]")
        return

    # Submit order
    item_ids = [f["id"] for f, _, _ in selected]

    try:
        order_response = planet.submit_order(
            f"PSScope Order {aoi_name} {start_date} to {end_date}",
            item_ids,
            product_bundle_order,
            aoi_geojson,
        )

        order_id = order_response["id"]
        console.print(f"[green]Order submitted successfully![/green]")
        console.print(f"[bold]Order ID:[/bold] {order_id}")

        # Save to database
        order = Order(
            order_id=order_id,
            aoi_name=aoi_name,
            order_type="PSScope",
            start_date=start_date,
            end_date=end_date,
            status="queued",
            num_bands=num_bands,
            product_bundle=product_bundle,
            product_bundle_order=product_bundle_order,
            clipped=True,
            aoi_area_sqkm=area_sqkm,
            scenes_selected=len(selected),
            scenes_found=len(features),
            quota_hectares=quota_hectares,
        )

        db.save_order(order)
        console.print("[dim]Order saved to database[/dim]")

    except Exception as e:
        console.print(f"[red]Order submission failed: {e}[/red]")


@click.command(name="batch-submit")
@click.option("--shp", required=True, type=click.Path(exists=True), help="Path to Shapefile with AOIs")
@click.option("--gage-id-col", default="gage_id", help="Column name for gage ID (default: gage_id)")
@click.option("--start-date-col", default="start_date", help="Column name for start date")
@click.option("--end-date-col", default="end_date", help="Column name for end date")
@click.option(
    "--num-bands",
    type=click.Choice(["four_bands", "eight_bands"]),
    default="four_bands",
    help="Choose 4B or 8B imagery",
)
@click.option("--api-key", default=None, help="Planet API Key")
@click.option("--bundle", default=None, help="Override bundle name")
@click.option(
    "--cadence",
    type=click.Choice(["daily", "weekly", "monthly"]),
    default="weekly",
    help="Scene selection cadence",
)
@click.option("--max-months", default=6, type=int, help="Maximum months per order chunk (default: 6)")
@click.option("--dry-run", is_flag=True, help="Preview orders without submitting")
@click.option("--skip-existing", is_flag=True, help="Skip orders that already exist in database")
def batch_submit(
    shp,
    gage_id_col,
    start_date_col,
    end_date_col,
    num_bands,
    api_key,
    bundle,
    cadence,
    max_months,
    dry_run,
    skip_existing,
):
    """Submit multiple PlanetScope orders from a shapefile."""
    db = get_database()
    planet = get_planet_client(api_key)

    # Read shapefile
    gdf = gpd.read_file(shp)
    gdf = gdf.to_crs(epsg=4326)
    original_crs = gdf.crs
    equal_area_crs = "EPSG:6933"

    console.print(f"[bold cyan]Loaded shapefile with {len(gdf)} features[/bold cyan]")
    console.print(f"[dim]Columns: {', '.join(gdf.columns.tolist())}[/dim]")

    # Validate required columns
    required_cols = [gage_id_col, start_date_col, end_date_col]
    missing_cols = [col for col in required_cols if col not in gdf.columns]
    if missing_cols:
        console.print(f"[red]Error: Missing required columns: {missing_cols}[/red]")
        console.print(f"[yellow]Available columns: {gdf.columns.tolist()}[/yellow]")
        return

    # Prepare orders
    all_orders = []
    for idx, row in gdf.iterrows():
        gage_id = str(row[gage_id_col])
        start_date = str(row[start_date_col])
        end_date = str(row[end_date_col])

        # Parse dates
        try:
            start_dt = datetime.strptime(start_date.strip(), "%Y-%m-%d")
            end_dt = datetime.strptime(end_date.strip(), "%Y-%m-%d")
            start_date = start_dt.strftime("%Y-%m-%d")
            end_date = end_dt.strftime("%Y-%m-%d")
        except ValueError as e:
            console.print(f"[yellow]Skipping {gage_id}: Invalid date format ({e})[/yellow]")
            continue

        # Subdivide if needed
        date_chunks = subdivide_date_range(start_date, end_date, max_months)

        for chunk_start, chunk_end in date_chunks:
            all_orders.append(
                {
                    "gage_id": gage_id,
                    "start_date": chunk_start,
                    "end_date": chunk_end,
                    "geometry": row.geometry,
                }
            )

    console.print(f"\n[bold green]Prepared {len(all_orders)} orders from {len(gdf)} gages[/bold green]")

    # Generate batch ID
    batch_id = str(uuid.uuid4())
    console.print(f"\n[bold cyan]Batch ID: {batch_id}[/bold cyan]")

    if dry_run:
        console.print("\n[bold yellow]DRY RUN MODE - No orders will be submitted[/bold yellow]")

    # Determine product bundle
    if bundle:
        product_bundle = bundle
    elif num_bands == "four_bands":
        product_bundle = "ortho_analytic_4b_sr"
    else:
        earliest_year = min(int(o["start_date"].split("-")[0]) for o in all_orders)
        product_bundle = "ortho_analytic_8b_sr" if earliest_year >= 2021 else "ortho_analytic_4b_sr"

    console.print(f"\n[bold]Using bundle:[/bold] {product_bundle}")

    # Cross walk bundle
    if product_bundle == "ortho_analytic_4b_sr":
        product_bundle_order = "analytic_sr_udm2"
    elif product_bundle == "ortho_analytic_8b_sr":
        product_bundle_order = "analytic_8b_sr_udm2"
    else:
        product_bundle_order = product_bundle

    # Process orders
    results = {"submitted": [], "skipped": [], "failed": [], "no_scenes": []}

    console.print("\n[bold]Processing orders...[/bold]\n")

    for i, order_info in enumerate(all_orders, 1):
        gage_id = order_info["gage_id"]
        start_date = order_info["start_date"]
        end_date = order_info["end_date"]
        geom = order_info["geometry"]

        console.print(f"[{i}/{len(all_orders)}] {gage_id}: {start_date} to {end_date}...", end=" ")

        # Check for existing order
        if skip_existing:
            if db.has_completed_order(gage_id, start_date, end_date):
                console.print("[yellow]Already completed, skipping[/yellow]")
                results["skipped"].append(gage_id)
                continue

            existing = db.find_existing_order(gage_id, start_date, end_date)
            if existing and existing.status in ["queued", "running"]:
                console.print(f"[yellow]Already pending ({existing.order_id}), skipping[/yellow]")
                results["skipped"].append(gage_id)
                continue

        # Prepare geometry
        aoi_geom = geom
        aoi_geojson = aoi_geom.__geo_interface__
        geom_equal_area = gpd.GeoSeries([geom], crs=original_crs).to_crs(equal_area_crs)
        aoi_area_sqkm = geom_equal_area.area.iloc[0] / 1e6

        # Search scenes
        try:
            features = planet.search_scenes(
                aoi_geojson, f"{start_date}T00:00:00Z", f"{end_date}T23:59:59Z", product_bundle
            )

            if not features:
                console.print("[yellow]No scenes found[/yellow]")
                results["no_scenes"].append(gage_id)
                continue

            # Select scenes
            selected = select_scenes_by_cadence(features, aoi_geom, cadence)

            if not selected:
                console.print("[yellow]No full-coverage scenes[/yellow]")
                results["no_scenes"].append(gage_id)
                continue

            quota_hectares = aoi_area_sqkm * len(selected) * 100

            if dry_run:
                console.print(
                    f"[green]Would submit ({len(features)} found, {len(selected)} selected, {quota_hectares:,.0f} ha)[/green]"
                )
                results["submitted"].append(gage_id)
            else:
                # Submit order
                item_ids = [f["id"] for f, _, _ in selected]
                order_response = planet.submit_order(
                    f"PSScope Order {gage_id} {start_date} to {end_date}",
                    item_ids,
                    product_bundle_order,
                    aoi_geojson,
                )

                order_id = order_response["id"]
                console.print(
                    f"[green]Order {order_id[:8]}... ({len(features)} found, {len(selected)} selected, {quota_hectares:,.0f} ha)[/green]"
                )

                # Save to database
                order = Order(
                    order_id=order_id,
                    aoi_name=gage_id,
                    order_type="PSScope",
                    start_date=start_date,
                    end_date=end_date,
                    status="queued",
                    num_bands=num_bands,
                    product_bundle=product_bundle,
                    product_bundle_order=product_bundle_order,
                    batch_id=batch_id,
                    batch_order=True,
                    aoi_area_sqkm=aoi_area_sqkm,
                    scenes_selected=len(selected),
                    scenes_found=len(features),
                    quota_hectares=quota_hectares,
                )

                db.save_order(order)
                results["submitted"].append(gage_id)

        except Exception as e:
            console.print(f"[red]Failed: {e}[/red]")
            results["failed"].append(gage_id)

    # Summary
    console.print("\n" + "=" * 60)
    console.print("[bold]Batch Order Summary[/bold]")
    console.print("=" * 60)

    if dry_run:
        console.print(f"[green]Would submit: {len(results['submitted'])} orders[/green]")
    else:
        console.print(f"[green]Submitted: {len(results['submitted'])} orders[/green]")

    if results["skipped"]:
        console.print(f"[yellow]Skipped (already exist): {len(results['skipped'])}[/yellow]")

    if results["no_scenes"]:
        console.print(f"[yellow]No valid scenes: {len(results['no_scenes'])}[/yellow]")

    if results["failed"]:
        console.print(f"[red]Failed: {len(results['failed'])}[/red]")

    if not dry_run and results["submitted"]:
        console.print(f"\n[bold cyan]Batch ID: {batch_id}[/bold cyan]")
        console.print(f"[dim]Check status: flowzero batch-check-status {batch_id}[/dim]")


@click.command(name="search-scenes")
@click.option("--geojson", required=True, type=click.Path(exists=True), help="Path to AOI GeoJSON")
@click.option("--start-date", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", required=True, help="End date (YYYY-MM-DD)")
@click.option(
    "--num-bands",
    type=click.Choice(["four_bands", "eight_bands"]),
    default="four_bands",
    help="Choose 4B or 8B imagery",
)
@click.option("--bundle", default=None, help="Override bundle name")
@click.option(
    "--cadence",
    type=click.Choice(["daily", "weekly", "monthly"]),
    default="weekly",
    help="Scene selection cadence",
)
@click.option("--api-key", default=None, help="Planet API Key")
def search_scenes(geojson, start_date, end_date, num_bands, bundle, cadence, api_key):
    """Search for available PlanetScope scenes without placing an order."""
    planet = get_planet_client(api_key)

    # Load AOI
    aoi_geom, aoi_geojson, area_sqkm = load_geojson(geojson)
    aoi_name = Path(geojson).stem

    console.print(f"[bold]AOI:[/bold] {aoi_name}")
    console.print(f"[bold]Area:[/bold] {area_sqkm:.2f} sq km")

    # Determine product bundle
    start_year = int(start_date.split("-")[0])
    if bundle:
        product_bundle = bundle
    elif num_bands == "four_bands":
        product_bundle = "ortho_analytic_4b_sr"
    else:
        product_bundle = "ortho_analytic_8b_sr" if start_year >= 2021 else "ortho_analytic_4b_sr"

    console.print(f"[bold]Bundle:[/bold] {product_bundle}")

    # Search scenes
    console.print("\n[bold]Searching for scenes...[/bold]")

    try:
        features = planet.search_scenes(
            aoi_geojson, f"{start_date}T00:00:00Z", f"{end_date}T23:59:59Z", product_bundle
        )
    except Exception as e:
        console.print(f"[red]Search failed: {e}[/red]")
        return

    if not features:
        console.print("[yellow]No scenes found.[/yellow]")
        return

    console.print(f"[bold]Found {len(features)} scenes matching initial criteria[/bold]")

    # Filter and select
    selected = select_scenes_by_cadence(features, aoi_geom, cadence)

    if not selected:
        console.print("[yellow]No full-coverage scenes matched filter.[/yellow]")
        return

    console.print(f"\n[green]Selected {len(selected)} best scenes ({cadence})[/green]")

    for f, cov, dt in selected:
        thumb = f["_links"].get("thumbnail")
        console.print(f"{dt.date()} | ID: {f['id']} | Coverage: {cov:.2f}%")

    # Calculate quota
    quota_sqkm = area_sqkm * len(selected)
    quota_hectares = quota_sqkm * 100

    console.print(f"\n[bold cyan]Total quota if ordered:[/bold cyan] {quota_hectares:,.0f} hectares")
