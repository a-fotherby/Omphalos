"""Unit tests for omphalos/generate_inputs.py."""

import contextlib
import io
import os
from pathlib import Path

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


class TestAuxiliaryFiles:
    """Tests for finding the data files a CrunchTope deck reads from disk.

    Only the database and the temperature file used to be staged into a run directory, so a deck
    reading porosity, saturation, tortuosity or permeability from a file ran without it.
    """

    @staticmethod
    def _template(tmp_path, poro_line='read_PorosityFile porosity.dat FullForm', extra=''):
        """A minimal working deck with a POROSITY block, built from the sukinda test input."""
        from omphalos.template import Template

        source = Path(__file__).resolve().parents[1] / 'omphalos_test' / 'sukinda_column.in'
        text = source.read_text().replace('POROSITY', f'POROSITY\n{poro_line}{extra}', 1)
        deck = tmp_path / 'deck.in'
        deck.write_text(text)

        with contextlib.redirect_stdout(io.StringIO()):
            return Template({'template': str(deck), 'aqueous_database': None,
                             'catabolic_pathways': None, 'database': None, 'conditions': None,
                             'later_inputfiles': None})

    def test_filename_is_the_first_token(self, tmp_path):
        """'read_PorosityFile porosity.dat FullForm' names a file and a format, in that order.

        StartTope.F90 passes the two to readFileName separately. Taking the last token instead —
        which is what the temperature-file copy used to do — tries to stage a file called FullForm.
        """
        template = self._template(tmp_path)

        assert gi.auxiliary_files(template) == ['porosity.dat']

    def test_bare_filename(self, tmp_path):
        template = self._template(tmp_path, poro_line='read_PorosityFile porosity.dat')

        assert gi.auxiliary_files(template) == ['porosity.dat']

    def test_every_read_file_keyword_is_found(self, tmp_path):
        """The keyword is matched by shape, so a deck using one we have not seen still works."""
        template = self._template(
            tmp_path,
            extra='\nread_saturationfile sat.dat\nread_TortuosityFile tort.dat\n'
                  'read_permfile perm.dat',
        )

        assert gi.auxiliary_files(template) == ['porosity.dat', 'sat.dat', 'tort.dat', 'perm.dat']

    def test_case_is_ignored(self, tmp_path):
        """The parser keys entries on the verbatim spelling the deck used."""
        template = self._template(tmp_path, poro_line='READ_POROSITYFILE porosity.dat')

        assert gi.auxiliary_files(template) == ['porosity.dat']

    def test_deck_without_any(self, tmp_path):
        template = self._template(tmp_path, poro_line='fix_porosity 0.3')

        assert gi.auxiliary_files(template) == []

    def test_object_without_keyword_blocks(self):
        """A PFLOTRAN template has none, and must not raise on the way past."""
        assert gi.auxiliary_files(object()) == []


class TestConfigAuxiliaryFiles:
    """Tests for the per-stage files a restart chain names, which appear in no template block."""

    def test_grid_porosity_files(self):
        config = {'restart_chain': {'stages': 2, 'grid': [
            {'xzones': [350, 0.1], 'porosity_file': 'porosity.dat'},
            {'xzones': [3500, 0.01], 'porosity_file': 'porosity_highres.dat'},
        ]}}

        assert gi.config_auxiliary_files(config) == ['porosity.dat', 'porosity_highres.dat']

    def test_stage_without_a_porosity_file(self):
        config = {'restart_chain': {'stages': 2, 'grid': [
            {'xzones': [350, 0.1]},
            {'xzones': [3500, 0.01], 'porosity_file': 'fine.dat'},
        ]}}

        assert gi.config_auxiliary_files(config) == ['fine.dat']

    @pytest.mark.parametrize('config', [
        {},
        {'restart_chain': None},
        {'restart_chain': {'stages': 2}},
        {'restart_chain': {'stages': 2, 'grid': None}},
    ])
    def test_no_grid(self, config):
        assert gi.config_auxiliary_files(config) == []

    @staticmethod
    def _staged(config, omphalos_test_dir):
        """Build a template and run the staged configuration, from the data directory.

        The sample config names its template and databases relatively, so it only resolves there.
        """
        from omphalos.template import Template

        cwd = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return gi.configure_staged_input_files(Template(config), '.', rhea=True)
        finally:
            os.chdir(cwd)

    def test_grid_is_a_valid_restart_chain_key(self, sample_config, omphalos_test_dir):
        """The validator rejects unknown keys, so 'grid' has to be allowed through it."""
        sample_config['restart_chain'] = {'stages': 1, 'grid': [{'xzones': [10, 1.0]}]}

        assert self._staged(sample_config, omphalos_test_dir)

    def test_unknown_key_is_still_rejected(self, sample_config, omphalos_test_dir):
        sample_config['restart_chain'] = {'stages': 1, 'grids': [{'xzones': [10, 1.0]}]}

        with pytest.raises(ValueError, match='Unknown key'):
            self._staged(sample_config, omphalos_test_dir)


