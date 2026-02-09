"""Database operations for order storage."""
import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager

from flowzero.config import config
from flowzero.models.order import Order


class Database:
    """SQLite database for order management."""

    def __init__(self, db_path=None):
        self.db_path = db_path or config.database_path
        self._ensure_initialized()

    def _ensure_initialized(self):
        """Create database and run migrations if needed."""
        migrations_dir = Path(__file__).parent / "migrations"
        migration_file = migrations_dir / "001_initial.sql"

        with self.get_connection() as conn:
            with open(migration_file) as f:
                conn.executescript(f.read())

    @contextmanager
    def get_connection(self):
        """Get database connection with automatic commit/rollback."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_order(self, order):
        """
        Save or update an order.

        Args:
            order: Order object or dict
        """
        if isinstance(order, Order):
            order_dict = order.to_dict()
        else:
            order_dict = order

        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO orders (
                    order_id, aoi_name, order_type, batch_id, start_date, end_date,
                    status, num_bands, product_bundle, product_bundle_order, clipped,
                    aoi_area_sqkm, scenes_selected, scenes_found, quota_hectares,
                    batch_order, mosaic_name, metadata, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_dict["order_id"],
                    order_dict["aoi_name"],
                    order_dict["order_type"],
                    order_dict.get("batch_id"),
                    order_dict.get("start_date"),
                    order_dict.get("end_date"),
                    order_dict.get("status"),
                    order_dict.get("num_bands"),
                    order_dict.get("product_bundle"),
                    order_dict.get("product_bundle_order"),
                    1 if order_dict.get("clipped", True) else 0,
                    order_dict.get("aoi_area_sqkm"),
                    order_dict.get("scenes_selected"),
                    order_dict.get("scenes_found"),
                    order_dict.get("quota_hectares"),
                    1 if order_dict.get("batch_order", False) else 0,
                    order_dict.get("mosaic_name"),
                    json.dumps(order_dict),  # Store full order as JSON in metadata
                    order_dict.get("timestamp"),
                ),
            )

    def get_order(self, order_id):
        """
        Get an order by ID.

        Args:
            order_id: Order ID

        Returns:
            Order object or None
        """
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT metadata FROM orders WHERE order_id = ?", (order_id,))
            row = cursor.fetchone()

            if row:
                return Order.from_dict(json.loads(row["metadata"]))
            return None

    def order_exists(self, order_id):
        """
        Check if order exists in database.

        Args:
            order_id: Order ID

        Returns:
            True if exists, False otherwise
        """
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT 1 FROM orders WHERE order_id = ? LIMIT 1", (order_id,))
            return cursor.fetchone() is not None

    def find_existing_order(self, aoi_name, start_date, end_date, order_type="PSScope"):
        """
        Find existing order with same parameters.

        Args:
            aoi_name: AOI name
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            order_type: Order type

        Returns:
            Order object if found, None otherwise
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT metadata FROM orders
                WHERE aoi_name = ? AND start_date = ? AND end_date = ? AND order_type = ?
                ORDER BY timestamp DESC LIMIT 1
                """,
                (aoi_name, start_date, end_date, order_type),
            )
            row = cursor.fetchone()
            if row:
                return Order.from_dict(json.loads(row["metadata"]))
            return None

    def has_completed_order(self, aoi_name, start_date, end_date):
        """
        Check if there's already a completed order for this AOI/date range.

        Args:
            aoi_name: AOI name
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            True if completed order exists, False otherwise
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT 1 FROM orders
                WHERE aoi_name = ? AND start_date = ? AND end_date = ?
                AND status = 'success'
                LIMIT 1
                """,
                (aoi_name, start_date, end_date),
            )
            return cursor.fetchone() is not None

    def get_pending_orders(self):
        """
        Get all orders that are pending (queued or running).

        Returns:
            List of Order objects
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT metadata FROM orders
                WHERE status IN ('queued', 'running', NULL)
                ORDER BY timestamp
                """
            )
            return [Order.from_dict(json.loads(row["metadata"])) for row in cursor.fetchall()]

    def get_batch_orders(self, batch_id):
        """
        Get all orders for a batch.

        Args:
            batch_id: Batch ID

        Returns:
            List of Order objects
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT metadata FROM orders WHERE batch_id = ? ORDER BY timestamp",
                (batch_id,),
            )
            return [Order.from_dict(json.loads(row["metadata"])) for row in cursor.fetchall()]

    def list_batches(self):
        """
        List all batch IDs with order counts.

        Returns:
            List of tuples (batch_id, order_count)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT batch_id, COUNT(*) as count
                FROM orders
                WHERE batch_id IS NOT NULL
                GROUP BY batch_id
                ORDER BY MAX(timestamp) DESC
                """
            )
            return cursor.fetchall()

    def get_orders_by_aoi(self, aoi_name):
        """
        Get all orders for an AOI.

        Args:
            aoi_name: AOI name

        Returns:
            List of Order objects
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT metadata FROM orders WHERE aoi_name = ? ORDER BY timestamp DESC",
                (aoi_name,),
            )
            return [Order.from_dict(json.loads(row["metadata"])) for row in cursor.fetchall()]

    def update_order_status(self, order_id, status):
        """
        Update order status.

        Args:
            order_id: Order ID
            status: New status (queued, running, success, partial, failed, cancelled)
        """
        with self.get_connection() as conn:
            conn.execute("UPDATE orders SET status = ? WHERE order_id = ?", (status, order_id))

    def bulk_update_statuses(self, order_status_pairs):
        """
        Bulk update order statuses.

        Args:
            order_status_pairs: List of (order_id, status) tuples
        """
        with self.get_connection() as conn:
            conn.executemany(
                "UPDATE orders SET status = ? WHERE order_id = ?",
                [(status, order_id) for order_id, status in order_status_pairs],
            )

    def get_orders_by_status(self, status):
        """
        Get all orders with a specific status.

        Args:
            status: Order status (queued, running, success, partial, failed, cancelled)

        Returns:
            List of Order objects
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT metadata FROM orders WHERE status = ? ORDER BY timestamp DESC", (status,)
            )
            return [Order.from_dict(json.loads(row["metadata"])) for row in cursor.fetchall()]

    def get_stats(self):
        """
        Get database statistics.

        Returns:
            Dict with stats
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as total_orders,
                    COUNT(DISTINCT batch_id) as total_batches,
                    COUNT(DISTINCT aoi_name) as total_aois,
                    SUM(scenes_selected) as total_scenes,
                    SUM(quota_hectares) as total_quota_ha,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as completed_orders,
                    SUM(CASE WHEN status IN ('queued', 'running') THEN 1 ELSE 0 END) as pending_orders,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_orders
                FROM orders
                """
            )
            row = cursor.fetchone()
            return dict(row)
