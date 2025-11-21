"""Status transformations for business status and date tracking."""

import pandas as pd
import numpy as np
import re
from datetime import datetime
from typing import Optional, Dict, Any, List, Set
from collections import defaultdict


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
        self.poi_history: Dict[str, List[Dict]] = {}
        self.poi_dates: Dict[str, Dict] = {}
        self.first_dataset_month: Optional[str] = None

    # ========================================================================
    # Status Normalization
    # ========================================================================

    def normalize_status(self, status: Any) -> str:
        """
        Normalize business status to standard values

        Args:
            status: Raw status string

        Returns:
            Normalized status: Open, Closed, or Temporarily Closed
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

    # ========================================================================
    # Historical Status Tracking
    # ========================================================================

    def reset_history(self):
        """Reset POI history tracking"""
        self.poi_history = {}
        self.poi_dates = {}
        self.first_dataset_month = None

    def add_to_history(self, poi_id: str, month: str, status: str):
        """
        Add POI status to history

        Args:
            poi_id: POI identifier
            month: Month string (YYYY-MM)
            status: Normalized status
        """
        if poi_id not in self.poi_history:
            self.poi_history[poi_id] = []

        self.poi_history[poi_id].append({
            'month': month,
            'status': status.lower()
        })

    def build_history_from_dataframe(self, df: pd.DataFrame, month: str):
        """
        Build POI history from a DataFrame

        Args:
            df: DataFrame with poi_id and status columns
            month: Month string for this dataset
        """
        if self.first_dataset_month is None:
            self.first_dataset_month = month

        for _, row in df.iterrows():
            poi_id = str(row['poi_id'])
            status = self.normalize_status(row.get('status', 'Unknown'))
            self.add_to_history(poi_id, month, status)

    def calculate_poi_dates(self):
        """
        Calculate open_date and closed_date for all POIs based on history

        Edge cases handled:
        - Boundary guard: No close_date if never seen open and first record is closed
        - Reopening detection: No close_date if POI reopened after closure
        """
        for poi_id, history in self.poi_history.items():
            # Sort history by month
            history.sort(key=lambda x: x['month'])

            first_appearance = history[0]

            # Determine open_date (None if in first month)
            if first_appearance['month'] == self.first_dataset_month:
                open_date = None
            else:
                open_date = first_appearance['month']

            # Find LAST time POI was open
            last_open_idx = None
            for i, record in enumerate(history):
                if record['status'] in self.OPEN_STATUSES:
                    last_open_idx = i

            # Start looking for closures AFTER last open
            start_idx = (last_open_idx + 1) if last_open_idx is not None else 0

            # Find FIRST closure after last open
            first_close_idx = None
            for i in range(start_idx, len(history)):
                if history[i]['status'] in self.CLOSED_STATUSES:
                    first_close_idx = i
                    break

            close_date = None

            if first_close_idx is not None:
                # EDGE CASE 1: Boundary guard
                if last_open_idx is None and first_close_idx == 0:
                    close_date = None
                else:
                    # EDGE CASE 2: Check for reopening after closure
                    reopened = False
                    for i in range(first_close_idx + 1, len(history)):
                        if history[i]['status'] in self.OPEN_STATUSES:
                            reopened = True
                            break

                    if not reopened:
                        close_month = history[first_close_idx]['month']
                        # Don't record if closure is in first month
                        if close_month != self.first_dataset_month:
                            close_date = close_month

            self.poi_dates[poi_id] = {
                'open_date': open_date,
                'closed_date': close_date,
                'history': history
            }

    def get_status_change(self, poi_id: str, current_month: str) -> Optional[str]:
        """
        Determine status change for a POI in a specific month

        Args:
            poi_id: POI identifier
            current_month: Current month (YYYY-MM)

        Returns:
            'Opened this month', 'Closed this month', or None
        """
        if poi_id not in self.poi_dates:
            return None

        dates = self.poi_dates[poi_id]

        # Check if opened this month
        if dates['open_date'] == current_month:
            return 'Opened this month'

        # Check if closed this month
        if dates['closed_date'] == current_month:
            return 'Closed this month'

        return None

    # ========================================================================
    # Batch Transformations
    # ========================================================================

    def transform_batch(self, df: pd.DataFrame, data_version_month: Optional[str] = None) -> pd.DataFrame:
        """
        Apply all status transformations to a DataFrame

        Args:
            df: Input DataFrame
            data_version_month: Month string for this dataset

        Returns:
            DataFrame with transformed columns
        """
        result = df.copy()

        # Normalize status
        if 'business_status' in df.columns:
            result['status'] = self.normalize_status_vectorized(df['business_status'])
        elif 'status' in df.columns:
            result['status'] = self.normalize_status_vectorized(df['status'])

        # Parse last verified date
        if 'day_time' in df.columns:
            result['last_verified_date'] = df['day_time'].apply(self.parse_date)
        else:
            result['last_verified_date'] = datetime.today().strftime('%Y-%m-%d')

        # Parse open date from oldest_date if available
        if 'oldest_date' in df.columns:
            result['open_date'] = df['oldest_date'].apply(self.parse_open_date)
        else:
            result['open_date'] = None

        # Initialize other columns
        result['closed_date'] = None
        result['status_change'] = None

        # If we have historical data, use it
        if self.poi_dates and 'poi_id' in result.columns:
            for idx, row in result.iterrows():
                poi_id = str(row['poi_id'])
                if poi_id in self.poi_dates:
                    dates = self.poi_dates[poi_id]
                    result.at[idx, 'open_date'] = dates['open_date']
                    result.at[idx, 'closed_date'] = dates['closed_date']
                    if data_version_month:
                        result.at[idx, 'status_change'] = self.get_status_change(poi_id, data_version_month)

        return result
