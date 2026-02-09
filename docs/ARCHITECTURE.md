# FlowZero Orders CLI - Architecture Specification

**Version:** 2.0.0
**Last Updated:** 2026-02-08

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Project Structure](#project-structure)
3. [Data Flow](#data-flow)
4. [Component Details](#component-details)
5. [Database Layer](#database-layer)
6. [API Clients](#api-clients)
7. [Download System](#download-system)
8. [CLI Layer](#cli-layer)
9. [Configuration System](#configuration-system)
10. [Error Handling](#error-handling)

---

## System Overview

FlowZero Orders CLI is a command-line tool for ordering and managing Planet Labs satellite imagery. It's designed as a modular Python application with clear separation of concerns.

### Key Architectural Decisions

1. **Modular Design** - Separated into distinct layers (CLI, API, Storage, Models, Utils)
2. **Database-First** - SQLite for order tracking and duplicate prevention
3. **Configuration-Driven** - Centralized YAML config with env var overrides
4. **Performance-Optimized** - Parallel downloads, retry logic, connection pooling
5. **Idempotent Operations** - Safe to run commands multiple times

### Technology Stack

- **Python 3.8+** - Core language
- **Click** - CLI framework
- **SQLite3** - Embedded database
- **Requests** - HTTP client for Planet API
- **Boto3** - AWS S3 client
- **Rich** - Terminal UI
- **GeoPandas/Shapely** - Geospatial operations
- **ThreadPoolExecutor** - Parallel downloads
- **s5cmd** (optional) - Ultra-fast S3 uploads

---

## Project Structure

```
flowzero-orders-cli/
├── flowzero/                      # Main package
│   ├── __init__.py                # Package init, version export
│   ├── config.py                  # Configuration loader
│   │
│   ├── api/                       # External API clients
│   │   ├── __init__.py
│   │   ├── planet.py              # Planet Labs API client
│   │   └── s3.py                  # AWS S3 client
│   │
│   ├── cli/                       # CLI commands
│   │   ├── __init__.py
│   │   ├── app.py                 # Main CLI entry point
│   │   ├── common.py              # Shared utilities
│   │   ├── db.py                  # Database query commands
│   │   ├── status.py              # Status checking & downloads
│   │   ├── orders.py              # Order submission commands
│   │   ├── aoi.py                 # AOI management
│   │   └── basemap.py             # Basemap operations
│   │
│   ├── models/                    # Data models
│   │   ├── __init__.py
│   │   ├── order.py               # Order dataclass
│   │   └── scene.py               # Scene dataclass
│   │
│   ├── storage/                   # Data persistence
│   │   ├── __init__.py
│   │   ├── database.py            # SQLite database layer
│   │   └── migrations/
│   │       └── 001_initial.sql    # Database schema
│   │
│   ├── downloaders/               # Download implementations
│   │   ├── __init__.py
│   │   ├── parallel.py            # ThreadPoolExecutor downloader
│   │   └── s5cmd.py               # s5cmd wrapper
│   │
│   └── utils/                     # Utility functions
│       ├── __init__.py
│       ├── geometry.py            # Geospatial utilities
│       └── dates.py               # Date parsing utilities
│
├── scripts/                       # Utility scripts
│   └── migrate_json_to_db.py      # Migration from old JSON format
│
├── docs/                          # Documentation
│   ├── context.md                 # Development context
│   ├── COMPARISON.md              # Old vs new comparison
│   ├── OPTIMIZATIONS.md           # Performance analysis
│   └── ARCHITECTURE.md            # This file
│
├── config.yaml                    # Configuration file
├── setup.py                       # Package setup
├── pyproject.toml                 # Modern Python packaging
├── requirements.txt               # Python dependencies
├── generate_aoi.py                # Standalone AOI generator
├── main.py                        # Legacy CLI (deprecated)
└── README.md                      # User documentation
```

---

## Data Flow

### 1. Order Submission Flow

```
User Command: flowzero submit --geojson aoi.geojson --start-date ... --end-date ...
    │
    ├─> CLI Layer (flowzero/cli/orders.py:submit)
    │   │
    │   ├─> Load GeoJSON (utils/geometry.py)
    │   ├─> Calculate area in equal-area CRS
    │   ├─> Check for duplicates (storage/database.py:find_existing_order)
    │   │
    │   └─> If no duplicate:
    │       │
    │       ├─> API Client (api/planet.py:search_scenes)
    │       │   │
    │       │   ├─> POST to Planet API (quick-search)
    │       │   ├─> Handle pagination (fetch all pages)
    │       │   ├─> Retry on failure (exponential backoff)
    │       │   └─> Return all scenes
    │       │
    │       ├─> Filter scenes (coverage ≥98%, cloud ≤0%)
    │       ├─> Group by cadence (daily/weekly/monthly)
    │       ├─> Select best scene per interval
    │       │
    │       ├─> API Client (api/planet.py:submit_order)
    │       │   │
    │       │   ├─> POST to Planet API (orders/v2)
    │       │   ├─> Retry on failure
    │       │   └─> Return order_id
    │       │
    │       └─> Database (storage/database.py:save_order)
    │           │
    │           └─> INSERT OR REPLACE into orders table
    │
    └─> Output: Order ID, quota used
```

### 2. Status Check & Download Flow

```
User Command: flowzero check-order-status <order_id> --use-s5cmd
    │
    ├─> CLI Layer (flowzero/cli/status.py:check_order_status)
    │   │
    │   ├─> Database (storage/database.py:get_order)
    │   │   └─> SELECT metadata FROM orders WHERE order_id = ?
    │   │
    │   ├─> API Client (api/planet.py:get_order_status)
    │   │   │
    │   │   ├─> GET to Planet API (orders/v2/{order_id})
    │   │   ├─> Retry on failure
    │   │   └─> Return order status + download links
    │   │
    │   ├─> Database (storage/database.py:update_order_status)
    │   │   └─> UPDATE orders SET status = ? WHERE order_id = ?
    │   │
    │   └─> If status is 'success' or 'partial':
    │       │
    │       ├─> Organize files (by week for PSScope, by date for Basemap)
    │       │
    │       ├─> Determine order type (PSScope vs Basemap)
    │       │
    │       └─> Download files:
    │           │
    │           ├─> Option A: s5cmd (if --use-s5cmd flag)
    │           │   │
    │           │   └─> Downloader (downloaders/s5cmd.py)
    │           │       │
    │           │       ├─> Create manifest file (URL -> S3 key pairs)
    │           │       ├─> Run: s5cmd --numworkers 20 cp --manifest manifest.txt
    │           │       └─> Return results (20-50x faster than boto3)
    │           │
    │           └─> Option B: Parallel downloader (default)
    │               │
    │               └─> Downloader (downloaders/parallel.py)
    │                   │
    │                   ├─> ThreadPoolExecutor (10 workers)
    │                   ├─> For each file:
    │                   │   │
    │                   │   ├─> Check if exists (S3 or local)
    │                   │   ├─> If exists and not overwrite: skip
    │                   │   ├─> Else: Download with requests.get(stream=True)
    │                   │   │
    │                   │   └─> Upload:
    │                   │       ├─> S3: multipart upload via boto3
    │                   │       └─> Local: write to file
    │                   │
    │                   └─> Yield results (success, destination, error)
    │
    └─> Output: Download summary (downloaded, skipped, failed)
```

### 3. Batch Operations Flow

```
User Command: flowzero batch-submit --shp gages.shp --cadence weekly
    │
    ├─> CLI Layer (flowzero/cli/orders.py:batch_submit)
    │   │
    │   ├─> Load shapefile (geopandas)
    │   ├─> Validate columns (gage_id, start_date, end_date)
    │   ├─> Generate batch_id (UUID)
    │   │
    │   └─> For each feature:
    │       │
    │       ├─> Extract AOI geometry
    │       ├─> Subdivide date range (if > max_months)
    │       │
    │       └─> For each date chunk:
    │           │
    │           ├─> Search scenes (same as submit flow)
    │           ├─> Filter and select
    │           ├─> Submit order
    │           └─> Save to database (with batch_id)
    │
    └─> Output: Batch ID, summary stats

User Command: flowzero batch-check-status <batch_id> --use-s5cmd
    │
    ├─> CLI Layer (flowzero/cli/status.py:batch_check_status)
    │   │
    │   ├─> Database (storage/database.py:get_batch_orders)
    │   │   └─> SELECT metadata FROM orders WHERE batch_id = ?
    │   │
    │   └─> For each order:
    │       │
    │       ├─> Skip if status is 'success' (unless --force)
    │       ├─> Skip if status is 'failed' or 'cancelled'
    │       │
    │       ├─> Check status (Planet API)
    │       ├─> Update database
    │       │
    │       └─> If 'success' or 'partial':
    │           └─> Download files (same as check_order_status)
    │
    └─> Output: Batch summary (success, partial, pending, failed)
```

### 4. Database Query Flow

```
User Command: flowzero db list-orders --status success
    │
    ├─> CLI Layer (flowzero/cli/db.py:list_orders)
    │   │
    │   └─> Database (storage/database.py:get_orders_by_status)
    │       │
    │       ├─> SELECT metadata FROM orders WHERE status = ?
    │       ├─> Parse JSON metadata
    │       └─> Return list of Order objects
    │
    └─> Output: Table of orders
```

---

## Component Details

### Configuration System

**File:** `flowzero/config.py`

Loads configuration from `config.yaml` and overrides with environment variables.

```python
class Config:
    def __init__(self, config_path=None):
        # Load config.yaml
        # Override with env vars (PL_API_KEY, AWS credentials)
        # Provide defaults
```

**Configuration hierarchy:**
1. `config.yaml` - Base configuration
2. Environment variables - Override secrets
3. Command-line flags - Override at runtime

**Example config.yaml:**
```yaml
planet:
  api_url: https://api.planet.com/data/v1
  orders_url: https://api.planet.com/compute/ops/orders/v2
  timeout: 30
  max_retries: 3

s3:
  bucket_name: flowzero
  region: us-west-2

downloads:
  max_workers: 10
  min_coverage_pct: 98.0
  cloud_cover_max: 0.0

database_path: ./orders.db
```

---

### Database Layer

**File:** `flowzero/storage/database.py`

SQLite database with automatic initialization and migration.

#### Initialization

Every instantiation runs `_ensure_initialized()`:
```python
def _ensure_initialized(self):
    migrations_dir = Path(__file__).parent / "migrations"
    migration_file = migrations_dir / "001_initial.sql"

    with self.get_connection() as conn:
        conn.executescript(f.read())  # CREATE TABLE IF NOT EXISTS
```

**First run:** Creates `orders.db` file and schema
**Subsequent runs:** Does nothing (IF NOT EXISTS)

#### Schema

**File:** `flowzero/storage/migrations/001_initial.sql`

```sql
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
    metadata TEXT,  -- Full order as JSON
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_batch_id ON orders(batch_id);
CREATE INDEX IF NOT EXISTS idx_aoi_name ON orders(aoi_name);
CREATE INDEX IF NOT EXISTS idx_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_timestamp ON orders(timestamp);
CREATE INDEX IF NOT EXISTS idx_order_type ON orders(order_type);
```

#### Key Methods

| Method | Purpose | Query Type |
|--------|---------|------------|
| `save_order(order)` | Insert/update order | INSERT OR REPLACE |
| `get_order(order_id)` | Get order by ID | O(1) - indexed PK |
| `order_exists(order_id)` | Check existence | O(1) - indexed PK |
| `find_existing_order(aoi, start, end)` | Duplicate check | O(1) - indexed |
| `has_completed_order(aoi, start, end)` | Check if done | O(1) - indexed |
| `get_batch_orders(batch_id)` | Get batch | O(1) - indexed |
| `update_order_status(order_id, status)` | Update status | O(1) - indexed PK |
| `get_orders_by_status(status)` | Query by status | O(n) - full scan with index |
| `get_stats()` | Aggregate stats | O(n) - full table scan |

---

### API Clients

#### Planet API Client

**File:** `flowzero/api/planet.py`

Handles all Planet Labs API interactions with automatic retry.

**Key Methods:**

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.exceptions.RequestException)
)
def search_scenes(self, aoi_geojson, start_date, end_date, ...):
    """
    Search for scenes with automatic pagination.

    Flow:
    1. POST to quick-search endpoint
    2. Get first page of results
    3. Check for _links["_next"]
    4. While _next exists:
       - GET next page
       - Append results
       - Sleep 0.5s (rate limiting)
    5. Return all features
    """
```

**Pagination Pattern:**
- First request: POST with payload
- Subsequent requests: GET to `_links["_next"]` URL
- Stops when `_next` is None or missing

**Retry Strategy:**
- 3 attempts maximum
- Exponential backoff: 2s, 4s, 8s
- Only retries on RequestException

#### S3 Client

**File:** `flowzero/api/s3.py`

Boto3 wrapper with connection pooling.

```python
class S3Client:
    def __init__(self):
        # Connection pooling (50 connections)
        boto_config = BotoConfig(
            max_pool_connections=50,
            retries={'max_attempts': 3, 'mode': 'adaptive'}
        )
        self.client = boto3.client('s3', config=boto_config)
```

**Key Methods:**
- `upload_fileobj(file, key)` - Multipart upload
- `key_exists(key)` - Check if object exists
- `download_file(key, path)` - Download to local

---

### Download System

#### Parallel Downloader

**File:** `flowzero/downloaders/parallel.py`

ThreadPoolExecutor-based concurrent downloader.

```python
class ParallelDownloader:
    def __init__(self, s3_client=None, max_workers=10):
        self.max_workers = max_workers
        self.s3_client = s3_client

    def download_batch(self, url_destination_pairs, is_s3, overwrite, check_exists_func):
        """
        Download multiple files in parallel.

        Args:
            url_destination_pairs: [(url, dest), ...]
            is_s3: Upload to S3 vs save locally
            overwrite: Re-download existing files
            check_exists_func: Function to check if file exists

        Yields:
            (success: bool, destination: str, error: str)
        """
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for url, dest in url_destination_pairs:
                if not overwrite and check_exists_func(dest):
                    yield (True, dest, "skipped")
                    continue

                future = executor.submit(self._download_one, url, dest, is_s3)
                futures[future] = (url, dest)

            for future in as_completed(futures):
                yield future.result()
```

**Performance:**
- 10 workers = 10 concurrent downloads
- ~0.5 seconds per file average
- 50 files = ~25 seconds (vs ~250 seconds sequential)
- **10-25x faster** than sequential

#### s5cmd Downloader

**File:** `flowzero/downloaders/s5cmd.py`

Wrapper for s5cmd Go-based tool.

```python
class S5cmdDownloader:
    def download_batch(self, url_destination_pairs):
        """
        Download using s5cmd for ultra-fast uploads.

        Process:
        1. Create manifest file:
           https://url1 s3://bucket/key1
           https://url2 s3://bucket/key2

        2. Run s5cmd:
           s5cmd --numworkers 20 cp --manifest manifest.txt

        3. Parse output
        4. Return results
        """
```

**Performance:**
- 20 workers (s5cmd default)
- Go-based parallel uploads
- ~0.2 seconds per file average
- 50 files = ~10 seconds
- **20-50x faster** than boto3

**Availability:**
- Checks if `s5cmd` binary exists
- Automatically falls back to parallel downloader if not found

---

### CLI Layer

#### Main Entry Point

**File:** `flowzero/cli/app.py`

Click-based CLI application.

```python
@click.group()
@click.version_option(version=__version__)
def cli(ctx):
    """FlowZero - CLI tool for ordering Planet Labs satellite imagery."""
    pass

# Register all command groups
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
```

#### Shared Utilities

**File:** `flowzero/cli/common.py`

Factory functions for consistent object creation.

```python
def get_database():
    """Get initialized database."""
    return Database()  # Auto-initializes schema

def get_planet_client(api_key=None):
    """Get Planet API client."""
    return PlanetAPIClient(api_key or config.pl_api_key)

def get_s3_client():
    """Get S3 client."""
    return S3Client()

def get_downloader(s3_client=None, max_workers=None):
    """Get parallel downloader."""
    return ParallelDownloader(s3_client, max_workers)
```

#### Command Organization

| File | Commands | Database? |
|------|----------|-----------|
| `db.py` | stats, list-batches, list-orders, pending, get | ✅ All |
| `orders.py` | submit, batch-submit, search-scenes | ✅ submit, batch-submit |
| `status.py` | check-order-status, batch-check-status | ✅ Both |
| `aoi.py` | generate-aoi, convert-shp | ❌ None |
| `basemap.py` | list-basemaps, order-basemap | ✅ order-basemap only |

---

## Error Handling

### Retry Strategy

All Planet API calls use tenacity retry decorator:

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.exceptions.RequestException)
)
```

**Behavior:**
- Attempt 1: Immediate
- Attempt 2: Wait 2 seconds
- Attempt 3: Wait 4 seconds
- Attempt 4: Wait 8 seconds (if configured)
- Raises exception after max attempts

### Database Error Handling

Context manager with automatic rollback:

```python
@contextmanager
def get_connection(self):
    conn = sqlite3.connect(self.db_path)
    try:
        yield conn
        conn.commit()  # Success
    except Exception:
        conn.rollback()  # Rollback on error
        raise
    finally:
        conn.close()
```

### Download Error Handling

Each download is isolated:

```python
try:
    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()
    # Upload to S3 or save locally
    return (True, destination, None)
except Exception as e:
    return (False, destination, str(e))
```

**Behavior:**
- One failure doesn't stop other downloads
- Errors are collected and reported
- User sees: "Downloaded: 23, Skipped: 5, Failed: 2"

---

## Performance Characteristics

### Query Performance

| Operation | Complexity | Notes |
|-----------|------------|-------|
| Get order by ID | O(1) | Primary key index |
| Find duplicate | O(1) | Composite index |
| Get batch orders | O(k) | k = orders in batch, indexed |
| Get by status | O(n) | Full scan with index filter |
| Get stats | O(n) | Full table aggregate |

### Download Performance

| Method | Speed | 50 Files |
|--------|-------|----------|
| Sequential (old) | 5 sec/file | ~250 sec |
| Parallel (10 workers) | 0.5 sec/file | ~25 sec |
| s5cmd (20 workers) | 0.2 sec/file | ~10 sec |

### API Performance

- **Pagination**: Automatic, transparent
- **Rate limiting**: 0.5s delay between pages
- **Retry overhead**: +2-14s on failures
- **Concurrent requests**: None (sequential by design)

---

## Security Considerations

### Credentials

- Never stored in code or config files
- Environment variables only (PL_API_KEY, AWS credentials)
- `.env` file in `.gitignore`

### Database

- SQLite file in project root (not committed)
- Contains order metadata (no credentials)
- World-readable by default (chmod if needed)

### API Requests

- HTTPS only
- Basic auth for Planet API (API key as username)
- AWS SigV4 for S3 (handled by boto3)

---

## Deployment Considerations

### Requirements

1. Python 3.8+
2. Install: `pip install -e .`
3. Environment variables set
4. s5cmd binary (optional, for performance)

### Storage

- Database: `orders.db` (~100 KB per 1000 orders)
- Logs: None (console output only)
- Cache: None

### Network

- Outbound HTTPS to:
  - `api.planet.com` (Planet API)
  - `s3.amazonaws.com` (S3 uploads)
- No inbound connections needed

---

## Future Improvements

### Migration System

Current: Single SQL file run on every init
Better: Track applied migrations

```sql
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Async API Calls

Current: Sequential Planet API calls
Better: Concurrent batch status checks with `asyncio`

### Progress Bars

Current: Line-by-line output
Better: `rich.progress` for visual feedback

### Response Caching

Current: Every query hits database
Better: LRU cache for hot queries

---

**End of Architecture Specification**
