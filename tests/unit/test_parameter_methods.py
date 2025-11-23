"""Unit tests for core/parameter_methods.py."""

import numpy as np
import pytest

from core import parameter_methods as pm
from core.parameter_methods import ParameterConfigError


class TestLinspace:
    """Tests for the linspace function."""

    def test_linspace_basic(self):
        """Test basic linspace functionality."""
        result = pm.linspace([1, 10], 10)
        assert len(result) == 10
        assert result[0] == 1.0
        assert result[-1] == 10.0

    def test_linspace_single_value(self):
        """Test linspace with single value (same start and end)."""
        result = pm.linspace([5, 5], 5)
        assert len(result) == 5
        assert all(v == 5.0 for v in result)

    def test_linspace_with_repeats(self):
        """Test linspace with repeat parameter."""
        result = pm.linspace([1, 10, 2], 10)
        assert len(result) == 10
        # With repeats=2, each value should appear twice
        assert result[0] == result[1]
        assert result[2] == result[3]

    def test_linspace_repeats_must_be_factor(self):
        """Test that repeats must be a factor of num_files."""
        with pytest.raises(ParameterConfigError) as exc_info:
            pm.linspace([1, 10, 3], 10)  # 3 is not a factor of 10
        assert "not a factor" in str(exc_info.value)

    def test_linspace_repeats_equal_to_num_files(self):
        """Test linspace when repeats equals num_files (constant)."""
        result = pm.linspace([5, 5, 10], 10)
        assert len(result) == 10
        assert all(v == 5.0 for v in result)

    def test_linspace_negative_values(self):
        """Test linspace with negative values."""
        result = pm.linspace([-10, -1], 10)
        assert result[0] == -10.0
        assert result[-1] == -1.0
        assert np.all(np.diff(result) > 0)  # Values increasing

    def test_linspace_float_bounds(self):
        """Test linspace with float boundaries."""
        result = pm.linspace([0.1, 0.9], 9)
        assert len(result) == 9
        np.testing.assert_almost_equal(result[0], 0.1)
        np.testing.assert_almost_equal(result[-1], 0.9)

    def test_linspace_returns_numpy_array(self):
        """Test that linspace returns a numpy array."""
        result = pm.linspace([1, 10], 10)
        assert isinstance(result, np.ndarray)


class TestRandomUniform:
    """Tests for the random_uniform function."""

    def test_random_uniform_basic(self):
        """Test basic random uniform functionality."""
        result = pm.random_uniform([0, 1], 100)
        assert len(result) == 100
        assert np.all(result >= 0)
        assert np.all(result <= 1)

    def test_random_uniform_range(self):
        """Test random uniform with specific range."""
        result = pm.random_uniform([10, 20], 1000)
        assert np.all(result >= 10)
        assert np.all(result <= 20)

    def test_random_uniform_negative_range(self):
        """Test random uniform with negative range."""
        result = pm.random_uniform([-5, -1], 100)
        assert np.all(result >= -5)
        assert np.all(result <= -1)

    def test_random_uniform_single_value(self):
        """Test random uniform with single value returns that value."""
        result = pm.random_uniform([5, 5], 10)
        assert np.all(result == 5)

    def test_random_uniform_returns_numpy_array(self):
        """Test that random_uniform returns a numpy array."""
        result = pm.random_uniform([0, 1], 10)
        assert isinstance(result, np.ndarray)

    def test_random_uniform_statistical_properties(self):
        """Test that random uniform has expected statistical properties."""
        np.random.seed(42)  # For reproducibility
        result = pm.random_uniform([0, 100], 10000)
        # Mean should be approximately 50
        assert 45 < np.mean(result) < 55
        # Std should be approximately 100/sqrt(12) ≈ 28.87
        assert 25 < np.std(result) < 32


