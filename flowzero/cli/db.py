"""Database query commands."""
import click
from flowzero.cli.common import console, get_database, print_order_summary, print_stats


@click.group(name="db")
def db_group():
    """Database query commands."""
    pass


@db_group.command(name="stats")
def stats():
    """Show database statistics."""
    db = get_database()
    stats = db.get_stats()
    print_stats(stats)


@db_group.command(name="list-batches")
def list_batches():
    """List all batch IDs with order counts."""
    db = get_database()
    batches = db.list_batches()

    if not batches:
        console.print("[yellow]No batches found[/yellow]")
        return

    console.print("\n[bold cyan]Batch Orders[/bold cyan]")
    console.print("=" * 60)
    for batch_id, count in batches:
        console.print(f"[bold]{batch_id}[/bold] - {count} orders")


@db_group.command(name="list-orders")
@click.option("--aoi", help="Filter by AOI name")
@click.option("--status", help="Filter by status (queued, running, success, partial, failed, cancelled)")
@click.option("--batch-id", help="Filter by batch ID")
def list_orders(aoi, status, batch_id):
    """List orders with optional filters."""
    db = get_database()

    if batch_id:
        orders = db.get_batch_orders(batch_id)
        title = f"Orders in Batch: {batch_id}"
    elif aoi:
        orders = db.get_orders_by_aoi(aoi)
        title = f"Orders for AOI: {aoi}"
    elif status:
        orders = db.get_orders_by_status(status)
        title = f"Orders with Status: {status}"
    else:
        console.print("[yellow]Please provide --aoi, --status, or --batch-id filter[/yellow]")
        return

    if not orders:
        console.print(f"[yellow]No orders found[/yellow]")
        return

    console.print(f"\n[bold cyan]{title}[/bold cyan]")
    console.print("=" * 60)

    for order in orders:
        console.print(f"\n[bold]Order:[/bold] {order.order_id}")
        console.print(f"  AOI: {order.aoi_name}")
        console.print(f"  Status: {order.status or 'unknown'}")
        console.print(f"  Dates: {order.start_date} to {order.end_date}")
        if order.scenes_selected:
            console.print(f"  Scenes: {order.scenes_selected}")
        if order.batch_id:
            console.print(f"  Batch: {order.batch_id}")

    console.print(f"\n[bold]Total:[/bold] {len(orders)} orders")


@db_group.command(name="pending")
def pending():
    """Show all pending orders (queued or running)."""
    db = get_database()
    orders = db.get_pending_orders()

    if not orders:
        console.print("[green]No pending orders[/green]")
        return

    console.print(f"\n[bold cyan]Pending Orders ({len(orders)})[/bold cyan]")
    console.print("=" * 60)

    for order in orders:
        console.print(f"\n[bold]{order.order_id}[/bold]")
        console.print(f"  AOI: {order.aoi_name}")
        console.print(f"  Status: {order.status or 'queued'}")
        console.print(f"  Submitted: {order.timestamp}")
        if order.batch_id:
            console.print(f"  Batch: {order.batch_id}")


@db_group.command(name="get")
@click.argument("order_id")
def get_order(order_id):
    """Get details for a specific order."""
    db = get_database()
    order = db.get_order(order_id)

    if not order:
        console.print(f"[red]Order not found: {order_id}[/red]")
        return

    console.print("\n[bold cyan]Order Details[/bold cyan]")
    console.print("=" * 60)
    print_order_summary(order)
