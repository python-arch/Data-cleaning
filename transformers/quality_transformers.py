"""Quality transformations for data quality scoring and verification."""

import pandas as pd
import numpy as np
import re
import phonenumbers
from typing import Optional, Any, Dict


class QualityTransformer:
    """Handles data quality scoring and verification flags."""

    QUALITY_WEIGHTS = {
        'has_name': 10,
        'has_valid_coords': 15,
        'has_address': 10,
        'has_phone': 10,
        'has_website': 5,
        'has_category': 10,
        'has_rating': 5,
        'has_reviews': 5,
        'has_hours': 5,
        'name_quality': 10,
        'address_quality': 10,
        'phone_valid': 5,
    }

    # Quality thresholds
    HIGH_CONFIDENCE_THRESHOLD = 70
    MEDIUM_CONFIDENCE_THRESHOLD = 40

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
    # Confidence Score Calculation
    # ========================================================================

    def calculate_confidence_score(self, row: pd.Series) -> int:
        """
        Calculate verification confidence score (0-100)

        Args:
            row: DataFrame row

        Returns:
            Confidence score (0-100)
        """
        score = 0

        # Has name
        if pd.notna(row.get('name')) and str(row.get('name', '')).strip():
            score += self.QUALITY_WEIGHTS['has_name']

        # Has valid coordinates
        lat = row.get('latitude')
        lon = row.get('longitude')
        if pd.notna(lat) and pd.notna(lon):
            try:
                lat_f = float(lat)
                lon_f = float(lon)
                if -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
                    score += self.QUALITY_WEIGHTS['has_valid_coords']
            except:
                pass

        # Has address
        address = row.get('address') or row.get('address_full')
        if pd.notna(address) and str(address).strip():
            score += self.QUALITY_WEIGHTS['has_address']

        # Has phone
        phone = row.get('phone')
        if pd.notna(phone) and str(phone).strip():
            score += self.QUALITY_WEIGHTS['has_phone']

        # Has website
        website = row.get('website_domain')
        if pd.notna(website) and str(website).strip():
            score += self.QUALITY_WEIGHTS['has_website']

        # Has category
        category = row.get('category_main') or row.get('category_level_1')
        if pd.notna(category) and str(category).strip():
            score += self.QUALITY_WEIGHTS['has_category']

        # Has rating
        rating = row.get('rating') or row.get('average_rating')
        if pd.notna(rating):
            score += self.QUALITY_WEIGHTS['has_rating']

        # Has reviews
        reviews = row.get('rating_count') or row.get('review_count')
        if pd.notna(reviews):
            try:
                if int(float(reviews)) > 0:
                    score += self.QUALITY_WEIGHTS['has_reviews']
            except:
                pass

        # Has hours
        hours = row.get('open_hours')
        if pd.notna(hours) and str(hours).strip():
            score += self.QUALITY_WEIGHTS['has_hours']

        # Name quality (not just numbers, coordinates, etc.)
        name = str(row.get('name', '')).strip()
        if name and not re.match(r'^\d+$', name) and not re.match(r'^-?\d+\.?\d*\s*,\s*-?\d+\.?\d*$', name):
            score += self.QUALITY_WEIGHTS['name_quality']

        # Address quality (not HTTP, has proper format)
        if pd.notna(address):
            addr_str = str(address)
            if 'http' not in addr_str.lower() and len(addr_str) > 10:
                score += self.QUALITY_WEIGHTS['address_quality']

        # Phone valid
        if self.is_phone_valid(row.get('phone')):
            score += self.QUALITY_WEIGHTS['phone_valid']

        return min(score, 100)  # Cap at 100

    # ========================================================================
    # Quality Flag Assessment
    # ========================================================================

    def assess_data_quality(self, row: pd.Series) -> str:
        """
        Assess overall data quality flag

        Args:
            row: DataFrame row

        Returns:
            Quality flag: 'Clean', 'Needs Review', or 'Low Confidence'
        """
        score = self.calculate_confidence_score(row)

        if score >= self.HIGH_CONFIDENCE_THRESHOLD:
            return 'Clean'
        elif score >= self.MEDIUM_CONFIDENCE_THRESHOLD:
            return 'Needs Review'
        else:
            return 'Low Confidence'

    def assess_quality_issues(self, row: pd.Series) -> str:
        """
        Get list of quality issues for a record

        Args:
            row: DataFrame row

        Returns:
            Semicolon-separated list of issues
        """
        issues = []

        # Name issues
        name = str(row.get('name', '')).strip()
        if not name:
            issues.append('missing name')
        elif re.match(r'^\d+$', name):
            issues.append('numeric name')
        elif re.match(r'^-?\d+\.?\d*\s*,\s*-?\d+\.?\d*$', name):
            issues.append('coordinate-like name')

        # Address issues
        address = row.get('address') or row.get('address_full')
        if pd.isna(address) or not str(address).strip():
            issues.append('missing address')
        elif 'http' in str(address).lower():
            issues.append('HTTP in address')

        # Phone issues
        phone = row.get('phone')
        if pd.isna(phone) or not str(phone).strip():
            issues.append('missing phone')
        elif not self.is_phone_valid(phone):
            issues.append('invalid phone')

        # Website issues
        website = row.get('website_domain')
        if pd.isna(website) or not str(website).strip():
            issues.append('missing website')
        elif re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', str(website)):
            issues.append('IP address website')

        # Coordinate issues
        lat = row.get('latitude')
        lon = row.get('longitude')
        if pd.isna(lat) or pd.isna(lon):
            issues.append('missing coordinates')
        else:
            try:
                lat_f = float(lat)
                lon_f = float(lon)
                if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
                    issues.append('invalid coordinates')
                elif not (24.0 <= lat_f <= 49.5 and -125.0 <= lon_f <= -66.0):
                    issues.append('outside USA')
            except:
                issues.append('non-numeric coordinates')

        return '; '.join(issues) if issues else ''

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

        # Verification source
        result['verification_source'] = df.apply(self.determine_verification_source, axis=1)

        # Confidence score
        result['verification_confidence_score'] = df.apply(self.calculate_confidence_score, axis=1)

        # Quality flag
        result['data_quality_flag'] = df.apply(self.assess_data_quality, axis=1)

        # Validate phone
        if 'phone' in df.columns:
            result['phone'] = df['phone'].apply(self.validate_phone)

        return result
