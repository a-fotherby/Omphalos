"""Unit tests for omphalos/run.py."""

from unittest.mock import Mock

import pytest

# omphalos.run imports omphalos.settings, which install.sh creates from settings_default.py and
# which is not tracked, so skip these tests where it is absent.
run = pytest.importorskip(
    'omphalos.run',
    reason='requires omphalos/settings.py (created by install.sh)',
)


class TestCrunchTopeErrorPatterns:
    """Tests for the CrunchTope stdout error patterns."""

    def test_missing_input_file_is_an_error_pattern(self):
        """Test that CrunchTope losing the input file is treated as an error.

        CrunchTope truncates long input file paths and then waits on stdin, which would otherwise
        burn the whole timeout before the run was recorded as failed.
        """
        assert 'Cannot find input file' in run.CT_ERROR_PATTERNS

    @pytest.mark.parametrize('pattern', run.CT_ERROR_PATTERNS)
    def test_error_pattern_sets_error_code_and_skips_parsing(self, pattern, tmp_path, monkeypatch):
        """Test that a matched error pattern flags the run and skips output parsing."""
        # pexpect's expect() returns the index into [EOF, TIMEOUT] + CT_ERROR_PATTERNS.
        error_code = run.CT_ERROR_PATTERNS.index(pattern) + 2
        process = Mock()
        process.expect.return_value = error_code
        monkeypatch.setattr(run.pexp, 'spawn', Mock(return_value=process))

        input_file = Mock()
        input_file.path = tmp_path / 'test.in'

        run.crunchtope(input_file, 0, 10, tmp_path)

        assert input_file.error_code == error_code
        input_file.get_results.assert_not_called()

    def test_successful_run_parses_results(self, tmp_path, monkeypatch):
        """Test that reaching EOF without an error pattern parses the outputs."""
        process = Mock()
        process.expect.return_value = 0        # pexpect.EOF
        monkeypatch.setattr(run.pexp, 'spawn', Mock(return_value=process))

        input_file = Mock()
        input_file.path = tmp_path / 'test.in'

        run.crunchtope(input_file, 0, 10, tmp_path)

        input_file.get_results.assert_called_once()

    def test_timeout_sets_error_code(self, tmp_path, monkeypatch):
        """Test that a timeout flags the run and skips output parsing."""
        process = Mock()
        process.expect.return_value = 1        # pexpect.TIMEOUT
        monkeypatch.setattr(run.pexp, 'spawn', Mock(return_value=process))

        input_file = Mock()
        input_file.path = tmp_path / 'test.in'

        run.crunchtope(input_file, 0, 10, tmp_path)

        assert input_file.error_code == 1
        input_file.get_results.assert_not_called()
