"""USA POI Data Pipeline - Processes POI data from S3 for USA locations."""

import os
import sys
import re
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

import pandas as pd
import numpy as np
import boto3
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))

from transformers import (
    CoreTransformer,
    LocationTransformer,
    CategoryTransformer,
    StatusTransformer,
    MetricsTransformer,
    QualityTransformer,
    EstablishmentTransformer,
    load_category_mapping,
    load_brand_config,
)

from config.schema_mapping import (
    SOURCE_COLUMNS,
    FINAL_OUTPUT_COLUMNS,
    REQUIRED_INPUT_COLUMNS,
)


def setup_logging(log_level: str = 'INFO', log_file: Optional[str] = None) -> logging.Logger:
    """Configure logging for the pipeline."""
    logger = logging.getLogger('usa_poi_pipeline')
    logger.setLevel(getattr(logging, log_level.upper()))

    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logging.getLogger('transformers').setLevel(getattr(logging, log_level.upper()))

    return logger


class USAPOIPipeline:
    """Main pipeline for processing USA POI data from S3."""

    def __init__(
        self,
        s3_client,
        s3_bucket_name: str,
        local_download_path: str,
        local_save_path: str,
        gadm_boundaries=None,
        category_mapping_df: Optional[pd.DataFrame] = None,
        brand_config_df: Optional[pd.DataFrame] = None,
        batch_size: int = 200000,
        logger: Optional[logging.Logger] = None,
    ):
        self.s3_client = s3_client
        self.s3_bucket_name = s3_bucket_name
        self.local_download_path = local_download_path
        self.local_save_path = local_save_path
        self.batch_size = batch_size
        self.logger = logger or logging.getLogger('usa_poi_pipeline')

        os.makedirs(local_download_path, exist_ok=True)
        os.makedirs(local_save_path, exist_ok=True)

        self.logger.info("Initializing transformers...")
        self.core_transformer = CoreTransformer(brand_config_df)
        self.location_transformer = LocationTransformer(gadm_boundaries)
        self.category_transformer = CategoryTransformer(category_mapping_df)
        self.status_transformer = StatusTransformer()
        self.metrics_transformer = MetricsTransformer()
        self.quality_transformer = QualityTransformer()
        self.establishment_transformer = EstablishmentTransformer()
        self.logger.info("Transformers initialized")

        self.stats = {
            'files_processed': 0,
            'files_skipped': 0,
            'total_input_rows': 0,
            'total_output_rows': 0,
            'removed_duplicates': 0,
            'removed_invalid_names': 0,
            'removed_outside_usa': 0,
            'removed_invalid_coords': 0,
        }

        # Store processed versions for comparison
        self.processed_versions: Dict[str, pd.DataFrame] = {}

    @staticmethod
    def extract_month_from_filename(filename: str) -> Optional[str]:
        match = re.search(r'(\d{8})', filename)
        if match:
            date_str = match.group(1)
            return f"{date_str[:4]}-{date_str[4:6]}"
        return None

    def _get_source_columns(self) -> List[str]:
        return [
            'google_id', 'name', 'name_second', 'country_name', 'country',
            'floor_no', 'phone', 'phone_local', 'street', 'locality',
            'sub_locality', 'region_level_1', 'region_level_2', 'postcode',
            'plus_code', 'address', 'latitude', 'longitude', 'rating',
            'rating_count', 'rating_by_star', 'price_range', 'price_reported',
            'business_status', 'area_type', 'is_claimed', 'types',
            'category_main', 'categories_list', 'description', 'place_amenities',
            'spoken_language', 'link', 'website', 'website_domain',
            'website_contact', 'inside_places', 'inside_places_categories',
            'inside_places_ids', 'open_hours', 'time_spent', 'price_level',
            'popular_times_data', 'popular_times_data_kg', 'describe_data',
            'zone', 'zone_main', 'timeoffset', 'hotel_stars', 'hotel_price',
            'day_time', 'photo_dates', 'review_dates', 'oldest_date', 'reviews',
        ]

    def _validate_input_columns(self, df: pd.DataFrame) -> None:
        """Validate that required input columns exist."""
        missing = [c for c in REQUIRED_INPUT_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"Input data missing required columns: {missing}")

    def _clean_coordinates(self, df: pd.DataFrame) -> pd.DataFrame:
        initial_rows = len(df)

        df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
        df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')

        valid_coords = df['latitude'].notna() & df['longitude'].notna()
        df = df[valid_coords].copy()

        valid_lat = (df['latitude'] >= -90) & (df['latitude'] <= 90)
        valid_lon = (df['longitude'] >= -180) & (df['longitude'] <= 180)
        df = df[valid_lat & valid_lon].copy()

        removed = initial_rows - len(df)
        self.stats['removed_invalid_coords'] += removed
        if removed > 0:
            self.logger.debug(f"Removed {removed:,} rows with invalid coordinates")
        return df

    def _filter_usa(self, df: pd.DataFrame) -> pd.DataFrame:
        initial_rows = len(df)

        outside_usa = self.location_transformer.is_outside_usa_vectorized(
            df['latitude'], df['longitude']
        )
        df = df[~outside_usa].copy()

        removed = initial_rows - len(df)
        self.stats['removed_outside_usa'] += removed
        if removed > 0:
            self.logger.debug(f"Removed {removed:,} rows outside USA")
        return df

    def _apply_transformations(self, df: pd.DataFrame, data_version_month: str,
                                version_comparison: Optional[Dict[str, str]] = None) -> pd.DataFrame:
        df = self.core_transformer.transform_batch(df)

        initial_rows = len(df)
        df = self.core_transformer.filter_valid_names(df)
        removed = initial_rows - len(df)
        self.stats['removed_invalid_names'] += removed
        if removed > 0:
            self.logger.debug(f"Removed {removed:,} rows with invalid names")

        df = self.location_transformer.transform_batch(df)
        df = self.category_transformer.transform_batch(df)
        df = self.status_transformer.transform_batch(df, data_version_month, version_comparison)
        df = self.metrics_transformer.transform_batch(df)
        df = self.establishment_transformer.transform_batch(df)
        df = self.quality_transformer.transform_batch(df, data_version_month)

        # Map locality and region columns
        if 'locality' not in df.columns and 'locality' in df.columns:
            pass  # Already named correctly
        if 'region' not in df.columns and 'region_level_1' in df.columns:
            df['region'] = df['region_level_1']

        return df

    def _select_output_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        output_cols = []

        for col in FINAL_OUTPUT_COLUMNS:
            if col in df.columns:
                output_cols.append(col)
            else:
                df[col] = None
                output_cols.append(col)

        return df[output_cols]

    def process_chunk(self, chunk: pd.DataFrame, data_version_month: str,
                      version_comparison: Optional[Dict[str, str]] = None) -> pd.DataFrame:
        self.logger.debug(f"Processing chunk: {len(chunk):,} rows")

        self._validate_input_columns(chunk)

        chunk = self._clean_coordinates(chunk)
        if chunk.empty:
            self.logger.debug("No valid data after coordinate cleaning")
            return pd.DataFrame()

        chunk = self._filter_usa(chunk)
        if chunk.empty:
            self.logger.debug("No USA data in this chunk")
            return pd.DataFrame()

        self.logger.debug(f"USA records: {len(chunk):,}")

        chunk = self._apply_transformations(chunk, data_version_month, version_comparison)
        chunk = self._select_output_columns(chunk)

        return chunk

    def process_file(self, object_key: str, previous_version_df: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
        data_version_month = self.extract_month_from_filename(object_key)
        path_parts = object_key.split('/')
        date_str = path_parts[-2] if len(path_parts) >= 2 else ''

        output_filename = f"USA_{date_str}.csv"
        local_save_csv_path = os.path.join(self.local_save_path, output_filename)

        if os.path.exists(local_save_csv_path):
            self.logger.info(f"Skipping {object_key} - already processed")
            self.stats['files_skipped'] += 1
            # Load existing file for version comparison
            try:
                return pd.read_csv(local_save_csv_path)
            except:
                return None

        zip_filename = os.path.basename(object_key)
        local_zip_path = os.path.join(self.local_download_path, zip_filename)

        self.logger.info(f"Processing: {object_key}")
        self.logger.info(f"Output: {output_filename}")

        file_start_time = time.time()

        # Prepare version comparison if previous version available
        version_comparison = None
        if previous_version_df is not None:
            self.logger.info("Comparing with previous version for status changes...")
            self.status_transformer.set_previous_version(previous_version_df)

        try:
            self.logger.info("Downloading from S3...")
            download_start = time.time()
            self.s3_client.download_file(self.s3_bucket_name, object_key, local_zip_path)
            download_time = time.time() - download_start

            file_size_mb = os.path.getsize(local_zip_path) / (1024 * 1024)
            self.logger.info(f"Downloaded: {file_size_mb:.1f} MB in {download_time:.1f}s")

            compression = 'zip' if object_key.lower().endswith('.zip') else 'infer'

            csv_chunker = pd.read_csv(
                local_zip_path,
                compression=compression,
                chunksize=self.batch_size,
                usecols=lambda x: x in self._get_source_columns(),
                low_memory=False,
                dtype={'postcode': str},
                encoding='utf-8',
                encoding_errors='ignore',
                on_bad_lines='skip'
            )

            all_chunks = []
            chunk_number = 0
            total_input_rows = 0

            for chunk in csv_chunker:
                chunk_number += 1
                total_input_rows += len(chunk)

                self.logger.info(f"Chunk {chunk_number}: {len(chunk):,} input rows")

                # For first chunk, do version comparison if available
                chunk_version_comparison = None
                if chunk_number == 1 and previous_version_df is not None:
                    chunk_version_comparison = self.status_transformer.compare_versions(chunk)

                processed_chunk = self.process_chunk(chunk, data_version_month, chunk_version_comparison)

                if not processed_chunk.empty:
                    all_chunks.append(processed_chunk)
                    self.logger.info(f"Chunk {chunk_number}: {len(processed_chunk):,} output rows")

            self.stats['total_input_rows'] += total_input_rows

            if all_chunks:
                self.logger.info(f"Merging {len(all_chunks)} chunks...")
                final_df = pd.concat(all_chunks, ignore_index=True)

                before = len(final_df)
                final_df = final_df.drop_duplicates(subset='poi_id', keep='first')
                removed_dupes = before - len(final_df)
                self.stats['removed_duplicates'] += removed_dupes

                if removed_dupes > 0:
                    self.logger.info(f"Removed {removed_dupes:,} duplicates")

                self.logger.info(f"Saving {len(final_df):,} rows to {output_filename}")
                final_df.to_csv(local_save_csv_path, index=False)

                self.stats['total_output_rows'] += len(final_df)
                self.stats['files_processed'] += 1

                file_time = time.time() - file_start_time
                self.logger.info(f"Completed in {file_time:.1f}s | Input: {total_input_rows:,} | Output: {len(final_df):,}")

                return final_df
            else:
                self.logger.warning("No data to save after processing")
                return None

        except Exception as e:
            self.logger.error(f"Error processing {object_key}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return None

        finally:
            if os.path.exists(local_zip_path):
                os.remove(local_zip_path)

    def run_from_csv(self, paths_csv: str):
        """
        Run pipeline for multiple versions from a CSV file containing S3 paths.

        The CSV should have a 'Path' column with S3 object keys like:
        "United States/20250114/United States.zip"
        "United States/20250202/United States.zip"
        ...

        Each consecutive pair of versions will be compared for status_change.

        Args:
            paths_csv: Path to CSV file with S3 paths
        """
        self.logger.info("=" * 60)
        self.logger.info("USA POI DATA PIPELINE - MULTI-VERSION MODE")
        self.logger.info("=" * 60)
        self.logger.info(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"Bucket: {self.s3_bucket_name}")
        self.logger.info(f"Paths CSV: {paths_csv}")
        self.logger.info("=" * 60)

        start_time = time.time()

        # Read paths CSV
        paths_df = pd.read_csv(paths_csv)
        if 'Path' not in paths_df.columns:
            raise ValueError("CSV must have 'Path' column")

        paths = paths_df['Path'].tolist()
        self.logger.info(f"Found {len(paths)} versions to process")

        # Sort paths by date to ensure chronological order
        paths = sorted(paths, key=lambda x: re.search(r'(\d{8})', x).group(1) if re.search(r'(\d{8})', x) else '')

        previous_version_df = None

        for i, object_key in enumerate(paths):
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"VERSION {i+1}/{len(paths)}: {object_key}")
            self.logger.info(f"{'='*60}")

            # Process file with comparison to previous version
            current_version_df = self.process_file(object_key, previous_version_df)

            # Store current version for next iteration
            if current_version_df is not None:
                previous_version_df = current_version_df
                self.processed_versions[object_key] = current_version_df

        total_time = time.time() - start_time

        self._print_summary(total_time)

    def run(self, prefix_filter: str = 'United States/2'):
        """Run pipeline for all files matching the prefix filter."""
        self.logger.info("=" * 60)
        self.logger.info("USA POI DATA PIPELINE")
        self.logger.info("=" * 60)
        self.logger.info(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"Bucket: {self.s3_bucket_name}")
        self.logger.info(f"Filter: {prefix_filter}")
        self.logger.info("=" * 60)

        start_time = time.time()

        paginator = self.s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=self.s3_bucket_name)

        # Collect all matching files
        matching_files = []
        for page in pages:
            if 'Contents' not in page:
                continue

            for obj in page['Contents']:
                object_key = obj['Key']

                if prefix_filter in object_key and 'big_categories_data' not in object_key:
                    matching_files.append(object_key)

        # Sort by date
        matching_files = sorted(matching_files, key=lambda x: re.search(r'(\d{8})', x).group(1) if re.search(r'(\d{8})', x) else '')

        self.logger.info(f"Found {len(matching_files)} files to process")

        previous_version_df = None

        for i, object_key in enumerate(matching_files):
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"VERSION {i+1}/{len(matching_files)}: {object_key}")
            self.logger.info(f"{'='*60}")

            current_version_df = self.process_file(object_key, previous_version_df)

            if current_version_df is not None:
                previous_version_df = current_version_df

        total_time = time.time() - start_time

        self._print_summary(total_time)

    def _print_summary(self, total_time: float):
        """Print pipeline summary."""
        self.logger.info("=" * 60)
        self.logger.info("PIPELINE COMPLETE")
        self.logger.info("=" * 60)
        self.logger.info(f"Files processed: {self.stats['files_processed']}")
        self.logger.info(f"Files skipped: {self.stats['files_skipped']}")
        self.logger.info(f"Total input rows: {self.stats['total_input_rows']:,}")
        self.logger.info(f"Total output rows: {self.stats['total_output_rows']:,}")
        self.logger.info("Records removed:")
        self.logger.info(f"  - Duplicates: {self.stats['removed_duplicates']:,}")
        self.logger.info(f"  - Invalid names: {self.stats['removed_invalid_names']:,}")
        self.logger.info(f"  - Invalid coords: {self.stats['removed_invalid_coords']:,}")
        self.logger.info(f"  - Outside USA: {self.stats['removed_outside_usa']:,}")
        self.logger.info(f"Runtime: {total_time/60:.1f} minutes")
        self.logger.info("=" * 60)


