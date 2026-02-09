"""Main CLI application entry point."""
import click
from flowzero import __version__


@click.group()
@click.version_option(version=__version__)
@click.pass_context
def cli(ctx):
    """FlowZero - CLI tool for ordering Planet Labs satellite imagery."""
    ctx.ensure_object(dict)


# Import command modules
from flowzero.cli import db, status, orders, aoi, basemap

# Register command groups
cli.add_command(db.db_group)
cli.add_command(status.check_order_status)
cli.add_command(status.batch_check_status)
cli.add_command(orders.submit)
cli.add_command(orders.batch_submit)
cli.add_command(orders.search_scenes)
cli.add_command(aoi.generate_aoi)
cli.add_command(aoi.convert_shp)
cli.add_command(basemap.list_basemaps)
cli.add_command(basemap.order_basemap)


if __name__ == "__main__":
    cli()
