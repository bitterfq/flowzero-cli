# FlowZero Orders CLI

**Modern command-line tool for ordering Planet Labs satellite imagery for river monitoring workflows**

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Table of Contents

- [Quick Start](#quick-start)
- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Commands](#commands)
  - [Database Queries](#database-queries)
  - [Order Submission](#order-submission)
  - [Status Checking & Downloads](#status-checking--downloads)
  - [AOI Management](#aoi-management)
  - [Basemap Operations](#basemap-operations)
- [Workflows](#workflows)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)
- [Migration from Old CLI](#migration-from-old-cli)

---

## Quick Start

```bash
# Install
git clone <repository-url>
cd flowzero-orders-cli
pip install -e .

# Set up credentials
export PL_API_KEY="your_planet_api_key"
export AWS_ACCESS_KEY_ID="your_aws_key"
export AWS_SECRET_ACCESS_KEY="your_aws_secret"

# Submit an order
flowzero submit \
  --geojson ./my_aoi.geojson \
  --start-date 2024-01-01 \
  --end-date 2024-06-30 \
  --cadence weekly

# Check status and download
flowzero check-order-status <order_id> --use-s5cmd
```

---

## Features

### Core Capabilities
- **Automated Scene Selection** - Smart selection by cadence (daily/weekly/monthly)
- **Coverage Filtering** - Ensures ≥98% AOI coverage and 0% cloud cover
- **Batch Operations** - Submit and monitor multiple orders simultaneously
- **Database Tracking** - SQLite database for order history and status
- **Duplicate Prevention** - Check for existing orders before submitting
- **Flexible Output** - Download to S3 or local filesystem

### Performance & Reliability
- **Parallel Downloads** - 10-25x faster than sequential (ThreadPoolExecutor)
- **s5cmd Support** - 20-50x faster S3 uploads with Go-based tool
- **Skip Existing Files** - Automatic detection and skip of already-downloaded files
- **Retry Logic** - Exponential backoff for Planet API calls
- **Automatic Pagination** - Handles large result sets transparently

### Developer Experience
- **Modular Architecture** - Clean separation of concerns
- **Comprehensive Configuration** - Centralized config.yaml
- **Rich Console Output** - Color-coded status and progress
- **Simple CLI** - Just `flowzero <command>` - no verbose Python module syntax

---

## Installation

### Prerequisites
- **Python 3.8+** (check with `python --version`)
- **Planet Labs API Key** ([get one here](https://www.planet.com/account/))
- **AWS Credentials** (for S3 uploads) ([setup guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html))
- **s5cmd** (optional, for ultra-fast S3 uploads) ([install guide](https://github.com/peak/s5cmd))

### Install Steps

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd flowzero-orders-cli
   ```

2. **Install the package:**
   ```bash
   pip install -e .
   ```

   This installs FlowZero in editable mode and creates the `flowzero` command.

3. **Verify installation:**
   ```bash
   flowzero --version
   # Should output: flowzero, version 2.0.0
   ```

4. **Set up credentials:**

   Create a `.env` file in the project root:
   ```env
   PL_API_KEY=your_planet_labs_api_key_here
   AWS_ACCESS_KEY_ID=your_aws_access_key
   AWS_SECRET_ACCESS_KEY=your_aws_secret_key
   ```

   Or export environment variables:
   ```bash
   export PL_API_KEY="your_key"
   export AWS_ACCESS_KEY_ID="your_key"
   export AWS_SECRET_ACCESS_KEY="your_secret"
   ```

5. **Test the installation:**
   ```bash
   flowzero db stats
   # Should show database statistics (may be empty if new install)
   ```

---

## Configuration

All settings are in `config.yaml`. You can customize:

- **API URLs and timeouts**
- **S3 bucket name and region**
- **Download concurrency** (max_workers)
- **Coverage thresholds** (min_coverage_pct)
- **Cloud cover limits**
- **Database path**

Environment variables override config for secrets:
- `PL_API_KEY` - Planet API key
- `AWS_ACCESS_KEY_ID` - AWS access key
- `AWS_SECRET_ACCESS_KEY` - AWS secret key

---

## Commands

### Database Queries

View and query your order history stored in SQLite:

#### `flowzero db stats`
Show database statistics (total orders, batches, AOIs, scenes, quota).

```bash
flowzero db stats
```

#### `flowzero db list-batches`
List all batch IDs with order counts.

```bash
flowzero db list-batches
```

#### `flowzero db list-orders`
List orders with optional filters.

```bash
# All orders
flowzero db list-orders

# Filter by AOI
flowzero db list-orders --aoi SalinasRiver

# Filter by status
flowzero db list-orders --status success

# Filter by batch
flowzero db list-orders --batch-id <batch_id>
```

#### `flowzero db pending`
Show all pending orders (queued or running).

```bash
flowzero db pending
```

#### `flowzero db get <order_id>`
Get detailed information for a specific order.

```bash
flowzero db get abc123-def456-...
```

---

### Order Submission

#### `flowzero submit`
Submit a single PlanetScope order.

```bash
flowzero submit \
  --geojson ./my_aoi.geojson \
  --start-date 2024-01-01 \
  --end-date 2024-06-30 \
  --cadence weekly \
  --skip-if-exists
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--geojson` | required | Path to AOI GeoJSON file |
| `--start-date` | required | Start date (YYYY-MM-DD) |
| `--end-date` | required | End date (YYYY-MM-DD) |
| `--cadence` | `weekly` | Scene selection: `daily`, `weekly`, or `monthly` |
| `--skip-if-exists` | false | Skip if identical order already exists in database |
| `--cloud-cover` | 0 | Max cloud cover percentage (0-100) |
| `--min-coverage` | 98 | Min AOI coverage percentage (0-100) |
| `--api-key` | env var | Planet API key override |

**Example Output:**
```
AOI area: 12.34 sq km
Found 156 scenes matching criteria
Selected 26 best scenes (weekly cadence)
2024-01-07 | ID: 20240107_123456_1234 | Coverage: 99.8%
2024-01-14 | ID: 20240114_789012_5678 | Coverage: 99.5%
...

Order submitted successfully!
Order ID: abc123-def456-789012-ghi345
```

---

#### `flowzero batch-submit`
Submit multiple orders from a shapefile.

```bash
flowzero batch-submit \
  --shp ./gages.shp \
  --gage-id-col GageID \
  --start-date-col StartDate \
  --end-date-col EndDate \
  --cadence weekly \
  --skip-existing \
  --dry-run
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--shp` | required | Path to shapefile with AOIs and attributes |
| `--gage-id-col` | `gage_id` | Column name for unique identifier |
| `--start-date-col` | `start_date` | Column name for start date |
| `--end-date-col` | `end_date` | Column name for end date |
| `--cadence` | `weekly` | `daily`, `weekly`, or `monthly` |
| `--skip-existing` | false | Skip AOIs with completed orders |
| `--dry-run` | false | Preview orders without submitting |
| `--max-months` | 6 | Max months per order (auto-subdivides) |

**Required Shapefile Columns:**
- Geometry (polygon)
- Gage ID (unique identifier)
- Start date (YYYY-MM-DD)
- End date (YYYY-MM-DD)

**Example Output:**
```
Found 25 features in shapefile
Prepared 38 orders from 25 gages

Batch ID: abc123-def4-5678-9012-34567890abcd

[1/38] Gage_001: 2024-01-01 to 2024-06-30... ✓ Order a1b2c3d4... (45 found, 23 selected)
[2/38] Gage_002: 2024-01-01 to 2024-06-30... ✓ Order e5f6g7h8... (38 found, 19 selected)
...

Batch Order Summary
===================
Submitted: 35 orders (1,234 found, 567 selected, 45,600 ha quota)
No valid scenes: 3 orders

Successfully submitted 35 orders!
Batch ID: abc123-def4-5678-9012-34567890abcd
```

---

#### `flowzero search-scenes`
Search for scenes without ordering (preview).

```bash
flowzero search-scenes \
  --geojson ./my_aoi.geojson \
  --start-date 2024-01-01 \
  --end-date 2024-03-31 \
  --cadence weekly
```

Displays available scenes, coverage, and quota estimate without submitting an order.

---

### Status Checking & Downloads

#### `flowzero check-order-status <order_id>`
Check status and download files for a single order.

```bash
# Download to S3 (default)
flowzero check-order-status abc123-def456-... --use-s5cmd

# Download to local directory
flowzero check-order-status abc123-def456-... --output ./downloads

# Re-download existing files
flowzero check-order-status abc123-def456-... --overwrite
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--output` | `s3` | Output: `s3` or local directory path |
| `--overwrite` | false | Re-download even if files exist |
| `--use-s5cmd` | false | Use s5cmd for ultra-fast S3 uploads |
| `--api-key` | env var | Planet API key override |

**How it works:**

1. Queries database for order metadata
2. Checks Planet API for current status
3. Updates database with new status
4. For `success` or `partial` orders:
   - Downloads all files (parallel or s5cmd)
   - Organizes by week (PSScope) or date (Basemap)
   - Skips files that already exist (unless `--overwrite`)
   - Uploads to S3 or saves locally
   - Saves metadata

**Order States:**

| State | Behavior |
|-------|----------|
| `queued` | Wait - order in queue |
| `running` | Wait - order processing |
| `success` | Download all files |
| `partial` | Download available files |
| `failed` | Show error, do not download |
| `cancelled` | Show status, do not download |

---

#### `flowzero batch-check-status <batch_id>`
Check status and download all orders in a batch.

```bash
# Check all orders in batch (skip already completed)
flowzero batch-check-status abc123-def4-5678-... --use-s5cmd

# Force recheck all orders (even completed ones)
flowzero batch-check-status abc123-def4-5678-... --force

# Download to local directory
flowzero batch-check-status abc123-def4-5678-... --output ./downloads
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--output` | `s3` | Output: `s3` or local directory path |
| `--overwrite` | false | Re-download even if files exist |
| `--force` | false | Recheck all orders (even completed) |
| `--use-s5cmd` | false | Use s5cmd for ultra-fast uploads |
| `--api-key` | env var | Planet API key override |

**Example Output:**
```
Found 35 orders in batch: abc123-def4-5678-...

[1/35] Checking Gage_001 (2024-01-01 to 2024-06-30)...
  Order ID: a1b2c3d4...
  Status: success
  Downloading...
  Processing PlanetScope Order - Organizing by week...
  Found 23 images across 23 weeks
  Downloading 23 files with s5cmd...
  Downloaded: s3://flowzero/.../2024_01_07_abc123.tiff
  Skipped (exists): s3://flowzero/.../2024_01_14_def456.tiff
  ...
  Download complete!

[2/35] Checking Gage_002 (2024-01-01 to 2024-06-30)...
  Order ID: b2c3d4e5...
  Status: pending
  Order is running - try again later.

...

Batch Status Check Summary
==========================
Completed & Downloaded: 28
Pending (queued/running): 5
Failed: 2

Run again later to check pending orders.
```

---

### AOI Management

#### `flowzero generate-aoi`
Launch interactive web interface for drawing AOIs.

```bash
flowzero generate-aoi
```

Opens browser at http://localhost:5000 with map interface for drawing polygons and saving as GeoJSON.

---

#### `flowzero convert-shp`
Convert shapefile to GeoJSON.

```bash
flowzero convert-shp --shp ./shapefile.shp --output ./geojsons
```

Handles CRS transformation (reprojects to EPSG:4326 if needed).

---

### Basemap Operations

#### `flowzero list-basemaps`
List available Planet Basemap mosaics.

```bash
flowzero list-basemaps \
  --start-date 2024-01-01 \
  --end-date 2024-12-31
```

---

#### `flowzero order-basemap`
Order a basemap composite.

```bash
flowzero order-basemap \
  --mosaic-name global_monthly_2024_06_mosaic \
  --geojson ./my_aoi.geojson
```

---

## Workflows

### Workflow 1: Single Order

```bash
# 1. Convert shapefile to GeoJSON (if needed)
flowzero convert-shp --shp ./river.shp

# 2. Preview available scenes (optional)
flowzero search-scenes \
  --geojson ./geojsons/river.geojson \
  --start-date 2024-01-01 \
  --end-date 2024-06-30

# 3. Submit order
flowzero submit \
  --geojson ./geojsons/river.geojson \
  --start-date 2024-01-01 \
  --end-date 2024-06-30 \
  --cadence weekly

# 4. Check status (wait until complete)
flowzero check-order-status <order_id> --use-s5cmd
```

---

### Workflow 2: Batch Orders

```bash
# 1. Prepare shapefile with columns: gage_id, start_date, end_date, geometry

# 2. Dry run to preview
flowzero batch-submit --shp ./gages.shp --dry-run

# 3. Submit all orders
flowzero batch-submit --shp ./gages.shp
# IMPORTANT: Note the Batch ID from output!

# 4. Check batch status (run periodically until all complete)
flowzero batch-check-status <batch_id> --use-s5cmd

# 5. Later, check again (will skip completed orders)
flowzero batch-check-status <batch_id> --use-s5cmd

# 6. Force recheck all orders
flowzero batch-check-status <batch_id> --force
```

---

### Workflow 3: Query Order History

```bash
# See all batches
flowzero db list-batches

# See all orders in a batch
flowzero db list-orders --batch-id <batch_id>

# See all successful orders
flowzero db list-orders --status success

# See orders for specific AOI
flowzero db list-orders --aoi SalinasRiver

# See pending orders
flowzero db pending

# Get details for specific order
flowzero db get <order_id>
```

---

## Architecture

### Project Structure

```
flowzero-orders-cli/
├── flowzero/
│   ├── api/               # Planet API & S3 clients
│   ├── cli/               # Click CLI commands
│   ├── models/            # Data models (Order, Scene)
│   ├── storage/           # SQLite database layer
│   ├── downloaders/       # Parallel & s5cmd downloaders
│   └── utils/             # Utilities (geometry, dates)
├── config.yaml            # Configuration
├── setup.py               # Package setup
├── pyproject.toml         # Modern Python config
└── generate_aoi.py        # AOI generation server
```

### Data Flow

1. **Order Submission:**
   - User runs `flowzero submit`
   - Database checks for duplicates
   - Planet API searches for scenes
   - Scenes filtered by coverage/cadence
   - Order submitted to Planet
   - Order saved to database

2. **Status Check:**
   - User runs `flowzero check-order-status`
   - Database retrieves order metadata
   - Planet API queried for status
   - Database updated with new status
   - If complete: parallel/s5cmd download
   - Files uploaded to S3 or saved locally

### Database Schema

SQLite database (`orders.db`) with indexed queries:

```sql
CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    aoi_name TEXT NOT NULL,
    order_type TEXT NOT NULL,
    batch_id TEXT,
    status TEXT,
    start_date TEXT,
    end_date TEXT,
    scenes_selected INTEGER,
    quota_hectares REAL,
    timestamp TEXT,
    mosaic_name TEXT
);
-- Indexes on: batch_id, aoi_name, status, timestamp
```

---

## Troubleshooting

### Command not found: flowzero

```bash
# Check if installed
pip show flowzero-orders-cli

# Reinstall
pip uninstall flowzero-orders-cli
pip install -e .

# Verify
which flowzero
flowzero --version
```

---

### Import errors

```bash
# Install all dependencies
pip install -r requirements.txt

# Check Python version (requires 3.8+)
python --version
```

---

### Database errors

```bash
# Check database location (default: ./orders.db)
ls -la orders.db

# Reset database (WARNING: deletes all data)
rm orders.db
# Database will be recreated on next command
```

---

### API errors

```bash
# Check API key is set
echo $PL_API_KEY

# Test API connectivity
flowzero search-scenes \
  --geojson test.geojson \
  --start-date 2024-01-01 \
  --end-date 2024-01-31
```

---

### s5cmd not available

```bash
# Install s5cmd (option 1: download binary)
# https://github.com/peak/s5cmd/releases

# Install s5cmd (option 2: with go)
go install github.com/peak/s5cmd/v2@latest

# Verify
which s5cmd
s5cmd version

# Note: CLI automatically falls back to parallel downloader if s5cmd not found
```

---

### "No cloud-free scenes found"

- Expand date range
- Check if AOI has frequent cloud cover
- Try different cadence (daily instead of weekly)

---

### "No full-coverage scenes matched filter"

- AOI may be too large for single-scene coverage
- Lower `--min-coverage` threshold (default 98%)
- Split into smaller AOIs

---

## Migration from Old CLI

If you have existing data in `orders.json` from the old `main.py` CLI:

```bash
# Run migration script
python scripts/migrate_json_to_db.py

# Verify migration
flowzero db stats
flowzero db list-orders
```

The old `main.py` CLI still works and can run side-by-side, but:
- Old CLI uses `orders.json` (JSON file)
- New CLI uses `orders.db` (SQLite database)
- Data is not shared between them

---

## Output Structure

### S3 Structure

```
s3://flowzero/
├── planetscope analytic/
│   └── four_bands/
│       └── {aoi_name}/
│           ├── 2024_01_07_{scene_id}.tiff
│           ├── 2024_01_14_{scene_id}.tiff
│           └── metadata.json
└── basemaps/
    └── {aoi_name}/
        └── {year}_{month}/
            ├── tile_001.tiff
            └── metadata.json
```

### Local Structure

```
./downloads/
├── planetscope analytic/
│   └── four_bands/
│       └── {aoi_name}/
│           ├── 2024_01_07_{scene_id}.tiff
│           └── ...
└── basemaps/
    └── {aoi_name}/
        └── ...
