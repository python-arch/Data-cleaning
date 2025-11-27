"""
Standalone script to analyze status changes across POI versions.

Reads a CSV with S3 paths, processes each version chronologically,
and outputs status change analysis for each version.

Output: One CSV per version with columns: poi_id, name, business_status, status_change
"""

import os
import sys
import re
import hashlib
import zipfile
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

import pandas as pd
import boto3
from dotenv import load_dotenv
from tqdm import tqdm


# ============================================================================
# Status Change Logic (copied from transformers/status_transformers.py)
# ============================================================================

class StatusAnalyzer:
    """Analyzes status changes between POI versions."""

    OPEN_STATUSES = {'open', 'open 24 hours'}
    CLOSED_STATUSES = {'temporarily closed', 'permanently closed'}

    STATUS_MAPPING = {
        'open': 'Open',
        'open 24 hours': 'Open',
        'permanently closed': 'Closed',
        'temporarily closed': 'Temporarily Closed',
    }

    def __init__(self):
        self.previous_version_pois: Dict[str, str] = {}

    def normalize_status(self, status) -> str:
        """Normalize business status to standard values."""
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

    def hash_poi_id(self, google_id: str) -> str:
        """Generate poi_id from google_id using MD5 hash."""
        if pd.isna(google_id):
            return ''
        return hashlib.md5(str(google_id).encode()).hexdigest()

    def set_previous_version(self, df: pd.DataFrame):
        """Store POI statuses from previous version for comparison."""
        self.previous_version_pois = {}

        if 'poi_id' in df.columns and 'business_status' in df.columns:
            for _, row in df.iterrows():
                poi_id = str(row['poi_id'])
                status = self.normalize_status(row['business_status'])
                self.previous_version_pois[poi_id] = status

    def determine_status_change(self, poi_id: str, current_status: str,
                                 oldest_date: str, data_version_month: str) -> Optional[str]:
        """
        Determine status_change for a POI based on version comparison.

        Logic:
        1. If oldest_date month matches processing month AND status is Open -> 'Opened this month'
        2. If status changed from Open to Closed -> 'Closed this month'
        3. If status changed from Closed to Open -> 'Recently Opened'
        4. Otherwise -> None
        """
        # Check if opened this month based on oldest_date
        if oldest_date and data_version_month:
            oldest_month = self._extract_month_from_date(oldest_date)
            if oldest_month == data_version_month and current_status == 'Open':
                return 'Opened this month'

        # Check version comparison if previous version exists
        if poi_id in self.previous_version_pois:
            prev_status = self.previous_version_pois[poi_id]

            # Check if status changed from open to closed
            if prev_status == 'Open' and current_status in ['Closed', 'Temporarily Closed']:
                return 'Closed this month'

            # Check if status changed from closed to open
            elif prev_status in ['Closed', 'Temporarily Closed'] and current_status == 'Open':
                return 'Recently Opened'

        return None

    @staticmethod
    def _extract_month_from_date(date_str) -> Optional[str]:
        """Extract YYYY-MM from a date string."""
        if pd.isna(date_str):
            return None

        date_str = str(date_str).strip()

        # Try various formats
        formats = [
            '%Y-%m-%d',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S.%fZ',
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str[:min(len(date_str), 26)], fmt)
                return dt.strftime('%Y-%m')
            except ValueError:
                continue

        return None


# ============================================================================
# Main Processing Logic
# ============================================================================

def load_config():
    """Load AWS credentials from .env file."""
    load_dotenv()

    return {
        'aws_access_key_id': os.getenv('aws_access_key_id'),
        'aws_secret_access_key': os.getenv('aws_secret_access_key'),
        'aws_region_name': os.getenv('aws_region_name', 'us-east-1'),
        's3_bucket_name': os.getenv('s3_bucket_name'),
    }


def download_from_s3(s3_client, bucket: str, object_key: str, local_path: str) -> bool:
    """Download a file from S3."""
    try:
        print(f"  Downloading: s3://{bucket}/{object_key}")
        s3_client.download_file(bucket, object_key, local_path)
        return True
    except Exception as e:
        print(f"  ERROR downloading {object_key}: {e}")
        return False


