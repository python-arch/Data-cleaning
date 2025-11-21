"""
USA POI Data Pipeline

Processes POI data from S3 for USA locations and outputs
clean CSV files with 35+ standardized fields.
"""

import os
import sys
import re
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import pandas as pd
import numpy as np
import boto3
from tqdm import tqdm

warnings.filterwarnings("ignore")
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
)


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
    ):
        self.s3_client = s3_client
        self.s3_bucket_name = s3_bucket_name
        self.local_download_path = local_download_path
        self.local_save_path = local_save_path
        self.batch_size = batch_size

        os.makedirs(local_download_path, exist_ok=True)
        os.makedirs(local_save_path, exist_ok=True)

        self.core_transformer = CoreTransformer(brand_config_df)
        self.location_transformer = LocationTransformer(gadm_boundaries)
        self.category_transformer = CategoryTransformer(category_mapping_df)
        self.status_transformer = StatusTransformer()
        self.metrics_transformer = MetricsTransformer()
        self.quality_transformer = QualityTransformer()
        self.establishment_transformer = EstablishmentTransformer()

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

    @staticmethod
    def extract_month_from_filename(filename: str) -> Optional[str]:
        """Get YYYY-MM from filename like '20250509'."""
        match = re.search(r'(\d{8})', filename)
        if match:
            date_str = match.group(1)
            return f"{date_str[:4]}-{date_str[4:6]}"
        return None

    def _get_source_columns(self) -> List[str]:
        """Columns we need from source data."""
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
            'day_time', 'photo_dates', 'review_dates', 'oldest_date',
        ]

    def _clean_coordinates(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove rows with invalid coordinates."""
        initial_rows = len(df)

        df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
        df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')

        valid_coords = df['latitude'].notna() & df['longitude'].notna()
        df = df[valid_coords].copy()

        valid_lat = (df['latitude'] >= -90) & (df['latitude'] <= 90)
        valid_lon = (df['longitude'] >= -180) & (df['longitude'] <= 180)
        df = df[valid_lat & valid_lon].copy()

        self.stats['removed_invalid_coords'] += initial_rows - len(df)
        return df

    def _filter_usa(self, df: pd.DataFrame) -> pd.DataFrame:
        """Keep only USA records."""
        initial_rows = len(df)

        outside_usa = self.location_transformer.is_outside_usa_vectorized(
            df['latitude'], df['longitude']
        )
        df = df[~outside_usa].copy()

        self.stats['removed_outside_usa'] += initial_rows - len(df)
        return df

    def _apply_transformations(self, df: pd.DataFrame, data_version_month: str) -> pd.DataFrame:
        """Run all transformers on the data."""
        df = self.core_transformer.transform_batch(df)

        initial_rows = len(df)
        df = self.core_transformer.filter_valid_names(df)
        self.stats['removed_invalid_names'] += initial_rows - len(df)

        df = self.location_transformer.transform_batch(df)
        df = self.category_transformer.transform_batch(df)
        df = self.status_transformer.transform_batch(df, data_version_month)
        df = self.metrics_transformer.transform_batch(df)
        df = self.establishment_transformer.transform_batch(df)
        df = self.quality_transformer.transform_batch(df, data_version_month)

        return df

    def _select_output_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Pick final output columns in order."""
        output_cols = []

        for col in FINAL_OUTPUT_COLUMNS:
            if col in df.columns:
                output_cols.append(col)
            else:
                df[col] = None
                output_cols.append(col)

        return df[output_cols]

    def process_chunk(self, chunk: pd.DataFrame, data_version_month: str) -> pd.DataFrame:
        """Process a single chunk of data."""
        print(f"  Processing chunk with {len(chunk):,} rows...")

        chunk = self._clean_coordinates(chunk)

        if chunk.empty:
            print("  No valid data after coordinate cleaning")
            return pd.DataFrame()

        chunk = self._filter_usa(chunk)

        if chunk.empty:
            print("  No USA data in this chunk")
            return pd.DataFrame()

        print(f"  Found {len(chunk):,} USA records")

        chunk = self._apply_transformations(chunk, data_version_month)
        chunk = self._select_output_columns(chunk)

        return chunk

    def process_file(self, object_key: str) -> Optional[pd.DataFrame]:
        """Process a single S3 file."""
        data_version_month = self.extract_month_from_filename(object_key)
        path_parts = object_key.split('/')
        date_str = path_parts[-2] if len(path_parts) >= 2 else ''

        output_filename = f"USA_{date_str}.csv"
        local_save_csv_path = os.path.join(self.local_save_path, output_filename)

        if os.path.exists(local_save_csv_path):
            print(f"\nSkipping {object_key} - already processed")
            self.stats['files_skipped'] += 1
            return None

        zip_filename = os.path.basename(object_key)
        local_zip_path = os.path.join(self.local_download_path, zip_filename)

        print(f"\n{'='*80}")
        print(f"Processing: {object_key}")
        print(f"Output: {output_filename}")
        print(f"{'='*80}")

        file_start_time = time.time()

        try:
            # Download file
            print("Downloading...")
            download_start = time.time()
            self.s3_client.download_file(self.s3_bucket_name, object_key, local_zip_path)
            download_time = time.time() - download_start

            file_size_mb = os.path.getsize(local_zip_path) / (1024 * 1024)
            print(f"Downloaded in {download_time:.2f}s ({file_size_mb:.2f} MB)")

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

                print(f"\nChunk {chunk_number}: {len(chunk):,} rows")

                processed_chunk = self.process_chunk(chunk, data_version_month)

                if not processed_chunk.empty:
                    all_chunks.append(processed_chunk)
                    print(f"  Output: {len(processed_chunk):,} rows")

            self.stats['total_input_rows'] += total_input_rows

            if all_chunks:
                print(f"\nConcatenating {len(all_chunks)} chunks...")
                final_df = pd.concat(all_chunks, ignore_index=True)

                before = len(final_df)
                final_df = final_df.drop_duplicates(subset='poi_id', keep='first')
                self.stats['removed_duplicates'] += before - len(final_df)

                print(f"Saving {len(final_df):,} rows to {local_save_csv_path}...")
                final_df.to_csv(local_save_csv_path, index=False)

                self.stats['total_output_rows'] += len(final_df)
                self.stats['files_processed'] += 1

                file_time = time.time() - file_start_time
                print(f"\nCompleted in {file_time:.2f}s")
                print(f"Input: {total_input_rows:,} | Output: {len(final_df):,}")

                return final_df
            else:
                print("No data to save")
                return None

        except Exception as e:
            print(f"Error processing {object_key}: {e}")
            import traceback
            traceback.print_exc()
            return None

        finally:
            if os.path.exists(local_zip_path):
                os.remove(local_zip_path)

    def run(self, prefix_filter: str = 'United States/2'):
        """Run the pipeline on all matching S3 files."""
        print("=" * 80)
        print("USA POI DATA PIPELINE")
        print("=" * 80)
        print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)

        start_time = time.time()

        paginator = self.s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=self.s3_bucket_name)

        for page in pages:
            if 'Contents' not in page:
                continue

            for obj in page['Contents']:
                object_key = obj['Key']

                if prefix_filter in object_key and 'big_categories_data' not in object_key:
                    self.process_file(object_key)

        total_time = time.time() - start_time

        print("\n" + "=" * 80)
        print("PIPELINE COMPLETE")
        print("=" * 80)
        print(f"Files processed: {self.stats['files_processed']}")
        print(f"Files skipped: {self.stats['files_skipped']}")
        print(f"Total input rows: {self.stats['total_input_rows']:,}")
        print(f"Total output rows: {self.stats['total_output_rows']:,}")
        print(f"\nRecords removed:")
        print(f"  - Duplicates: {self.stats['removed_duplicates']:,}")
        print(f"  - Invalid names: {self.stats['removed_invalid_names']:,}")
        print(f"  - Invalid coordinates: {self.stats['removed_invalid_coords']:,}")
        print(f"  - Outside USA: {self.stats['removed_outside_usa']:,}")
        print(f"\nTotal runtime: {total_time/60:.2f} minutes")
        print("=" * 80)


