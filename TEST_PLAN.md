# FlowZero Test Plan

## Business Value Focus

Tests must protect against **real user pain**:
1. **Lost data** - Orders not saved, wrong status
2. **Wasted quota** - Duplicate orders, wrong scenes selected
3. **Missing files** - Downloads fail, go to wrong location
4. **Wrong imagery** - Poor coverage, wrong dates, wrong cadence

---

## Test Categories

### 1. Database Layer (CRITICAL - Data Integrity)

**Why:** Users lose order history, can't track quota, duplicate orders waste money

**Tests:**
- ✅ `test_save_and_retrieve_order` - Data persistence works
- ✅ `test_find_existing_order_detects_duplicate` - Prevents duplicate orders (saves $$)
- ✅ `test_find_existing_order_allows_different_dates` - Doesn't block legitimate orders
- ✅ `test_update_order_status` - Status tracking works (users know when ready)
- ✅ `test_get_batch_orders` - Batch operations work
- ✅ `test_get_pending_orders` - Users can find incomplete orders
- ✅ `test_stats_aggregation` - Quota tracking accurate

**Value:** Prevents data loss, prevents wasted quota ($$$)

---

### 2. Scene Filtering Logic (CRITICAL - Correct Imagery)

**Why:** Wrong scenes = wasted quota, missing data, unusable imagery

**Tests:**
- ✅ `test_coverage_filter_rejects_low_coverage` - Only ≥98% coverage scenes
- ✅ `test_cadence_weekly_groups_by_week` - One image per week
- ✅ `test_cadence_monthly_groups_by_month` - One image per month
- ✅ `test_selects_best_scene_per_interval` - Highest coverage wins
- ✅ `test_tie_breaking_earliest_date_wins` - Consistent selection
- ✅ `test_date_range_subdivision` - Long ranges split correctly (6-month chunks)
- ✅ `test_no_subdivision_for_short_ranges` - Don't over-split

**Value:** Ensures users get exactly the imagery they need

---

### 3. API Pagination (HIGH - Complete Results)

**Why:** Missing pages = missing scenes = incomplete orders = wasted quota

**Tests:**
- ✅ `test_pagination_fetches_all_pages` - Gets all results, not just first page
- ✅ `test_pagination_stops_when_no_next` - Doesn't infinite loop
- ✅ `test_pagination_handles_single_page` - Works for small result sets

**Value:** Ensures users see ALL available scenes

---

### 4. Download System (HIGH - Data Delivery)

**Why:** Failed downloads = lost data, re-downloads waste time/bandwidth

**Tests:**
- ✅ `test_skip_existing_files` - Doesn't re-download (saves time/bandwidth)
- ✅ `test_overwrite_flag_redownloads` - Overwrite works when needed
- ✅ `test_parallel_downloads_faster_than_sequential` - Performance benefit real
- ✅ `test_one_failure_doesnt_stop_others` - Resilient downloads
- ✅ `test_week_grouping_for_psscope` - Files organized correctly

**Value:** Reliable, efficient data delivery

---

### 5. API Client Retry Logic (MEDIUM - Reliability)

**Why:** Transient failures shouldn't break orders

**Tests:**
- ✅ `test_retry_on_transient_failure` - Recovers from network blips
- ✅ `test_exponential_backoff` - Waits before retry (2s, 4s, 8s)
- ✅ `test_gives_up_after_max_retries` - Doesn't hang forever
- ✅ `test_no_retry_on_4xx_errors` - Don't retry auth/validation errors

**Value:** Resilient to network issues

---

### 6. Integration Tests (HIGH - End-to-End)

**Why:** Components work in isolation but break together

**Tests:**
- ✅ `test_submit_order_full_flow` - Geojson → filter → submit → save to DB
- ✅ `test_duplicate_prevention_blocks_resubmission` - Real duplicate scenario
- ✅ `test_status_check_updates_db` - Status check → DB update
- ✅ `test_batch_submit_creates_batch_id` - Batch tracking works
- ✅ `test_batch_check_processes_all_orders` - Batch operations complete

**Value:** Catches integration bugs

---

## Tests to SKIP (Low Value)

### Don't Test External Libraries
- ❌ Click command parsing (Click's job)
- ❌ Boto3 S3 uploads (boto3's job)
- ❌ Requests HTTP (requests' job)
- ❌ SQLite operations (sqlite3's job)
- ❌ GeoJSON parsing (geopandas' job)

### Don't Test UI/Output
- ❌ Console print statements
- ❌ Rich formatting
- ❌ Color codes
- ❌ Progress indicators

### Don't Test Configuration
- ❌ YAML parsing (pyyaml's job)
- ❌ Environment variable reading (os.getenv works)

---

## Test Structure

```
tests/
├── test_storage/
│   └── test_database.py          # Database operations
├── test_utils/
│   ├── test_scene_filtering.py   # Coverage, cadence logic
│   └── test_dates.py              # Date subdivision
├── test_api/
│   ├── test_pagination.py        # Planet API pagination
│   └── test_retry_logic.py       # Exponential backoff
├── test_downloaders/
│   └── test_parallel.py          # Download logic
└── test_integration/
    ├── test_submit_flow.py       # End-to-end submit
    └── test_status_flow.py       # End-to-end status check
```

---

## Test Data Strategy

### Use Real Scenarios
- Real Planet scene responses (mocked)
- Real order IDs and batch IDs
- Real date ranges users would submit
- Real AOI coverage percentages

### Don't Use
- Trivial "hello world" data
- Edge cases that never happen
- Unrealistic scenarios

---

## Success Metrics

Good test suite means:
1. **Duplicate orders blocked** - Zero false positives/negatives
2. **Scene selection accurate** - Gets expected scenes for cadence
3. **Downloads resilient** - One failure doesn't kill batch
4. **Data persisted** - Zero data loss scenarios
5. **Pagination complete** - Gets all pages, every time

---

## Coverage Target

**80% coverage on business logic:**
- `flowzero/storage/database.py` - 90%+ (critical)
- `flowzero/utils/dates.py` - 90%+ (critical filtering)
- `flowzero/api/planet.py` - 80%+ (pagination, retry)
- `flowzero/downloaders/parallel.py` - 80%+ (resilience)

**Don't care about coverage on:**
- CLI entry points (Click handles this)
- Print statements
- Import statements
- Config loading

---

## Test Implementation Priority

1. **Database tests** (30 min) - Data integrity is #1
2. **Scene filtering tests** (30 min) - Wrong scenes = wasted quota
3. **Pagination tests** (20 min) - Missing scenes = incomplete orders
4. **Download tests** (30 min) - Failed downloads = lost data
5. **Integration tests** (40 min) - Catch real-world issues

**Total: ~2.5 hours for high-value test suite**

---

## Anti-Patterns to Avoid

### ❌ Testing Implementation Details
```python
# BAD - testing internal variable names
def test_planet_client_has_api_key_attribute():
    client = PlanetAPIClient("key")
    assert client.api_key == "key"
```

### ✅ Testing Behavior
```python
# GOOD - testing what users care about
def test_duplicate_order_prevented():
    db.save_order(order1)
    duplicate = db.find_existing_order(aoi, start, end)
    assert duplicate is not None
```

---

## Running Tests

```bash
# Run all tests
pytest tests/

# Run specific category
pytest tests/test_storage/

# Run with coverage
pytest --cov=flowzero tests/

# Run only fast tests (skip integration)
pytest -m "not integration" tests/
```
