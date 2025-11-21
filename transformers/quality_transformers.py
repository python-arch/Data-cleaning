"""Quality transformations for data quality scoring and verification."""

import pandas as pd
import numpy as np
import re
import json
import phonenumbers
from typing import Optional, Any, Dict
from ast import literal_eval


class QualityTransformer:
    """Handles data quality scoring and verification flags."""

    def __init__(self):
        """Initialize QualityTransformer"""
        pass

    # ========================================================================
    # Data Version
    # ========================================================================

    @staticmethod
    def set_data_version_month(month_str: str) -> str:
        """
        Set data version month

        Args:
            month_str: Month string (YYYY-MM)

        Returns:
            Formatted version string (e.g., "2025-10")
        """
        return month_str

    @staticmethod
    def extract_month_from_filename(filename: str) -> Optional[str]:
        """
        Extract YYYY-MM from filename

        Args:
            filename: Filename with date pattern

        Returns:
            Month string or None
        """
        match = re.search(r'(\d{8})', filename)
        if match:
            date_str = match.group(1)
            year = date_str[:4]
            month = date_str[4:6]
            return f"{year}-{month}"
        return None

    # ========================================================================
    # Review Count Extraction
    # ========================================================================

    @staticmethod
    def extract_review_count(reviews_data: Any) -> Optional[int]:
        """
        Extract review count from reviews JSON column

        Sample input:
        {'reviews': [...], 'summary': {'count': 8, 'avg_rating': 3.75, ...}}

        Args:
            reviews_data: Raw reviews data (string or dict)

        Returns:
            Number of reviews or None
        """
        if pd.isna(reviews_data) or reviews_data == '':
            return None

        try:
            # Parse if string
            if isinstance(reviews_data, str):
                reviews_str = reviews_data.strip()
                if not reviews_str:
                    return None
                try:
                    reviews_data = json.loads(reviews_str.replace("'", "\""))
                except json.JSONDecodeError:
                    try:
                        reviews_data = literal_eval(reviews_str)
                    except (ValueError, SyntaxError):
                        return None

            if not isinstance(reviews_data, dict):
                return None

            # Try to get count from summary
            summary = reviews_data.get('summary', {})
            if isinstance(summary, dict) and 'count' in summary:
                return int(summary['count'])

            # Fallback: count reviews list
            reviews_list = reviews_data.get('reviews', [])
            if isinstance(reviews_list, list):
                return len(reviews_list)

            return None

        except Exception:
            return None

    # ========================================================================
    # Open Hours Reformatting
    # ========================================================================

    @staticmethod
    def reformat_open_hours(open_hours_data: Any) -> Optional[str]:
        """
        Reformat open_hours from complex JSON to simpler format

        Input format:
        {
            "Sunday": {"intervals": [{"start": "11:00", "end": "18:00"}], "is_24h": false, "closed": false},
            ...
        }

        Output format (simpler JSON):
        {"Mon": "11:00-18:00", "Tue": "11:00-18:00", ..., "Sun": "Closed"}

        Args:
            open_hours_data: Raw open hours data

        Returns:
            Reformatted JSON string or None
        """
        if pd.isna(open_hours_data) or open_hours_data == '':
            return None

        try:
            # Parse if string
            if isinstance(open_hours_data, str):
                hours_str = open_hours_data.strip()
                if not hours_str:
                    return None
                try:
                    open_hours_data = json.loads(hours_str.replace("'", "\""))
                except json.JSONDecodeError:
                    try:
                        open_hours_data = literal_eval(hours_str)
                    except (ValueError, SyntaxError):
                        return None

            if not isinstance(open_hours_data, dict):
                return None

            # Day name mapping to abbreviations
            day_abbrevs = {
                'Sunday': 'Sun',
                'Monday': 'Mon',
                'Tuesday': 'Tue',
                'Wednesday': 'Wed',
                'Thursday': 'Thu',
                'Friday': 'Fri',
                'Saturday': 'Sat'
            }

            # Standard day order
            day_order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

            result = {}

            for full_day, abbrev in day_abbrevs.items():
                if full_day in open_hours_data:
                    day_data = open_hours_data[full_day]

                    if isinstance(day_data, dict):
                        # Check if 24h
                        if day_data.get('is_24h', False):
                            result[abbrev] = '24 hours'
                        # Check if closed
                        elif day_data.get('closed', False):
                            result[abbrev] = 'Closed'
                        # Get intervals
                        elif 'intervals' in day_data:
                            intervals = day_data['intervals']
                            if isinstance(intervals, list) and intervals:
                                # Format each interval
                                interval_strs = []
                                for interval in intervals:
                                    if isinstance(interval, dict):
                                        start = interval.get('start', '')
                                        end = interval.get('end', '')
                                        if start and end:
                                            interval_strs.append(f"{start}-{end}")
                                if interval_strs:
                                    result[abbrev] = ', '.join(interval_strs)
                                else:
                                    result[abbrev] = 'Closed'
                            else:
                                result[abbrev] = 'Closed'
                        else:
                            result[abbrev] = 'Closed'
                    else:
                        result[abbrev] = 'Closed'

            # Return ordered result as JSON string
            if result:
                ordered_result = {day: result.get(day, 'Closed') for day in day_order if day in result}
                return json.dumps(ordered_result)

            return None

        except Exception:
            return None

    # ========================================================================
    # Verification Source
    # ========================================================================

    @staticmethod
    def determine_verification_source(row: pd.Series) -> str:
        """
        Determine verification source based on data characteristics

        Args:
            row: DataFrame row

        Returns:
            Source: 'Manual', 'Partner', or 'Automated'
        """
        # Check for partner indicators
        is_claimed = row.get('is_claimed')
        if pd.notna(is_claimed) and str(is_claimed).lower() == 'true':
            return 'Partner'

        # Check for manual verification indicators
        has_detailed_description = pd.notna(row.get('description')) and len(str(row.get('description', ''))) > 100
        has_multiple_photos = pd.notna(row.get('photo_dates')) and ',' in str(row.get('photo_dates', ''))

        if has_detailed_description and has_multiple_photos:
            return 'Manual'

        return 'Automated'

    # ========================================================================
    # Phone Validation
    # ========================================================================

    @staticmethod
    def validate_phone(number: Any) -> Optional[str]:
        """
        Validate and format phone number

        Args:
            number: Raw phone number

        Returns:
            Validated phone number or None
        """
        if pd.isna(number) or str(number).strip() == '':
            return None

        try:
            cleaned_number = ' '.join(str(number).split())
            parsed_number = phonenumbers.parse(cleaned_number, None)
            if phonenumbers.is_valid_number(parsed_number):
                return number
            return None
        except:
            return None

    @staticmethod
    def is_phone_valid(number: Any) -> bool:
        """Check if phone number is valid"""
        if pd.isna(number) or str(number).strip() == '':
            return False

        try:
            cleaned_number = ' '.join(str(number).split())
            parsed_number = phonenumbers.parse(cleaned_number, None)
            return phonenumbers.is_valid_number(parsed_number)
        except:
            return False

    # ========================================================================
    # Data Quality Flag (NEW LOGIC)
    # ========================================================================

    def assess_data_quality(self, row: pd.Series) -> str:
        """
        Assess overall data quality flag based on is_claimed, rating_count, review_count

        Logic:
        - Clean: is_claimed=true AND rating_count > 5 AND review_count > 3
        - Needs Review: rating_count >= 1 OR is_claimed=true (some verification exists)
        - Low Confidence: Everything else (no reviews, not claimed)

        Args:
            row: DataFrame row

        Returns:
            Quality flag: 'Clean', 'Needs Review', or 'Low Confidence'
        """
        # Get values
        is_claimed = row.get('is_claimed')
        is_claimed_bool = pd.notna(is_claimed) and str(is_claimed).lower() == 'true'

        rating_count = row.get('rating_count', 0)
        try:
            rating_count = int(float(rating_count)) if pd.notna(rating_count) else 0
        except (TypeError, ValueError):
            rating_count = 0

        review_count = row.get('review_count', 0)
        try:
            review_count = int(float(review_count)) if pd.notna(review_count) else 0
        except (TypeError, ValueError):
            review_count = 0

        # Clean: is_claimed=true AND rating_count > 5 AND review_count > 3
        if is_claimed_bool and rating_count > 5 and review_count > 3:
            return 'Clean'

        # Needs Review: rating_count >= 1 OR is_claimed=true
        if rating_count >= 1 or is_claimed_bool:
            return 'Needs Review'

        # Low Confidence: Everything else
        return 'Low Confidence'

    # ========================================================================
    # Confidence Score (kept for reference but not used for quality flag)
    # ========================================================================

    def calculate_confidence_score(self, row: pd.Series) -> int:
        """
        Calculate verification confidence score (0-100)
        This is kept for backwards compatibility but not used for data_quality_flag

        Args:
            row: DataFrame row

        Returns:
            Confidence score (0-100)
        """
        score = 0

        # Has name (+10)
        if pd.notna(row.get('name')) and str(row.get('name', '')).strip():
            score += 10

        # Has valid coordinates (+15)
        lat = row.get('latitude')
        lon = row.get('longitude')
        if pd.notna(lat) and pd.notna(lon):
            try:
                lat_f = float(lat)
                lon_f = float(lon)
                if -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
                    score += 15
            except:
                pass

        # Has address (+10)
        address = row.get('address') or row.get('address_full')
        if pd.notna(address) and str(address).strip():
            score += 10

        # Has phone (+10)
        phone = row.get('phone')
        if pd.notna(phone) and str(phone).strip():
            score += 10

        # Has website (+5)
        website = row.get('website_domain')
        if pd.notna(website) and str(website).strip():
            score += 5

        # Has category (+10)
        category = row.get('category_main') or row.get('category_level_1')
        if pd.notna(category) and str(category).strip():
            score += 10

        # Has rating (+5)
        rating = row.get('rating') or row.get('average_rating')
        if pd.notna(rating):
            score += 5

        # Has reviews (+5)
        reviews = row.get('rating_count') or row.get('review_count')
        if pd.notna(reviews):
            try:
                if int(float(reviews)) > 0:
                    score += 5
            except:
                pass

        # Has hours (+5)
        hours = row.get('open_hours')
        if pd.notna(hours) and str(hours).strip():
            score += 5

        # Name quality (+10)
        name = str(row.get('name', '')).strip()
        if name and not re.match(r'^\d+$', name) and not re.match(r'^-?\d+\.?\d*\s*,\s*-?\d+\.?\d*$', name):
            score += 10

        # Address quality (+10)
        if pd.notna(address):
            addr_str = str(address)
            if 'http' not in addr_str.lower() and len(addr_str) > 10:
                score += 10

        # Phone valid (+5)
        if self.is_phone_valid(row.get('phone')):
            score += 5

        return min(score, 100)  # Cap at 100

    # ========================================================================
    # Batch Transformations
    # ========================================================================

    def transform_batch(self, df: pd.DataFrame, data_version_month: str) -> pd.DataFrame:
        """
        Apply all quality transformations to a DataFrame

        Args:
            df: Input DataFrame
            data_version_month: Version string (YYYY-MM)

        Returns:
            DataFrame with transformed columns
        """
        result = df.copy()

        # Data version
        result['data_version_month'] = data_version_month

        # Extract review_count from reviews JSON
        if 'reviews' in df.columns:
            result['review_count'] = df['reviews'].apply(self.extract_review_count)
        else:
            result['review_count'] = None

        # Reformat open_hours to simpler format
        if 'open_hours' in df.columns:
            result['open_hours'] = df['open_hours'].apply(self.reformat_open_hours)

        # Verification source
        result['verification_source'] = df.apply(self.determine_verification_source, axis=1)

        # Confidence score (kept for reference)
        result['verification_confidence_score'] = df.apply(self.calculate_confidence_score, axis=1)

        # Quality flag (NEW LOGIC using is_claimed, rating_count, review_count)
        result['data_quality_flag'] = result.apply(self.assess_data_quality, axis=1)

        # Validate phone
        if 'phone' in df.columns:
            result['phone'] = df['phone'].apply(self.validate_phone)

        return result
