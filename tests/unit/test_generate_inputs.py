"""Unit tests for omphalos/generate_inputs.py."""

import contextlib
import io
import os
from pathlib import Path

import pytest
import numpy as np

# Import from omphalos (which re-exports from core)
from core import spatial_constructor as sc
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


class TestRefineZones:
    """Tests for deriving a finer grid from a coarser one."""

    def test_uniform(self):
        assert gi.refine_zones(['10', '10.0'], 2) == ['20', '5']

    def test_grading_and_length_are_preserved(self):
        refined = gi.refine_zones(['4', '10.0', '12', '2.5', '4', '7.5'], 5)

        assert refined == ['20', '2', '60', '0.5', '20', '1.5']
        counts = [int(refined[i]) for i in range(0, len(refined), 2)]
        widths = [float(refined[i]) for i in range(1, len(refined), 2)]
        assert sum(counts) == 100
        assert sum(c * w for c, w in zip(counts, widths)) == pytest.approx(100.0)

    def test_bare_count_takes_unit_width(self):
        assert gi.refine_zones(['10'], 2) == ['20', '0.5']

    @pytest.mark.parametrize('factor', [1, 0, -2, 1.5])
    def test_useless_factors_are_rejected(self, factor):
        with pytest.raises(ValueError, match='at least 2'):
            gi.refine_zones(['10', '1.0'], factor)


