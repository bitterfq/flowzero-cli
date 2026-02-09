# FlowZero Orders CLI - Optimization Plan

**Analysis Date:** 2026-02-08
**Current Status:** 1440 lines in single file, sequential downloads, JSON-based storage

---

## CRITICAL BOTTLENECKS

### 1. Sequential Downloads
**Location:** `main.py:918-934` (PSScope), `main.py:969-985` (Basemap)
**Problem:** Downloads happen one at a time in blocking for loops
**Solution:** Implement parallel downloads with ThreadPoolExecutor or s5cmd

### 2. Sequential Batch Status Checks
**Location:** `main.py:796-841`
**Problem:** Each order status check is synchronous
**Solution:** Use aiohttp for concurrent API calls

### 3. Memory-Inefficient File Handling
**Location:** `main.py:919` - `io.BytesIO(r.content)`
**Problem:** Loads entire file into memory before upload
**Solution:** Stream directly to S3 with multipart upload

---

## TIER S OPTIMIZATIONS

### S1. Parallel Downloads with ThreadPoolExecutor
**Impact:** Major speedup for batch operations
**Implementation:** Replace sequential for loops with concurrent.futures

### S2. s5cmd Integration for S3 Uploads
**Impact:** Significantly faster than boto3 for batch operations
**Implementation:** Wrapper around s5cmd with fallback to boto3

### S3. HTTP Connection Pooling
**Location:** `main.py:34-38`
**Problem:** New connection for every S3 upload
**Solution:** Configure boto3 with max_pool_connections

### S4. SQLite Instead of JSON
**Location:** `main.py:49-63`, `main.py:618-631`, `main.py:761-766`
**Problem:** orders.json is 4025 lines, loaded entirely into memory, O(n) scans
**Solution:** SQLite with indexed queries for O(1) lookups

---

## TIER A OPTIMIZATIONS

### A1. API Response Caching
**Location:** `main.py:75-116`
**Problem:** Same API queries repeated without caching
**Solution:** File-based cache with TTL

### A2. Retry Logic with Exponential Backoff
**Location:** All API/download calls
**Solution:** Use tenacity library for automatic retries

### A3. Progress Bars
**Location:** All download operations
**Solution:** rich library progress bars with speed/ETA

### A4. Async Batch Operations
**Location:** `main.py:796-841`
**Solution:** Use aiohttp for concurrent API requests

---

## TIER B OPTIMIZATIONS

### B1. Configuration Management
**Problem:** Hardcoded values (MIN_COV_PCT, S3_BUCKET, timeouts, etc.)
**Solution:** config.yaml for all configuration

### B2. Comprehensive Logging
**Problem:** Minimal logging, hard to debug production issues
**Solution:** Structured logging with file rotation

### B3. Error Context
**Problem:** Bare except clauses, minimal error context
**Solution:** Proper exception handling with context

---

## ARCHITECTURAL REFACTORING

### Current Structure
```
flowzero-orders-cli/
├── main.py              # 1440 lines - everything in one file
├── generate_aoi.py      # 205 lines
├── requirements.txt
└── orders.json          # 4025 lines
```

### Proposed Structure
```
flowzero-orders-cli/
├── setup.py
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── config.yaml
├── README.md
├── OPTIMIZATIONS.md
│
├── flowzero/
│   ├── __init__.py
│   ├── config.py
│   │
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── aoi.py
│   │   ├── orders.py
│   │   ├── status.py
│   │   └── basemap.py
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── planet.py
│   │   ├── s3.py
│   │   └── base.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── order.py
│   │   ├── aoi.py
│   │   └── scene.py
│   │
│   ├── downloaders/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── parallel.py
│   │   ├── async_downloader.py
│   │   └── s5cmd.py
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py
│   │   ├── cache.py
│   │   └── migrations/
│   │       └── 001_initial.sql
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── geometry.py
│   │   ├── dates.py
│   │   └── validation.py
│   │
│   └── web/
│       ├── __init__.py
│       ├── app.py
│       └── routes.py
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api/
│   ├── test_downloaders/
│   └── test_storage/
│
└── scripts/
    ├── migrate_json_to_db.py
    └── benchmark.py
```

---

## CODE SMELLS

### Critical
1. Line 919: `io.BytesIO(r.content)` - entire file loaded into memory
2. Lines 918-934: No concurrency - serial downloads
3. Line 72: Bare `except:` clause
4. Line 618: Linear JSON search - O(n) complexity
5. No test coverage

### Medium
6. Line 111: Hardcoded `time.sleep(0.5)`
7. Lines 34-38: No validation of AWS credentials
8. Line 31: Hardcoded `MIN_COV_PCT = 98.0`
9. Line 39: Hardcoded `S3_BUCKET = "flowzero"`
10. Mixed concerns: CLI logic with business logic

### Low Priority
11. Duplicate code: Scene filtering logic repeated 3+ times
12. No input validation
13. Inconsistent error messages

---

## IMPLEMENTATION PHASES

### Phase 1: Core Refactoring
- Extract API clients into `api/` module
- Create data models in `models/`
- Implement database layer in `storage/`
- Add configuration management
- Set up logging infrastructure

### Phase 2: Download Optimization
- Implement ThreadPoolExecutor downloader
- Add streaming multipart S3 uploads
- Integrate s5cmd wrapper
- Add progress bars
- Implement retry logic

### Phase 3: API Optimization
- Convert batch operations to async with aiohttp
- Add response caching layer
- Implement connection pooling
- Add rate limiting

### Phase 4: Testing & Polish
- Write unit tests
- Write integration tests
- Add CLI improvements
- Documentation

---

## ADDITIONAL DEPENDENCIES

### Production
```txt
# New - Performance
aiohttp>=3.9.0
tenacity>=8.2.0

# New - Monitoring
structlog>=23.0.0
```

### Development
```txt
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
black>=23.0.0
ruff>=0.1.0
```

---

## CONFIGURATION SCHEMA

```yaml
api:
  planet_base_url: "https://api.planet.com"
  min_coverage_pct: 98.0
  rate_limit_delay: 0.5
  pagination_delay: 0.5

s3:
  bucket: "flowzero"
  region: "us-west-2"
  max_workers: 20

downloads:
  chunk_size: 8388608
  max_concurrent: 10
  timeout: 60
  retry_attempts: 3

logging:
  level: INFO
  file_retention_days: 30
```

---

## DATABASE SCHEMA

```sql
CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    aoi_name TEXT,
    order_type TEXT,
    batch_id TEXT,
    start_date TEXT,
    end_date TEXT,
    status TEXT,
    scenes_selected INTEGER,
    quota_hectares REAL,
    metadata JSON,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_batch_id ON orders(batch_id);
CREATE INDEX idx_aoi_name ON orders(aoi_name);
CREATE INDEX idx_status ON orders(status);
CREATE INDEX idx_timestamp ON orders(timestamp);
```

---

**Status:** Ready for Implementation
