#!/usr/bin/env python3
"""
Google Photos Processor Validation Script (Simplified File Size Comparison)

This script validates that media files from Google Photos takeout input folders
have been correctly processed and exist in the output folder with acceptable file sizes.

The script:
1. Finds all "Photos from YYYY" folders in the input path
2. For each media file, determines where it should be in the processed output
3. Compares file sizes (output should be >= input, but not more than 10KB larger)
4. Reports missing files, size mismatches, and summary statistics
5. Writes mismatched files to a text file with mismatch reasons
6. Logs all console output to a timestamped log file

Requirements:
- Python 3.9+

Usage:
    python validate_processor.py /path/to/takeout/folder [-o /custom/output/path]
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")

class ValidationResult:
    def __init__(self):
        self.total_input_files = 0
        self.found_in_output = 0
        self.content_matches = 0
        self.content_mismatches = 0
        self.missing_files = []
        self.mismatch_files = []  # Now stores (input_file, output_file, reason)
        self.errors = []

class GooglePhotosValidator:
    JSON_LENGTH_LIMIT = 50  # Max length of JSON filename (incl. .json)
    MEDIA_EXTS = {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
        ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp",
        ".heic", ".heif",
    }

    def __init__(self, base_path: Path, output_path: Path = None):
        self.base_path = base_path
        self.output_path = output_path or (base_path / "processed")
        self.result = ValidationResult()
        
        # Setup logging to both console and file
        self._setup_logging()

    def _setup_logging(self):
        """Setup logging to both console and timestamped log file"""
        log_file = self.base_path / f"validation_verbose.log"
        
        # Clear any existing handlers
        logging.getLogger().handlers.clear()
        
        # Create formatter
        formatter = logging.Formatter("%(asctime)s %(levelname)s | %(message)s", 
                                    datefmt="%Y-%m-%d %H:%M:%S")
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        
        # File handler
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        
        # Configure root logger
        logging.basicConfig(
            level=logging.INFO,
            handlers=[console_handler, file_handler]
        )
        
        logging.info("Validation started - logging to %s", log_file)

    def _find_year_folders(self):
        """Find all 'Photos from YYYY' folders"""
        pattern = re.compile(r"^Photos from (\d{4})$", re.IGNORECASE)
        for item in self.base_path.iterdir():
            if item.is_dir():
                match = pattern.match(item.name)
                if match:
                    yield item, match.group(1)

    def _load_json(self, json_path: Path):
        """Load JSON metadata file"""
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:
            logging.warning("Could not parse %s: %s", json_path, e)
            return None

    def _find_json_for_media(self, media_file: Path, json_files: list[Path]):
        """Find matching JSON file for a media file using the same logic as the processor"""
        media_name = media_file.name

        # Rule 1: Exact match (case insensitive)
        exact_json = media_name + ".json"
        for json_file in json_files:
            if json_file.name.lower() == exact_json.lower():
                return json_file

        # Rule 2: Truncated match (50 char limit, case insensitive)
        if len(exact_json) > self.JSON_LENGTH_LIMIT:
            truncated = media_name[:self.JSON_LENGTH_LIMIT - 5]
            for json_file in json_files:
                if json_file.name.lower().startswith(truncated.lower()) and json_file.name.lower().endswith('.json'):
                    json_base = json_file.name[:-5]
                    if media_name.lower().startswith(json_base.lower()):
                        return json_file

        # Rule 3: Parenthetical match (case insensitive)
        match = re.match(r'^(.+)\((\d+)\)(\.[^.]+)$', media_name)
        if match:
            base_name, number, extension = match.groups()
            alt_json = f"{base_name}{extension}({number}).json"
            for json_file in json_files:
                if json_file.name.lower() == alt_json.lower():
                    return json_file

        # Rule 4: Check for '-edited' from filename if present (case insensitive)
        edited_match = re.match(r"^(.*)-edited(\.[^.]+)$", media_name, re.IGNORECASE)
        if edited_match:
            base_name = edited_match.group(1) + edited_match.group(2)
            rule4_json = base_name + ".json"
            for json_file in json_files:
                if json_file.name.lower() == rule4_json.lower():
                    return json_file

        # Rule 5 - Live photos (JPG or HEIC fallback, case insensitive)
        if media_name.lower().endswith('.mp4'):
            base_name = media_name[:-4]
            jpg_name = base_name + '.JPG'
            jpg_json_name = jpg_name + '.json'
            heic_name = base_name + '.HEIC'
            heic_json_name = heic_name + '.json'
            for json_file in json_files:
                if json_file.name.lower() == jpg_json_name.lower():
                    return json_file
            for json_file in json_files:
                if json_file.name.lower() == heic_json_name.lower():
                    return json_file

        # Rule 6 - (1).mp4/JPG or (1).mp4/HEIC fallback (live photo duplicates)
        m = re.match(r"^(.+)\(\d+\)\.mp4$", media_name, re.IGNORECASE)
        if m:
            base_name = m.group(1)
            jpg_name = base_name + '.JPG'
            jpg_json_name = jpg_name + '.json'
            heic_name = base_name + '.HEIC'
            heic_json_name = heic_name + '.json'
            for json_file in json_files:
                if json_file.name.lower() == jpg_json_name.lower():
                    return json_file
            for json_file in json_files:
                if json_file.name.lower() == heic_json_name.lower():
                    return json_file
        # Rule 7: PNG fallback (case insensitive)
        png_match = re.match(r"^(.*)\.png$", media_name, re.IGNORECASE)
        if png_match:
            base_name = png_match.group(1)
            png_json_name = base_name + ".json"
            for json_file in json_files:
                if json_file.name.lower() == png_json_name.lower():
                    return json_file

        # Rule 8: Title-based match
        for json_file in json_files:
            metadata = self._load_json(json_file)
            if metadata and metadata.get('title') == media_name:
                return json_file
        return None

    def _get_expected_output_path(self, media_file: Path, json_files: list[Path]):
        """Determine where this media file should be in the processed output"""
        json_file = self._find_json_for_media(media_file, json_files)
        if not json_file:
            return None

        metadata = self._load_json(json_file)
        if not metadata:
            return None

        # Get timestamp and convert to Pacific time (same logic as processor)
        timestamp = None
        for time_field in ['photoTakenTime', 'creationTime']:
            if time_field in metadata:
                timestamp = metadata[time_field].get('timestamp')
                if timestamp:
                    break

        if not timestamp:
            return None

        try:
            # Convert UTC timestamp to Pacific time
            dt_utc = datetime.fromtimestamp(int(timestamp), tz=UTC)
            dt_pacific = dt_utc.astimezone(PACIFIC)
            
            # Expected path: output/YYYY/MM/filename
            expected_path = self.output_path / str(dt_pacific.year) / f"{dt_pacific.month:02d}" / media_file.name
            return expected_path
        except (ValueError, TypeError):
            return None

    def _compare_file_sizes(self, input_file: Path, output_file: Path):
        """
        Compare file sizes with expanded logic:
        - Output size can be up to 32 bytes smaller than input
        - Output size should not be more than 10KB larger than input
        Returns (is_match: bool, reason: str)
        """
        if not output_file.exists():
            return False, "Output file does not exist"

        try:
            input_size = input_file.stat().st_size
            output_size = output_file.stat().st_size
            size_diff = output_size - input_size

            if size_diff < -32:
                return False, f"Output smaller than input by more than 32 bytes ({input_size} → {output_size}, {size_diff} bytes)"
            elif size_diff > 10240:  # 10KB = 10240 bytes
                return False, f"Output too much larger than input ({input_size} → {output_size}, +{size_diff} bytes)"
            else:
                return True, f"Size acceptable ({input_size} → {output_size}, {'+' if size_diff >= 0 else ''}{size_diff} bytes)"
        except Exception as e:
            return False, f"Error comparing file sizes: {e}"

    def _validate_year_folder(self, year_folder: Path, year: str, wait=False):
        """Validate all media files in a year folder, with per-year log file and orphan JSON detection"""
        # Setup per-year log file
        year_log_file = self.base_path / f"{year}_validation.log"
        year_logger = logging.getLogger(f"year_{year}")
        year_logger.handlers.clear()
        formatter = logging.Formatter("%(asctime)s %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        file_handler = logging.FileHandler(year_log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        year_logger.addHandler(file_handler)
        year_logger.setLevel(logging.INFO)

        year_logger.info("Processing folder: %s", year_folder.name)

        # Collect media files and JSON files
        media_files = []
        json_files = []

        for file_path in year_folder.rglob('*'):
            if file_path.is_file():
                if file_path.suffix.lower() in self.MEDIA_EXTS:
                    media_files.append(file_path)
                elif file_path.suffix.lower() == '.json':
                    json_files.append(file_path)

        year_logger.info("Found %d media files in %s", len(media_files), year_folder.name)
        self.result.total_input_files += len(media_files)

        # Track consumed JSON files
        consumed_jsons = set()
        mismatched_files = []

        # --- New validation: check processed/YYYY/MM files for invalid modified date ---
        processed_base = self.output_path / year
        invalid_date_log = self.base_path / f"{year}_validation_result_invalid_date.txt"
        invalid_date_files = []
        if processed_base.exists():
            for month_folder in processed_base.iterdir():
                if month_folder.is_dir() and re.match(r"^\d{2}$", month_folder.name):
                    expected_year = int(year)
                    expected_month = int(month_folder.name)
                    for file in month_folder.iterdir():
                        if file.is_file() and file.suffix.lower() in self.MEDIA_EXTS:
                            try:
                                mtime = datetime.fromtimestamp(file.stat().st_mtime, tz=PACIFIC)
                                if mtime.year != expected_year or mtime.month != expected_month:
                                    invalid_date_files.append(str(file))
                            except Exception:
                                pass
        if invalid_date_files:
            with open(invalid_date_log, 'w', encoding='utf-8') as f:
                f.write(f"Files in processed/{year}/MM with invalid modified date\n")
                f.write("=" * 50 + "\n")
                for fname in invalid_date_files:
                    f.write(f"{fname}\n")
            year_logger.info(f"Invalid date files written to: {invalid_date_log}")

        for media_file in media_files:
            json_file = self._find_json_for_media(media_file, json_files)
            expected_output = None
            if json_file:
                consumed_jsons.add(json_file)
                expected_output = self._get_expected_output_path(media_file, json_files)
            else:
                expected_output = self._get_expected_output_path(media_file, json_files)

            if not expected_output:
                self.result.errors.append(f"Could not determine output path for: {media_file}")
                year_logger.warning("Could not determine output path for: %s", media_file)
                continue

            if not expected_output.exists():
                self.result.missing_files.append(str(media_file))
                year_logger.warning("Missing in output: %s (expected at: %s)", media_file.name, expected_output)
                continue

            self.result.found_in_output += 1

            # Compare file sizes
            is_match, reason = self._compare_file_sizes(media_file, expected_output)

            if is_match:
                self.result.content_matches += 1
                year_logger.info("Size match: %s - %s", media_file.name, reason)
            else:
                self.result.content_mismatches += 1
                self.result.mismatch_files.append((str(media_file), str(expected_output), reason))
                mismatched_files.append((str(media_file), str(expected_output), reason))
                year_logger.warning("Size mismatch: %s - %s", media_file.name, reason)

        # After processing, find orphan JSON files
        orphan_jsons = [str(j) for j in json_files if j not in consumed_jsons]
        if orphan_jsons:
            year_logger.info("\nORPHAN JSON FILES (not matched to any media file):")
            print(f"\nORPHAN JSON FILES in {year_folder.name} ({len(orphan_jsons)}):")
            for orphan in orphan_jsons:
                year_logger.info("  %s", orphan)
                print(f"  {orphan}")

        # Write invalid date files for this year
        invalid_date_log = self.base_path / f"{year}_validation_result_invalid_date.txt"
        if invalid_date_files:
            with open(invalid_date_log, 'w', encoding='utf-8') as f:
                f.write(f"Files in processed/{year}/MM with invalid modified date\n")
                f.write("=" * 50 + "\n")
                for fname in invalid_date_files:
                    f.write(f"{fname}\n")
            year_logger.info(f"Invalid date files written to: {invalid_date_log}")

        # Write missing files for this year
        not_present_file = self.base_path / f"{year}_validation_result_not_present.txt"
        missing_files = [m for m in media_files if not self._get_expected_output_path(m, json_files)]
        if missing_files:
            with open(not_present_file, 'w', encoding='utf-8') as f:
                f.write(f"Missing output files for year {year}\n")
                f.write("=" * 50 + "\n")
                for fname in missing_files:
                    f.write(f"{fname}\n")
            year_logger.info(f"Missing files written to: {not_present_file}")

        # Write mismatched files for this year
        mismatched_file_path = self.base_path / f"{year}_validation_result_size_mismatch.txt"
        if mismatched_files:
            with open(mismatched_file_path, 'w', encoding='utf-8') as f:
                f.write(f"Mismatched files for year {year}\n")
                f.write("=" * 50 + "\n")
                for input_file, output_file, reason in mismatched_files:
                    f.write(f"Input:  {input_file}\n")
                    f.write(f"Output: {output_file}\n")
                    f.write(f"Reason: {reason}\n\n")
            year_logger.info(f"Mismatched files written to: {mismatched_file_path}")

        # Write orphan json files for this year
        orphan_json_file_path = self.base_path / f"{year}_validation_result_orphan_json.txt"
        orphan_json_url_file_path = self.base_path / f"{year}_validation_result_orphan_json_url.txt"
        orphan_json_folder = self.base_path / "orphan_json" / f"Photos from {year}" 
        if orphan_jsons:
            with open(orphan_json_file_path, 'w', encoding='utf-8') as f:
                f.write(f"Orphan JSON files for year {year}\n")
                f.write("=" * 50 + "\n")
                for orphan in orphan_jsons:
                    f.write(f"{orphan}\n")
            year_logger.info(f"Orphan JSON files written to: {orphan_json_file_path}")

            # Write orphaned JSON URLs (one per line, no extra text)
            with open(orphan_json_url_file_path, 'w', encoding='utf-8') as f:
                for orphan in orphan_jsons:
                    try:
                        data = self._load_json(Path(orphan))
                        url = data.get('url') if data else None
                        if url:
                            f.write(f"{url}\n")
                    except Exception:
                        pass
            year_logger.info(f"Orphan JSON URLs written to: {orphan_json_url_file_path}")

            # Create orphan_json/Photos from YYYY/ and copy orphan JSON files
            orphan_json_folder.mkdir(parents=True, exist_ok=True)
            for orphan in orphan_jsons:
                try:
                    src_path = Path(orphan)
                    dest_path = orphan_json_folder / src_path.name
                    if src_path.exists():
                        import shutil
                        shutil.copy2(src_path, dest_path)
                        year_logger.info(f"Copied orphan JSON {src_path} to {dest_path}")
                except Exception as e:
                    year_logger.warning(f"Failed to copy orphan JSON {orphan}: {e}")

        # Print per-year summary (improved format)
        label_width = 38
        value_width = 6
        print(f"\nYEAR {year} SUMMARY:")
        print(f"  Total media files:{' ' * (label_width - len('Total media files:'))}{len(media_files):>{value_width}}")
        print(f"  Test 1: Output files not present:{' ' * (label_width - len('Test 1: Output files not present:'))}{len([m for m in media_files if not self._get_expected_output_path(m, json_files)]):>{value_width}}")
        print(f"  Test 2: Output file size mismatch:{' ' * (label_width - len('Test 2: Output file size mismatch:'))}{len(mismatched_files):>{value_width}}")
        print(f"  Test 3: Output file modified date invalid:{' ' * (label_width - len('Test 3: Output file modified date invalid:'))}{len(invalid_date_files):>{value_width}}")
        print(f"  Test 4: Orphan JSON files:{' ' * (label_width - len('Test 4: Orphan JSON files:'))}{len(orphan_jsons):>{value_width}}")

        # Pause for user input after each year only if wait is True
        if wait:
            input(f"\nPress Enter to continue after reviewing year {year}...")

    def _save_mismatch_files(self):
        """Save mismatched files to a text file"""
        if not self.result.mismatch_files:
            return
            
        mismatch_file = self.base_path / f"content_mismatches_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        with open(mismatch_file, 'w', encoding='utf-8') as f:
            f.write("Google Photos Processor - File Size Mismatches\n")
            f.write("=" * 50 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total mismatches: {len(self.result.mismatch_files)}\n\n")
            
            for input_file, output_file, reason in self.result.mismatch_files:
                f.write(f"Input:  {input_file}\n")
                f.write(f"Output: {output_file}\n")
                f.write(f"Reason: {reason}\n\n")
        
        logging.info("File size mismatches written to: %s", mismatch_file)

    def validate(self, wait=False):
        """Run the full validation"""
        logging.info("Starting validation of processed Google Photos (file size comparison)")
        logging.info("Input path: %s", self.base_path)
        logging.info("Output path: %s", self.output_path)
        
        if not self.output_path.exists():
            logging.error("Output path does not exist: %s", self.output_path)
            return False

        # Find and process each year folder
        year_folders = list(self._find_year_folders())
        if not year_folders:
            logging.error("No 'Photos from YYYY' folders found in: %s", self.base_path)
            return False

        logging.info("Found %d year folders to validate", len(year_folders))

        for year_folder, year in year_folders:
            self._validate_year_folder(year_folder, year, wait=wait)

        # Save mismatch files if any
        self._save_mismatch_files()

        # Print and log summary
        self._print_summary()
        
        return True

    def _print_summary(self):
        """Print validation summary"""
        summary_lines = [
            "\n" + "=" * 70,
            "VALIDATION SUMMARY (File Size Comparison)",
            "=" * 70,
            f"Total input media files:     {self.result.total_input_files}",
            f"Found in output:             {self.result.found_in_output}",
            f"Missing files:               {len(self.result.missing_files)}",
            f"Size matches:                {self.result.content_matches}",
            f"Size mismatches:             {self.result.content_mismatches}",
            f"Errors:                      {len(self.result.errors)}"
        ]
        
        if self.result.total_input_files > 0:
            success_rate = (self.result.content_matches / self.result.total_input_files) * 100
            summary_lines.append(f"Success rate:                {success_rate:.1f}%")

        for line in summary_lines:
            print(line)
            logging.info(line.replace("=" * 70, "").strip())

        if self.result.missing_files:
            print(f"\nMISSING FILES ({len(self.result.missing_files)}):")
            logging.info("MISSING FILES (%d):", len(self.result.missing_files))
            for i, missing in enumerate(self.result.missing_files[:10]):  # Show first 10
                print(f"  - {missing}")
                logging.info("  Missing: %s", missing)
            if len(self.result.missing_files) > 10:
                remaining = len(self.result.missing_files) - 10
                print(f"  ... and {remaining} more")
                logging.info("  ... and %d more", remaining)

        if self.result.mismatch_files:
            print(f"\nSIZE MISMATCHES ({len(self.result.mismatch_files)}):")
            logging.info("SIZE MISMATCHES (%d):", len(self.result.mismatch_files))
            for i, (input_file, output_file, reason) in enumerate(self.result.mismatch_files[:5]):  # Show first 5
                print(f"  - Input:  {input_file}")
                print(f"    Output: {output_file}")
                print(f"    Reason: {reason}")
                logging.info("  Mismatch - Input: %s", input_file)
                logging.info("  Mismatch - Output: %s", output_file)
                logging.info("  Mismatch - Reason: %s", reason)
            if len(self.result.mismatch_files) > 5:
                remaining = len(self.result.mismatch_files) - 5
                print(f"  ... and {remaining} more")
                logging.info("  ... and %d more", remaining)

        if self.result.errors:
            print(f"\nERRORS ({len(self.result.errors)}):")
            logging.info("ERRORS (%d):", len(self.result.errors))
            for error in self.result.errors[:5]:  # Show first 5
                print(f"  - {error}")
                logging.info("  Error: %s", error)
            if len(self.result.errors) > 5:
                remaining = len(self.result.errors) - 5
                print(f"  ... and {remaining} more")
                logging.info("  ... and %d more", remaining)

        print("=" * 70)
        logging.info("=" * 70)

        # Save detailed report
        report_file = self.base_path / f"validation_summary.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("Google Photos Processor Validation Report (File Size Comparison)\n")
            f.write("=" * 50 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Input path: {self.base_path}\n")
            f.write(f"Output path: {self.output_path}\n\n")
            
            f.write("SUMMARY:\n")
            f.write(f"Total input files: {self.result.total_input_files}\n")
            f.write(f"Found in output: {self.result.found_in_output}\n")
            f.write(f"Size matches: {self.result.content_matches}\n")
            f.write(f"Size mismatches: {self.result.content_mismatches}\n")
            f.write(f"Missing files: {len(self.result.missing_files)}\n")
            f.write(f"Errors: {len(self.result.errors)}\n\n")
            
            if self.result.missing_files:
                f.write("MISSING FILES:\n")
                for missing in self.result.missing_files:
                    f.write(f"{missing}\n")
                f.write("\n")
            
            if self.result.mismatch_files:
                f.write("SIZE MISMATCHES:\n")
                for input_file, output_file, reason in self.result.mismatch_files:
                    f.write(f"Input:  {input_file}\n")
                    f.write(f"Output: {output_file}\n")
                    f.write(f"Reason: {reason}\n\n")
            
            if self.result.errors:
                f.write("ERRORS:\n")
                for error in self.result.errors:
                    f.write(f"{error}\n")

        print(f"Detailed report saved to: {report_file}")
        logging.info("Detailed report saved to: %s", report_file)

def main():
    parser = argparse.ArgumentParser(description='Validate Google Photos processor output (file size comparison)')
    parser.add_argument('input_path', help='Path to the Google Photos takeout folder')
    parser.add_argument('-o', '--output', help='Path to processed output folder (default: input_path/processed)')
    parser.add_argument('--wait', action='store_true', help='Pause after each year summary')
    args = parser.parse_args()
    base_path = Path(args.input_path).resolve()
    output_path = Path(args.output).resolve() if args.output else None
    if not base_path.exists():
        print(f"Error: Input path does not exist: {base_path}")
        sys.exit(1)
    validator = GooglePhotosValidator(base_path, output_path)
    validator.validate(wait=args.wait)
    sys.exit(0)

if __name__ == "__main__":
    main()