class TestSupportFiles:
    """Tests for the combined list rhea stages into every run directory."""

    def test_template_and_config_are_combined(self, tmp_path):
        template = TestAuxiliaryFiles._template(tmp_path)
        config = {'restart_chain': {'grid': [{'porosity_file': 'fine.dat'}]}}

        assert gi.support_files(template, config) == ['porosity.dat', 'fine.dat']

    def test_duplicates_are_dropped(self, tmp_path):
        """A config naming the file the template already names should stage it once."""
        template = TestAuxiliaryFiles._template(tmp_path)
        config = {'restart_chain': {'grid': [{'porosity_file': 'porosity.dat'}]}}

        assert gi.support_files(template, config) == ['porosity.dat']

    def test_absolute_paths_are_left_alone(self, tmp_path):
        """CrunchTope resolves an absolute path identically from any run directory."""
        template = TestAuxiliaryFiles._template(
            tmp_path, poro_line='read_PorosityFile /shared/porosity.dat')

        assert gi.support_files(template, {}) == []


class TestStageSupportFiles:
    """Tests for the copy itself, on the sequential (non-rhea) path."""

    def test_files_are_copied(self, tmp_path):
        (tmp_path / 'porosity.dat').write_text('0.3\n')
        template = TestAuxiliaryFiles._template(tmp_path)
        template.config['database'] = None
        run_dir = tmp_path / 'run'
        run_dir.mkdir()

        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            gi.stage_support_files(template, run_dir)
        finally:
            os.chdir(cwd)

        assert (run_dir / 'porosity.dat').read_text() == '0.3\n'

    def test_relative_path_is_preserved(self, tmp_path):
        """CrunchTope opens the name exactly as the deck writes it, subdirectory and all."""
        (tmp_path / 'data').mkdir()
        (tmp_path / 'data' / 'porosity.dat').write_text('0.3\n')
        template = TestAuxiliaryFiles._template(
            tmp_path, poro_line='read_PorosityFile data/porosity.dat')
        template.config['database'] = None
        run_dir = tmp_path / 'run'
        run_dir.mkdir()

        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            gi.stage_support_files(template, run_dir)
        finally:
            os.chdir(cwd)

        assert (run_dir / 'data' / 'porosity.dat').read_text() == '0.3\n'

    def test_missing_file_warns_and_continues(self, tmp_path, capsys):
        """CrunchTope's own failure does not say which file or why; this one does."""
        template = TestAuxiliaryFiles._template(tmp_path)
        template.config['database'] = None
        run_dir = tmp_path / 'run'
        run_dir.mkdir()

        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            gi.stage_support_files(template, run_dir)
        finally:
            os.chdir(cwd)

        out = capsys.readouterr().out
        assert 'porosity.dat' in out
        assert 'CrunchTope will not find it' in out


class TestRescaleRegion:
    """Tests for moving a 1-indexed inclusive cell range between grid resolutions."""

    def test_whole_column(self):
        assert gi.rescale_region([1, 10], 10, 25) == [1, 25]

    def test_coarsening(self):
        assert gi.rescale_region([1, 25], 25, 10) == [1, 10]

    def test_zones_stay_abutting(self):
        """No gap and no overlap where one zone ends and the next begins."""
        first = gi.rescale_region([1, 5], 10, 25)
        second = gi.rescale_region([6, 10], 10, 25)

        assert second[0] == first[1] + 1
        assert first[0] == 1 and second[1] == 25

    def test_identity(self):
        assert gi.rescale_region([3, 7], 10, 10) == [3, 7]

    def test_thin_zone_survives_coarsening(self):
        """A zone thinner than one cell of the coarser grid would otherwise invert."""
        bounds = gi.rescale_region([5, 5], 100, 4)

        assert bounds[1] >= bounds[0]


