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
from json_matcher import load_json, match_json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/Los_Angeles"
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
        self.invalid_date_files = 0  # Aggregate count
        self.orphan_json_files = 0  # Aggregate count

class GooglePhotosValidator:
    def _find_json_for_media(self, media_file: Path, json_files: list[Path]):
        """Find the best matching JSON file for a given media file using match_json rules."""
        from json_matcher import match_json
        matches = match_json(media_file, json_files)
        return matches[0] if matches else None
    JSON_LENGTH_LIMIT = 50  # Max length of JSON filename (incl. .json)

    def __init__(self, base_path: Path, output_path: Path = None, time_zone: str = DEFAULT_TZ):
        self.base_path = base_path
        self.output_path = output_path or (base_path / "processed")
        self.result = ValidationResult()
        self.time_zone = ZoneInfo(time_zone)
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


    def _get_expected_output_path(self, media_file: Path, json_files: list[Path]):
        """Determine where this media file should be in the processed output"""
        matches = match_json(media_file, json_files)
        json_file = matches[0] if matches else None
        if not json_file:
            return None

        metadata = load_json(json_file)
        if not metadata:
            return None

        # Get timestamp and convert to input time zone 
        timestamp = None
        for time_field in ['photoTakenTime', 'creationTime']:
            if time_field in metadata:
                timestamp = metadata[time_field].get('timestamp')
                if timestamp:
                    break

        if not timestamp:
            return None

        try:
            # Convert UTC timestamp to specified time zone
            dt_utc = datetime.fromtimestamp(int(timestamp), tz=UTC)
            dt_local = dt_utc.astimezone(self.time_zone)
            # Expected path: output/YYYY/MM/filename
            expected_path = self.output_path / str(dt_local.year) / f"{dt_local.month:02d}" / media_file.name
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
        print(f"Scanning all files in '{year_folder.name}' (this may take a few seconds)...")
        media_files = []
        json_files = []

        for file_path in year_folder.rglob('*'):
            if file_path.is_file():
                if file_path.suffix.lower() != ".json":
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
                        if file.is_file() and file.suffix.lower() != ".json":
                            try:
                                mtime = datetime.fromtimestamp(file.stat().st_mtime, tz=self.time_zone)
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
        # Aggregate count for overall summary
        self.result.invalid_date_files += len(invalid_date_files)

        # Track per-year missing files for overall summary
        if not hasattr(self.result, 'per_year_missing_files'):
            self.result.per_year_missing_files = []
        missing_files = [m for m in media_files if not self._get_expected_output_path(m, json_files) or not (self._get_expected_output_path(m, json_files) and self._get_expected_output_path(m, json_files).exists())]
        self.result.per_year_missing_files.extend(str(m) for m in missing_files)

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
        # Aggregate count for overall summary
        self.result.orphan_json_files += len(orphan_jsons)

        # Print per-year summary (improved format)
        label_width = 38
        value_width = 6
        year_summary_lines = []
        year_summary_lines.append(f"\nYEAR {year} SUMMARY:")
        year_summary_lines.append(f"  Total media files:{' ' * (label_width - len('Total media files:'))}{len(media_files):>{value_width}}")
        year_summary_lines.append(f"  Test 1: Output files not present:{' ' * (label_width - len('Test 1: Output files not present:'))}{len(missing_files):>{value_width}}")
        year_summary_lines.append(f"  Test 2: Output file size mismatch:{' ' * (label_width - len('Test 2: Output file size mismatch:'))}{len(mismatched_files):>{value_width}}")
        year_summary_lines.append(f"  Test 3: Output file modified date invalid:{' ' * (label_width - len('Test 3: Output file modified date invalid:'))}{len(invalid_date_files):>{value_width}}")
        year_summary_lines.append(f"  Test 4: Orphan JSON files:{' ' * (label_width - len('Test 4: Orphan JSON files:'))}{len(orphan_jsons):>{value_width}}")
        for line in year_summary_lines:
            print(line)
        # Write per-year summary to text file
        year_summary_file = self.base_path / f"{year}_validation_summary.txt"
        with open(year_summary_file, 'w', encoding='utf-8') as f:
            for line in year_summary_lines:
                f.write(line + "\n")

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
        """Print validation summary (no timestamps, at end only)"""
        # Print improved overall summary (aligned, descriptive, no timestamps)
        # Use fixed column for numbers (col 42)
        label_width = 40
        value_col = 42
        def pad(label):
            return ' ' * (value_col - len(label))
        print("\n" + "=" * 70)
        print("OVERALL VALIDATION SUMMARY:")
        print("=" * 70)
        print(f"  Total media files:{pad('Total media files:')}{self.result.total_input_files}")
        print(f"  Test 1: Output files not present:{pad('Test 1: Output files not present:')}{len(self.result.missing_files)}")
        print(f"  Test 2: Output file size mismatch:{pad('Test 2: Output file size mismatch:')}{self.result.content_mismatches}")
        print(f"  Test 3: Output file modified date invalid:{pad('Test 3: Output file modified date invalid:')}{self.result.invalid_date_files}")
        print(f"  Test 4: Orphan JSON files:{pad('Test 4: Orphan JSON files:')}{self.result.orphan_json_files}")
        print(f"  Errors:{pad('Errors:')}{len(self.result.errors)}")
        if self.result.total_input_files > 0:
            success_rate = (self.result.content_matches / self.result.total_input_files) * 100
            print(f"  Success rate:{pad('Success rate:')}{success_rate:.1f}%")
        print("=" * 70)
        # Save detailed report
        report_file = self.base_path / f"validation_summary.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("Google Photos Processor Validation Report (File Size Comparison)\n")
            f.write("=" * 50 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Input path: {self.base_path}\n")
            f.write(f"Output path: {self.output_path}\n\n")
            f.write("OVERALL SUMMARY:\n")
            f.write(f"Total media files: {self.result.total_input_files}\n")
            f.write(f"Test 1: Output files not present: {len(self.result.missing_files)}\n")
            f.write(f"Test 2: Output file size mismatch: {self.result.content_mismatches}\n")
            f.write(f"Test 3: Output file modified date invalid: {self.result.invalid_date_files}\n")
            f.write(f"Test 4: Orphan JSON files: {self.result.orphan_json_files}\n")
            f.write(f"Errors: {len(self.result.errors)}\n")
            if self.result.total_input_files > 0:
                f.write(f"Success rate: {success_rate:.1f}%\n\n")
        print(f"Detailed report saved to: {report_file}")
        print("Note: Overall missing files may differ from per-year missing files if a file is not matched to any year folder, or if output path calculation fails for a file present in input but not in any year folder.")
        # Write missing files not accounted to any year folder
        if hasattr(self.result, 'per_year_missing_files'):
            per_year_missing = set(self.result.per_year_missing_files)
            unaccounted_missing = [f for f in self.result.missing_files if f not in per_year_missing]
            if unaccounted_missing:
                unaccounted_file = self.base_path / "unaccounted_missing_files.txt"
                with open(unaccounted_file, 'w', encoding='utf-8') as f:
                    f.write("Missing files not accounted to any year folder\n")
                    f.write("=" * 50 + "\n")
                    for fname in unaccounted_missing:
                        f.write(f"{fname}\n")
                print(f"Unaccounted missing files written to: {unaccounted_file}")

def main():
    parser = argparse.ArgumentParser(description='Validate Google Photos processor output (file size comparison)')
    parser.add_argument('input_path', help='Path to the Google Photos takeout folder')
    parser.add_argument('-o', '--output', help='Path to processed output folder (default: input_path/processed)')
    parser.add_argument('--wait', action='store_true', help='Pause after each year summary')
    parser.add_argument('--time-zone', default=DEFAULT_TZ, help='Time zone for date conversion (default: America/Los_Angeles)')
    args = parser.parse_args()
    base_path = Path(args.input_path).resolve()
    output_path = Path(args.output).resolve() if args.output else None
    if not base_path.exists():
        print(f"Error: Input path does not exist: {base_path}")
        sys.exit(1)
    validator = GooglePhotosValidator(base_path, output_path, time_zone=args.time_zone)
    validator.validate(wait=args.wait)
    sys.exit(0)

if __name__ == "__main__":
    main()