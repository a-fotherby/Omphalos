"""Unit tests for coeus/helper.py."""

import types

import numpy as np
import pytest

from coeus.helper import filter_errors, map_smalls


def _entry(error_code):
    obj = types.SimpleNamespace()
    obj.error_code = error_code
    return obj


class TestFilterErrors:
    def test_all_clean_returns_all(self, capsys):
        dataset = {0: _entry(0), 1: _entry(0), 2: _entry(0)}
        result, errors = filter_errors(dataset)
        assert len(result) == 3
        assert len(errors) == 0

    def test_all_errors_returns_empty_dataset(self, capsys):
        dataset = {0: _entry(1), 1: _entry(2)}
        result, errors = filter_errors(dataset)
        assert len(result) == 0
        assert len(errors) == 2

    def test_mixed_separates_correctly(self, capsys):
        dataset = {0: _entry(0), 1: _entry(1), 2: _entry(0)}
        result, errors = filter_errors(dataset)
        assert set(result.keys()) == {0, 2}
        assert set(errors.keys()) == {1}

    def test_error_entry_moved_to_errors_dict(self, capsys):
        dataset = {0: _entry(0), 1: _entry(3)}
        result, errors = filter_errors(dataset)
        assert errors[1].error_code == 3
        assert 1 not in result

    def test_returns_same_dataset_object(self, capsys):
        dataset = {0: _entry(0)}
        result, errors = filter_errors(dataset)
        assert result is dataset

    def test_single_error_entry(self, capsys):
        dataset = {0: _entry(2)}
        result, errors = filter_errors(dataset)
        assert len(result) == 0
        assert 0 in errors


class TestMapSmalls:
    def test_valid_numeric_array_returned_unchanged(self):
        x = np.array([1.0, 2.5, 0.0])
        result = map_smalls(x)
        assert result is x

    def test_non_castable_object_array_returns_zero(self):
        x = np.array(['abc', 'xyz'], dtype=object)
        result = map_smalls(x)
        assert result == 0

    def test_integer_array_returned_unchanged(self):
        x = np.array([1, 2, 3])
        result = map_smalls(x)
        assert result is x
