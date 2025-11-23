"""Integration tests for complete Omphalos workflows."""

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
import yaml


class TestOmphalosWorkflow:
    """Integration tests for the complete Omphalos workflow."""

    def test_template_to_file_dict_workflow(self, omphalos_test_dir, sample_config):
        """Test complete workflow from template to file dictionary."""
        original_dir = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            from omphalos.template import Template
            from omphalos import generate_inputs as gi
            import io
            import contextlib

            # Create template
            with contextlib.redirect_stdout(io.StringIO()):
                template = Template(sample_config)

            # Generate file dictionary
            with tempfile.TemporaryDirectory() as tmp_dir:
                with contextlib.redirect_stdout(io.StringIO()):
                    file_dict = gi.configure_input_files(template, tmp_dir + '/', rhea=True)

                # Verify file dictionary
                assert len(file_dict) == sample_config['number_of_files']

                # Each file should have unique modifications if config specifies them
                if 'concentrations' in sample_config:
                    for condition in sample_config['concentrations']:
                        for species in sample_config['concentrations'][condition]:
                            values = []
                            for f in file_dict:
                                val = file_dict[f].condition_blocks[condition].concentrations[species][-1]
                                values.append(float(val))

                            # Values should vary unless constant was specified
                            spec = sample_config['concentrations'][condition][species][0]
                            if spec != 'constant':
                                assert len(set(values)) > 1, f"{species} should have varied values"
        finally:
            os.chdir(original_dir)

    def test_parameter_variation_linspace(self, omphalos_test_dir):
        """Test that linspace parameter variation works correctly."""
        original_dir = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            from omphalos.template import Template
            from omphalos import generate_inputs as gi
            import io
            import contextlib

            # Create config with linspace variation
            config = {
                'template': 'sukinda_column.in',
                'database': 'SukindaCr53.dbs',
                'aqueous_database': 'aqueous.dbs',
                'catabolic_pathways': 'CatabolicPathways.in',
                'restart_file': '',
                'timeout': 60,
                'conditions': ['boundary'],
                'number_of_files': 5,
                'nodes': 1,
                'concentrations': {
                    'boundary': {
                        'SO4--': ['linspace', [1, 5]],
                    }
                }
            }

            with contextlib.redirect_stdout(io.StringIO()):
                template = Template(config)

            with tempfile.TemporaryDirectory() as tmp_dir:
                with contextlib.redirect_stdout(io.StringIO()):
                    file_dict = gi.configure_input_files(template, tmp_dir + '/', rhea=True)

                # Extract SO4-- values
                so4_values = []
                for f in file_dict:
                    val = float(file_dict[f].condition_blocks['boundary'].concentrations['SO4--'][-1])
                    so4_values.append(val)

                # Should be linearly spaced from 1 to 5
                expected = np.linspace(1, 5, 5)
                np.testing.assert_array_almost_equal(sorted(so4_values), expected)
        finally:
            os.chdir(original_dir)

    def test_parameter_variation_constant(self, omphalos_test_dir):
        """Test that constant parameter variation works correctly."""
        original_dir = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            from omphalos.template import Template
            from omphalos import generate_inputs as gi
            import io
            import contextlib

            config = {
                'template': 'sukinda_column.in',
                'database': 'SukindaCr53.dbs',
                'aqueous_database': 'aqueous.dbs',
                'catabolic_pathways': 'CatabolicPathways.in',
                'restart_file': '',
                'timeout': 60,
                'conditions': ['boundary'],
                'number_of_files': 5,
                'nodes': 1,
                'concentrations': {
                    'boundary': {
                        'Fe++': ['constant', 1e-6],
                    }
                }
            }

            with contextlib.redirect_stdout(io.StringIO()):
                template = Template(config)

            with tempfile.TemporaryDirectory() as tmp_dir:
                with contextlib.redirect_stdout(io.StringIO()):
                    file_dict = gi.configure_input_files(template, tmp_dir + '/', rhea=True)

                # Extract Fe++ values
                fe_values = []
                for f in file_dict:
                    val = float(file_dict[f].condition_blocks['boundary'].concentrations['Fe++'][-1])
                    fe_values.append(val)

                # All should be 1e-6
                assert all(v == pytest.approx(1e-6) for v in fe_values)
        finally:
            os.chdir(original_dir)


class TestCoreModuleIntegration:
    """Integration tests for core module components."""

    def test_parameter_methods_work_with_keyword_blocks(self):
        """Test that parameter methods integrate with keyword blocks."""
        from core.keyword_block import KeywordBlock, ConditionBlock
        from core import parameter_methods as pm

        # Create a condition block
        block = ConditionBlock()
        block.concentrations = {'SO4--': ['1.0', 'mM']}

        # Generate values using parameter methods
        values = pm.linspace([1, 10], 10)

        # Apply to block
        for val in values:
            block.modify('SO4--', str(val), 0, species_type='concentrations')
            assert float(block.concentrations['SO4--'][0]) == val

    def test_file_methods_pickle_roundtrip(self, tmp_path):
        """Test that file methods can pickle and unpickle complex objects."""
        from core import file_methods as fm
        from core.keyword_block import KeywordBlock, ConditionBlock

        # Create complex data structure
        block = KeywordBlock('RUNTIME')
        block.contents = {'timestep_max': ['0.01']}

        cond = ConditionBlock()
        cond.concentrations = {'SO4--': ['1.0']}

        data = {
            'keyword_block': block,
            'condition_block': cond,
            'config': {'number_of_files': 10},
        }

        # Pickle and unpickle
        fm.pickle_data_set(data, 'test.pkl', str(tmp_path))
        loaded = fm.unpickle(tmp_path / 'test.pkl')

        # Verify
        assert loaded['keyword_block'].contents == block.contents
        assert loaded['condition_block'].concentrations == cond.concentrations
        assert loaded['config'] == data['config']


