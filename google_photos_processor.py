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

DEFAULT_TZ = "America/Los_Angeles"
UTC = ZoneInfo("UTC")

class GooglePhotosProcessor:
    def __init__(self, base: Path, output: Path | None, time_zone: str = DEFAULT_TZ):
        self.base = base
        self.out_base = output if output else base / "processed"
        self.skipped: list[str] = []
        self.processed = 0
        self.copied_only = 0  # Files copied without metadata embedding
        self.time_zone = ZoneInfo(time_zone)
        # For per-folder stats
        self._reset_folder_stats()

    def _reset_folder_stats(self):
        from json_matcher import get_total_rule_count
        self.folder_processed = 0
        self.folder_copied_only = 0
        self.folder_skipped = 0
        num_rules = get_total_rule_count()
        self.folder_rule_counts = {i: 0 for i in range(1, num_rules + 1)}
    JSON_LENGTH_LIMIT = 50  # Max length of JSON filename (incl. .json)
    
    # Formats that ExifTool can write metadata to
    WRITABLE_FORMATS = {
        ".360", ".3g2", ".3gp", ".aax", ".ai", ".arq", ".arw", ".avif",
        ".cr2", ".cr3", ".crm", ".crw", ".cs1", ".dcp", ".dng", ".dr4",
        ".dvb", ".eps", ".erf", ".exif", ".exv", ".f4a", ".f4v", ".fff",
        ".flif", ".gif", ".glv", ".gpr", ".hdp", ".heic", ".heif", ".icc",
        ".iiq", ".ind", ".insp", ".jng", ".jp2", ".jpeg", ".jpg", ".jxl",
        ".lrv", ".m4a", ".m4v", ".mef", ".mie", ".mng", ".mos", ".mov",
        ".mp4", ".mpo", ".mqv", ".mrw", ".nef", ".nksc", ".nrw", ".orf",
        ".ori", ".pbm", ".pdf", ".pef", ".pgm", ".png", ".ppm", ".ps",
        ".psb", ".psd", ".qtif", ".raf", ".raw", ".rw2", ".rwl", ".sr2",
        ".srw", ".thm", ".tif", ".tiff", ".vrd", ".wdp", ".webp", ".x3f",
        ".xmp"
    }

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
    def _json_time_to_local(self, ts: str | int) -> str:
        """Convert Unix-timestamp-in-UTC → formatted local-time string."""
        try:
            dt_utc = datetime.fromtimestamp(int(ts), tz=UTC)
            dt_local = dt_utc.astimezone(self.time_zone)
            return dt_local.strftime("%Y:%m:%d %H:%M:%S")
        except Exception:
            return ""

    # ---------- folder discovery ----------
    def _year_folders(self):
        pat = re.compile(r"^Photos from (\d{4})$", re.IGNORECASE)
        for p in self.base.iterdir():
            if p.is_dir() and pat.match(p.name):
                yield p


    # ---------- exiftool command ----------
    def _build_cmd(self, meta: dict, target_path: Path):
        """Build exiftool command for embedding metadata - FIXED VERSION"""
        # Find exiftool executable (support exiftool(-k).exe and exiftool.exe)
        import shutil
        exiftool_path = shutil.which("exiftool.exe")
        if not exiftool_path:
            if shutil.which("exiftool(-k).exe"):
                raise RuntimeError("Found exiftool(-k).exe, but this version is not supported for scripting. Please rename it to exiftool.exe and try again.")
            raise RuntimeError("ExifTool executable not found. Please ensure exiftool.exe is in your PATH.")
        cmd = [
            exiftool_path,
            "-overwrite_original",
            "-q",
            "-m",
        ]
        
        # Dates
        date_str = ""
        if ts := meta.get("photoTakenTime", {}).get("timestamp"):
            date_str = self._json_time_to_local(ts)
        elif ts := meta.get("creationTime", {}).get("timestamp"):
            date_str = self._json_time_to_local(ts)
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
        from json_matcher import load_json
        meta = load_json(jpath, log_func=self.log_message)
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
        dt = datetime.fromtimestamp(int(ts), tz=UTC).astimezone(self.time_zone)
        target_dir = self.out_base / str(dt.year) / f"{dt.month:02d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / media.name
        # Copy file to destination first
        shutil.copy2(media, target)
        # Check if this format supports metadata writing
        file_ext = media.suffix.lower()
        if file_ext not in self.WRITABLE_FORMATS:
            # For formats that don't support metadata, update modified date using os.utime
            try:
                # Get Pacific time as datetime object
                local_dt = datetime.fromtimestamp(int(ts), tz=UTC).astimezone(self.time_zone)
                # Convert to timestamp (seconds since epoch)
                mod_time = local_dt.timestamp()
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
                # Log ExifTool error output for debugging
                error_output = res.stderr.strip() if res.stderr else "No error output."
                self.log_message("ERROR", f"ExifTool failed for {media.name}: {error_output}", progress=progress)
                # Update modified time for copied only files (even for writable formats)
                try:
                    local_dt = datetime.fromtimestamp(int(ts), tz=UTC).astimezone(self.time_zone)
                    mod_time = local_dt.timestamp()
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
                    local_dt = datetime.fromtimestamp(int(ts), tz=UTC).astimezone(self.time_zone)
                    mod_time = local_dt.timestamp()
                    import os
                    os.utime(target, (mod_time, mod_time))
                    self.log_message("INFO", f"Updated modified date for copied only file: {media.name} → {dt.year}/{dt.month:02d}", progress=progress)
                except Exception as e:
                    self.log_message("WARNING", f"Failed to update modified date for {media.name}: {e}", progress=progress)
                self.log_message("INFO", f"Copied only (metadata not supported): {media.name} → {dt.year}/{dt.month:02d}", progress=progress)

    def _process_folder(self, year_folder: Path, process_files_set=None):
        from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
        from datetime import timedelta
        # Use self.console for both progress and logging
        json_files = list(year_folder.rglob("*.json"))
        media_files = [p for p in year_folder.rglob("*") if p.suffix.lower() != ".json"]

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
        def format_time_remaining(seconds):
            if seconds is None or seconds < 0:
                return "N/A"
            from datetime import timedelta
            return str(timedelta(seconds=int(seconds)))

        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.1f}%",
            TextColumn("| Files processed: {task.completed}/{task.total} | Time remaining: {task.fields[time_fmt]}", justify="left", style="progress.remaining"),
            console=self.console,
            transient=False,
        ) as progress:
            task = progress.add_task(progress_label, total=total_files, time_fmt="N/A")
            from json_matcher import match_json
            for media in media_files:
                matches = match_json(media, json_files, log_func=self.log_message, rule_counts=self.folder_rule_counts)
                if len(matches) == 1:
                    self._process_file(media, matches[0], progress=progress)
                else:
                    self.skipped.append(str(media))
                    self.folder_skipped += 1
                    self.log_message("WARNING", f"Skip {media.name} (no or multi JSON)", progress=progress)
                # Update time remaining field
                current_task = progress.tasks[task]
                progress.update(task, advance=1, time_fmt=format_time_remaining(current_task.time_remaining))

    # ---------- run ----------
    def run(self):
        self._setup_logging()
        # Check for exiftool.exe only
        import shutil
        if not shutil.which("exiftool.exe"):
            if shutil.which("exiftool(-k).exe"):
                self.log_message("ERROR", "Please exiftool(-k).exe, please rename to exiftool.exe and try again.")
            else:
                self.log_message("ERROR", "ExifTool not found in PATH. Please ensure exiftool.exe is available.")
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
                from json_matcher import get_rule_description, get_total_rule_count
                num_rules = get_total_rule_count()
                for rule_num in range(1, num_rules + 1):
                    desc = get_rule_description(rule_num)
                    self.log_message("INFO", f"  Rule {rule_num} ({desc}) match count: {self.folder_rule_counts.get(rule_num, 0)}")
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
    ap.add_argument("--time-zone", default=DEFAULT_TZ, help="Time zone for conversions (default: America/Los_Angeles)")
    args = ap.parse_args()
    base = Path(args.input_path).expanduser().resolve()
    output = Path(args.output).expanduser().resolve() if args.output else None
    skipped_files_folder = Path(args.skipped_files).expanduser().resolve() if args.skipped_files else None
    time_zone = args.time_zone
    if skipped_files_folder and base == skipped_files_folder:
        print("Error: input_path and skipped_files folder cannot be the same.")
        sys.exit(1)
    proc = GooglePhotosProcessor(base, output, time_zone)
    proc._skipped_files_folder = skipped_files_folder
    sys.exit(proc.run())

if __name__ == "__main__":
    main()