def extract_zip(zip_path: str, extract_to: str) -> Optional[str]:
    """Extract ZIP file and return path to the CSV file."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)

        # Find the CSV file
        csv_files = list(Path(extract_to).glob('*.csv'))
        if csv_files:
            return str(csv_files[0])
        return None
    except Exception as e:
        print(f"  ERROR extracting ZIP: {e}")
        return None


def extract_month_from_path(path: str) -> Optional[str]:
    """Extract YYYY-MM from path like 'United States/20250501/...'."""
    match = re.search(r'(\d{8})', path)
    if match:
        date_str = match.group(1)
        year = date_str[:4]
        month = date_str[4:6]
        return f"{year}-{month}"
    return None


def process_version(csv_path: str, analyzer: StatusAnalyzer,
                     data_version_month: str) -> pd.DataFrame:
    """
    Process a single version and calculate status changes.

    Returns DataFrame with: poi_id, name, business_status, status_change
    """
    print(f"  Reading CSV: {csv_path}")

    # Read only required columns
    required_cols = ['google_id', 'name', 'business_status', 'oldest_date']

    try:
        df = pd.read_csv(csv_path, usecols=lambda x: x in required_cols, low_memory=False)
    except Exception as e:
        print(f"  ERROR reading CSV: {e}")
        return pd.DataFrame()

    print(f"  Loaded {len(df):,} rows")

    # Generate poi_id from google_id
    df['poi_id'] = df['google_id'].apply(analyzer.hash_poi_id)

    # Normalize status
    df['normalized_status'] = df['business_status'].apply(analyzer.normalize_status)

    # Calculate status_change
    print(f"  Calculating status changes...")
    df['status_change'] = df.apply(
        lambda row: analyzer.determine_status_change(
            poi_id=row['poi_id'],
            current_status=row['normalized_status'],
            oldest_date=row.get('oldest_date'),
            data_version_month=data_version_month
        ),
        axis=1
    )

    # Prepare output with only required columns
    result = df[['poi_id', 'name', 'business_status', 'status_change']].copy()

    # Store this version for next comparison (only poi_id and status)
    version_summary = df[['poi_id', 'business_status']].copy()

    return result, version_summary


def main():
    print("=" * 70)
    print("POI STATUS CHANGE ANALYZER")
    print("=" * 70)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Load configuration
    config = load_config()

    if not config['s3_bucket_name']:
        print("ERROR: s3_bucket_name not found in .env file")
        sys.exit(1)

    # Get paths CSV from environment or command line
    paths_csv = os.getenv('PATHS_CSV')
    if len(sys.argv) > 1:
        paths_csv = sys.argv[1]

    if not paths_csv or not os.path.exists(paths_csv):
        print(f"ERROR: Paths CSV not found: {paths_csv}")
        print("Usage: python analyze_status_changes.py <paths_csv>")
        print("   OR: Set PATHS_CSV in .env file")
        sys.exit(1)

    print(f"Paths CSV: {paths_csv}")
    print(f"S3 Bucket: {config['s3_bucket_name']}")
    print()

    # Read paths
    paths_df = pd.read_csv(paths_csv)
    if 'Path' not in paths_df.columns:
        print("ERROR: CSV must have 'Path' column")
        sys.exit(1)

    paths = paths_df['Path'].tolist()
    paths = sorted(paths, key=lambda x: re.search(r'(\d{8})', x).group(1) if re.search(r'(\d{8})', x) else '')

    print(f"Found {len(paths)} versions to process")
    print()

    # Initialize S3 client
    s3_client = boto3.client(
        's3',
        aws_access_key_id=config['aws_access_key_id'],
        aws_secret_access_key=config['aws_secret_access_key'],
        region_name=config['aws_region_name'],
    )

    # Initialize analyzer
    analyzer = StatusAnalyzer()

    # Create output directory
    output_dir = Path('./output/status_analysis')
    output_dir.mkdir(parents=True, exist_ok=True)

    # Temporary directory for downloads
    temp_dir = Path('/tmp/status_analysis')
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Process each version
    stats = {
        'total_processed': 0,
        'total_records': 0,
        'total_status_changes': 0,
    }

    for i, s3_path in enumerate(paths, 1):
        print(f"\n{'='*70}")
        print(f"VERSION {i}/{len(paths)}: {s3_path}")
        print(f"{'='*70}")

        # Extract date from path
        data_version_month = extract_month_from_path(s3_path)
        if not data_version_month:
            print(f"  WARNING: Could not extract date from path, skipping")
            continue

        print(f"  Version month: {data_version_month}")

        # Download from S3
        zip_filename = s3_path.split('/')[-1]
        local_zip_path = temp_dir / f"version_{i}_{zip_filename}"

        if not download_from_s3(s3_client, config['s3_bucket_name'], s3_path, str(local_zip_path)):
            print(f"  Skipping due to download error")
            continue

        # Extract ZIP
        extract_dir = temp_dir / f"version_{i}_extracted"
        extract_dir.mkdir(exist_ok=True)

        csv_path = extract_zip(str(local_zip_path), str(extract_dir))
        if not csv_path:
            print(f"  ERROR: No CSV found in ZIP")
            local_zip_path.unlink()
            continue

        # Process version
        result_df, version_summary = process_version(csv_path, analyzer, data_version_month)

        if result_df.empty:
            print(f"  Skipping due to processing error")
            local_zip_path.unlink()
            continue

        # Count status changes
        status_changes = result_df['status_change'].notna().sum()
        print(f"  Status changes detected: {status_changes:,}")

        # Save output
        output_filename = f"status_changes_{data_version_month.replace('-', '')}.csv"
        output_path = output_dir / output_filename
        result_df.to_csv(output_path, index=False)
        print(f"  ✅ Saved: {output_path}")

        # Update stats
        stats['total_processed'] += 1
        stats['total_records'] += len(result_df)
        stats['total_status_changes'] += status_changes

        # Store this version for next comparison
        analyzer.set_previous_version(version_summary)

        # Clean up
        local_zip_path.unlink()
        import shutil
        shutil.rmtree(extract_dir)

    # Print summary
    print()
    print("=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)
    print(f"Versions processed: {stats['total_processed']}")
    print(f"Total records analyzed: {stats['total_records']:,}")
    print(f"Total status changes detected: {stats['total_status_changes']:,}")
    print(f"Output directory: {output_dir.absolute()}")
    print()
    print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)


if __name__ == '__main__':
    main()
