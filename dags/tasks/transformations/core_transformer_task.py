"""
Airflow Task: Core Transformer
Handles POI ID hashing, name cleaning, and brand/chain detection
"""

import logging
import pandas as pd
from pathlib import Path
from typing import Dict, Optional
from airflow.decorators import task
from airflow.exceptions import AirflowException

# Import the transformer classes from your existing codebase
import sys
sys.path.insert(0, '/home/user/Data-cleaning')
from transformers import CoreTransformer, load_brand_config

logger = logging.getLogger(__name__)


@task
def apply_core_transformations(
    input_file_path: str,
    brand_config_path: Optional[str] = None,
    dag_run_id: Optional[str] = None,
) -> Dict[str, any]:
    """
    Apply core transformations to POI data.

    Transformations include:
    - Hash google_id to create poi_id (MD5)
    - Clean POI names (normalize whitespace)
    - Detect chain_flag (yes/no based on brand config)
    - Match brand_name (standardized brand name)
    - Filter invalid names (coordinates, meaningless strings, etc.)

    Args:
        input_file_path: Path to preprocessed parquet file
        brand_config_path: Optional path to brand config CSV
        dag_run_id: DAG run ID for output naming

    Returns:
        dict: {
            'output_file_path': str,
            'rows_input': int,
            'rows_output': int,
            'rows_removed': int,
            'chains_detected': int,
            'brands_matched': int,
            'poi_ids_created': int,
        }

    Raises:
        AirflowException: If data processing fails or required columns missing
    """
    logger.info("=" * 80)
    logger.info("CORE TRANSFORMER TASK STARTED")
    logger.info("=" * 80)

    try:
        # =====================================================================
        # 1. LOAD INPUT DATA
        # =====================================================================
        logger.info(f"Loading input data from: {input_file_path}")

        if not Path(input_file_path).exists():
            raise AirflowException(f"Input file not found: {input_file_path}")

        df = pd.read_parquet(input_file_path)
        initial_row_count = len(df)
        logger.info(f"✅ Loaded {initial_row_count:,} rows")

        # Validate required columns
        required_columns = ['google_id', 'name']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise AirflowException(
                f"Missing required columns: {missing_columns}. "
                f"Available columns: {list(df.columns)}"
            )

        # =====================================================================
        # 2. LOAD BRAND CONFIG
        # =====================================================================
        brand_config_df = None
        if brand_config_path and Path(brand_config_path).exists():
            logger.info(f"Loading brand config from: {brand_config_path}")
            try:
                brand_config_df = load_brand_config(brand_config_path)
                logger.info(f"✅ Loaded {len(brand_config_df):,} brand entries")
            except Exception as e:
                logger.warning(f"Failed to load brand config: {e}")
                logger.warning("Continuing without brand detection")
        else:
            logger.warning(f"Brand config not found at: {brand_config_path}")
            logger.warning("Chain detection will be disabled")

        # =====================================================================
        # 3. INITIALIZE TRANSFORMER
        # =====================================================================
        logger.info("Initializing CoreTransformer...")
        transformer = CoreTransformer(brand_config_df)
        logger.info("✅ CoreTransformer initialized")

        # =====================================================================
        # 4. APPLY TRANSFORMATIONS
        # =====================================================================
        logger.info("Applying core transformations...")

        # Transform batch (creates poi_id, cleans names, detects chains/brands)
        df = transformer.transform_batch(df)
        logger.info("✅ Transformations applied")

        # Count statistics before filtering
        poi_ids_created = df['poi_id'].notna().sum()
        chains_detected = (df['chain_flag'] == 'yes').sum()
        brands_matched = df['brand_name'].notna().sum()

        logger.info(f"  - POI IDs created: {poi_ids_created:,}")
        logger.info(f"  - Chains detected: {chains_detected:,}")
        logger.info(f"  - Brands matched: {brands_matched:,}")

        # =====================================================================
        # 5. FILTER INVALID NAMES
        # =====================================================================
        logger.info("Filtering invalid names...")
        rows_before_filter = len(df)

        df = transformer.filter_valid_names(df)

        rows_after_filter = len(df)
        rows_removed = rows_before_filter - rows_after_filter

        if rows_removed > 0:
            logger.info(f"✅ Removed {rows_removed:,} rows with invalid names "
                       f"({(rows_removed/rows_before_filter)*100:.2f}%)")
        else:
            logger.info("✅ All names valid, no rows removed")

        # =====================================================================
        # 6. VALIDATE OUTPUT
        # =====================================================================
        if df.empty:
            raise AirflowException("All rows filtered out - no valid data remaining!")

        # Check for duplicate POI IDs
        duplicate_count = df['poi_id'].duplicated().sum()
        if duplicate_count > 0:
            logger.warning(f"⚠️  Found {duplicate_count:,} duplicate POI IDs")

        # Check for missing POI IDs
        missing_poi_ids = df['poi_id'].isna().sum()
        if missing_poi_ids > 0:
            logger.warning(f"⚠️  Found {missing_poi_ids:,} missing POI IDs")

        # =====================================================================
        # 7. SAVE OUTPUT
        # =====================================================================
        # Generate output filename
        input_filename = Path(input_file_path).stem
        output_filename = f"{input_filename}_core_transformed.parquet"
        output_file_path = str(Path(input_file_path).parent / output_filename)

        logger.info(f"Saving transformed data to: {output_file_path}")
        df.to_parquet(output_file_path, index=False)
        logger.info(f"✅ Saved {len(df):,} rows")

        # =====================================================================
        # 8. PREPARE RETURN STATISTICS
        # =====================================================================
        result = {
            'output_file_path': output_file_path,
            'rows_input': initial_row_count,
            'rows_output': len(df),
            'rows_removed': rows_removed,
            'chains_detected': int(chains_detected),
            'brands_matched': int(brands_matched),
            'poi_ids_created': int(poi_ids_created),
            'duplicate_poi_ids': int(duplicate_count),
            'missing_poi_ids': int(missing_poi_ids),
        }

        # =====================================================================
        # 9. LOG SUMMARY
        # =====================================================================
        logger.info("=" * 80)
        logger.info("CORE TRANSFORMER TASK COMPLETED")
        logger.info("=" * 80)
        logger.info(f"Input rows:       {result['rows_input']:>12,}")
        logger.info(f"Output rows:      {result['rows_output']:>12,}")
        logger.info(f"Removed rows:     {result['rows_removed']:>12,}")
        logger.info(f"Chains detected:  {result['chains_detected']:>12,}")
        logger.info(f"Brands matched:   {result['brands_matched']:>12,}")
        logger.info(f"POI IDs created:  {result['poi_ids_created']:>12,}")
        logger.info(f"Output file:      {output_file_path}")
        logger.info("=" * 80)

        return result

    except Exception as e:
        logger.error("=" * 80)
        logger.error("CORE TRANSFORMER TASK FAILED")
        logger.error("=" * 80)
        logger.error(f"Error: {str(e)}")
        logger.error(f"Input file: {input_file_path}")
        raise AirflowException(f"Core transformation failed: {str(e)}") from e


