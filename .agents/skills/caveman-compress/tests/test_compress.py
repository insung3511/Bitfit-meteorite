from __future__ import annotations

import io
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from scripts import cli, compress, validate  # noqa: E402


class CompressSafetyTests(unittest.TestCase):
    def test_backup_identity_uses_full_canonical_path(self):
        with tempfile.TemporaryDirectory() as root:
            first = Path(root) / "one" / "shared" / "notes.md"
            second = Path(root) / "two" / "shared" / "notes.md"
            self.assertNotEqual(
                compress.backup_path_for(first), compress.backup_path_for(second)
            )

    def test_sensitive_symlink_name_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "notes.md"
            link = Path(root) / "credentials.md"
            target.write_text("ordinary text", encoding="utf-8")
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(ValueError, "sensitive"):
                compress.compress_file(link)

    def test_cli_preserves_sensitive_symlink_name(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "notes.md"
            link = Path(root) / "credentials.md"
            target.write_text("ordinary natural language", encoding="utf-8")
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlinks unavailable")

            output = io.StringIO()
            with (
                mock.patch.object(sys, "argv", ["caveman", str(link)]),
                mock.patch.object(cli, "detect_file_type", return_value="markdown"),
                mock.patch.object(cli, "should_compress", return_value=True),
                redirect_stdout(output),
                self.assertRaises(SystemExit) as raised,
            ):
                cli.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertIn("sensitive", output.getvalue())
            self.assertEqual(target.read_text(encoding="utf-8"), "ordinary natural language")

    def test_retry_preserves_frontmatter_and_byte_exact_backup(self):
        original = (
            b"---\r\nsecret: keep\r\n---\r\n"
            b"# Heading\r\nVisit https://example.com/a_(b).\r\nNatural language here.\r\n"
        )
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "notes.md"
            source.write_bytes(original)
            responses = [
                "# Heading\nNatural shorter.",
                "# Heading\nVisit https://example.com/a_(b).\nShort.",
            ]
            with (
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(root_path / "data")}),
                mock.patch.object(compress, "should_compress", return_value=True),
                mock.patch.object(compress, "call_claude", side_effect=responses) as call,
            ):
                self.assertTrue(compress.compress_file(source))
                backup = compress.backup_path_for(source)

            self.assertEqual(backup.read_bytes(), original)
            output = source.read_bytes()
            self.assertTrue(output.startswith(b"---\r\nsecret: keep\r\n---\r\n"))
            self.assertEqual(call.call_count, 2)
            self.assertNotIn("secret: keep", call.call_args_list[0].args[0])
            self.assertNotIn("secret: keep", call.call_args_list[1].args[0])

    def test_validation_exception_restores_original_bytes_and_mode(self):
        original = b"# Heading\nNatural language that should remain intact.\n"
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "notes.md"
            source.write_bytes(original)
            source.chmod(0o640)
            with (
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(root_path / "data")}),
                mock.patch.object(compress, "should_compress", return_value=True),
                mock.patch.object(compress, "call_claude", return_value="# Heading\nShort."),
                mock.patch.object(compress, "validate", side_effect=RuntimeError("validator failed")),
                self.assertRaisesRegex(RuntimeError, "validator failed"),
            ):
                compress.compress_file(source)

            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o640)
            self.assertFalse(compress.backup_path_for(source).exists())

    def test_retry_exception_restores_original(self):
        original = b"# Heading\nNatural language that should remain intact.\n"
        invalid = mock.Mock(is_valid=False, errors=["URL mismatch"])
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "notes.md"
            source.write_bytes(original)
            with (
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(root_path / "data")}),
                mock.patch.object(compress, "should_compress", return_value=True),
                mock.patch.object(
                    compress,
                    "call_claude",
                    side_effect=["# Heading\nShort.", RuntimeError("retry failed")],
                ),
                mock.patch.object(compress, "validate", return_value=invalid),
                self.assertRaisesRegex(RuntimeError, "retry failed"),
            ):
                compress.compress_file(source)

            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(compress.backup_path_for(source).exists())

    @unittest.skipIf(os.name == "nt", "POSIX permission bits required")
    def test_backup_permissions_are_private_and_source_mode_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "notes.md"
            source.write_text("# Heading\nNatural language here.\n", encoding="utf-8")
            source.chmod(0o640)
            with (
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(root_path / "data")}),
                mock.patch.object(compress, "should_compress", return_value=True),
                mock.patch.object(compress, "call_claude", return_value="# Heading\nShort."),
            ):
                self.assertTrue(compress.compress_file(source))
                backup = compress.backup_path_for(source)

            self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o640)
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(backup.parent.stat().st_mode), 0o700)


