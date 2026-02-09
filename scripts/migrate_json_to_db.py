#!/usr/bin/env python
"""Migrate orders.json to SQLite database."""
import json
import sys
from pathlib import Path

# Add parent directory to path to import flowzero
sys.path.insert(0, str(Path(__file__).parent.parent))

from flowzero.storage.database import Database
from flowzero.models.order import Order


def migrate(json_path="orders.json", db_path="flowzero.db"):
    """
    Migrate orders from JSON file to SQLite database.

    Args:
        json_path: Path to orders.json
        db_path: Path to SQLite database
    """
    json_file = Path(json_path)
    if not json_file.exists():
        print(f"Error: {json_path} not found")
        return

    # Load JSON data
    with open(json_file) as f:
        orders_data = json.load(f)

    print(f"Found {len(orders_data)} orders in {json_path}")

    # Initialize database
    db = Database(db_path)

    # Migrate each order
    migrated = 0
    errors = 0

    for order_dict in orders_data:
        try:
            # Ensure required fields exist
            if "order_id" not in order_dict or "aoi_name" not in order_dict:
                print(f"Warning: Skipping invalid order (missing required fields): {order_dict}")
                errors += 1
                continue

            # Create Order object and save
            order = Order.from_dict(order_dict)
            db.save_order(order)
            migrated += 1

        except Exception as e:
            print(f"Error migrating order {order_dict.get('order_id', 'unknown')}: {e}")
            errors += 1

    print(f"\nMigration complete:")
    print(f"  Migrated: {migrated}")
    print(f"  Errors: {errors}")
    print(f"  Database: {db_path}")

    # Print stats
    stats = db.get_stats()
    print(f"\nDatabase statistics:")
    print(f"  Total orders: {stats['total_orders']}")
    print(f"  Total batches: {stats['total_batches']}")
    print(f"  Total AOIs: {stats['total_aois']}")
    print(f"  Total scenes: {stats['total_scenes']}")
    print(f"  Total quota: {stats['total_quota_ha']:.0f} hectares")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate orders.json to SQLite database")
    parser.add_argument(
        "--json", default="orders.json", help="Path to orders.json (default: orders.json)"
    )
    parser.add_argument(
        "--db", default="flowzero.db", help="Path to database (default: flowzero.db)"
    )

    args = parser.parse_args()
    migrate(args.json, args.db)