class TestRefineDataFile:
    """Tests for regenerating a spatial input file on a finer grid."""

    def test_single_column_is_replicated(self, tmp_path):
        source, destination = tmp_path / 'in.dat', tmp_path / 'out.dat'
        np.savetxt(source, [0.3, 0.4, 0.5])

        rows = gi.refine_data_file(source, destination, 3)

        assert rows == 9
        assert np.allclose(np.loadtxt(destination), np.repeat([0.3, 0.4, 0.5], 3))

    def test_steps_are_not_smoothed(self, tmp_path):
        """A layered porosity profile must keep its steps: interpolation would round them off and
        so change the effective diffusivity through cementation_exponent."""
        source, destination = tmp_path / 'in.dat', tmp_path / 'out.dat'
        np.savetxt(source, [0.2, 0.2, 0.8, 0.8])

        gi.refine_data_file(source, destination, 4)
        result = np.loadtxt(destination)

        assert set(np.unique(result)) == {0.2, 0.8}, 'intermediate values were invented'

    def test_two_column_positions_are_rebuilt(self, tmp_path):
        """CrunchTope discards the position column, but it should still describe the new grid."""
        source, destination = tmp_path / 'in.dat', tmp_path / 'out.dat'
        np.savetxt(source, np.column_stack([[5.0, 15.0], [4.0, 20.0]]))

        gi.refine_data_file(source, destination, 2, zones=['4', '5.0'])
        result = np.loadtxt(destination)

        assert np.allclose(result[:, 0], [2.5, 7.5, 12.5, 17.5])
        assert np.allclose(result[:, 1], [4.0, 4.0, 20.0, 20.0])

    def test_step_is_the_default(self, tmp_path):
        """Adding the method option must not change what an existing config produces."""
        source = tmp_path / 'in.dat'
        np.savetxt(source, [0.2, 0.8])

        gi.refine_data_file(source, tmp_path / 'a.dat', 4)
        gi.refine_data_file(source, tmp_path / 'b.dat', 4, method='step')

        assert np.allclose(np.loadtxt(tmp_path / 'a.dat'), np.loadtxt(tmp_path / 'b.dat'))

    def test_linear_ramps_each_step_over_factor_cells(self, tmp_path):
        """The change between two coarse cells is spread over the fine cells spanning them.

        An odd factor is used because only then does a fine cell land on a coarse centre: for
        an even factor the centre falls between two fine cells, so the coarse value is never
        reproduced exactly and there is nothing sharper to assert than the bounds.
        """
        source, destination = tmp_path / 'in.dat', tmp_path / 'out.dat'
        np.savetxt(source, [0.2, 0.2, 0.8, 0.8])

        gi.refine_data_file(source, destination, 3, method='linear')
        result = np.loadtxt(destination)

        assert len(result) == 12
        # Coarse centres sit on fine cells 1, 4, 7, 10 and keep their values exactly.
        assert np.allclose(result[[1, 4, 7, 10]], [0.2, 0.2, 0.8, 0.8])
        # One ramp, spanning the single coarse-cell width between the two plateaux.
        intermediate = np.flatnonzero((result > 0.2 + 1e-12) & (result < 0.8 - 1e-12))
        assert len(intermediate) == 2, 'ramp is not factor - 1 interior cells wide'
        assert np.all(np.diff(result[4:8]) > 0)
        assert result.min() == pytest.approx(0.2) and result.max() == pytest.approx(0.8)

    def test_linear_holds_the_ends(self, tmp_path):
        """Fine cells outside the first and last coarse centres clamp rather than extrapolate."""
        source, destination = tmp_path / 'in.dat', tmp_path / 'out.dat'
        np.savetxt(source, [0.9, 0.5, 0.4])

        gi.refine_data_file(source, destination, 3, method='linear')
        result = np.loadtxt(destination)

        assert result[0] == pytest.approx(0.9)
        assert result[-1] == pytest.approx(0.4)
        assert result.max() == pytest.approx(0.9) and result.min() == pytest.approx(0.4)

    def test_linear_interpolates_by_position_on_a_graded_grid(self, tmp_path):
        """Interpolating by index would misplace the ramp where cell widths differ."""
        source = tmp_path / 'in.dat'
        np.savetxt(source, [0.0, 1.0])
        zones = ['2', '1.0', '2', '4.0']          # 2 cells refined from each of 2 coarse cells

        gi.refine_data_file(source, tmp_path / 'graded.dat', 2, zones=zones, method='linear')
        graded = np.loadtxt(tmp_path / 'graded.dat')

        centres = gi._cell_centres(zones, 4)
        coarse = centres.reshape(2, 2).mean(axis=1)
        assert np.allclose(graded, np.interp(centres, coarse, [0.0, 1.0]))
        # And it is genuinely different from the uniform placement.
        gi.refine_data_file(source, tmp_path / 'uniform.dat', 2, method='linear')
        assert not np.allclose(graded, np.loadtxt(tmp_path / 'uniform.dat'))

    def test_smoothstep_matches_linear_at_the_nodes_but_not_between(self, tmp_path):
        source = tmp_path / 'in.dat'
        np.savetxt(source, [0.0, 0.0, 1.0, 1.0])

        gi.refine_data_file(source, tmp_path / 'lin.dat', 3, method='linear')
        gi.refine_data_file(source, tmp_path / 'smooth.dat', 3, method='smoothstep')
        lin, smooth = np.loadtxt(tmp_path / 'lin.dat'), np.loadtxt(tmp_path / 'smooth.dat')

        nodes = [1, 4, 7, 10]
        assert np.allclose(lin[nodes], smooth[nodes])
        assert not np.allclose(lin, smooth)
        assert smooth.min() == pytest.approx(0.0) and smooth.max() == pytest.approx(1.0)

    def test_unknown_method_raises(self, tmp_path):
        source = tmp_path / 'in.dat'
        np.savetxt(source, [0.2, 0.8])

        with pytest.raises(ValueError, match='unknown refine method'):
            gi.refine_data_file(source, tmp_path / 'out.dat', 2, method='cubic')


class TestSpinupTime:
    """Tests for reading the clock a chain's spinup restart starts from."""

    @staticmethod
    def _fixture():
        return Path(__file__).resolve().parents[1] / 'restart_test' / 'sukinda10.rst'

    def test_no_restart_file_starts_from_zero(self):
        assert gi.spinup_time({}) == 0.0
        assert gi.spinup_time({'restart_file': None}) == 0.0

    def test_reads_the_stored_clock(self, tmp_path, monkeypatch):
        from omphalos import restart_file as rf

        expected = float(rf.stored_counters(self._fixture())['time'])
        (tmp_path / 'spinup.rst').write_bytes(self._fixture().read_bytes())
        monkeypatch.chdir(tmp_path)

        assert gi.spinup_time({'restart_file': 'spinup.rst'}) == expected
        assert expected > 0.0, 'fixture should carry a non-zero clock for this to mean anything'

    def test_missing_file_warns_and_starts_from_zero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        assert gi.spinup_time({'restart_file': 'absent.rst'}) == 0.0
        assert 'absent.rst' in capsys.readouterr().out