class TestConstant:
    """Tests for the constant function."""

    def test_constant_basic(self):
        """Test basic constant functionality."""
        result = pm.constant(42, 5)
        assert len(result) == 5
        assert np.all(result == 42)

    def test_constant_float(self):
        """Test constant with float value."""
        result = pm.constant(3.14159, 10)
        assert np.all(result == 3.14159)

    def test_constant_zero(self):
        """Test constant with zero value."""
        result = pm.constant(0, 5)
        assert np.all(result == 0)

    def test_constant_negative(self):
        """Test constant with negative value."""
        result = pm.constant(-100, 5)
        assert np.all(result == -100)

    def test_constant_scientific_notation(self):
        """Test constant with scientific notation."""
        result = pm.constant(1e-10, 5)
        assert np.all(result == 1e-10)

    def test_constant_returns_numpy_array(self):
        """Test that constant returns a numpy array."""
        result = pm.constant(1, 10)
        assert isinstance(result, np.ndarray)


class TestCustomList:
    """Tests for the custom_list function."""

    def test_custom_list_basic(self):
        """Test basic custom_list functionality."""
        input_list = [1, 2, 3, 4, 5]
        result = pm.custom_list(input_list, 5)
        assert result == input_list

    def test_custom_list_floats(self):
        """Test custom_list with float values."""
        input_list = [1.1, 2.2, 3.3]
        result = pm.custom_list(input_list, 3)
        assert result == input_list

    def test_custom_list_mixed_types(self):
        """Test custom_list with mixed types."""
        input_list = [1, 2.5, 3, 4.5]
        result = pm.custom_list(input_list, 4)
        assert result == input_list

    def test_custom_list_empty(self):
        """Test custom_list with empty list."""
        result = pm.custom_list([], 0)
        assert result == []

    def test_custom_list_single_value(self):
        """Test custom_list with single value."""
        result = pm.custom_list([42], 1)
        assert result == [42]

    def test_custom_list_returns_same_object(self):
        """Test that custom_list returns the same list object."""
        input_list = [1, 2, 3]
        result = pm.custom_list(input_list, 3)
        assert result is input_list


class TestFixRatio:
    """Tests for the fix_ratio function."""

    def test_fix_ratio_with_dict(self):
        """Test fix_ratio with dictionary reference."""
        ref_vars = {'Fe++': ['1e-6']}
        to_change = ['fix_ratio', 'Fe++', 2.0]
        result = pm.fix_ratio(to_change, 10, ref_vars)
        assert result == 2e-6

    def test_fix_ratio_with_keyword_block(self):
        """Test fix_ratio with KeywordBlock reference."""
        from core.keyword_block import KeywordBlock
        block = KeywordBlock('TEST')
        block.contents = {'Fe++': ['1e-3']}
        to_change = ['fix_ratio', 'Fe++', 0.5]
        result = pm.fix_ratio(to_change, 10, block)
        assert result == 0.5e-3

    def test_fix_ratio_invalid_ref_type(self):
        """Test fix_ratio with invalid reference type raises error."""
        with pytest.raises(ParameterConfigError) as exc_info:
            pm.fix_ratio(['fix_ratio', 'Fe++', 2.0], 10, "invalid")
        assert "unknown type" in str(exc_info.value)

    def test_fix_ratio_multiplier_zero(self):
        """Test fix_ratio with zero multiplier."""
        ref_vars = {'Fe++': ['1e-6']}
        to_change = ['fix_ratio', 'Fe++', 0]
        result = pm.fix_ratio(to_change, 10, ref_vars)
        assert result == 0

    def test_fix_ratio_negative_multiplier(self):
        """Test fix_ratio with negative multiplier."""
        ref_vars = {'Fe++': ['1e-6']}
        to_change = ['fix_ratio', 'Fe++', -1]
        result = pm.fix_ratio(to_change, 10, ref_vars)
        assert result == -1e-6


class TestParameterConfigError:
    """Tests for the ParameterConfigError exception."""

    def test_exception_can_be_raised(self):
        """Test that ParameterConfigError can be raised."""
        with pytest.raises(ParameterConfigError):
            raise ParameterConfigError("Test error")

    def test_exception_message(self):
        """Test that exception message is preserved."""
        msg = "Custom error message"
        with pytest.raises(ParameterConfigError) as exc_info:
            raise ParameterConfigError(msg)
        assert msg in str(exc_info.value)

    def test_exception_is_exception_subclass(self):
        """Test that ParameterConfigError is an Exception subclass."""
        assert issubclass(ParameterConfigError, Exception)
