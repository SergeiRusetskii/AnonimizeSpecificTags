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

    # Study Information
    (0x0020, 0x0010): "STUDY001",               # Study ID
}

# UID tags that need to be regenerated
UID_TAGS = [
    (0x0020, 0x000D),  # Study Instance UID
    (0x0020, 0x000E),  # Series Instance UID
    (0x0008, 0x0018),  # SOP Instance UID
    (0x0020, 0x0052),  # Frame of Reference UID
    (0x0008, 0x3010),  # Irradiation Event UID
]


def update_uids_in_sequences(dataset, uid_cache: Dict[str, str], path: str = "", is_top_level: bool = True):
    """
    Recursively walk through dataset sequences and update instance/reference UIDs.

    This ensures that referenced UIDs in sequences (like Referenced SOP Instance UID
    in Referenced RT Plan Sequence) are also anonymized, maintaining consistency
    with the top-level UID changes.

    Only instance-identifying UIDs are anonymized. Class/type UIDs (SOP Class,
    Transfer Syntax, Coding Scheme) and registry UIDs are preserved to maintain
    data integrity and terminology references.

    Args:
        dataset: DICOM dataset or sequence item to process
        uid_cache: Dictionary mapping original UIDs to anonymized UIDs
        path: Current path in the dataset (for debugging)
        is_top_level: True if this is the top-level dataset (to skip file_meta and top-level UIDs)
    """
    # Standard UID prefixes that should NOT be anonymized
    # These are well-known registries and standard UIDs
    STANDARD_UID_PREFIXES = [
        '1.2.840.10008.',      # DICOM standard UIDs (SOP Classes, Transfer Syntaxes, etc.)
        '2.16.840.1.113883.',  # HL7 OID namespace (includes SNOMED, LOINC, etc.)
        '1.2.840.10065.',      # IHE
        '1.3.6.1.4.1.',        # IANA Private Enterprise Numbers
        '2.16.840.1.114',      # DCM4CHE and other medical registries
    ]

    # UID tags that should NEVER be anonymized (class/type UIDs, not instance UIDs)
    # These define object types, encoding methods, or coding schemes
    PRESERVE_UID_TAGS = {
        # SOP Class UIDs (define object types)
        (0x0008, 0x0016),  # SOP Class UID
        (0x0008, 0x1150),  # Referenced SOP Class UID
        (0x0002, 0x0002),  # Media Storage SOP Class UID

        # Transfer Syntax UIDs (define encoding methods)
        (0x0002, 0x0010),  # Transfer Syntax UID
        (0x0004, 0x1512),  # Referenced Transfer Syntax UID

        # Coding Scheme UIDs (define coding systems like SNOMED, LOINC)
        (0x0008, 0x010C),  # Coding Scheme UID
        (0x0008, 0x010B),  # Context Group Extension Creator UID

        # Other non-identifying UIDs
        (0x0040, 0xDB0D),  # Template Extension Creator UID
        (0x0008, 0x0062),  # SOP Class UID (in SOP Class Extended Negotiation Sub-Item)
    }

    # Tags that are already handled at the top level
    TOP_LEVEL_UID_TAGS = [
        (0x0020, 0x000D),  # Study Instance UID
        (0x0020, 0x000E),  # Series Instance UID
        (0x0008, 0x0018),  # SOP Instance UID
        (0x0020, 0x0052),  # Frame of Reference UID
        (0x0008, 0x3010),  # Irradiation Event UID
    ]

    for elem in dataset:
        # Skip file_meta at the top level (it's handled separately)
        if is_top_level and elem.tag.group == 0x0002:
            continue

        # Check if this element is a UID that needs to be anonymized
        if elem.VR == 'UI' and elem.value:  # UID Value Representation
            # Skip top-level UIDs (already handled)
            if is_top_level and (elem.tag.group, elem.tag.elem) in TOP_LEVEL_UID_TAGS:
                continue

            # Skip UIDs that should be preserved (class/type UIDs, not instance UIDs)
            if (elem.tag.group, elem.tag.elem) in PRESERVE_UID_TAGS:
                logger.debug(f"  Preserving class/type UID {elem.name}: {elem.value}")
                continue

            # Handle both single and multi-valued UIDs
            # MultiValue UIDs (e.g., SOP Classes in Study) need special handling
            uid_value = elem.value

            # Check if it's a MultiValue (list of UIDs) or single UID
            is_multi_value = hasattr(uid_value, '__iter__') and not isinstance(uid_value, str)

            if is_multi_value:
                # Handle multi-valued UID attribute
                new_uids = []
                for original_uid in uid_value:
                    # Don't anonymize standard DICOM UIDs or registry UIDs
                    if any(str(original_uid).startswith(prefix) for prefix in STANDARD_UID_PREFIXES):
                        logger.debug(f"  Preserving standard/registry UID in multi-value: {original_uid}")
                        new_uids.append(original_uid)
                        continue

                    # Check if we've already mapped this UID
                    if original_uid not in uid_cache:
                        uid_cache[original_uid] = generate_uid()
                        logger.debug(f"  Generated new UID for multi-value reference: {original_uid} -> {uid_cache[original_uid]}")

                    new_uids.append(uid_cache[original_uid])
                    logger.debug(f"  Updated UID in multi-value {path}.{elem.name}: {original_uid} -> {uid_cache[original_uid]}")

                # Update the element with the list of new UIDs
                elem.value = new_uids
            else:
                # Handle single UID
                original_uid = uid_value

                # Don't anonymize standard DICOM UIDs or registry UIDs
                if any(str(original_uid).startswith(prefix) for prefix in STANDARD_UID_PREFIXES):
                    logger.debug(f"  Preserving standard/registry UID: {original_uid}")
                    continue

                # Check if we've already mapped this UID
                if original_uid not in uid_cache:
                    # Generate new UID and cache it
                    uid_cache[original_uid] = generate_uid()
                    logger.debug(f"  Generated new UID for sequence reference: {original_uid} -> {uid_cache[original_uid]}")

                # Update to the anonymized UID
                elem.value = uid_cache[original_uid]
                logger.debug(f"  Updated UID in sequence {path}.{elem.name}: {original_uid} -> {elem.value}")

        # If this element is a sequence, recurse into it
        if elem.VR == 'SQ' and elem.value:  # Sequence
            for i, seq_item in enumerate(elem.value):
                seq_path = f"{path}.{elem.name}[{i}]" if path else f"{elem.name}[{i}]"
                update_uids_in_sequences(seq_item, uid_cache, seq_path, is_top_level=False)


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

        # Update UIDs in sequences to maintain consistency
        # This handles referenced UIDs in nested sequences (e.g., Referenced RT Plan Sequence)
        update_uids_in_sequences(ds, uid_cache)

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