class TestConfigureSpatialProfile:
    """Tests for how a chain's per-stage output times are placed on the clock."""

    @staticmethod
    def _deck(times=('100',)):
        from types import SimpleNamespace

        return SimpleNamespace(keyword_blocks={
            'OUTPUT': SimpleNamespace(contents={'spatial_profile': list(times)})})

    @staticmethod
    def _times(deck):
        return [float(t) for t in deck.keyword_blocks['OUTPUT'].contents['spatial_profile']]

    def test_stage_times_are_cumulative_durations(self):
        config = [[4500], [500]]
        first, second = self._deck(), self._deck()

        gi._configure_spatial_profile(first, config, 0)
        gi._configure_spatial_profile(second, config, 1)

        assert self._times(first) == [4500.0]
        assert self._times(second) == [5000.0], 'stage 1 follows stage 0, not restarts the clock'

    def test_a_spinup_shifts_every_stage(self):
        """The config's times stay durations: a spinup at t=2000 with [[500], [500]] gives
        outputs at 2500 and 3000, rather than forcing stage 0 to be written as absolute."""
        config = [[500], [500]]
        first, second = self._deck(), self._deck()

        gi._configure_spatial_profile(first, config, 0, base_time=2000.0)
        gi._configure_spatial_profile(second, config, 1, base_time=2000.0)

        assert self._times(first) == [2500.0]
        assert self._times(second) == [3000.0]

    def test_no_spinup_is_unchanged(self):
        """base_time defaults to zero, so an existing config produces what it always did."""
        config = [[1000, 2000], [500]]
        with_default, explicit = self._deck(), self._deck()

        gi._configure_spatial_profile(with_default, config, 1)
        gi._configure_spatial_profile(explicit, config, 1, base_time=0.0)

        assert self._times(with_default) == self._times(explicit) == [2500.0]

    def test_auto_adjust_shifts_stage_zero_for_a_spinup(self):
        """Without this, stage 0 keeps the template's times, which land before the restart
        and make CrunchTope stop on 'output time < the restart time'."""
        deck = self._deck(('250', '500'))

        gi._auto_adjust_spatial_profile(deck, 0, base_time=2000.0)

        assert self._times(deck) == [2250.0, 2500.0]

    def test_auto_adjust_without_a_spinup_is_unchanged(self):
        deck = self._deck(('250', '500'))

        gi._auto_adjust_spatial_profile(deck, 1)

        assert self._times(deck) == [750.0, 1000.0]


class TestConfigureRestartDirectives:
    """Tests for the restart/save_restart keywords a staged chain writes per stage."""

    @staticmethod
    def _deck(runtime=None):
        """A stand-in exposing only what the function touches: RUNTIME contents."""
        from types import SimpleNamespace

        return SimpleNamespace(
            keyword_blocks={'RUNTIME': SimpleNamespace(contents=dict(runtime or {}))})

    @staticmethod
    def _runtime(deck):
        return deck.keyword_blocks['RUNTIME'].contents

    def test_first_stage_starts_cold_by_default(self):
        deck = self._deck()

        gi._configure_restart_directives(deck, 0, 0, 2)

        assert 'restart' not in self._runtime(deck)
        assert self._runtime(deck)['save_restart'] == ['restart_0_stage0.rst']

    def test_first_stage_restarts_from_the_config_spinup(self):
        """rhea copies restart_file into every run directory, but nothing used to read it:
        stage 0's restart keyword was deleted unconditionally, so the chain silently
        recomputed a spinup that had already been staged for it."""
        deck = self._deck()

        gi._configure_restart_directives(deck, 0, 0, 2, spinup_restart='spinup.rst')

        assert self._runtime(deck)['restart'] == ['spinup.rst', 'append']

    def test_a_template_restart_line_is_replaced_not_duplicated(self):
        deck = self._deck({'restart': ['stale.rst', 'append']})

        gi._configure_restart_directives(deck, 0, 0, 2, spinup_restart='spinup.rst')

        assert self._runtime(deck)['restart'] == ['spinup.rst', 'append']

    def test_a_template_restart_line_is_dropped_without_a_spinup(self):
        deck = self._deck({'restart': ['stale.rst', 'append']})

        gi._configure_restart_directives(deck, 0, 0, 2)

        assert 'restart' not in self._runtime(deck)

    def test_later_stages_ignore_the_spinup(self):
        """Stage 1 restarts from stage 0's output, not from the config's spinup."""
        deck = self._deck()

        gi._configure_restart_directives(deck, 3, 1, 3, spinup_restart='spinup.rst')

        assert self._runtime(deck)['restart'] == ['restart_3_stage0.rst', 'append']
        assert self._runtime(deck)['save_restart'] == ['restart_3_stage1.rst']

    def test_last_stage_writes_no_restart(self):
        deck = self._deck({'save_restart': ['stale.rst']})

        gi._configure_restart_directives(deck, 0, 1, 2, spinup_restart='spinup.rst')

        assert 'save_restart' not in self._runtime(deck)


