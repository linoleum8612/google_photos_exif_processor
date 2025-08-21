#!/usr/bin/env python3
"""
Google Photos Takeout EXIF Processor (Pacific-Time Version) - FIXED

Changes requested:
1. Convert all times stored in JSON (assumed UTC) to U.S. Pacific Time (America/Los_Angeles) before embedding.
2. Update DateTimeOriginal, CreateDate, ModifyDate **and** FileModifyDate to the converted Pacific Time value.
3. Keep all previous matching logic intact.
4. Mirror console output to a timestamped log file located in the input folder.
5. FIX: Handle AVI and other video formats that don't support EXIF writing

Requirements:
- Python ≥ 3.9 (for zoneinfo)
- ExifTool in PATH

Usage:
    python google_photos_processor.py <takeout_folder> [-o <output_folder>]
"""
import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")

class GooglePhotosProcessor:
    def __init__(self, base: Path, output: Path | None):
        self.base = base
        self.out_base = output if output else base / "processed"
        self.skipped: list[str] = []
        self.processed = 0
        self.copied_only = 0  # Files copied without metadata embedding
        # For per-folder stats
        self._reset_folder_stats()

    def _reset_folder_stats(self):
        self.folder_processed = 0
        self.folder_copied_only = 0
        self.folder_skipped = 0
        self.folder_rule_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0}
    JSON_LENGTH_LIMIT = 50  # Max length of JSON filename (incl. .json)
    MEDIA_EXTS = {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
        ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp",
        ".heic", ".heif",
    }
    
    # Formats that ExifTool can write metadata to
    WRITABLE_FORMATS = {
        ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".heif",
        ".mp4", ".mov", ".m4v", ".3gp"
    }
    
    # Formats that don't support metadata writing
    READ_ONLY_FORMATS = {
        ".avi", ".mkv", ".webm", ".gif", ".bmp"
    }

    def __init__(self, base: Path, output: Path | None):
        self.base = base
        self.out_base = output if output else base / "processed"
        self.skipped: list[str] = []
        self.processed = 0
        self.copied_only = 0  # Files copied without metadata embedding

    # ---------- logging ----------
    def _setup_logging(self):
        log_file = self.base / f"gp_processor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.log_file_path = log_file
        # Write initial log line
        with open(self.log_file_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} INFO | Logging to {log_file}\n")
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} INFO | ==============================\n")
        from rich.console import Console
        self.console = Console()
        # Do not print to console here

    def log_message(self, level: str, message: str, progress=None):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"{timestamp} {level.upper()} | {message}"
        if progress is not None:
            progress.console.print(log_line)
        else:
            self.console.print(log_line)
        if self.log_file_path:
            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")

    # ---------- utilities ----------
    @staticmethod
    def _json_time_to_pacific(ts: str | int) -> str:
        """Convert Unix-timestamp-in-UTC → formatted Pacific-time string."""
        try:
            dt_utc = datetime.fromtimestamp(int(ts), tz=UTC)
            dt_pst = dt_utc.astimezone(PACIFIC)
            return dt_pst.strftime("%Y:%m:%d %H:%M:%S")
        except Exception:
            return ""

    # ---------- folder discovery ----------
    def _year_folders(self):
        pat = re.compile(r"^Photos from (\d{4})$", re.IGNORECASE)
        for p in self.base.iterdir():
            if p.is_dir() and pat.match(p.name):
                yield p

    # ---------- JSON matching (unchanged logic) ----------
    def _load_json(self, path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            self.log_message("WARNING", f"Could not parse {path}: {e}")
            return None

    def _match_json(self, media: Path, json_files: list[Path]):
        name = media.name
        # Rule 1 - Exact match
        exact = name + ".json"
        for j in json_files:
            if j.name.lower() == exact.lower():
                self.log_message("INFO", f"JSON match - Rule 1 (direct): {name} → {j.name}")
                self.folder_rule_counts[1] += 1
                return [j]
        # Rule 2 - Truncated match
        if len(exact) > self.JSON_LENGTH_LIMIT:
            trunc = name[: self.JSON_LENGTH_LIMIT - 5]
            for j in json_files:
                if j.name.lower().startswith(trunc.lower()):
                    self.log_message("INFO", f"JSON match - Rule 2 (truncated): {name} → {j.name}")
                    self.folder_rule_counts[2] += 1
                    return [j]
        # Rule 3 - Parenthetical match
        m = re.match(r"^(.+)\((\d+)\)(\.[^.]+)$", name)
        if m:
            alt = f"{m.group(1)}{m.group(3)}({m.group(2)}).json"
            for j in json_files:
                if j.name.lower() == alt.lower():
                    self.log_message("INFO", f"JSON match - Rule 3 (parenthetical): {name} → {j.name}")
                    self.folder_rule_counts[3] += 1
                    return [j]
        # Rule 4 - Remove '-edited' from filename if present
        edited_match = re.match(r"^(.*)-edited(\.[^.]+)$", name, re.IGNORECASE)
        if edited_match:
            base_name = edited_match.group(1) + edited_match.group(2)
            rule4_json = base_name + ".json"
            for j in json_files:
                if j.name.lower() == rule4_json.lower():
                    self.log_message("INFO", f"JSON match - Rule 4 (edited): {name} → {j.name}")
                    self.folder_rule_counts[4] += 1
                    return [j]
        # Rule 5 - MP4/JPG or MP4/HEIC fallback
        if name.lower().endswith('.mp4'):
            base_name = name[:-4]
            jpg_name = base_name + '.JPG'
            jpg_json_name = jpg_name + '.json'
            heic_name = base_name + '.HEIC'
            heic_json_name = heic_name + '.json'
            for j in json_files:
                if j.name.lower() == jpg_json_name.lower():
                    self.log_message("INFO", f"JSON match - Rule 5 (live photos): {name} → {j.name}")
                    self.folder_rule_counts[5] = self.folder_rule_counts.get(5, 0) + 1
                    return [j]
            for j in json_files:
                if j.name.lower() == heic_json_name.lower():
                    self.log_message("INFO", f"JSON match - Rule 5 (live photos): {name} → {j.name}")
                    self.folder_rule_counts[5] = self.folder_rule_counts.get(5, 0) + 1
                    return [j]
        # Rule 6 - (1).mp4/JPG or (1).mp4/HEIC fallback
        m = re.match(r"^(.+)\(\d+\)\.mp4$", name, re.IGNORECASE)
        if m:
            base_name = m.group(1)
            jpg_name = base_name + '.JPG'
            jpg_json_name = jpg_name + '.json'
            heic_name = base_name + '.HEIC'
            heic_json_name = heic_name + '.json'
            for j in json_files:
                if j.name.lower() == jpg_json_name.lower():
                    self.log_message("INFO", f"JSON match - Rule 6 (live photos duplicates): {name} → {j.name}")
                    self.folder_rule_counts[6] = self.folder_rule_counts.get(6, 0) + 1
                    return [j]
            for j in json_files:
                if j.name.lower() == heic_json_name.lower():
                    self.log_message("INFO", f"JSON match - Rule 6 (live photos duplicates): {name} → {j.name}")
                    self.folder_rule_counts[6] = self.folder_rule_counts.get(6, 0) + 1
                    return [j]
        # Rule 7 - PNG fallback (case insensitive)
        png_match = re.match(r"^(.*)\.png$", name, re.IGNORECASE)
        if png_match:
            base_name = png_match.group(1)
            png_json_name = base_name + ".json"
            for j in json_files:
                if j.name.lower() == png_json_name.lower():
                    self.log_message("INFO", f"JSON match - Rule 7 (PNG): {name} → {j.name}")
                    self.folder_rule_counts[7] = self.folder_rule_counts.get(7, 0) + 1
                    return [j]
        # Rule 8 - Title field fallback
        for j in json_files:
            data = self._load_json(j)
            if data and data.get("title") == name:
                self.log_message("INFO", f"JSON match - Rule 8 (via JSON title): {name} → {j.name}")
                self.folder_rule_counts[8] = self.folder_rule_counts.get(8, 0) + 1
                return [j]
        return []

    # ---------- exiftool command ----------
    def _build_cmd(self, meta: dict, target_path: Path):
        """Build exiftool command for embedding metadata - FIXED VERSION"""
        cmd = [
            "exiftool",
            "-overwrite_original",
            "-q",
            "-m",
        ]
        
        # Dates
        date_str = ""
        if ts := meta.get("photoTakenTime", {}).get("timestamp"):
            date_str = self._json_time_to_pacific(ts)
        elif ts := meta.get("creationTime", {}).get("timestamp"):
            date_str = self._json_time_to_pacific(ts)
        if date_str:
            cmd += [
                f"-DateTimeOriginal={date_str}",
                f"-CreateDate={date_str}",
                f"-ModifyDate={date_str}",
                f"-FileModifyDate={date_str}",
                f"-FileCreateDate={date_str}",
            ]
        
        # GPS
        geo = meta.get("geoData", {})
        if geo.get("latitude") or geo.get("longitude"):
            cmd += [
                f"-GPSLatitude={geo.get('latitude', 0)}",
                f"-GPSLongitude={geo.get('longitude', 0)}",
            ]
            if alt := geo.get("altitude"):
                cmd.append(f"-GPSAltitude={alt}")
        
        # People
        names = "; ".join(p.get("name", "") for p in meta.get("people", []) if p.get("name"))
        if names:
            cmd += [f"-Keywords={names}", f"-Subject={names}"]
        
        # Description
        if desc := meta.get("description"):
            cmd.append(f"-ImageDescription={desc}")
        
        # Target file (NOT using -o= which causes the error)
        cmd.append(str(target_path))
        
        return cmd

    # ---------- processing ----------
    def _process_file(self, media: Path, jpath: Path, progress=None):
        meta = self._load_json(jpath)
        if not meta:
            self.skipped.append(str(media))
            self.folder_skipped += 1
            self.log_message("WARNING", f"Skip {media.name} (bad JSON)", progress=progress)
            return
        
        # Determine target subdir from Pacific date
        ts = meta.get("photoTakenTime", {}).get("timestamp") or meta.get("creationTime", {}).get("timestamp")
        if not ts:
            self.skipped.append(str(media))
            self.folder_skipped += 1
            self.log_message("WARNING", f"Skip {media.name} (no timestamp)", progress=progress)
            return
        
        dt = datetime.fromtimestamp(int(ts), tz=UTC).astimezone(PACIFIC)
        target_dir = self.out_base / str(dt.year) / f"{dt.month:02d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / media.name
        
        # Copy file to destination first
        shutil.copy2(media, target)
        
        # Check if this format supports metadata writing
        file_ext = media.suffix.lower()
        
        if file_ext in self.READ_ONLY_FORMATS:
            # For formats that don't support metadata, update modified date using os.utime
            try:
                # Get Pacific time as datetime object
                pacific_dt = datetime.fromtimestamp(int(ts), tz=UTC).astimezone(PACIFIC)
                # Convert to timestamp (seconds since epoch)
                mod_time = pacific_dt.timestamp()
                # Set both access and modified time
                import os
                os.utime(target, (mod_time, mod_time))
                self.log_message("INFO", f"Updated modified date only (format doesn't support metadata): {media.name} → {dt.year}/{dt.month:02d}", progress=progress)
            except Exception as e:
                self.log_message("WARNING", f"Failed to update modified date for {media.name}: {e}", progress=progress)
            self.copied_only += 1
            self.folder_copied_only += 1
            if hasattr(self, 'copied_only_files'):
                self.copied_only_files.append(str(media))
            return
        
        if file_ext in self.WRITABLE_FORMATS:
            # Try to embed metadata for supported formats
            cmd = self._build_cmd(meta, target)
            res = subprocess.run(cmd, capture_output=True, text=True)
            
            if res.returncode == 0:
                self.processed += 1
                self.folder_processed += 1
                self.log_message("INFO", f"Processed with metadata: {media.name} → {dt.year}/{dt.month:02d}", progress=progress)
            else:
                self.copied_only += 1
                self.folder_copied_only += 1
                if hasattr(self, 'copied_only_files'):
                    self.copied_only_files.append(str(media))
                # Update modified time for copied only files (even for writable formats)
                try:
                    pacific_dt = datetime.fromtimestamp(int(ts), tz=UTC).astimezone(PACIFIC)
                    mod_time = pacific_dt.timestamp()
                    import os
                    os.utime(target, (mod_time, mod_time))
                    self.log_message("WARNING", f"Updated modified date only (metadata embedding failed): {media.name} → {dt.year}/{dt.month:02d}", progress=progress)
                except Exception as e:
                    self.log_message("WARNING", f"Copied only (metadata embedding failed): {media.name} → {dt.year}/{dt.month:02d}", progress=progress)
        else:
            # Unknown format - try to embed metadata but don't fail if it doesn't work
            cmd = self._build_cmd(meta, target)
            res = subprocess.run(cmd, capture_output=True, text=True)
            
            if res.returncode == 0:
                self.processed += 1
                self.folder_processed += 1
                self.log_message("INFO", f"Processed with metadata: {media.name} → {dt.year}/{dt.month:02d}", progress=progress)
            else:
                self.copied_only += 1
                self.folder_copied_only += 1
                if hasattr(self, 'copied_only_files'):
                    self.copied_only_files.append(str(media))
                # Update modified time for copied only files (unknown formats)
                try:
                    pacific_dt = datetime.fromtimestamp(int(ts), tz=UTC).astimezone(PACIFIC)
                    mod_time = pacific_dt.timestamp()
                    import os
                    os.utime(target, (mod_time, mod_time))
                    self.log_message("INFO", f"Updated modified date for copied only file: {media.name} → {dt.year}/{dt.month:02d}", progress=progress)
                except Exception as e:
                    self.log_message("WARNING", f"Failed to update modified date for {media.name}: {e}", progress=progress)
                self.log_message("INFO", f"Copied only (metadata not supported): {media.name} → {dt.year}/{dt.month:02d}", progress=progress)

    def _process_folder(self, year_folder: Path, process_files_set=None):
        from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
        # Use self.console for both progress and logging
        json_files = list(year_folder.rglob("*.json"))
        media_files = [p for p in year_folder.rglob("*") if p.suffix.lower() in self.MEDIA_EXTS]

        # If process_files_set is specified, filter media_files by file name only
        if process_files_set is not None:
            media_files = [p for p in media_files if p.name in process_files_set]

        # Track copied only files for this folder
        self.copied_only_files = []

        self._reset_folder_stats()

        total_files = len(media_files)
        year_str = None
        m = re.match(r"^Photos from (\d{4})$", year_folder.name, re.IGNORECASE)
        if m:
            year_str = m.group(1)
        if year_str:
            self.console.print(f"\nProcessing {year_str}....")

        # Custom logging handler for rich Console
        class RichLoggingHandler(logging.Handler):
            def emit(self, record):
                msg = self.format(record)
                self.console.print(msg)
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        logging.basicConfig(handlers=[RichLoggingHandler()], level=logging.INFO, format='%(asctime)s %(levelname)s | %(message)s', force=True)

        progress_label = f"{year_str} Processing" if year_str else "Processing"
        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.1f}%",
            "{task.completed}/{task.total}",
            TimeRemainingColumn(),
            console=self.console,
            transient=False
        ) as progress:
            task = progress.add_task(progress_label, total=total_files)
            for media in media_files:
                matches = self._match_json(media, json_files)
                if len(matches) == 1:
                    self._process_file(media, matches[0], progress=progress)
                else:
                    self.skipped.append(str(media))
                    self.folder_skipped += 1
                    self.log_message("WARNING", f"Skip {media.name} (no or multi JSON)", progress=progress)
                progress.update(task, advance=1)

    # ---------- run ----------
    def run(self):
        self._setup_logging()
        if shutil.which("exiftool") is None:
            self.log_message("ERROR", "ExifTool not found in PATH")
            return 1

        self.out_base.mkdir(parents=True, exist_ok=True)

        # Track skipped and copied only files per year
        skipped_by_year = {}
        copied_only_by_year = {}

        for yf in self._year_folders():
            self.log_message("INFO", "==============================")
            self.log_message("INFO", f"START PROCESSING YEAR FOLDER: {yf.name}")
            self.log_message("INFO", "==============================")
            # Extract year from folder name
            m = re.match(r"^Photos from (\d{4})$", yf.name, re.IGNORECASE)
            year = m.group(1) if m else None

            # If skipped_files_folder is specified, check for YYYY_skipped_files.txt
            process_files_set = None
            if hasattr(self, '_skipped_files_folder') and self._skipped_files_folder and year:
                skipped_file_path = self._skipped_files_folder / f"{year}_skipped_files.txt"
                if not skipped_file_path.exists():
                    self.log_message("INFO", f"Skipped file list {skipped_file_path} not found. Skipping folder {yf.name}.")
                    continue
                # Read only file names from the skipped file list
                with open(skipped_file_path, 'r', encoding='utf-8') as f:
                    process_files_set = set(Path(line.strip()).name for line in f if line.strip())

            # Clear skipped and copied only for each year folder
            self.skipped = []
            self.copied_only_files = []
            self._reset_folder_stats()
            self._process_folder(yf, process_files_set)
            if year:
                if self.skipped:
                    skipped_by_year[year] = list(self.skipped)
                    # Write per-year skipped file
                    skipped_path = self.base / f"{year}_skipped_files.txt"
                    skipped_path.write_text("\n".join(self.skipped), encoding="utf-8")
                    self.log_message("INFO", f"Skipped list written to {skipped_path}")
                if self.copied_only_files:
                    copied_only_by_year[year] = list(self.copied_only_files)
                    copied_only_path = self.base / f"{year}_copied_only.txt"
                    copied_only_path.write_text("\n".join(self.copied_only_files), encoding="utf-8")
                    self.log_message("INFO", f"Copied only list written to {copied_only_path}")
                self.log_message("INFO", f"YEAR {year} SUMMARY:")
                self.log_message("INFO", f"  Processed with metadata: {self.folder_processed}")
                self.log_message("INFO", f"  Copied only: {self.folder_copied_only}")
                self.log_message("INFO", f"  Skipped: {self.folder_skipped}")
                for rule_num in range(1, 9):
                    self.log_message("INFO", f"  Rule {rule_num} matches: {self.folder_rule_counts.get(rule_num, 0)}")
        total_skipped = sum(len(v) for v in skipped_by_year.values())
        total_copied_only = sum(len(v) for v in copied_only_by_year.values())
        self.log_message("INFO", f"COMPLETED PROCESSING. Total processed with metadata={self.processed}  Copied only (no metadata update)={self.copied_only}  Skipped={total_skipped}")

        return 0

