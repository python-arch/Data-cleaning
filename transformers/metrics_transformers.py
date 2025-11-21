"""
Metrics Transformers - Traffic, Duration, Pricing, Reviews
"""

import pandas as pd
import numpy as np
import re
import json
from typing import Optional, Any


class MetricsTransformer:
    """
    Handles metrics-related transformations:
    - price_level: 1-5 scale (standardized)
    - average_stay_duration_minutes: Time spent
    - traffic_score: Visitor traffic index
    - review_count: Total reviews
    - average_rating: Mean rating score
    """

    def __init__(self):
        """Initialize MetricsTransformer"""
        pass

    # ========================================================================
    # Price Level Transformation
    # ========================================================================

    @staticmethod
    def standardize_price_level(price_str: Any) -> Optional[int]:
        """
        Standardize price level to 1-5 scale

        Handles:
        - Dollar signs: $, $$, $$$, $$$$
        - Numeric ranges: $1-10, $10-20, etc.
        - Empty/null values

        Args:
            price_str: Raw price string

        Returns:
            Standardized price level (1-5) or None
        """
        if pd.isna(price_str) or price_str == '' or price_str is None:
            return None

        price_str = str(price_str).strip()

        # Pattern 1: Dollar signs only ($, $$, $$$, $$$$)
        if re.match(r'^\$+$', price_str):
            dollar_count = price_str.count('$')
            if dollar_count == 1:
                return 1
            elif dollar_count == 2:
                return 2
            elif dollar_count == 3:
                return 4
            elif dollar_count >= 4:
                return 5

        # Pattern 2: Numeric values
        numbers = re.findall(r'\d+', price_str)

        if numbers:
            if len(numbers) >= 2:
                # Range format: use average
                avg_price = (int(numbers[0]) + int(numbers[1])) / 2
            else:
                avg_price = int(numbers[0])

            # Classification thresholds
            if avg_price < 15:
                return 1
            elif avg_price < 25:
                return 2
            elif avg_price < 40:
                return 3
            elif avg_price < 75:
                return 4
            else:
                return 5

        return None

    def standardize_price_level_vectorized(self, prices: pd.Series) -> pd.Series:
        """Vectorized price level standardization"""
        return prices.apply(self.standardize_price_level)

    # ========================================================================
    # Duration Transformation
    # ========================================================================

    @staticmethod
    def parse_duration_minutes(time_spent: Any) -> Optional[int]:
        """
        Parse time_spent string to minutes

        Handles formats like:
        - "People typically spend up to 3 hours here"
        - "People typically spend 30 min to 1 hour here"
        - "1-2 hours"
        - "30 minutes"

        Args:
            time_spent: Raw time spent string

        Returns:
            Duration in minutes or None
        """
        if pd.isna(time_spent):
            return None

        time_str = str(time_spent).lower()

        # Find hour patterns
        hour_matches = re.findall(r'(\d+(?:\.\d+)?)\s*(?:hour|hr)', time_str)
        # Find minute patterns
        minute_matches = re.findall(r'(\d+)\s*(?:minute|min)', time_str)

        total_minutes = 0

        if hour_matches:
            # Use the largest hour value if range given
            hours = max(float(h) for h in hour_matches)
            total_minutes += int(hours * 60)

        if minute_matches:
            # Use the largest minute value
            minutes = max(int(m) for m in minute_matches)
            total_minutes += minutes

        # If we found "up to X hours", use that value
        up_to_match = re.search(r'up to\s*(\d+(?:\.\d+)?)\s*(?:hour|hr)', time_str)
        if up_to_match:
            total_minutes = int(float(up_to_match.group(1)) * 60)

        return total_minutes if total_minutes > 0 else None

    def parse_duration_vectorized(self, durations: pd.Series) -> pd.Series:
        """Vectorized duration parsing"""
        return durations.apply(self.parse_duration_minutes)

    # ========================================================================
    # Traffic Score Transformation
    # ========================================================================

    @staticmethod
    def calculate_traffic_score(traffic_data: Any) -> Optional[float]:
        """
        Calculate traffic score from popular times data

        Handles multiple traffic data schemas:
        1. Processed format: {'popular_times': [{'day': '...', 'avg': 75}, ...]}
        2. Raw format with day keys: {'Sunday': [..., {'average_popularity': X}, ...], ...}
           - average_popularity is typically at index -3 (third from last)

        Args:
            traffic_data: Raw popular times data (string or dict)

        Returns:
            Average traffic score (0-100) or None
        """
        if pd.isna(traffic_data):
            return None

        try:
            # Parse if string - handle both single and double quotes
            if isinstance(traffic_data, str):
                traffic_str = traffic_data.strip()
                if not traffic_str:
                    return None
                try:
                    traffic_data = json.loads(traffic_str.replace("'", "\""))
                except json.JSONDecodeError:
                    # Try with ast.literal_eval as fallback for Python dict strings
                    try:
                        from ast import literal_eval
                        traffic_data = literal_eval(traffic_str)
                    except (ValueError, SyntaxError):
                        return None

            if not isinstance(traffic_data, dict):
                return None

            if not traffic_data:
                return None

            # Schema 1: Processed format with 'popular_times' key
            if 'popular_times' in traffic_data:
                popular_times = traffic_data['popular_times']
                if not isinstance(popular_times, list):
                    return None

                daily_avgs = []
                for day in popular_times:
                    if isinstance(day, dict) and 'avg' in day:
                        avg_val = day.get('avg')
                        if avg_val is not None:
                            try:
                                daily_avgs.append(float(avg_val))
                            except (TypeError, ValueError):
                                continue

                if daily_avgs:
                    return round(sum(daily_avgs) / len(daily_avgs), 2)
                return None

            # Schema 2: Raw format with day names as keys
            # average_popularity is at index -3 (third from last) in the day's list
            valid_days_scores = []

            # Check for any day keys (could be full names or abbreviations)
            day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
            day_abbrevs = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

            for day_key in traffic_data.keys():
                # Match full day names or abbreviations (case-insensitive)
                if day_key in day_names or day_key in day_abbrevs or \
                   day_key.lower() in [d.lower() for d in day_names] or \
                   day_key.lower() in [d.lower() for d in day_abbrevs]:

                    day_data = traffic_data[day_key]
                    if isinstance(day_data, list) and len(day_data) >= 3:
                        # Get average_popularity from third-to-last element
                        try:
                            entry = day_data[-3]
                            if isinstance(entry, dict):
                                avg_pop = entry.get('average_popularity')
                                if avg_pop is not None:
                                    try:
                                        valid_days_scores.append(float(avg_pop))
                                    except (TypeError, ValueError):
                                        continue
                        except (IndexError, TypeError):
                            continue

            # Filter out None values (already done, but be safe)
            valid_days_scores = [v for v in valid_days_scores if v is not None]

            if valid_days_scores:
                return round(sum(valid_days_scores) / len(valid_days_scores), 2)

            # Fallback: Try to find average_popularity anywhere in the structure
            all_avgs = []
            for day_key, day_data in traffic_data.items():
                if isinstance(day_data, list):
                    for entry in day_data:
                        if isinstance(entry, dict) and 'average_popularity' in entry:
                            avg_pop = entry.get('average_popularity')
                            if avg_pop is not None:
                                try:
                                    all_avgs.append(float(avg_pop))
                                except (TypeError, ValueError):
                                    continue
                            break  # Only take one per day

            if all_avgs:
                return round(sum(all_avgs) / len(all_avgs), 2)

            return None

        except Exception:
            # Catch-all for any unexpected errors
            return None

    def calculate_traffic_vectorized(self, traffic_series: pd.Series) -> pd.Series:
        """Vectorized traffic score calculation"""
        return traffic_series.apply(self.calculate_traffic_score)

    # ========================================================================
    # Reviews Transformation
    # ========================================================================

    @staticmethod
    def clean_rating(rating: Any) -> Optional[float]:
        """
        Clean and validate rating value

        Args:
            rating: Raw rating value

        Returns:
            Rating (0-5 scale) or None
        """
        if pd.isna(rating):
            return None

        try:
            rating_f = float(rating)
            if 0 <= rating_f <= 5:
                return round(rating_f, 2)
            return None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def clean_review_count(count: Any) -> Optional[int]:
        """
        Clean and validate review count

        Args:
            count: Raw review count

        Returns:
            Review count as integer or None
        """
        if pd.isna(count):
            return None

        try:
            count_i = int(float(count))
            return count_i if count_i >= 0 else None
        except (TypeError, ValueError):
            return None

    # ========================================================================
    # Batch Transformations
    # ========================================================================

    def transform_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply all metrics transformations to a DataFrame

        Args:
            df: Input DataFrame

        Returns:
            DataFrame with transformed columns
        """
        result = df.copy()

        # Price level
        if 'price_level' in df.columns:
            result['price_level'] = self.standardize_price_level_vectorized(df['price_level'])
        elif 'price_range' in df.columns:
            result['price_level'] = self.standardize_price_level_vectorized(df['price_range'])

        # Duration
        if 'time_spent' in df.columns:
            result['average_stay_duration_minutes'] = self.parse_duration_vectorized(df['time_spent'])

        # Traffic score
        if 'popular_times_data' in df.columns:
            result['traffic_score'] = self.calculate_traffic_vectorized(df['popular_times_data'])
        elif 'popular_times_data_kg' in df.columns:
            result['traffic_score'] = self.calculate_traffic_vectorized(df['popular_times_data_kg'])

        # Reviews
        if 'rating' in df.columns:
            result['average_rating'] = df['rating'].apply(self.clean_rating)
        if 'rating_count' in df.columns:
            result['review_count'] = df['rating_count'].apply(self.clean_review_count)

        return result