class TestNameRegriddedRestart:
    """Tests for the name a stage reads when the chain resamples between grids."""

    @staticmethod
    def _deck(zones=None, restart=None):
        from types import SimpleNamespace

        blocks = {'RUNTIME': SimpleNamespace(
            contents={'restart': [restart, 'append']} if restart else {})}
        if zones is not None:
            blocks['DISCRETIZATION'] = SimpleNamespace(contents={'xzones': zones})

        return SimpleNamespace(keyword_blocks=blocks)

    @staticmethod
    def _restart(deck):
        return deck.keyword_blocks['RUNTIME'].contents.get('restart')

    def test_a_refining_stage_reads_a_distinct_name(self):
        """The cell count goes in the name, so the coarse file keeps its own honest one."""
        current = self._deck(['3500', '0.01'], 'restart_0_stage0.rst')

        gi._name_regridded_restart(current, self._deck(['350', '0.1']))

        assert self._restart(current) == ['restart_0_stage0_nx3500.rst', 'append']

    def test_an_unchanged_grid_reads_the_file_as_written(self):
        """No resample happens, so renaming would point at a file nothing writes."""
        current = self._deck(['350', '0.1'], 'restart_0_stage0.rst')

        gi._name_regridded_restart(current, self._deck(['350', '0.1']))

        assert self._restart(current) == ['restart_0_stage0.rst', 'append']

    def test_redistributed_cells_at_constant_nx_still_rename(self):
        """Same nx, different widths, is a different grid: run.py resamples, so the name changes."""
        current = self._deck(['2', '20.0', '6', '6.6667', '2', '20.0'], 'restart_0_stage0.rst')

        gi._name_regridded_restart(current, self._deck(['10', '10.0']))

        assert self._restart(current) == ['restart_0_stage0_nx10.rst', 'append']

    def test_an_undeclared_grid_is_left_alone(self):
        """Without xzones on both sides the chain cannot know the grid changed, and nor can this."""
        current = self._deck(None, 'restart_0_stage0.rst')

        gi._name_regridded_restart(current, self._deck(['350', '0.1']))

        assert self._restart(current) == ['restart_0_stage0.rst', 'append']

    def test_a_stage_with_no_restart_is_left_alone(self):
        current = self._deck(['3500', '0.01'])

        gi._name_regridded_restart(current, self._deck(['350', '0.1']))

        assert self._restart(current) is None


class TestRefineSpec:
    """Tests for normalising the two forms a refine entry may take."""

    def test_bare_factor_defaults_to_step(self):
        assert gi._refine_spec(10, 0) == (10, 'step')

    def test_absent_refine(self):
        assert gi._refine_spec(None, 0) == (None, 'step')

    def test_mapping_carries_the_method(self):
        assert gi._refine_spec({'factor': 4, 'method': 'linear'}, 1) == (4, 'linear')

    def test_mapping_without_method_defaults_to_step(self):
        assert gi._refine_spec({'factor': 4}, 1) == (4, 'step')

    def test_mapping_without_factor_raises(self):
        with pytest.raises(ValueError, match="omits 'factor'"):
            gi._refine_spec({'method': 'linear'}, 2)

    def test_unknown_mapping_key_raises(self):
        with pytest.raises(ValueError, match='Unknown key'):
            gi._refine_spec({'factor': 2, 'mode': 'linear'}, 0)

    def test_unknown_method_raises(self):
        with pytest.raises(ValueError, match='unknown refine method'):
            gi._refine_spec({'factor': 2, 'method': 'spline'}, 0)


