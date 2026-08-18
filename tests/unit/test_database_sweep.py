"""Tests for sweeping thermodynamic database parameters.

The capability these cover is the one the CrunchFlow short-course exercises need and Omphalos did
not have: varying an ion-exchange selectivity coefficient, or a mineral rate constant, across a set
of runs. Those numbers live in the .dbs, not in the deck.
"""

import contextlib
import copy
import io
import os

import pytest

from omphalos import generate_inputs as gi
from omphalos import run as run_module
from omphalos.database import Database
from omphalos.template import Template

EXCHANGE_SWEEP = {
    'exchange': {
        'CaXRifle': {
            'log_k': ['linspace', [-1.2, -0.6]],
        },
    },
}


@pytest.fixture
def in_test_dir(omphalos_test_dir):
    """Run inside the test data directory, since config paths are relative to it."""
    original = os.getcwd()
    os.chdir(omphalos_test_dir)
    try:
        yield omphalos_test_dir
    finally:
        os.chdir(original)


@pytest.fixture
def sweep_config(sample_config):
    config = copy.deepcopy(sample_config)
    config['number_of_files'] = 3
    config['database_parameters'] = copy.deepcopy(EXCHANGE_SWEEP)
    return config


@pytest.fixture
def template(sweep_config, in_test_dir):
    with contextlib.redirect_stdout(io.StringIO()):
        return Template(sweep_config)


class TestEvaluateConfig:
    def test_database_parameters_are_evaluated(self, sweep_config):
        modified = gi.evaluate_config(sweep_config)

        assert modified['database_parameters']['exchange']['CaXRifle']['log_k'] == pytest.approx(
            [-1.2, -0.9, -0.6]
        )

    def test_absent_from_config_means_absent_from_results(self, sample_config):
        assert 'database_parameters' not in gi.evaluate_config(sample_config)

    def test_registered_as_a_sweepable_block(self):
        assert 'database_parameters' in gi.CT_IDs

    def test_staged_database_parameters_are_detected(self, sweep_config):
        sweep_config['database_parameters']['exchange']['CaXRifle']['log_k'] = [
            'staged', [[-1.2], [-0.6]]
        ]
        assert gi.has_staged_params(sweep_config)

    def test_unstaged_database_parameters_are_not(self, sweep_config):
        assert not gi.has_staged_params(sweep_config)


class TestTemplate:
    def test_database_is_parsed_when_a_sweep_asks_for_it(self, template):
        assert isinstance(template.database, Database)

    def test_database_is_left_alone_otherwise(self, sample_config, in_test_dir):
        # Parsing 3500 lines per template is not free, and a config that edits nothing in the
        # database wants the file staged exactly as it is.
        with contextlib.redirect_stdout(io.StringIO()):
            plain = Template(sample_config)

        assert plain.database is None


class TestPerRunDatabases:
    @pytest.fixture
    def file_dict(self, template, tmp_path):
        with contextlib.redirect_stdout(io.StringIO()):
            return gi.configure_input_files(template, str(tmp_path) + '/', rhea=True)

    def test_each_run_gets_its_own_value(self, file_dict):
        found = [
            file_dict[run].database.value('exchange', 'CaXRifle', 'log_k') for run in file_dict
        ]
        assert found == pytest.approx([-1.2, -0.9, -0.6])

    def test_databases_are_not_shared_between_runs(self, file_dict):
        assert len({id(file_dict[run].database.lines) for run in file_dict}) == len(file_dict)

    def test_the_parse_is_shared_rather_than_copied(self, file_dict, template):
        # A deep copy per run of several thousand parsed species objects would cost of order a
        # gigabyte over a hundred runs. Only the lines are copied.
        assert all(
            file_dict[run].database.index is template.database.index for run in file_dict
        )

    def test_the_template_database_is_not_edited(self, template, file_dict):
        assert template.database.value('exchange', 'CaXRifle', 'log_k') == pytest.approx(-0.9)

    def test_only_the_swept_line_differs_between_runs(self, file_dict):
        runs = list(file_dict)
        first = file_dict[runs[0]].database.lines
        last = file_dict[runs[-1]].database.lines
        differing = [i for i, (a, b) in enumerate(zip(first, last)) if a != b]

        assert differing == [file_dict[runs[0]].database.exchange['CaXRifle'].line_index]


class TestStagedRuns:
    def test_each_stage_gets_its_own_database(self, sweep_config, in_test_dir, tmp_path):
        sweep_config['restart_chain'] = {'stages': 2}
        sweep_config['database_parameters']['exchange']['CaXRifle']['log_k'] = [
            'staged', [[-1.2, -1.2, -1.2], [-0.6, -0.6, -0.6]]
        ]

        with contextlib.redirect_stdout(io.StringIO()):
            template = Template(sweep_config)
            staged = gi.configure_staged_input_files(template, str(tmp_path) + '/', rhea=True)

        for run in staged:
            values = [
                staged[run][stage].database.value('exchange', 'CaXRifle', 'log_k')
                for stage in staged[run]
            ]
            assert values == pytest.approx([-1.2, -0.6])


