-- Initial database schema for FlowZero Orders CLI

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    aoi_name TEXT NOT NULL,
    order_type TEXT NOT NULL,
    batch_id TEXT,
    start_date TEXT,
    end_date TEXT,
    status TEXT,
    num_bands TEXT,
    product_bundle TEXT,
    product_bundle_order TEXT,
    clipped INTEGER DEFAULT 1,
    aoi_area_sqkm REAL,
    scenes_selected INTEGER,
    scenes_found INTEGER,
    quota_hectares REAL,
    batch_order INTEGER DEFAULT 0,
    mosaic_name TEXT,
    metadata TEXT,  -- JSON blob for additional data
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_batch_id ON orders(batch_id);
CREATE INDEX IF NOT EXISTS idx_aoi_name ON orders(aoi_name);
CREATE INDEX IF NOT EXISTS idx_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_timestamp ON orders(timestamp);
CREATE INDEX IF NOT EXISTS idx_order_type ON orders(order_type);

-- Trigger to update updated_at timestamp
CREATE TRIGGER IF NOT EXISTS update_orders_timestamp
AFTER UPDATE ON orders
BEGIN
    UPDATE orders SET updated_at = CURRENT_TIMESTAMP WHERE order_id = NEW.order_id;
END;