class TestResolveGrid:
    """Tests for expanding the refine shorthand into explicit per-stage grids."""

    @staticmethod
    def _template(tmp_path, extra_blocks=''):
        from omphalos.template import Template

        source = Path(__file__).resolve().parents[1] / 'omphalos_test' / 'sukinda_column.in'
        text = source.read_text()
        if extra_blocks:
            text = text.replace('TEMPERATURE', f'TEMPERATURE\n{extra_blocks}', 1)
        deck = tmp_path / 'deck.in'
        deck.write_text(text)

        with contextlib.redirect_stdout(io.StringIO()):
            return Template({'template': str(deck), 'aqueous_database': None,
                             'catabolic_pathways': None, 'database': None, 'conditions': None,
                             'later_inputfiles': None})

    def test_dict_form_refines_every_stage_after_the_first(self, tmp_path):
        template = self._template(tmp_path)
        config = {'restart_chain': {'stages': 3, 'grid': {'refine': 2}}}

        with contextlib.redirect_stdout(io.StringIO()):
            resolved = gi.resolve_grid(config, template)

        assert len(resolved) == 3
        assert resolved[0] == {}
        assert resolved[1]['xzones'] == ['20', '5']
        assert resolved[2]['xzones'] == ['40', '2.5'], 'each stage refines the one before it'

    def test_list_form_refines_one_stage(self, tmp_path):
        template = self._template(tmp_path)
        config = {'restart_chain': {'stages': 2, 'grid': [{}, {'refine': 5}]}}

        with contextlib.redirect_stdout(io.StringIO()):
            resolved = gi.resolve_grid(config, template)

        assert resolved[1]['xzones'] == ['50', '2']

    def test_refine_follows_an_explicit_grid(self, tmp_path):
        """A stage may set its grid outright and a later one refine that."""
        template = self._template(tmp_path)
        config = {'restart_chain': {'stages': 2,
                                    'grid': [{'xzones': [4, 10.0, 12, 2.5, 4, 7.5]},
                                             {'refine': 2}]}}

        with contextlib.redirect_stdout(io.StringIO()):
            resolved = gi.resolve_grid(config, template)

        assert resolved[1]['xzones'] == ['8', '5', '24', '1.25', '8', '3.75']

    def test_data_files_are_refined_with_the_grid(self, tmp_path):
        """The gap this closes: a temperature file sized for the coarse grid makes the refined
        stage die with 'Fortran runtime error: End of file'."""
        (tmp_path / 'temps.dat').write_text('\n'.join(str(4.0 + i) for i in range(10)) + '\n')
        template = self._template(tmp_path, 'read_temperaturefile temps.dat')
        config = {'restart_chain': {'stages': 2, 'grid': {'refine': 2}}}

        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                resolved = gi.resolve_grid(config, template)
        finally:
            os.chdir(cwd)

        assert resolved[1]['files'] == {'temps.dat': 'temps_stage1.dat'}
        assert len(np.loadtxt(tmp_path / 'temps_stage1.dat')) == 20

    def test_refine_method_reaches_the_generated_files(self, tmp_path):
        """The wiring, not the maths: a method chosen in the config must reach the file writer.

        Step replication can only ever produce values already in the source, so a source of two
        distinct plateaux distinguishes the two methods without depending on any interpolated
        value in particular.
        """
        (tmp_path / 'poro.dat').write_text('\n'.join(['0.2'] * 5 + ['0.8'] * 5) + '\n')
        template = self._template(tmp_path, 'read_PorosityFile poro.dat')
        config = {'restart_chain': {'stages': 2,
                                    'grid': [{}, {'refine': {'factor': 3,
                                                             'method': 'linear'}}]}}

        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                resolved = gi.resolve_grid(config, template)
        finally:
            os.chdir(cwd)

        assert sc.zone_cell_count(resolved[1]['xzones']) == 30
        refined = np.loadtxt(tmp_path / 'poro_stage1.dat')
        assert len(refined) == 30
        intermediate = refined[(refined > 0.2 + 1e-12) & (refined < 0.8 - 1e-12)]
        assert len(intermediate) == 2, 'the linear method did not reach the file writer'

    def test_refine_mapping_defaults_to_step(self, tmp_path):
        """The mapping form without a method must behave exactly as the bare factor does."""
        (tmp_path / 'poro.dat').write_text('\n'.join(['0.2'] * 5 + ['0.8'] * 5) + '\n')
        template = self._template(tmp_path, 'read_PorosityFile poro.dat')
        config = {'restart_chain': {'stages': 2, 'grid': [{}, {'refine': {'factor': 3}}]}}

        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                gi.resolve_grid(config, template)
        finally:
            os.chdir(cwd)

        refined = np.loadtxt(tmp_path / 'poro_stage1.dat')
        assert set(np.unique(refined)) == {0.2, 0.8}, 'values were invented'

    def test_refined_files_are_staged(self, tmp_path):
        """rhea copies what the config names, so the generated file has to appear there."""
        (tmp_path / 'temps.dat').write_text('\n'.join(str(4.0 + i) for i in range(10)) + '\n')
        template = self._template(tmp_path, 'read_temperaturefile temps.dat')
        config = {'restart_chain': {'stages': 2, 'grid': {'refine': 2}}}

        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                gi.resolve_grid(config, template)
        finally:
            os.chdir(cwd)

        assert 'temps_stage1.dat' in gi.config_auxiliary_files(config)

    def test_wrong_length_file_is_left_alone(self, tmp_path, capsys):
        """A file stored on cell faces has a different row count, and guessing would corrupt it."""
        (tmp_path / 'flow.dat').write_text('\n'.join(str(i) for i in range(11)) + '\n')
        template = self._template(tmp_path, 'read_flowfile flow.dat')
        config = {'restart_chain': {'stages': 2, 'grid': {'refine': 2}}}

        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            gi.resolve_grid(config, template)
        finally:
            os.chdir(cwd)

        assert not config['restart_chain']['grid'][1].get('files')
        assert 'has 11 rows' in capsys.readouterr().out

    def test_refine_without_a_grid_to_refine_from(self, tmp_path):
        template = self._template(tmp_path)
        template.keyword_blocks['DISCRETIZATION'].contents.pop('xzones')
        config = {'restart_chain': {'stages': 2, 'grid': {'refine': 2}}}

        with pytest.raises(ValueError, match='declares xzones to refine from'):
            gi.resolve_grid(config, template)

    def test_unknown_key_is_rejected(self, tmp_path):
        template = self._template(tmp_path)
        config = {'restart_chain': {'stages': 2, 'grid': [{}, {'refined': 2}]}}

        with pytest.raises(ValueError, match='Unknown key'):
            gi.resolve_grid(config, template)

    def test_no_grid_is_a_no_op(self, tmp_path):
        template = self._template(tmp_path)

        assert gi.resolve_grid({'restart_chain': {'stages': 2}}, template) == []
        assert gi.resolve_grid({}, template) == []


