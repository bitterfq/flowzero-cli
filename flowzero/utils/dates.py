"""Date utilities for scene selection and ordering."""
import re
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta


def subdivide_date_range(start_date, end_date, max_months=6):
    """
    Subdivide a date range into chunks of max_months or less.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        max_months: Maximum number of months per chunk

    Returns:
        List of (start_date, end_date) tuples for each chunk
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    chunks = []
    current_start = start_dt

    while current_start <= end_dt:
        chunk_end = current_start + relativedelta(months=max_months) - timedelta(days=1)
        if chunk_end > end_dt:
            chunk_end = end_dt

        chunks.append((current_start.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))

        current_start = chunk_end + timedelta(days=1)

    return chunks


def extract_date_from_filename(filename):
    """
    Extract the acquisition date from Planet product filename.

    Args:
        filename: Planet filename

    Returns:
        Date string in YYYY_MM_DD format or None
    """
    pattern = r"(\d{4})(\d{2})(\d{2})_"
    match = re.search(pattern, filename)
    if match:
        year, month, day = match.groups()
        return f"{year}_{month}_{day}"
    return None


def extract_scene_id(filename):
    """
    Extract scene ID from Planet product filename.

    Args:
        filename: Planet filename

    Returns:
        Scene ID or None
    """
    pattern = r"\d{8}_(\w+)_"
    match = re.search(pattern, filename)
    if match:
        return match.group(1)
    return None


def get_week_start_date(date_str):
    """
    Get start of week (Sunday) for a given date string (YYYY_MM_DD).

    Args:
        date_str: Date string in YYYY_MM_DD format

    Returns:
        Week start date in YYYY_MM_DD format
    """
    year, month, day = map(int, date_str.split("_"))
    date_obj = datetime(year, month, day)
    days_to_sunday = date_obj.weekday() + 1
    if days_to_sunday == 7:
        return date_str
    sunday = date_obj - timedelta(days=days_to_sunday)
    return sunday.strftime("%Y_%m_%d")


def get_interval_key(date_obj, cadence):
    """
    Get interval key for scene grouping based on cadence.

    Args:
        date_obj: datetime object
        cadence: One of 'daily', 'weekly', 'monthly'

    Returns:
        Interval key string
    """
    if cadence == "daily":
        return date_obj.strftime("%Y-%m-%d")
    elif cadence == "weekly":
        sunday = date_obj - timedelta(
            days=date_obj.weekday() + 1 if date_obj.weekday() != 6 else 0
        )
        return sunday.strftime("%Y-%m-%d")
    elif cadence == "monthly":
        return date_obj.strftime("%Y-%m")
    else:
        raise ValueError(f"Invalid cadence: {cadence}")
