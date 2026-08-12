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
