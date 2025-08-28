# Google Photos Takeout EXIF Processor

This project provides a set of scripts for processing EXIF metadata for Google Photos Takeout exports on Windows. The main processor script organizes your exported media into YYYY/MM, embeds metadata from JSON sidecar files—including creation date (in pacific time) and people tags—into supported image and video formats. The validator script checks the processed output for missing files and validates file sizes to help ensure your export was handled correctly. These tools are designed to help you preserve important metadata and maintain the integrity of your photo library during migration or archival.


## Quickstart Guide

**Important Notice:** This script is provided as-is and may contain bugs or edge cases that could result in data corruption or loss. Please use at your own risk. Always work with backups of your original Google Photos Takeout data before running any processing or validation steps.

This section provides a step-by-step guide to help you get started with the Google Photos Takeout Processor and Validator on Windows.

### 1. Prerequisites and Installation

Before running the scripts, ensure you have the following installed:

- **Python 3.9 or higher**
- **ExifTool**: Download from [ExifTool](https://exiftool.org/), extract the zip, rename `exiftool(-k).exe` to `exiftool.exe`, and place it in your PATH (e.g., `C:\Windows` or your project folder).
- **tzdata** and **rich** Python packages:

    ```powershell
    pip install tzdata rich
    ```

### 2. Processing Your Takeout Data

Run the processor script to organize and embed metadata into your exported media files:

```powershell
python google_photos_processor.py "C:\Path\To\Takeout" [-o "C:\Path\To\Output"]
```

If you omit the `-o` flag, processed files will be placed in a `processed` subfolder within your takeout directory.

### 3. Validating the Output



After processing, run the validator script to check for missing files and compare file sizes:

```powershell
python validate.py "C:\Path\To\Takeout" [-o "C:\Path\To\Processed"] [--time-zone "America/New_York"]
```

If you omit the `-o` flag, the validator will look for output in the default `processed` subfolder. If you omit the `--time-zone` flag, the validator will use Pacific Time (`America/Los_Angeles`) by default. You can specify any valid IANA time zone name for date conversion.

---

---

## Detailed Features & Usage


### Overview

This project provides two thorough but experimental scripts for processing and validating Google Photos Takeout exports on Windows. While the scripts aim to cover a wide range of scenarios, they may still contain bugs or edge cases. Use with caution and always keep backups of your data.

- **google_photos_processor.py**: Processes your exported media, embeds metadata from JSON sidecars, and organizes files by date and month.
- **validate.py**: Validates the output by comparing file sizes and existence, ensuring files were processed correctly.

All features and instructions below are Windows-specific.

---

### Input Structure

Your Google Photos Takeout should look like this:

```
Takeout\
├── Photos from 2020\
│   ├── IMG_001.jpg
│   ├── IMG_001.jpg.json
│   ├── VID_002.mp4
│   ├── VID_002.mp4.json
│   └── ...
├── Photos from 2021\
│   └── ...
└── Photos from 2022\
         └── ...
```

### Output Structure

Processed files are organized by year and month:

```
processed\
├── 2020\
│   ├── 01\
│   │   ├── IMG_001.jpg
│   │   └── VID_002.mp4
│   ├── 02\
│   └── ...
├── 2021\
└── 2022\
```

---

### Features: google_photos_processor.py

- **EXIF & Metadata Embedding**: For supported formats, embeds metadata from JSON into EXIF fields using ExifTool.
- **Date Conversion**: All dates from JSON (UTC) are converted to U.S. Pacific Time before embedding and organizing.
- **File Organization**: Files are copied into `processed/YYYY/MM/` folders based on their Pacific Time date.
- **Read-Only Format Handling**: For formats that do not support metadata writing (e.g., AVI, MKV, GIF, BMP, WEBM):
    - The file is still copied to the output folder.
    - The file's modified date is updated to match the Pacific Time date from the JSON (using Windows-compatible Python code).
    - **Rule-Based JSON Matching**: Due to the unreliable and non-standard naming of JSON sidecar files in Google Takeout, matching them to their corresponding media files is a significant challenge and source of frustration. This script uses a series of rules to work around these inconsistencies:
        1. **Direct match**: `<filename>.<ext>.json` (JSON file matches media filename exactly)
        2. **Truncated match**: Handles long filenames
        3. **Parenthetical match**: Handles files like `IMG(1).jpg` and their JSONs
        4. **Edited filename match**: Handles `-edited` suffixes
        5. **Live photo**: Matches MP4s for live photos
        6. **Duplicate live photos**: Handles `(1).mp4` from live photos
        7. **Title-based match**: Uses the `title` field in JSON for matching
        8. **Base filename match**: Matches any JSON file starting with the base filename (without extension), e.g. for `0.png` matches `0.supplemental-metadata.json`, `0.json`, etc.
        9. **Other custom rules**: You can add more rules as needed for edge cases by editing `json_matcher.py`.
- **Logging**: All console output is mirrored to a timestamped log file in the input folder, providing a complete record of the processing session. For each year, the script also writes summary statistics and lists of files that were either skipped or processed as "copied-only" to separate text files. 
    - **Copied-only files** are files that could not have metadata embedded (either due to format limitations or errors during embedding) and were only copied to the output folder with their modified date updated. These files are tracked and reported so you can review which files may lack full metadata.
- **Error Handling**: Skipped files (missing JSON, bad JSON, ambiguous matches, missing date) are logged for review.
- **Optional Flags**:
    - `-o <output_folder>`: Specify a custom output folder (default: `<takeout_folder>/processed`)
    - `--skipped_files <skipped_files_folder>`: Retry processing files listed in per-year skipped files text files. Files are marked as skipped if they could not be matched with any JSON sidecar file using the available rules. You can manually review these edge cases, add new matching rules to the script if needed, and then rerun the processor with this option to attempt processing only the previously skipped files.
    - `--time-zone "<time_zone>"`: Specify the time zone for date/time conversions in TZ identifier format. The value should be a valid [IANA time zone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones), e.g., `America/New_York`, `Asia/Kolkata`, etc. Default is `America/Los_Angeles` (Pacific Time).
#### Usage Example

```powershell
python google_photos_processor.py "C:\Path\To\Takeout" -o "C:\Path\To\Output" --skipped_files "C:\Path\To\SkippedFilesFolder" --time-zone "Europe/London"
```

---

### Features: validate_processor.py

**Test 1: File Existence Check**
    - Verifies every input media file has a corresponding output file in the correct folder.

**Test 2: File Size Comparison**
    - Checks that the output file size is not significantly smaller or larger than the original input file. Specifically, the validator considers a file valid if its size is no more than 32 bytes smaller and no more than 10KB (10,240 bytes) larger than the input. Typically, adding metadata increases the file size by 1–2 KB, but in some cases, the file size may decrease slightly due to metadata optimization or removal. This test flags any files where the size changes beyond these reasonable bounds, so you can manually review them to ensure the file was not corrupted during processing.

**Test 3: Invalid Modified Date Check**
    - Identifies files in the processed output whose modified date does not match the expected year and month folder. This can happen if the metadata embedding or file copying did not correctly update the file's timestamps. The validator writes these files to a text report so you can manually review and correct any inconsistencies in file dates.

**Test 4: Orphan JSON Detection**
    - Identifies JSON files not matched to any media file. This is another major pain point with Google Takeout—sometimes a JSON sidecar file will exist, but the actual media file it references is missing from the export. In these cases, the script extracts the Google Photos URL from the orphaned JSON so you can manually download the missing media and then reprocess it. This helps recover important photos or videos that would otherwise be lost due to Takeout's inconsistencies.


**Optional Flags**:
    - `-o <output_folder>`: Specify a custom processed output folder (default: `<takeout_folder>/processed`)
    - `--wait`: Pause after each year summary for review
    - `--time-zone "<time_zone>"`: Specify the time zone for date/time conversions in TZ identifier format. The value should be a valid [IANA time zone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones), e.g., `America/New_York`, `Asia/Kolkata`, etc. Default is `America/Los_Angeles` (Pacific Time).

#### Usage Example

```powershell
python validate.py "C:\Path\To\Takeout" -o "C:\Path\To\Processed" --wait --time-zone "Europe/London"
```

---

### Common Issues & Troubleshooting

**ExifTool Not Found**

If you see:

```
Error: ExifTool not found in PATH
```

**Solution**: Ensure `exiftool.exe` is added to the PATH variable. If you only have `exiftool(-k).exe`, rename it to `exiftool.exe`.

**Permission Errors**

```
PermissionError: [Errno 13] Permission denied
```

**Solution**: Run PowerShell as Administrator or ensure you have read/write permissions for all folders.

**Large Datasets**

- For very large takeouts, process one year at a time by moving folders.
- Monitor disk space in the output directory.
- Consider using an SSD for faster processing.

**JSON Encoding Issues**

If you see Unicode errors, the script will skip problematic files and log them.

---

### Safety & Performance

- **Non-destructive**: Originals are never modified; all processing is done on copies.
- **Retry-able**: You can re-run the processor for skipped files after adding additional JSON matching rules.
- **Detailed Logging**: All actions are logged for audit and troubleshooting.
- **Performance**: Typical speed is 1-3 files/sec when reading and writing to same storage drive. Use different source and target drives for better performance.

---

### Advanced Configuration

- To change which JSON fields map to EXIF tags, edit the `_build_cmd` method in `google_photos_processor.py`.
- To add/remove supported formats, edit the `MEDIA_EXTS`, `WRITABLE_FORMATS`, and `READ_ONLY_FORMATS` sets in the processor script.
- Date fallback logic (photoTakenTime vs. creationTime) can be changed in the processor script.

---

### Limitations

- **Complex filename patterns**: Some edge cases may not match perfectly; review logs for skipped files.
- **Video metadata**: Some video formats have limited EXIF support; for read-only formats, only the modified date is updated.
- **Windows path length**: Avoid very long folder paths to prevent errors.

---

### Contact & Support

For issues or questions, please open an issue on the project repository. This repository is provided as-is and is not expected to be regularly maintained or updated. The scripts were tested on a Google Takeout export created in January 2024 and may not handle changes Google has made to the Takeout format since then. Use with caution and review any updates to Google Photos Takeout before relying on this tool for future exports.