def load_environment():
    """Load AWS credentials from .env file."""
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
    """Entry point."""
    print("\n" + "=" * 80)
    print("USA POI DATA PIPELINE")
    print("=" * 80)

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
            print(f"Loaded GADM boundaries: {len(gadm_boundaries)} features")
    except Exception as e:
        print(f"Warning: Could not load GADM boundaries: {e}")

    try:
        cat_path = os.getenv('CATEGORY_MAPPING_PATH', 'data/xmap_poi_categorization.csv')
        category_mapping_df = load_category_mapping(cat_path)
        if category_mapping_df is not None:
            print(f"Loaded category mapping: {len(category_mapping_df)} categories")
        else:
            print(f"Warning: Could not load category mapping from {cat_path}")
    except Exception as e:
        print(f"Warning: Could not load category mapping: {e}")

    try:
        brand_path = os.getenv('BRAND_CONFIG_PATH', 'data/branding_usa_configs.csv')
        brand_config_df = load_brand_config(brand_path)
        if brand_config_df is not None:
            print(f"Loaded brand config: {len(brand_config_df)} brands")
        else:
            print(f"Warning: Could not load brand config from {brand_path}")
    except Exception as e:
        print(f"Warning: Could not load brand config: {e}")

    pipeline = USAPOIPipeline(
        s3_client=s3_client,
        s3_bucket_name=env['s3_bucket_name'],
        local_download_path=LOCAL_DOWNLOAD_PATH,
        local_save_path=LOCAL_SAVE_PATH,
        gadm_boundaries=gadm_boundaries,
        category_mapping_df=category_mapping_df,
        brand_config_df=brand_config_df,
        batch_size=BATCH_SIZE,
    )

    try:
        pipeline.run()
    except KeyboardInterrupt:
        print("\n\nPipeline interrupted by user")
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