class ValidatorTests(unittest.TestCase):
    def _validate_text(self, original: str, compressed: str):
        with tempfile.TemporaryDirectory() as root:
            original_path = Path(root) / "original.md"
            compressed_path = Path(root) / "compressed.md"
            original_path.write_text(original, encoding="utf-8")
            compressed_path.write_text(compressed, encoding="utf-8")
            return validate.validate(original_path, compressed_path)

    def test_parenthesized_duplicate_urls_and_multibacktick_code(self):
        text = (
            "# H\n"
            "https://example.com/a_(b) and https://example.com/a_(b)\n"
            "Use ``value with ` inside``.\n"
        )
        self.assertTrue(self._validate_text(text, text).is_valid)
        missing = text.replace(" and https://example.com/a_(b)", "")
        self.assertFalse(self._validate_text(text, missing).is_valid)

    def test_terminal_url_punctuation_is_preserved(self):
        for suffix in ("!", ")", "]", "}"):
            with self.subTest(suffix=suffix):
                original = f"# H\nhttps://example.com/search?q=x{suffix}\n"
                compressed = "# H\nhttps://example.com/search?q=x\n"
                result = self._validate_text(original, compressed)
                self.assertFalse(result.is_valid)
                self.assertTrue(any("URL" in error for error in result.errors))

    def test_unclosed_fence_is_validated_through_eof(self):
        original = "# H\n```python\nprint('one')\n"
        compressed = "# H\n```python\nprint('two')\n"
        result = self._validate_text(original, compressed)
        self.assertFalse(result.is_valid)
        self.assertIn("Code blocks", " ".join(result.errors))

    def test_indented_code_blocks_are_compared_exactly(self):
        original = "# H\n\n    echo one\n    echo two\n"
        compressed = "# H\n\n    echo one\n    echo changed\n"
        result = self._validate_text(original, compressed)
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Code blocks" in error for error in result.errors))

    def test_commands_after_markdown_container_prefixes_are_preserved(self):
        original = (
            "- $ python tool.py ./input.md\n"
            "2. npm run build\n"
            "> git status\n"
        )
        unchanged = (
            "* $ python tool.py ./input.md\n"
            "1. npm run build\n"
            "> git status\n"
        )
        self.assertTrue(self._validate_text(original, unchanged).is_valid)

        changed = unchanged.replace("npm run build", "npm run deploy")
        result = self._validate_text(original, changed)
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Command" in error for error in result.errors))

    def test_task_list_and_make_commands_are_preserved(self):
        original = "- [ ] npm run build\n> make build\n"
        compressed = "- [ ] npm run deploy\n> make clean\n"
        result = self._validate_text(original, compressed)
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Command" in error for error in result.errors))

    def test_headings_paths_and_commands_are_errors(self):
        original = "# Exact\npython tool.py ./input/file.md\n"
        compressed = "# Changed\npython other.py ./other/file.md\n"
        result = self._validate_text(original, compressed)
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Headings" in error for error in result.errors))
        self.assertTrue(any("Path" in error for error in result.errors))
        self.assertTrue(any("Command" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
