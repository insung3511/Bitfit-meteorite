#!/usr/bin/env python3
import re
from collections import Counter
from pathlib import Path

URL_CANDIDATE_REGEX = re.compile(r"https?://\S+")
FENCE_OPEN_REGEX = re.compile(r"^(\s{0,3})(`{3,}|~{3,})(.*)$")
HEADING_REGEX = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)
BULLET_REGEX = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
PATH_REGEX = re.compile(r"(?:\./|\.\./|/|[A-Za-z]:\\)[\w\-/\\\.]+|[\w\-\.]+[/\\][\w\-/\\\.]+")
COMMAND_REGEX = re.compile(
    r"^[ \t]*(?:(?:>[ \t]*)|(?:(?:[-*+]|\d+[.)])[ \t]+)(?:\[[ xX]\][ \t]+)?)*"
    r"((?:\$\s+|(?:python(?:3)?|pip(?:3)?|npm|pnpm|yarn|git|docker|kubectl|curl|uvicorn|make)\s+).+)$",
    re.MULTILINE,
)
INDENTED_CODE_REGEX = re.compile(r"^(?: {4}|\t)")


class ValidationResult:
    def __init__(self):
        self.is_valid = True
        self.errors = []
        self.warnings = []

    def add_error(self, msg):
        self.is_valid = False
        self.errors.append(msg)

    def add_warning(self, msg):
        self.warnings.append(msg)


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_headings(text):
    return [(level, title.strip()) for level, title in HEADING_REGEX.findall(text)]


def extract_code_blocks(text):
    """Extract fenced and indented blocks, including fences continuing to EOF."""
    blocks = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        match = FENCE_OPEN_REGEX.match(lines[i])
        if match:
            fence_char = match.group(2)[0]
            fence_len = len(match.group(2))
            block_lines = [lines[i]]
            i += 1
            while i < len(lines):
                close = FENCE_OPEN_REGEX.match(lines[i])
                block_lines.append(lines[i])
                i += 1
                if (
                    close
                    and close.group(2)[0] == fence_char
                    and len(close.group(2)) >= fence_len
                    and close.group(3).strip() == ""
                ):
                    break
            blocks.append("\n".join(block_lines))
            continue

        if INDENTED_CODE_REGEX.match(lines[i]):
            block_lines = [lines[i]]
            i += 1
            while i < len(lines) and (
                INDENTED_CODE_REGEX.match(lines[i]) or not lines[i].strip()
            ):
                block_lines.append(lines[i])
                i += 1
            while block_lines and not block_lines[-1].strip():
                block_lines.pop()
            blocks.append("\n".join(block_lines))
            continue

        i += 1
    return blocks


def _outside_fences(text):
    lines = text.split("\n")
    result = []
    fence_char = None
    fence_len = 0
    for line in lines:
        match = FENCE_OPEN_REGEX.match(line)
        if fence_char is None:
            if match:
                fence_char = match.group(2)[0]
                fence_len = len(match.group(2))
                result.append("")
            else:
                result.append(line)
        else:
            result.append("")
            if (
                match
                and match.group(2)[0] == fence_char
                and len(match.group(2)) >= fence_len
                and match.group(3).strip() == ""
            ):
                fence_char = None
                fence_len = 0
    return "\n".join(result)


def _balanced_url(candidate):
    # Every non-whitespace character can be URL data. Preserve candidate exactly;
    # conservative false positives are safer than accepting a changed URL.
    return candidate


def extract_urls(text):
    return Counter(_balanced_url(match.group(0)) for match in URL_CANDIDATE_REGEX.finditer(text))


def extract_paths(text):
    return Counter(PATH_REGEX.findall(_outside_fences(text)))


def extract_commands(text):
    return Counter(command.strip() for command in COMMAND_REGEX.findall(_outside_fences(text)))


def count_bullets(text):
    return len(BULLET_REGEX.findall(text))


def extract_inline_codes(text):
    """Parse inline code spans with arbitrary backtick delimiter lengths."""
    spans = []
    source = _outside_fences(text)
    index = 0
    while index < len(source):
        if source[index] != "`":
            index += 1
            continue
        end = index
        while end < len(source) and source[end] == "`":
            end += 1
        delimiter = source[index:end]
        close = source.find(delimiter, end)
        if close < 0:
            index = end
            continue
        spans.append(source[end:close])
        index = close + len(delimiter)
    return spans


def _validate_counter(name, original, compressed, result):
    if original != compressed:
        result.add_error(
            f"{name} mismatch: lost={original - compressed}, added={compressed - original}"
        )


def validate_headings(orig, comp, result):
    original = extract_headings(orig)
    compressed = extract_headings(comp)
    if original != compressed:
        result.add_error(f"Headings changed: expected={original}, actual={compressed}")


def validate_code_blocks(orig, comp, result):
    if extract_code_blocks(orig) != extract_code_blocks(comp):
        result.add_error("Code blocks not preserved exactly")


def validate_urls(orig, comp, result):
    _validate_counter("URL", extract_urls(orig), extract_urls(comp), result)


def validate_paths(orig, comp, result):
    _validate_counter("Path", extract_paths(orig), extract_paths(comp), result)


def validate_commands(orig, comp, result):
    _validate_counter("Command", extract_commands(orig), extract_commands(comp), result)


def validate_bullets(orig, comp, result):
    original = count_bullets(orig)
    compressed = count_bullets(comp)
    if original and abs(original - compressed) / original > 0.15:
        result.add_warning(f"Bullet count changed too much: {original} -> {compressed}")


def validate_inline_codes(orig, comp, result):
    _validate_counter(
        "Inline code", Counter(extract_inline_codes(orig)), Counter(extract_inline_codes(comp)), result
    )


def validate(original_path: Path, compressed_path: Path) -> ValidationResult:
    result = ValidationResult()
    orig = read_file(original_path)
    comp = read_file(compressed_path)
    validate_headings(orig, comp, result)
    validate_code_blocks(orig, comp, result)
    validate_urls(orig, comp, result)
    validate_paths(orig, comp, result)
    validate_commands(orig, comp, result)
    validate_bullets(orig, comp, result)
    validate_inline_codes(orig, comp, result)
    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python validate.py <original> <compressed>")
        sys.exit(1)
    res = validate(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
    print(f"\nValid: {res.is_valid}")
    if res.errors:
        print("\nErrors:")
        for error in res.errors:
            print(f"  - {error}")
    if res.warnings:
        print("\nWarnings:")
        for warning in res.warnings:
            print(f"  - {warning}")
    sys.exit(0 if res.is_valid else 2)
