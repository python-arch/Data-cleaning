"""
Data Loaders - Robust data loading utilities for reference files
"""

import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any
from pathlib import Path


def load_csv_robust(
    filepath: str,
    required_columns: Optional[List[str]] = None,
    column_candidates: Optional[Dict[str, List[str]]] = None,
    drop_unnamed: bool = True,
    encoding: str = 'utf-8',
    encoding_errors: str = 'ignore'
) -> Optional[pd.DataFrame]:
    """
    Load CSV file with robust error handling and flexible column detection

    Args:
        filepath: Path to CSV file
        required_columns: List of columns that must be present (exact match)
        column_candidates: Dict mapping required column names to list of candidate names
            e.g., {'name': ['name', 'poi_name', 'business_name']}
        drop_unnamed: Whether to drop unnamed columns (e.g., from CSV index)
        encoding: File encoding
        encoding_errors: How to handle encoding errors

    Returns:
        Loaded DataFrame or None if loading fails
    """
    if not filepath or not Path(filepath).exists():
        return None

    try:
        # Try different encodings
        encodings = [encoding, 'latin-1', 'cp1252', 'iso-8859-1']
        df = None

        for enc in encodings:
            try:
                df = pd.read_csv(
                    filepath,
                    encoding=enc,
                    encoding_errors=encoding_errors,
                    on_bad_lines='skip',
                    low_memory=False
                )
                break
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue

        if df is None:
            return None

        # Drop unnamed columns if requested
        if drop_unnamed:
            unnamed_cols = [c for c in df.columns if c.startswith('Unnamed:') or c == '']
            if unnamed_cols:
                df = df.drop(columns=unnamed_cols)

        # Clean column names (strip whitespace)
        df.columns = [str(c).strip() for c in df.columns]

        # Validate required columns
        if required_columns:
            missing = [c for c in required_columns if c not in df.columns]
            if missing:
                print(f"Warning: Missing required columns in {filepath}: {missing}")
                return None

        # Map column candidates to standardized names
        if column_candidates:
            for target_name, candidates in column_candidates.items():
                if target_name not in df.columns:
                    for candidate in candidates:
                        if candidate in df.columns:
                            df = df.rename(columns={candidate: target_name})
                            break

        return df

    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return None


def load_category_mapping(filepath: str) -> Optional[pd.DataFrame]:
    """
    Load category mapping file with flexible schema support

    Expected schemas:
    1. Standard: original_category, target_category, middle_category, meta_category
    2. Extended: original_category, mapped_category, confidence, big_category,
                 target_category, match_quality, middle_category, meta_category

    Args:
        filepath: Path to category mapping CSV

    Returns:
        Loaded DataFrame with standardized columns or None
    """
    column_candidates = {
        'original_category': ['original_category', 'source_category', 'category', 'category_main'],
        'meta_category': ['meta_category', 'big_category', 'category_level_1', 'category_l1'],
        'middle_category': ['middle_category', 'mapped_category', 'category_level_2', 'category_l2'],
        'target_category': ['target_category', 'final_category', 'category_level_3', 'category_l3'],
    }

    df = load_csv_robust(filepath, column_candidates=column_candidates)

    if df is None:
        return None

    # Ensure at least original_category is present
    if 'original_category' not in df.columns:
        # Try to find a suitable column
        for col in df.columns:
            if 'category' in col.lower() and 'target' not in col.lower() and 'meta' not in col.lower():
                df = df.rename(columns={col: 'original_category'})
                break

    if 'original_category' not in df.columns:
        print(f"Warning: Could not find original_category column in {filepath}")
        return None

    return df


def load_brand_config(filepath: str) -> Optional[pd.DataFrame]:
    """
    Load brand configuration file with flexible schema support

    Expected schemas:
    1. Standard: name, website_domain, brand_name
    2. Extended: ,website_domain,name,original_category,brand_name,user_category,category_level2
       (First column may be unnamed index)

    Args:
        filepath: Path to brand config CSV

    Returns:
        Loaded DataFrame with standardized columns or None
    """
    column_candidates = {
        'name': ['name', 'poi_name', 'business_name', 'place_name'],
        'website_domain': ['website_domain', 'domain', 'website', 'web_domain'],
        'brand_name': ['brand_name', 'brand', 'chain_name', 'parent_brand'],
    }

    df = load_csv_robust(filepath, column_candidates=column_candidates)

    if df is None:
        return None

    # Ensure at least brand_name is present
    if 'brand_name' not in df.columns:
        print(f"Warning: Could not find brand_name column in {filepath}")
        return None

    return df


def validate_dataframe(
    df: pd.DataFrame,
    required_columns: Optional[List[str]] = None,
    numeric_columns: Optional[List[str]] = None,
    non_empty_columns: Optional[List[str]] = None
) -> pd.DataFrame:
    """
    Validate and clean a DataFrame

    Args:
        df: Input DataFrame
        required_columns: Columns that must be present
        numeric_columns: Columns that should be numeric
        non_empty_columns: Columns that should not have empty values

    Returns:
        Validated DataFrame (may be filtered)
    """
    result = df.copy()

    # Check required columns
    if required_columns:
        missing = [c for c in required_columns if c not in result.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

    # Convert numeric columns
    if numeric_columns:
        for col in numeric_columns:
            if col in result.columns:
                result[col] = pd.to_numeric(result[col], errors='coerce')

    # Filter out rows with empty required values
    if non_empty_columns:
        for col in non_empty_columns:
            if col in result.columns:
                result = result[result[col].notna() & (result[col] != '')]

    return result


def safe_json_parse(value: Any, default: Any = None) -> Any:
    """
    Safely parse JSON from a value

    Args:
        value: Value to parse (string, dict, or other)
        default: Default value if parsing fails

    Returns:
        Parsed JSON or default
    """
    import json
    from ast import literal_eval

    if pd.isna(value) or value is None:
        return default

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default

        # Try JSON parsing
        try:
            return json.loads(value.replace("'", "\""))
        except json.JSONDecodeError:
            pass

        # Try literal_eval for Python dict strings
        try:
            result = literal_eval(value)
            if isinstance(result, dict):
                return result
        except (ValueError, SyntaxError):
            pass

    return default
