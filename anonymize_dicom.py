#!/usr/bin/env python3
"""
DICOM Anonymization Script

This script processes all DICOM files from the /input/ directory (including subdirectories),
anonymizes specific tags, regenerates UIDs, and saves them to /anonymized/ while preserving
the folder structure.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Tuple, Dict, Literal
import pydicom
from pydicom.uid import generate_uid
from pydicom.errors import InvalidDicomError


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('anonymization.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# Tags to anonymize with their new values
ANONYMIZATION_MAP = {
    # Institution & Device Information
    (0x0008, 0x0080): "Research Institution",  # Institution Name
    (0x0008, 0x0090): "Physician",              # Referring Physician's Name
    (0x0008, 0x1070): "Operator",               # Operators' Name
    (0x0008, 0x1010): "Station",                # Station Name
    (0x0008, 0x1040): "Department",             # Institutional Department Name
    (0x0018, 0x1000): "1111",                   # Device Serial Number

    # Patient Information
    (0x0010, 0x0010): "Name",                   # Patient's Name
    (0x0010, 0x0020): "ID",                     # Patient ID
    (0x0010, 0x0030): "19910101",               # Patient's Birth Date (DICOM format: YYYYMMDD)
}

# UID tags that need to be regenerated
UID_TAGS = [
    (0x0020, 0x000D),  # Study Instance UID
    (0x0020, 0x000E),  # Series Instance UID
    (0x0008, 0x0018),  # SOP Instance UID
    (0x0020, 0x0052),  # Frame of Reference UID
]


def anonymize_dicom_file(
    input_path: Path,
    output_path: Path,
    uid_cache: Dict[str, str]
) -> Literal['success', 'skipped', 'failed']:
    """
    Anonymize a single DICOM file.

    Args:
        input_path: Path to the input DICOM file
        output_path: Path where the anonymized file should be saved
        uid_cache: Dictionary mapping original UIDs to anonymized UIDs for consistency

    Returns:
        'success' if file was successfully anonymized
        'skipped' if file is not a valid DICOM file
        'failed' if an error occurred during processing
    """
    try:
        # Read the DICOM file
        ds = pydicom.dcmread(str(input_path))

        # Anonymize specified tags
        for tag, new_value in ANONYMIZATION_MAP.items():
            if tag in ds:
                ds[tag].value = new_value
                logger.debug(f"  Anonymized tag {tag}: {new_value}")

        # Regenerate UIDs to break linkability while maintaining consistency
        # across files that belong to the same study/series
        for tag in UID_TAGS:
            if tag in ds:
                old_uid = ds[tag].value

                # Check if we've already generated a new UID for this original UID
                if old_uid not in uid_cache:
                    # Generate new UID and cache it
                    uid_cache[old_uid] = generate_uid()

                new_uid = uid_cache[old_uid]
                ds[tag].value = new_uid
                logger.debug(f"  Regenerated UID {tag}: {old_uid} -> {new_uid}")

                # Sync File Meta SOP Instance UID with dataset SOP Instance UID
                # to maintain DICOM consistency and prevent exposing original UID
                if tag == (0x0008, 0x0018) and hasattr(ds, 'file_meta'):
                    if hasattr(ds.file_meta, 'MediaStorageSOPInstanceUID'):
                        ds.file_meta.MediaStorageSOPInstanceUID = new_uid
                        logger.debug(f"  Updated File Meta MediaStorageSOPInstanceUID: {new_uid}")

        # Create output directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save the anonymized DICOM file
        ds.save_as(str(output_path))

        return 'success'

    except InvalidDicomError:
        logger.warning(f"Skipped (not a valid DICOM file): {input_path}")
        return 'skipped'
    except Exception as e:
        logger.error(f"Error processing {input_path}: {str(e)}")
        return 'failed'


def process_directory(input_dir: Path, output_dir: Path) -> Dict[str, int]:
    """
    Process all files in the input directory recursively.

    Args:
        input_dir: Root input directory
        output_dir: Root output directory

    Returns:
        Dictionary with processing statistics
    """
    stats = {
        'total_files': 0,
        'processed': 0,
        'skipped': 0,
        'failed': 0
    }

    # UID cache to maintain consistency across files in the same study/series
    # Maps original UIDs to their anonymized versions
    uid_cache: Dict[str, str] = {}

    # Walk through all files in input directory
    for root, dirs, files in os.walk(input_dir):
        for filename in files:
            stats['total_files'] += 1

            input_path = Path(root) / filename

            # Calculate relative path to preserve folder structure
            relative_path = input_path.relative_to(input_dir)
            output_path = output_dir / relative_path

            logger.info(f"Processing: {relative_path}")

            # Try to anonymize the file
            result = anonymize_dicom_file(input_path, output_path, uid_cache)

            if result == 'success':
                stats['processed'] += 1
                logger.info(f"  ✓ Successfully anonymized: {relative_path}")
            elif result == 'skipped':
                stats['skipped'] += 1
            elif result == 'failed':
                stats['failed'] += 1

    return stats


def main():
    """Main entry point for the script."""
    # Define input and output directories
    script_dir = Path(__file__).parent
    input_dir = script_dir / "input"
    output_dir = script_dir / "anonymized"

    # Check if input directory exists
    if not input_dir.exists():
        logger.error(f"Input directory does not exist: {input_dir}")
        logger.info(f"Creating input directory: {input_dir}")
        input_dir.mkdir(parents=True, exist_ok=True)
        logger.warning("Input directory is empty. Please add DICOM files to process.")
        return

    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 80)
    logger.info("DICOM Anonymization Script")
    logger.info("=" * 80)
    logger.info(f"Input directory:  {input_dir}")
    logger.info(f"Output directory: {output_dir}")
    logger.info("")

    # Process all files
    stats = process_directory(input_dir, output_dir)

    # Print summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("ANONYMIZATION SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total files found:       {stats['total_files']}")
    logger.info(f"Successfully processed:  {stats['processed']}")
    logger.info(f"Skipped (non-DICOM):     {stats['skipped']}")
    logger.info(f"Failed (errors):         {stats['failed']}")
    logger.info("=" * 80)

    if stats['processed'] > 0:
        logger.info(f"\n✓ Anonymized files saved to: {output_dir}")
    else:
        logger.warning("\n⚠ No DICOM files were processed!")


if __name__ == "__main__":
    main()
