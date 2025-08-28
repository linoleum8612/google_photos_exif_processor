def get_rule_description(index: int) -> str:
    """Return the description for a given rule index."""
    return RULE_DESCRIPTIONS.get(index, "")
def get_total_rule_count():
    """Return the total number of matching rules."""
    return len(RULE_DESCRIPTIONS)

RULE_DESCRIPTIONS = {
    1: "direct",
    2: "truncated",
    3: "parenthetical",
    4: "-edited",
    5: "live photos",
    6: "live photos duplicates",
    7: "via JSON title",
    8: "filename*.json"
}
import re
import json
from pathlib import Path

def load_json(path: Path, log_func=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        if log_func:
            log_func("WARNING", f"Could not parse {path}: {e}")
        return None

def match_json(media: Path, json_files: list[Path], log_func=None, rule_counts=None, json_length_limit=50):
    name = media.name
    # Rule 1 - Direct match (filename.ext*.json)
    rule_index = 1
    pattern = re.compile(rf"^{re.escape(name)}.*\.json$", re.IGNORECASE)
    for j in json_files:
        if pattern.match(j.name):
            desc = RULE_DESCRIPTIONS.get(rule_index, "")
            if log_func: log_func("INFO", f"JSON match - Rule {rule_index} ({desc}): {name} → {j.name}")
            if rule_counts is not None: rule_counts[rule_index] = rule_counts.get(rule_index, 0) + 1
            return [j]
    # Rule 2 - Truncated match
    rule_index = 2
    if len(name + ".json") > json_length_limit:
        trunc = name[: json_length_limit - 5]
        for j in json_files:
            if j.name.lower().startswith(trunc.lower()):
                desc = RULE_DESCRIPTIONS.get(rule_index, "")
                if log_func: log_func("INFO", f"JSON match - Rule {rule_index} ({desc}): {name} → {j.name}")
                if rule_counts is not None: rule_counts[rule_index] = rule_counts.get(rule_index, 0) + 1
                return [j]
    # Rule 3 - Relaxed parenthetical match
    rule_index = 3
    m = re.match(r"^(.+)\((\d+)\)(\.[^.]+)$", name)
    if m:
        base = m.group(1)
        num = m.group(2)
        ext = m.group(3)
        pattern = re.compile(rf"^{re.escape(base)}{re.escape(ext)}.*\({num}\)\.json$", re.IGNORECASE)
        for j in json_files:
            if pattern.match(j.name):
                desc = RULE_DESCRIPTIONS.get(rule_index, "")
                if log_func: log_func("INFO", f"JSON match - Rule {rule_index} ({desc}): {name} → {j.name}")
                if rule_counts is not None: rule_counts[rule_index] = rule_counts.get(rule_index, 0) + 1
                return [j]
    # Rule 4 - Remove '-edited' from filename if present
    rule_index = 4
    edited_match = re.match(r"^(.*)-edited(\.[^.]+)$", name, re.IGNORECASE)
    if edited_match:
        base_name = edited_match.group(1) + edited_match.group(2)
        pattern = re.compile(rf"^{re.escape(base_name)}.*\.json$", re.IGNORECASE)
        for j in json_files:
            if pattern.match(j.name):
                desc = RULE_DESCRIPTIONS.get(rule_index, "")
                if log_func: log_func("INFO", f"JSON match - Rule {rule_index} ({desc}): {name} → {j.name}")
                if rule_counts is not None: rule_counts[rule_index] = rule_counts.get(rule_index, 0) + 1
                return [j]
    # Rule 5 - Live photos
    rule_index = 5
    if name.lower().endswith('.mp4'):
        base_name = name[:-4]
        for j in json_files:
            if j.name.lower().startswith(base_name.lower()) and j.name.lower().endswith('.json'):
                desc = RULE_DESCRIPTIONS.get(rule_index, "")
                if log_func: log_func("INFO", f"JSON match - Rule {rule_index} ({desc}): {name} → {j.name}")
                if rule_counts is not None: rule_counts[rule_index] = rule_counts.get(rule_index, 0) + 1
                return [j]
    # Rule 6 - Live photos duplicates
    rule_index = 6
    m = re.match(r"^(.+)\(\d+\)\.mp4$", name, re.IGNORECASE)
    if m:
        base_name = m.group(1)
        for j in json_files:
            if j.name.lower().startswith(base_name.lower()) and j.name.lower().endswith('.json'):
                desc = RULE_DESCRIPTIONS.get(rule_index, "")
                if log_func: log_func("INFO", f"JSON match - Rule {rule_index} ({desc}): {name} → {j.name}")
                if rule_counts is not None: rule_counts[rule_index] = rule_counts.get(rule_index, 0) + 1
                return [j]
    # Rule 7 - JSON Title field
    rule_index = 7
    for j in json_files:
        data = load_json(j, log_func)
        if data and data.get("title") == name:
            desc = RULE_DESCRIPTIONS.get(rule_index, "")
            if log_func: log_func("INFO", f"JSON match - Rule {rule_index} ({desc}): {name} → {j.name}")
            if rule_counts is not None: rule_counts[rule_index] = rule_counts.get(rule_index, 0) + 1
            return [j]
    # Rule 8 - filename.ext to filename*.json
    rule_index = 8
    ext_match = re.match(r"^(.*)(\.[^.]+)$", name, re.IGNORECASE)
    if ext_match:
        base_name = ext_match.group(1)
        pattern = re.compile(rf"^{re.escape(base_name)}.*\.json$", re.IGNORECASE)
        for j in json_files:
            if pattern.match(j.name):
                desc = RULE_DESCRIPTIONS.get(rule_index, "")
                if log_func: log_func("INFO", f"JSON match - Rule {rule_index} ({desc}): {name} → {j.name}")
                if rule_counts is not None: rule_counts[rule_index] = rule_counts.get(rule_index, 0) + 1
                return [j]
    return []