class TestConfigureGrid:
    """Tests for applying a restart chain's per-stage grid to a stage's input file."""

    @staticmethod
    def _stage(sample_config, omphalos_test_dir, grid, stage_num=0, stages=2):
        from omphalos.template import Template

        sample_config['number_of_files'] = 1
        sample_config['restart_chain'] = {'stages': stages, 'grid': grid}
        cwd = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                staged = gi.configure_staged_input_files(Template(sample_config), '.', rhea=True)
        finally:
            os.chdir(cwd)

        return staged[0][stage_num]

    def test_xzones_is_written(self, sample_config, omphalos_test_dir):
        stage = self._stage(sample_config, omphalos_test_dir,
                            [{'xzones': [10, 10.0]}, {'xzones': [25, 4.0]}], stage_num=1)

        assert stage.keyword_blocks['DISCRETIZATION'].contents['xzones'] == ['25', '4.0']

    def test_porosity_file_is_written(self, sample_config, omphalos_test_dir):
        stage = self._stage(sample_config, omphalos_test_dir,
                            [{'porosity_file': 'poro10.dat'}, {'porosity_file': 'poro25.dat'}],
                            stage_num=1)

        assert stage.keyword_blocks['POROSITY'].contents['read_PorosityFile'] == ['poro25.dat']

    def test_fix_porosity_is_dropped(self, sample_config, omphalos_test_dir):
        """StartTope reads fix_porosity first and jumps past read_porosityfile if it is set.

        Leaving both in place would silently ignore the file the stage is meant to read.
        """
        stage = self._stage(sample_config, omphalos_test_dir, [{'porosity_file': 'poro10.dat'}])

        keywords = {k.lower() for k in stage.keyword_blocks['POROSITY'].contents}
        assert 'fix_porosity' not in keywords
        assert 'read_porosityfile' in keywords

    def test_initial_conditions_follow_the_grid(self, sample_config, omphalos_test_dir):
        """CrunchTope aborts with 'corner at JX > NX' if a region runs past the end of the grid."""
        stage = self._stage(sample_config, omphalos_test_dir,
                            [{'xzones': [10, 10.0]}, {'xzones': [25, 4.0]}], stage_num=1)

        assert stage.condition_blocks['initial'].region == [[[1, 25], [1, 1], [1, 1]]]
        assert '1-25 1-1 1-1' in stage.keyword_blocks['INITIAL_CONDITIONS'].contents

    def test_stage_without_a_grid_entry_is_untouched(self, sample_config, omphalos_test_dir):
        """A chain declaring a grid for only its first stage leaves the rest on the template's."""
        stage = self._stage(sample_config, omphalos_test_dir, [{'xzones': [10, 10.0]}], stage_num=1)

        assert stage.keyword_blocks['DISCRETIZATION'].contents['xzones'] == ['10', '10.0']
        assert stage.condition_blocks['initial'].region == [[[1, 10], [1, 1], [1, 1]]]

    def test_unknown_grid_key_is_rejected(self, sample_config, omphalos_test_dir):
        with pytest.raises(ValueError, match='Unknown key'):
            self._stage(sample_config, omphalos_test_dir, [{'xzone': [10, 10.0]}])

    def test_graded_grid(self, sample_config, omphalos_test_dir):
        """Coarse at the top, fine in the middle, coarse at the bottom: 4 + 12 + 4 = 20 cells."""
        stage = self._stage(sample_config, omphalos_test_dir,
                            [{'xzones': [10, 10.0]}, {'xzones': [4, 10.0, 12, 2.5, 4, 7.5]}],
                            stage_num=1)

        assert stage.condition_blocks['initial'].region == [[[1, 20], [1, 1], [1, 1]]]