# ============================================================================
# OPTIONAL: SEPARATE TASK FOR NAME VALIDATION ONLY (if needed)
# ============================================================================
@task
def validate_poi_names(input_file_path: str) -> Dict[str, any]:
    """
    Standalone task to validate POI names without other transformations.
    Useful for data quality checks.

    Args:
        input_file_path: Path to parquet file with 'name' column

    Returns:
        dict: Validation statistics
    """
    logger.info("Validating POI names...")

    df = pd.read_parquet(input_file_path)

    if 'name' not in df.columns:
        raise AirflowException("Column 'name' not found in input data")

    # Check name validity
    valid_mask = df['name'].apply(CoreTransformer.is_valid_name)

    result = {
        'total_rows': len(df),
        'valid_names': valid_mask.sum(),
        'invalid_names': (~valid_mask).sum(),
        'invalid_percentage': (1 - valid_mask.mean()) * 100,
    }

    logger.info(f"Valid names:   {result['valid_names']:,} ({100-result['invalid_percentage']:.2f}%)")
    logger.info(f"Invalid names: {result['invalid_names']:,} ({result['invalid_percentage']:.2f}%)")

    return result


# ============================================================================
# OPTIONAL: TASK FOR BRAND DETECTION ONLY (if needed)
# ============================================================================
@task
def detect_brands_only(
    input_file_path: str,
    brand_config_path: str,
) -> Dict[str, any]:
    """
    Standalone task to detect brands/chains without other transformations.
    Useful for testing brand detection logic.

    Args:
        input_file_path: Path to parquet file
        brand_config_path: Path to brand config CSV

    Returns:
        dict: Brand detection statistics
    """
    logger.info("Detecting brands and chains...")

    # Load data
    df = pd.read_parquet(input_file_path)

    # Load brand config
    brand_config_df = load_brand_config(brand_config_path)

    # Initialize transformer
    transformer = CoreTransformer(brand_config_df)

    # Apply brand detection
    df['chain_flag'] = df.apply(transformer.detect_chain, axis=1)
    df['brand_name'] = df.apply(transformer.match_brand, axis=1)

    result = {
        'total_rows': len(df),
        'chains_detected': (df['chain_flag'] == 'yes').sum(),
        'brands_matched': df['brand_name'].notna().sum(),
        'chain_percentage': ((df['chain_flag'] == 'yes').sum() / len(df)) * 100,
    }

    logger.info(f"Chains detected: {result['chains_detected']:,} ({result['chain_percentage']:.2f}%)")
    logger.info(f"Brands matched:  {result['brands_matched']:,}")

    return result
