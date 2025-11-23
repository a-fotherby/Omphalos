"""Unit tests for omphalos/generate_inputs.py."""

import pytest
import numpy as np

# Import from omphalos (which re-exports from core)
from omphalos import generate_inputs as gi
from omphalos import parameter_methods as pm


class TestGetBlockChanges:
    """Tests for the get_block_changes function."""

    def test_get_block_changes_linspace(self):
        """Test get_block_changes with linspace."""
        block = {
            'SO4--': ['linspace', [1, 10]],
        }
        result = gi.get_block_changes(block, 10)

        assert 'SO4--' in result
        assert len(result['SO4--']) == 10
        assert result['SO4--'][0] == 1.0
        assert result['SO4--'][-1] == 10.0

    def test_get_block_changes_constant(self):
        """Test get_block_changes with constant."""
        block = {
            'Fe++': ['constant', 1e-6],
        }
        result = gi.get_block_changes(block, 5)

        assert 'Fe++' in result
        assert len(result['Fe++']) == 5
        assert all(v == 1e-6 for v in result['Fe++'])

    def test_get_block_changes_random_uniform(self):
        """Test get_block_changes with random_uniform."""
        block = {
            'Ca++': ['random_uniform', [0, 1]],
        }
        result = gi.get_block_changes(block, 100)

        assert 'Ca++' in result
        assert len(result['Ca++']) == 100
        assert all(0 <= v <= 1 for v in result['Ca++'])

    def test_get_block_changes_multiple_entries(self):
        """Test get_block_changes with multiple entries."""
        block = {
            'SO4--': ['linspace', [1, 10]],
            'Fe++': ['constant', 1e-6],
            'pH': ['random_uniform', [6, 8]],
        }
        result = gi.get_block_changes(block, 10)

        assert len(result) == 3
        assert 'SO4--' in result
        assert 'Fe++' in result
        assert 'pH' in result


class TestEvaluateConfig:
    """Tests for the evaluate_config function."""

    def test_evaluate_config_concentrations(self):
        """Test evaluate_config with concentration modifications."""
        config = {
            'number_of_files': 5,
            'concentrations': {
                'boundary': {
                    'SO4--': ['linspace', [1, 5]],
                }
            }
        }
        result = gi.evaluate_config(config)

        assert 'concentrations' in result
        assert 'boundary' in result['concentrations']
        assert 'SO4--' in result['concentrations']['boundary']

    def test_evaluate_config_mineral_volumes(self):
        """Test evaluate_config with mineral volume modifications."""
        config = {
            'number_of_files': 5,
            'mineral_volumes': {
                'initial': {
                    'Calcite': ['constant', 0.01],
                }
            }
        }
        result = gi.evaluate_config(config)

        assert 'mineral_volumes' in result

    def test_evaluate_config_mineral_rates(self):
        """Test evaluate_config with mineral rate modifications."""
        config = {
            'number_of_files': 5,
            'mineral_rates': {
                'Quartz&default': ['random_uniform', [1e-16, 1e-15]],
            }
        }
        result = gi.evaluate_config(config)

        assert 'mineral_rates' in result

    def test_evaluate_config_empty_config(self):
        """Test evaluate_config with minimal config."""
        config = {
            'number_of_files': 5,
        }
        result = gi.evaluate_config(config)

        assert result == {}

    def test_evaluate_config_multiple_blocks(self):
        """Test evaluate_config with multiple block types."""
        config = {
            'number_of_files': 10,
            'concentrations': {
                'boundary': {'SO4--': ['linspace', [1, 10]]}
            },
            'mineral_volumes': {
                'initial': {'Calcite': ['constant', 0.01]}
            },
            'runtime': {
                'timestep_max': ['constant', 0.001]
            }
        }
        result = gi.evaluate_config(config)

        assert 'concentrations' in result
        assert 'mineral_volumes' in result
        assert 'runtime' in result


class TestGetConfigArray:
    """Tests for the get_config_array function."""

    def test_get_config_array_linspace(self):
        """Test get_config_array with linspace spec."""
        result = gi.get_config_array('linspace', [1, 10], 10)
        assert len(result) == 10
        assert result[0] == 1.0
        assert result[-1] == 10.0

    def test_get_config_array_random_uniform(self):
        """Test get_config_array with random_uniform spec."""
        result = gi.get_config_array('random_uniform', [0, 100], 100)
        assert len(result) == 100
        assert all(0 <= v <= 100 for v in result)

    def test_get_config_array_constant(self):
        """Test get_config_array with constant spec."""
        result = gi.get_config_array('constant', 42, 5)
        assert len(result) == 5
        assert all(v == 42 for v in result)

    def test_get_config_array_custom(self):
        """Test get_config_array with custom spec."""
        custom_values = [1, 2, 3, 4, 5]
        result = gi.get_config_array('custom', custom_values, 5)
        assert result == custom_values

    def test_get_config_array_invalid_spec(self):
        """Test get_config_array with invalid spec raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            gi.get_config_array('invalid_method', [1, 10], 10)

        assert 'Unknown parameter setting' in str(exc_info.value)
        assert 'invalid_method' in str(exc_info.value)

    def test_get_config_array_error_message_contains_valid_options(self):
        """Test that error message lists valid options."""
        with pytest.raises(ValueError) as exc_info:
            gi.get_config_array('bad_spec', [], 10)

        error_msg = str(exc_info.value)
        assert 'linspace' in error_msg
        assert 'random_uniform' in error_msg
        assert 'constant' in error_msg
        assert 'custom' in error_msg
        assert 'fix_ratio' in error_msg


class TestCTIDs:
    """Tests for the CT_IDs configuration dictionary."""

    def test_ct_ids_exists(self):
        """Test that CT_IDs dictionary exists."""
        assert hasattr(gi, 'CT_IDs')
        assert isinstance(gi.CT_IDs, dict)

    def test_ct_ids_contains_expected_keys(self):
        """Test that CT_IDs contains expected block types."""
        expected_keys = [
            'runtime', 'concentrations', 'mineral_volumes',
            'mineral_rates', 'mineral_ssa', 'parameters'
        ]
        for key in expected_keys:
            assert key in gi.CT_IDs, f"Missing key: {key}"

    def test_ct_ids_values_are_lists(self):
        """Test that CT_IDs values are lists."""
        for key, value in gi.CT_IDs.items():
            assert isinstance(value, list), f"Value for {key} should be a list"

    def test_ct_ids_geochemical_conditions(self):
        """Test that concentration-related entries map to geochemical condition."""
        geochemical_keys = ['concentrations', 'mineral_volumes', 'mineral_ssa', 'parameters', 'gases']
        for key in geochemical_keys:
            if key in gi.CT_IDs:
                assert gi.CT_IDs[key][0] == 'geochemical condition'


class TestBackwardCompatibility:
    """Tests for backward compatibility with omphalos imports."""

    def test_import_from_omphalos(self):
        """Test that generate_inputs can be imported from omphalos."""
        from omphalos import generate_inputs
        assert hasattr(generate_inputs, 'configure_input_files')
        assert hasattr(generate_inputs, 'evaluate_config')
        assert hasattr(generate_inputs, 'get_config_array')

    def test_parameter_methods_accessible(self):
        """Test that parameter_methods are accessible via dispatch."""
        # The dispatch dict should be created inside get_config_array
        # but we can verify the underlying methods work
        assert callable(pm.linspace)
        assert callable(pm.random_uniform)
        assert callable(pm.constant)
        assert callable(pm.custom_list)
        assert callable(pm.fix_ratio)