def load_environment():
    from dotenv import load_dotenv

    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)

    return {
        'aws_access_key_id': os.getenv("aws_access_key_id"),
        'aws_secret_access_key': os.getenv("aws_secret_access_key"),
        'aws_region_name': os.getenv("aws_region_name"),
        's3_bucket_name': os.getenv("s3_bucket_name"),
    }


def main():
    logger = setup_logging(log_level='INFO')

    logger.info("Loading environment...")
    env = load_environment()

    s3_client = boto3.client(
        's3',
        aws_access_key_id=env['aws_access_key_id'],
        aws_secret_access_key=env['aws_secret_access_key'],
        region_name=env['aws_region_name'],
    )

    LOCAL_DOWNLOAD_PATH = '/tmp/s3_data_download'
    LOCAL_SAVE_PATH = './output/usa'
    BATCH_SIZE = 200000

    gadm_boundaries = None
    category_mapping_df = None
    brand_config_df = None

    try:
        import geopandas as gpd
        gadm_path = os.getenv('GADM_PATH', 'data/usa_admin.geojson')
        if os.path.exists(gadm_path):
            gadm_boundaries = gpd.read_file(gadm_path)
            logger.info(f"Loaded GADM boundaries: {len(gadm_boundaries)} features")
    except Exception as e:
        logger.warning(f"Could not load GADM boundaries: {e}")

    try:
        cat_path = os.getenv('CATEGORY_MAPPING_PATH', 'data/xmap_poi_categorization.csv')
        if os.path.exists(cat_path):
            category_mapping_df = load_category_mapping(cat_path)
            logger.info(f"Loaded category mapping: {len(category_mapping_df)} entries")
    except Exception as e:
        logger.error(f"Failed to load category mapping: {e}")
        raise

    try:
        brand_path = os.getenv('BRAND_CONFIG_PATH', 'data/branding_usa_configs.csv')
        if os.path.exists(brand_path):
            brand_config_df = load_brand_config(brand_path)
            logger.info(f"Loaded brand config: {len(brand_config_df)} entries")
    except Exception as e:
        logger.error(f"Failed to load brand config: {e}")
        raise

    pipeline = USAPOIPipeline(
        s3_client=s3_client,
        s3_bucket_name=env['s3_bucket_name'],
        local_download_path=LOCAL_DOWNLOAD_PATH,
        local_save_path=LOCAL_SAVE_PATH,
        gadm_boundaries=gadm_boundaries,
        category_mapping_df=category_mapping_df,
        brand_config_df=brand_config_df,
        batch_size=BATCH_SIZE,
        logger=logger,
    )

    # Check if paths CSV is provided
    paths_csv = os.getenv('PATHS_CSV')
    if paths_csv and os.path.exists(paths_csv):
        logger.info(f"Using paths CSV: {paths_csv}")
        pipeline.run_from_csv(paths_csv)
    else:
        pipeline.run()


if __name__ == '__main__':
    main()
