"""Status transformations for business status and date tracking."""

import pandas as pd
import numpy as np
import re
from datetime import datetime
from typing import Optional, Dict, Any, List, Set


class StatusTransformer:
    """Handles business status normalization and date tracking."""

    OPEN_STATUSES: Set[str] = {'open', 'open 24 hours'}
    CLOSED_STATUSES: Set[str] = {'temporarily closed', 'permanently closed'}

    STATUS_MAPPING = {
        'open': 'Open',
        'open 24 hours': 'Open',
        'permanently closed': 'Closed',
        'temporarily closed': 'Temporarily Closed',
    }

    def __init__(self):
        """Initialize StatusTransformer"""
        # For multi-version comparison
        self.previous_version_pois: Dict[str, str] = {}  # poi_id -> status
        self.current_version_pois: Dict[str, str] = {}   # poi_id -> status

    # ========================================================================
    # Status Normalization
    # ========================================================================

    def normalize_status(self, status: Any) -> str:
        """
        Normalize business status to standard values

        Args:
            status: Raw status string

        Returns:
            Normalized status: Open, Closed, Temporarily Closed, or Unknown
        """
        if pd.isna(status):
            return 'Unknown'

        status_lower = str(status).strip().lower()

        if status_lower in self.STATUS_MAPPING:
            return self.STATUS_MAPPING[status_lower]

        # Fuzzy matching
        if 'open' in status_lower:
            return 'Open'
        if 'temporary' in status_lower or 'temporarily' in status_lower:
            return 'Temporarily Closed'
        if 'closed' in status_lower:
            return 'Closed'

        return 'Unknown'

    def normalize_status_vectorized(self, statuses: pd.Series) -> pd.Series:
        """Vectorized status normalization"""
        return statuses.apply(self.normalize_status)

    # ========================================================================
    # Date Parsing
    # ========================================================================

    @staticmethod
    def parse_date(date_str: Any) -> Optional[str]:
        """
        Parse date string to standard format (YYYY-MM-DD)

        Args:
            date_str: Raw date string

        Returns:
            Standardized date string or None
        """
        if pd.isna(date_str):
            return None

        date_str = str(date_str).strip()

        # Try various formats
        formats = [
            '%Y-%m-%d',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%d-%m-%Y',
            '%m/%d/%Y',
            '%Y/%m/%d',
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str[:min(len(date_str), 26)], fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue

        return None

    @staticmethod
    def parse_open_date(oldest_date: Any) -> Optional[str]:
        """
        Parse open date from oldest_date field

        Args:
            oldest_date: Raw oldest date string

        Returns:
            Opening date string (YYYY-MM-DD) or None
        """
        return StatusTransformer.parse_date(oldest_date)

    @staticmethod
    def extract_month_from_filename(filename: str) -> Optional[str]:
        """
        Extract YYYY-MM from filename pattern

        Args:
            filename: Filename like "20250509" or "United States/20250509/..."

        Returns:
            Month string (YYYY-MM) or None
        """
        match = re.search(r'(\d{8})', filename)
        if match:
            date_str = match.group(1)
            year = date_str[:4]
            month = date_str[4:6]
            return f"{year}-{month}"
        return None

    @staticmethod
    def extract_month_from_date(date_str: Any) -> Optional[str]:
        """
        Extract YYYY-MM from a date string

        Args:
            date_str: Date string in various formats

        Returns:
            Month string (YYYY-MM) or None
        """
        parsed = StatusTransformer.parse_date(date_str)
        if parsed:
            return parsed[:7]  # YYYY-MM
        return None

    # ========================================================================
    # Multi-Version Comparison
    # ========================================================================

    def reset_version_tracking(self):
        """Reset version tracking for new comparison"""
        self.previous_version_pois = {}
        self.current_version_pois = {}

    def set_previous_version(self, df: pd.DataFrame):
        """
        Store POI statuses from previous version for comparison

        Args:
            df: DataFrame with poi_id and status columns
        """
        self.previous_version_pois = {}
        if 'poi_id' in df.columns and 'status' in df.columns:
            for _, row in df.iterrows():
                poi_id = str(row['poi_id'])
                status = self.normalize_status(row.get('business_status', row.get('status', 'Unknown')))
                self.previous_version_pois[poi_id] = status

    def compare_versions(self, current_df: pd.DataFrame) -> Dict[str, str]:
        """
        Compare current version with previous version to detect status changes

        Args:
            current_df: Current version DataFrame with poi_id and status

        Returns:
            Dict mapping poi_id to status change ('Opened this month' or 'Closed this month')
        """
        status_changes = {}

        for _, row in current_df.iterrows():
            poi_id = str(row['poi_id'])
            current_status = self.normalize_status(row.get('business_status', row.get('status', 'Unknown')))

            if poi_id in self.previous_version_pois:
                prev_status = self.previous_version_pois[poi_id]

                # Check if status changed from open to closed
                if prev_status == 'Open' and current_status in ['Closed', 'Temporarily Closed']:
                    status_changes[poi_id] = 'Closed this month'
                # Check if status changed from closed to open
                elif prev_status in ['Closed', 'Temporarily Closed'] and current_status == 'Open':
                    status_changes[poi_id] = 'Opened this month'
            else:
                # New POI in current version - check if it opened this month
                if current_status == 'Open':
                    status_changes[poi_id] = 'Opened this month'

        return status_changes

    def determine_status_change(self, row: pd.Series, data_version_month: str,
                                 version_comparison: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Determine status_change for a POI based on oldest_date and version comparison

        Logic:
        1. If oldest_date month matches processing month AND status is Open -> 'Opened this month'
        2. If version_comparison has a status change for this POI, use it
        3. Otherwise -> None

        Args:
            row: DataFrame row
            data_version_month: Processing month (YYYY-MM)
            version_comparison: Optional dict from compare_versions

        Returns:
            'Opened this month', 'Closed this month', or None
        """
        poi_id = str(row.get('poi_id', ''))
        status = row.get('status', 'Unknown')
        oldest_date = row.get('oldest_date')

        # Check if opened this month based on oldest_date
        oldest_month = self.extract_month_from_date(oldest_date)
        if oldest_month == data_version_month and status == 'Open':
            return 'Opened this month'

        # Check version comparison if available
        if version_comparison and poi_id in version_comparison:
            return version_comparison[poi_id]

        return None

    # ========================================================================
    # Batch Transformations
    # ========================================================================

    def transform_batch(self, df: pd.DataFrame, data_version_month: Optional[str] = None,
                        version_comparison: Optional[Dict[str, str]] = None) -> pd.DataFrame:
        """
        Apply all status transformations to a DataFrame

        Args:
            df: Input DataFrame
            data_version_month: Month string for this dataset (YYYY-MM)
            version_comparison: Optional dict from compare_versions for status_change

        Returns:
            DataFrame with transformed columns
        """
        result = df.copy()

        # Normalize status
        if 'business_status' in df.columns:
            result['status'] = self.normalize_status_vectorized(df['business_status'])
        elif 'status' in df.columns:
            result['status'] = self.normalize_status_vectorized(df['status'])
        else:
            result['status'] = 'Unknown'

        # Parse last verified date
        if 'day_time' in df.columns:
            result['last_verified_date'] = df['day_time'].apply(self.parse_date)
        else:
            result['last_verified_date'] = datetime.today().strftime('%Y-%m-%d')

        # Parse open date from oldest_date (sole source)
        if 'oldest_date' in df.columns:
            result['open_date'] = df['oldest_date'].apply(self.parse_open_date)
        else:
            result['open_date'] = None

        # closed_date is determined by version comparison only
        result['closed_date'] = None

        # Determine status_change
        if data_version_month:
            result['status_change'] = result.apply(
                lambda row: self.determine_status_change(row, data_version_month, version_comparison),
                axis=1
            )
        else:
            result['status_change'] = None

        return result