# ---------- CLI ----------

def main():
    if len(sys.argv) == 1:
        print("""
Google Photos Takeout EXIF Processor (Pacific-Time Version)

Usage:
    python google_photos_processor.py <takeout_folder> [-o <output_folder>] [--skipped_files <skipped_files_folder>]

Arguments:
    <takeout_folder>         Path to Google Photos takeout folder
    -o, --output            Path to output folder (default: <takeout_folder>/processed)
    --skipped_files         Path to folder containing per-year skipped files txt to retry.
""")
        sys.exit(1)
    ap = argparse.ArgumentParser()
    ap.add_argument("input_path", help="Google Photos takeout folder")
    ap.add_argument("-o", "--output", help="Output folder")
    ap.add_argument("--skipped_files", help="Path to folder containing per-year skipped files txt")
    args = ap.parse_args()
    base = Path(args.input_path).expanduser().resolve()
    output = Path(args.output).expanduser().resolve() if args.output else None
    skipped_files_folder = Path(args.skipped_files).expanduser().resolve() if args.skipped_files else None
    if skipped_files_folder and base == skipped_files_folder:
        print("Error: input_path and skipped_files folder cannot be the same.")
        sys.exit(1)
    proc = GooglePhotosProcessor(base, output)
    proc._skipped_files_folder = skipped_files_folder
    sys.exit(proc.run())

if __name__ == "__main__":
    main()