class TestFormatTokenIsKept:
    """A read_*file keyword may carry a format specifier after the filename."""

    def test_porosity_format_survives_a_per_stage_override(self, tmp_path):
        """Dropping 'FullForm' would leave CrunchTope reading a two-column file as one column."""
        from omphalos.template import Template

        source = Path(__file__).resolve().parents[1] / 'omphalos_test' / 'sukinda_column.in'
        deck = tmp_path / 'deck.in'
        deck.write_text(source.read_text().replace(
            'POROSITY', 'POROSITY\nread_PorosityFile poro.dat FullForm', 1))
        with contextlib.redirect_stdout(io.StringIO()):
            template = Template({'template': str(deck), 'aqueous_database': None,
                                 'catabolic_pathways': None, 'database': None, 'conditions': None,
                                 'later_inputfiles': None})

        with contextlib.redirect_stdout(io.StringIO()):
            gi._configure_grid(template, {'restart_chain': {'grid': [{'porosity_file': 'fine.dat'}]}}, 0)

        assert template.keyword_blocks['POROSITY'].contents['read_PorosityFile'] == \
            ['fine.dat', 'FullForm']

    def test_renaming_a_file_keeps_its_format(self, tmp_path):
        from omphalos.template import Template

        source = Path(__file__).resolve().parents[1] / 'omphalos_test' / 'sukinda_column.in'
        deck = tmp_path / 'deck.in'
        deck.write_text(source.read_text().replace(
            'TEMPERATURE', 'TEMPERATURE\nread_temperaturefile t.dat FullForm', 1))
        with contextlib.redirect_stdout(io.StringIO()):
            template = Template({'template': str(deck), 'aqueous_database': None,
                                 'catabolic_pathways': None, 'database': None, 'conditions': None,
                                 'later_inputfiles': None})

        gi._rename_data_file(template, 't.dat', 't_stage1.dat')

        assert template.keyword_blocks['TEMPERATURE'].contents['read_temperaturefile'] == \
            ['t_stage1.dat', 'FullForm']


