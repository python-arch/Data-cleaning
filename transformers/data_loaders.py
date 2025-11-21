"""Data loading utilities for reference files."""

import logging
import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

BRAND_REQUIRED_COLUMNS = ['name', 'website_domain', 'brand_name']
CATEGORY_REQUIRED_COLUMNS = ['original_category', 'meta_category', 'middle_category', 'target_category']


def load_csv_robust(filepath: str, encoding: str = 'utf-8') -> Optional[pd.DataFrame]:
    """Load CSV file with encoding fallback."""
    if not filepath or not Path(filepath).exists():
        logger.error(f"File not found: {filepath}")
        return None

    encodings = [encoding, 'latin-1', 'cp1252', 'iso-8859-1']

    for enc in encodings:
        try:
            df = pd.read_csv(
                filepath,
                encoding=enc,
                encoding_errors='ignore',
                on_bad_lines='skip',
                low_memory=False
            )

            unnamed_cols = [c for c in df.columns if c.startswith('Unnamed:') or c == '']
            if unnamed_cols:
                df = df.drop(columns=unnamed_cols)

            df.columns = [str(c).strip() for c in df.columns]
            logger.debug(f"Loaded {filepath} with encoding {enc}")
            return df

        except (UnicodeDecodeError, pd.errors.ParserError) as e:
            logger.debug(f"Failed to load with {enc}: {e}")
            continue

    logger.error(f"Could not load {filepath} with any encoding")
    return None


def load_category_mapping(filepath: str) -> Optional[pd.DataFrame]:
    """Load category mapping file with strict schema validation."""
    df = load_csv_robust(filepath)

    if df is None:
        return None

    missing = [c for c in CATEGORY_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Category mapping file missing required columns: {missing}. "
            f"Expected columns: {CATEGORY_REQUIRED_COLUMNS}. "
            f"Found columns: {list(df.columns)}"
        )

    logger.info(f"Loaded category mapping: {len(df)} rows from {filepath}")
    return df


def load_brand_config(filepath: str) -> Optional[pd.DataFrame]:
    """Load brand configuration file with strict schema validation."""
    df = load_csv_robust(filepath)

    if df is None:
        return None

    missing = [c for c in BRAND_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Brand config file missing required columns: {missing}. "
            f"Expected columns: {BRAND_REQUIRED_COLUMNS}. "
            f"Found columns: {list(df.columns)}"
        )

    logger.info(f"Loaded brand config: {len(df)} rows from {filepath}")
    return df


def validate_dataframe(
    df: pd.DataFrame,
    required_columns: Optional[List[str]] = None,
    numeric_columns: Optional[List[str]] = None,
    non_empty_columns: Optional[List[str]] = None
) -> pd.DataFrame:
    """Validate and clean a DataFrame."""
    result = df.copy()

    if required_columns:
        missing = [c for c in required_columns if c not in result.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

    if numeric_columns:
        for col in numeric_columns:
            if col in result.columns:
                result[col] = pd.to_numeric(result[col], errors='coerce')

    if non_empty_columns:
        for col in non_empty_columns:
            if col in result.columns:
                result = result[result[col].notna() & (result[col] != '')]

    return result


def safe_json_parse(value: Any, default: Any = None) -> Any:
    """Safely parse JSON from a value."""
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

        try:
            return json.loads(value.replace("'", "\""))
        except json.JSONDecodeError:
            pass

        try:
            result = literal_eval(value)
            if isinstance(result, dict):
                return result
        except (ValueError, SyntaxError):
            pass

    return default
