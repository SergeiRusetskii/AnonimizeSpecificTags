# DICOM Anonymization Tool

A Python tool for anonymizing specific DICOM tags while preserving folder structure.

## Features

- Recursively processes all DICOM files from `/input/` directory (including subdirectories)
- Anonymizes specific patient, institution, and device tags
- Regenerates UIDs to break linkability between studies
- Preserves folder structure in `/anonymized/` output directory
- Handles non-DICOM files gracefully (skips and logs)
- Overwrites existing files in output directory

## Anonymized Tags

### Institution & Device Information
- `(0008,0080)` Institution Name → `Research Institution`
- `(0008,0090)` Referring Physician's Name → `Physician`
- `(0008,1070)` Operators' Name → `Operator`
- `(0008,1010)` Station Name → `Station`
- `(0008,1040)` Institutional Department Name → `Department`
- `(0018,1000)` Device Serial Number → `1111`

### Patient Information
- `(0010,0010)` Patient's Name → `Name`
- `(0010,0020)` Patient ID → `ID`
- `(0010,0030)` Patient's Birth Date → `19910101`

### Regenerated UIDs
- `(0020,000D)` Study Instance UID
- `(0020,000E)` Series Instance UID
- `(0008,0018)` SOP Instance UID
- `(0020,0052)` Frame of Reference UID

### Preserved Tags
- All date/time tags remain unchanged

## Requirements

```bash
pip install pydicom
```

## Usage

1. Place your DICOM files in the `/input/` directory (supports subdirectories)
2. Run the anonymization script:

```bash
python3 anonymize_dicom.py
```

3. Anonymized files will be saved to `/anonymized/` with the same folder structure

## Output

- Console and log file (`anonymization.log`) show processing progress
- Summary statistics displayed at completion
- Non-DICOM files are skipped and logged as warnings

## Example

```
input/
  ├── study1/
  │   └── series1/
  │       └── image1.dcm
  └── study2/
      └── image2.dcm

anonymized/
  ├── study1/
  │   └── series1/
  │       └── image1.dcm  (anonymized)
  └── study2/
      └── image2.dcm  (anonymized)
```