# A deck with an ISOTOPES block, minimal but complete enough to parse and print. The recrystallisation
# option is the last token of the 'mineral' line, and both 'primary' and 'mineral' repeat as leftmost
# words, so the block is keyed on the rare isotope rather than on the keyword.
ISOTOPE_DECK = """TITLE
isotope sweep
END

RUNTIME
database  d.dbs
END

OUTPUT
spatial_profile  80.0
END

PRIMARY_SPECIES
Ca++
Ca44++
END

MINERALS
CalciteRifle    -label default -rate  -4.1
Calcite44Rifle  -label default -rate  -4.10086946
END

ISOTOPES
primary  Ca44++  Ca++  0.021667
mineral  Calcite44Rifle  CalciteRifle  bulk
END

DISCRETIZATION
xzones  1  1.0
END

Condition amendment
temperature  25.0
END

INITIAL_CONDITIONS
amendment  1-1  1-1  1-1
END
"""


class TestIsotopeSweep:
    """Tests for sweeping the ISOTOPES block.

    The Ex8 short-course exercise sweeps the recrystallisation option -- bulk, surface or none -- which
    decides how much of the mineral already present the isotopes may exchange with. It is a word, not a
    number, and it sits in a block whose leftmost words repeat.
    """

    def _template(self, tmp_path, config_extra):
        deck = tmp_path / 'iso.in'
        deck.write_text(ISOTOPE_DECK)

        from omphalos.template import Template

        config = {
            'template': str(deck), 'database': None, 'aqueous_database': None,
            'catabolic_pathways': None, 'number_of_files': 3, 'timeout': 60, 'conditions': None,
        }
        config.update(config_extra)

        with contextlib.redirect_stdout(io.StringIO()):
            return Template(config)

    def test_isotopes_is_sweepable(self):
        """Test that the block is addressable at all, at its last token."""
        assert gi.CT_IDs['isotopes'] == ['ISOTOPES', -1]

    def test_the_recrystallisation_option_reaches_every_run(self, tmp_path):
        """Test that each run's deck carries the word the config gave it."""
        template = self._template(tmp_path, {
            'isotopes': {'Calcite44Rifle': ['custom', ['none', 'surface', 'bulk']]},
        })

        with contextlib.redirect_stdout(io.StringIO()):
            file_dict = gi.configure_input_files(template, str(tmp_path) + '/')

        options = [file_dict[run].keyword_blocks['ISOTOPES'].contents['Calcite44Rifle'][-1]
                   for run in sorted(file_dict)]
        assert options == ['none', 'surface', 'bulk']

    def test_the_primary_line_is_left_alone(self, tmp_path):
        """Test that sweeping the mineral line does not disturb the isotope pair or its standard."""
        template = self._template(tmp_path, {
            'isotopes': {'Calcite44Rifle': ['custom', ['none', 'surface', 'bulk']]},
        })

        with contextlib.redirect_stdout(io.StringIO()):
            file_dict = gi.configure_input_files(template, str(tmp_path) + '/')

        for run in file_dict:
            assert file_dict[run].keyword_blocks['ISOTOPES'].contents['Ca44++'] == \
                ['primary', 'Ca++', '0.021667']

    def test_the_written_deck_round_trips(self, tmp_path):
        """Test that the swept block prints back in the order CrunchTope reads it.

        The ISOTOPES block is keyed on its second word, so printing has to put the key back in the
        middle: 'mineral <rare> <common> <option>'. A block that printed in dictionary order would be
        read by CrunchTope as a different statement entirely.
        """
        template = self._template(tmp_path, {
            'isotopes': {'Calcite44Rifle': ['custom', ['none', 'surface', 'bulk']]},
        })

        with contextlib.redirect_stdout(io.StringIO()):
            file_dict = gi.configure_input_files(template, str(tmp_path) + '/')

        written = tmp_path / 'written.in'
        file_dict[1].path = written
        file_dict[1].print()

        lines = [line.split() for line in written.read_text().splitlines()]
        assert ['mineral', 'Calcite44Rifle', 'CalciteRifle', 'surface'] in lines
        assert ['primary', 'Ca44++', 'Ca++', '0.021667'] in lines
