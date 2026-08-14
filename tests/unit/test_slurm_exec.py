"""Unit tests for rhea/slurm_exec.py."""

from pathlib import Path
from unittest.mock import patch

import pytest

# slurm_exec imports omphalos.run, which imports omphalos.settings -- created by install.sh and not
# tracked, so skip where it is absent.
pytest.importorskip(
    'omphalos.settings',
    reason='requires omphalos/settings.py (created by install.sh)',
)

from rhea import slurm_exec       # noqa: E402


class TestAuxiliaryFilesAreWritten:
    """Tests that the non-staged CrunchTope path writes the auxiliary namelists before running.

    The sequential path (run.input_file) and the staged path (run.run_staged_input) both call
    run._print_aux_files. This branch called run.crunchtope directly and skipped it, so a deck
    needing CatabolicPathways.in never got one, and -- silently -- a sweep of the 'namelists:'
    section ran every file against the unmodified aqueous database, because the only copy in the
    run directory was the verbatim one prep_directories.sh had placed there.
    """

    CONFIG = {
        'template': 'model.in',
        'database': 'database.dbs',
        'aqueous_database': 'aqueous.dbs',
        'catabolic_pathways': 'CatabolicPathways.in',
        'timeout': 300,
    }

    def test_aux_files_are_printed_before_crunchtope_runs(self):
        """Test that _print_aux_files is called, and called before the simulation starts."""
        calls = []

        with patch('omphalos.template.Template') as template, \
             patch('omphalos.run._print_aux_files',
                   side_effect=lambda *a, **k: calls.append('aux')) as aux, \
             patch('omphalos.run.crunchtope',
                   side_effect=lambda *a, **k: calls.append('run')):
            template.return_value.path = Path('model.in')
            slurm_exec.execute('3', dict(self.CONFIG), pflo=False)

        assert aux.called, '_print_aux_files was not called on the non-staged CrunchTope path'
        assert calls == ['aux', 'run'], f'expected aux files written before the run, got {calls}'

    def test_aux_files_are_printed_into_the_run_directory(self):
        """Test that the namelists are written to run<N>, not to the working directory."""
        with patch('omphalos.template.Template') as template, \
             patch('omphalos.run._print_aux_files') as aux, \
             patch('omphalos.run.crunchtope'):
            template.return_value.path = Path('model.in')
            slurm_exec.execute('7', dict(self.CONFIG), pflo=False)

        destination = aux.call_args[0][1]
        assert Path(destination).name == 'run7'
        assert Path(destination).is_absolute(), 'aux files must be written to a resolved path'

    def test_pflotran_path_does_not_print_aux_files(self):
        """Test that the PFLOTRAN branch is untouched: it has no namelists to write."""
        with patch('pflotran.template.Template') as template, \
             patch('omphalos.run._print_aux_files') as aux, \
             patch('pflotran.run.pflotran'):
            template.return_value.path = Path('model.in')
            slurm_exec.execute('0', dict(self.CONFIG), pflo=True)

        assert not aux.called


class TestDatabaseIsReadFromTheRunDirectory:
    """The run directory's database is the swept one; the config names the template's.

    Reading the config's path here would hand every run the unswept file, and _print_aux_files
    would then write it over the swept copy -- the same failure the namelists had, and invisible,
    because CrunchTope would run happily on the wrong numbers.
    """

    CONFIG = {
        'template': 'model.in',
        'database': 'database.dbs',
        'aqueous_database': 'aqueous.dbs',
        'catabolic_pathways': 'CatabolicPathways.in',
        'timeout': 300,
    }

    def _config_seen_by_template(self, config):
        with patch('omphalos.template.Template') as template, \
             patch('omphalos.run._print_aux_files'), \
             patch('omphalos.run.crunchtope'):
            template.return_value.path = Path('model.in')
            slurm_exec.execute('4', dict(config), pflo=False)

        return template.call_args[0][0]

    def test_database_path_points_into_the_run_directory(self):
        seen = self._config_seen_by_template(self.CONFIG)

        assert Path(seen['database']).parent.name == 'run4'
        assert Path(seen['database']).name == 'database.dbs'

    def test_the_other_auxiliary_files_still_do_too(self):
        seen = self._config_seen_by_template(self.CONFIG)

        assert Path(seen['aqueous_database']).parent.name == 'run4'
        assert Path(seen['catabolic_pathways']).parent.name == 'run4'

    def test_a_config_naming_no_database_is_left_alone(self):
        config = dict(self.CONFIG)
        config['database'] = None

        assert self._config_seen_by_template(config)['database'] is None


class TestStagedConfigsPointAtTheirOwnAuxiliaryFiles:
    """Each stage of a chain reads the auxiliary files rhea/main.py wrote for that stage.

    Reading the run directory's copies instead handed every stage the same ones -- stage 0's, since
    that is what runs first -- so a 'staged' sweep of database_parameters or namelists was silently
    discarded and the chain ran every stage on stage 0's values.
    """

    CONFIG = {
        'template': 'model.in',
        'database': 'database.dbs',
        'aqueous_database': 'aqueous.dbs',
        'catabolic_pathways': 'CatabolicPathways.in',
        'timeout': 300,
        'restart_chain': {'stages': 2},
    }

    def _stage_configs(self, tmp_path, monkeypatch, make_aux=True):
        monkeypatch.chdir(tmp_path)
        run_dir = tmp_path / 'run5'
        run_dir.mkdir()

        if make_aux:
            for stage_num in range(2):
                stage_aux = run_dir / f'stage{stage_num}_aux'
                stage_aux.mkdir()
                for name in ('database.dbs', 'aqueous.dbs', 'CatabolicPathways.in'):
                    (stage_aux / name).write_text('')

        with patch('omphalos.template.Template') as template, \
             patch('omphalos.run.run_staged_input'):
            template.return_value.path = Path('model.in')
            slurm_exec.execute('5', dict(self.CONFIG), pflo=False)

        return [call.args[0] for call in template.call_args_list]

    def test_each_stage_reads_its_own_database(self, tmp_path, monkeypatch):
        configs = self._stage_configs(tmp_path, monkeypatch)

        assert [Path(c['database']).parent.name for c in configs] == ['stage0_aux', 'stage1_aux']

    def test_each_stage_reads_its_own_namelists(self, tmp_path, monkeypatch):
        configs = self._stage_configs(tmp_path, monkeypatch)

        assert [Path(c['aqueous_database']).parent.name for c in configs] == [
            'stage0_aux', 'stage1_aux'
        ]
        assert [Path(c['catabolic_pathways']).parent.name for c in configs] == [
            'stage0_aux', 'stage1_aux'
        ]

    def test_without_per_stage_files_the_run_directory_copies_are_used(self, tmp_path, monkeypatch):
        # A chain generated before this existed, or one whose aux files were staged by hand.
        configs = self._stage_configs(tmp_path, monkeypatch, make_aux=False)

        assert [Path(c['database']).parent.name for c in configs] == ['run5', 'run5']