class TestPrintAuxFiles:
    """One write point covers the sequential, rhea and staged paths."""

    def test_database_is_written_under_the_name_the_deck_uses(self, template, tmp_path):
        input_file = template.make_dict()[0]
        input_file.database.modify('exchange', 'CaXRifle', 'log_k', -1.25)

        run_module._print_aux_files(input_file, tmp_path)

        written = Database(str(tmp_path / 'SukindaCr53.dbs'))
        assert written.value('exchange', 'CaXRifle', 'log_k') == pytest.approx(-1.25)

    def test_nothing_is_written_when_no_database_is_carried(self, sample_config, in_test_dir,
                                                            tmp_path):
        with contextlib.redirect_stdout(io.StringIO()):
            plain = Template(sample_config)

        run_module._print_aux_files(plain.make_dict()[0], tmp_path)

        assert not (tmp_path / 'SukindaCr53.dbs').exists()


class TestConfigErrors:
    def test_sweeping_without_a_database_fails_loudly(self, sweep_config, in_test_dir):
        # Doing nothing here would run every case against the same unedited database. Caught when
        # the template is read, which is before anything has been generated.
        sweep_config['database'] = None

        with pytest.raises(ValueError, match="need a 'database' entry"):
            with contextlib.redirect_stdout(io.StringIO()):
                Template(sweep_config)

    @pytest.mark.parametrize('section', ['database_parameters', 'database_logk',
                                         'database_isotopes'])
    def test_every_database_section_needs_a_database(self, sample_config, in_test_dir, section):
        # database_logk and database_isotopes used to be skipped in silence.
        import copy as copy_module

        config = copy_module.deepcopy(sample_config)
        config['database'] = None
        config.pop('database_parameters', None)
        config[section] = [{'element': 'Ca', 'label': 44}] if section == 'database_isotopes' else {
            'exchange': {'CaXRifle': {'log_k': ['constant', -1.0]}}}

        with pytest.raises(ValueError, match=section):
            with contextlib.redirect_stdout(io.StringIO()):
                Template(config)

    def test_unknown_species_fails_at_generation_time(self, sweep_config, in_test_dir, tmp_path):
        sweep_config['database_parameters'] = {
            'exchange': {'NotASpecies': {'log_k': ['constant', -1.0]}}
        }

        with contextlib.redirect_stdout(io.StringIO()):
            template = Template(sweep_config)

        with pytest.raises(KeyError, match="not in the 'exchange' section"):
            gi.configure_input_files(template, str(tmp_path) + '/', rhea=True)


class TestSurfaceComplexation:
    """Surface complexation constants are fitted parameters, swept for the same reasons as
    exchange coefficients. The section was indexed and editable but never exercised end to end."""

    @pytest.fixture
    def swept(self, sample_config, in_test_dir, tmp_path):
        config = copy.deepcopy(sample_config)
        config['number_of_files'] = 3
        config['database_parameters'] = {
            'surface_complexation': {'>FeO-_str': {'log_k': ['custom', [-8.5, -8.8, -9.1]]}},
        }
        with contextlib.redirect_stdout(io.StringIO()):
            template = Template(config)
            return gi.configure_input_files(template, str(tmp_path) + '/', rhea=True)

    def test_each_run_gets_its_own_constant(self, swept):
        found = [
            float(swept[run].database.value('surface_complexation', '>FeO-_str', 'log_k')[0])
            for run in swept
        ]
        assert found == pytest.approx([-8.5, -8.8, -9.1])

    def test_only_that_row_changes(self, swept):
        runs = list(swept)
        first = swept[runs[0]].database.lines
        last = swept[runs[-1]].database.lines
        differing = [i for i, (a, b) in enumerate(zip(first, last)) if a != b]

        assert differing == [
            swept[runs[0]].database.surface_complexation['>FeO-_str'].line_index
        ]

    def test_a_scalar_fills_the_whole_vector(self, swept):
        # Worth pinning: many surface complexation rows carry data at 25 C only, the rest being the
        # no-data value, and a scalar sweep replaces all eight points. Consistent with minerals, but
        # it changes the row's temperature dependence.
        values = [float(v) for v in
                  swept[0].database.value('surface_complexation', '>FeO-_str', 'log_k')]

        assert len(set(values)) == 1 and values[0] == pytest.approx(-8.5)