class TestBackwardCompatibility:
    """Tests for backward compatibility of module imports."""

    def test_omphalos_imports_work(self):
        """Test that importing from omphalos still works."""
        from omphalos import parameter_methods
        from omphalos import file_methods
        from omphalos import keyword_block
        from omphalos import attributes
        from omphalos import spatial_constructor

        # Verify functions exist
        assert hasattr(parameter_methods, 'linspace')
        assert hasattr(file_methods, 'search_file')
        assert hasattr(keyword_block, 'KeywordBlock')
        assert hasattr(attributes, 'boundary_condition')
        assert hasattr(spatial_constructor, 'populate_array')

    def test_pflotran_imports_work(self):
        """Test that importing from pflotran still works."""
        from pflotran import parameter_methods
        from pflotran import file_methods
        from pflotran import keyword_block
        from pflotran import attributes
        from pflotran import spatial_constructor

        # Verify functions exist
        assert hasattr(parameter_methods, 'linspace')
        assert hasattr(file_methods, 'search_file')
        assert hasattr(keyword_block, 'KeywordBlock')
        assert hasattr(attributes, 'boundary_condition')
        assert hasattr(spatial_constructor, 'populate_array')

    def test_core_and_omphalos_share_implementation(self):
        """Test that core and omphalos modules share the same implementation."""
        from core import parameter_methods as core_pm
        from omphalos import parameter_methods as omp_pm
        from pflotran import parameter_methods as pf_pm

        # All should reference the same functions
        assert core_pm.linspace is omp_pm.linspace
        assert core_pm.linspace is pf_pm.linspace


class TestEndToEndWithRealData:
    """End-to-end tests using real test data files."""

    def test_full_workflow_with_sukinda_config(self, omphalos_test_dir):
        """Test complete workflow with sukinda test configuration."""
        original_dir = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            from omphalos.template import Template
            from omphalos import generate_inputs as gi
            from omphalos import file_methods as fm
            import io
            import contextlib

            # Load actual config file
            with open('sukinda_cr.yaml') as f:
                config = yaml.safe_load(f)

            # Create template
            with contextlib.redirect_stdout(io.StringIO()):
                template = Template(config)

            # Generate files
            with tempfile.TemporaryDirectory() as tmp_dir:
                with contextlib.redirect_stdout(io.StringIO()):
                    file_dict = gi.configure_input_files(template, tmp_dir + '/', rhea=True)

                # Verify we got the expected number of files
                assert len(file_dict) == config['number_of_files']

                # Verify each file is properly configured
                for file_num in file_dict:
                    input_file = file_dict[file_num]
                    assert input_file.file_num == file_num
                    assert hasattr(input_file, 'keyword_blocks')
                    assert hasattr(input_file, 'condition_blocks')

                # Test pickle roundtrip
                fm.pickle_data_set(file_dict, 'test_output.pkl', tmp_dir)
                loaded = fm.unpickle(Path(tmp_dir) / 'test_output.pkl')
                assert len(loaded) == len(file_dict)
        finally:
            os.chdir(original_dir)

    def test_multiple_conditions_workflow(self, omphalos_test_dir):
        """Test workflow with multiple conditions."""
        original_dir = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            from omphalos.template import Template
            from omphalos import generate_inputs as gi
            import io
            import contextlib

            config = {
                'template': 'sukinda_column.in',
                'database': 'SukindaCr53.dbs',
                'aqueous_database': 'aqueous.dbs',
                'catabolic_pathways': 'CatabolicPathways.in',
                'restart_file': '',
                'timeout': 60,
                'conditions': ['boundary', 'initial'],
                'number_of_files': 3,
                'nodes': 1,
                'concentrations': {
                    'boundary': {
                        'SO4--': ['linspace', [1, 3]],
                    },
                    'initial': {
                        'Fe++': ['constant', 1e-9],
                    }
                }
            }

            with contextlib.redirect_stdout(io.StringIO()):
                template = Template(config)

            with tempfile.TemporaryDirectory() as tmp_dir:
                with contextlib.redirect_stdout(io.StringIO()):
                    file_dict = gi.configure_input_files(template, tmp_dir + '/', rhea=True)

                # Verify both conditions are modified
                for f in file_dict:
                    # Boundary condition SO4-- should vary
                    assert 'SO4--' in file_dict[f].condition_blocks['boundary'].concentrations

                    # Initial condition Fe++ should be constant
                    fe_val = float(file_dict[f].condition_blocks['initial'].concentrations['Fe++'][-1])
                    assert fe_val == pytest.approx(1e-9)
        finally:
            os.chdir(original_dir)
