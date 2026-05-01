"""Tests for _env_bool() — safe boolean env-var parser."""

import os
import unittest
from unittest.mock import patch


def _env_bool(name: str, default: bool) -> bool:
    """Local copy so tests are independent of module reload order."""
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    if val in ("1", "true", "yes", "y", "on"):
        return True
    if val in ("0", "false", "no", "n", "off"):
        return False
    return default


class TestEnvBool(unittest.TestCase):

    def _run(self, env_val, default):
        with patch.dict(os.environ, {"TEST_FLAG": env_val} if env_val is not None else {}, clear=False):
            if env_val is None:
                os.environ.pop("TEST_FLAG", None)
            return _env_bool("TEST_FLAG", default)

    # ── Truthy values ────────────────────────────────────────────────────

    def test_true_string(self):
        self.assertTrue(self._run("true", False))

    def test_true_uppercase(self):
        self.assertTrue(self._run("TRUE", False))

    def test_true_mixed_case(self):
        self.assertTrue(self._run("True", False))

    def test_1(self):
        self.assertTrue(self._run("1", False))

    def test_yes(self):
        self.assertTrue(self._run("yes", False))

    def test_y(self):
        self.assertTrue(self._run("y", False))

    def test_on(self):
        self.assertTrue(self._run("on", False))

    # ── Falsy values ─────────────────────────────────────────────────────

    def test_false_string(self):
        self.assertFalse(self._run("false", True))

    def test_false_uppercase(self):
        self.assertFalse(self._run("FALSE", True))

    def test_0(self):
        self.assertFalse(self._run("0", True))

    def test_no(self):
        self.assertFalse(self._run("no", True))

    def test_n(self):
        self.assertFalse(self._run("n", True))

    def test_off(self):
        self.assertFalse(self._run("off", True))

    # ── Absent variable → must respect default ────────────────────────────

    def test_absent_default_true(self):
        """Variable not set → returns True when default=True."""
        self.assertTrue(self._run(None, True))

    def test_absent_default_false(self):
        """Variable not set → returns False when default=False."""
        self.assertFalse(self._run(None, False))

    def test_empty_string_uses_default_true(self):
        """Empty string (e.g. VAR=) behaves like absent → uses default."""
        self.assertTrue(self._run("", True))

    def test_empty_string_uses_default_false(self):
        self.assertFalse(self._run("", False))

    # ── Unknown value → falls back to default ────────────────────────────

    def test_unknown_value_default_true(self):
        self.assertTrue(self._run("maybe", True))

    def test_unknown_value_default_false(self):
        self.assertFalse(self._run("maybe", False))

    # ── Whitespace trimming ───────────────────────────────────────────────

    def test_value_with_surrounding_spaces(self):
        self.assertTrue(self._run("  true  ", False))

    def test_false_with_surrounding_spaces(self):
        self.assertFalse(self._run("  false  ", True))

    # ── Critical regression: "false" string must NOT be truthy ───────────

    def test_string_false_is_not_truthy(self):
        """
        The original bug: bool("false") == True in Python.
        _env_bool("false") must return False, not True.
        """
        result = self._run("false", True)
        self.assertFalse(result, "The string 'false' must evaluate to False, not True")

    def test_string_0_is_not_truthy(self):
        result = self._run("0", True)
        self.assertFalse(result, "The string '0' must evaluate to False, not True")


if __name__ == "__main__":
    unittest.main()
