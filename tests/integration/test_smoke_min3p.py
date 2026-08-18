"""End-to-end tests that actually run MIN3P.

The MIN3P unit tests in `tests/unit/test_min3p.py` parse the shipped benchmark decks and check that
a read -> print round trip reproduces them line for line, but nothing there asks the solver whether
what Omphalos wrote is a file it will read. That is a different question: a deck can round-trip
perfectly and still be rejected, because MIN3P's list-directed reader cares about token counts and
about constraints spanning blocks that no parser test knows of. One such constraint surfaced while
these tests were being written -- a restart chain whose early stages end before a time the deck's
`output control` block asks for is refused outright, which is why the chain below extends past the
deck's output time rather than subdividing it.

These skip where no MIN3P binary or benchmark tree is configured, the same way `test_min3p.py` gates
its benchmark round trips. They are the MIN3P counterpart of `test_smoke.py`, and cost a few seconds
rather than the milliseconds of `tests/unit`.
"""

import contextlib
import io
import os
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke


def min3p_binary():
    """The configured MIN3P executable, or None where there is none to run."""
    try:
        from min3p.run import MIN3P_BINARY
    except ImportError:
        return None

    path = Path(MIN3P_BINARY)

    return path if path.is_file() and os.access(path, os.X_OK) else None


def min3p_examples():
    """Root of the MIN3P examples tree, resolved as `tests/unit/test_min3p.py` resolves it."""
    root = os.environ.get('MIN3P_EXAMPLES')

    if root:
        return Path(root)

    try:
        from min3p.settings import min3p_examples as configured
    except ImportError:
        return Path('/path/to/MIN3P/Examples')

    return Path(configured)


EXAMPLES = min3p_examples()
APPELO = EXAMPLES / 'Benchmarks/benchmarks_standard/batch/appelo'
DISSOL = EXAMPLES / 'Benchmarks/benchmarks_standard/reactran/dissol'
DATABASE = EXAMPLES / 'database/default'

needs_min3p = pytest.mark.skipif(
    min3p_binary() is None or not DATABASE.is_dir(),
    reason='no MIN3P binary or database directory configured in min3p/settings.py',
)


def _copy_deck(source, destination):
    """Copy a benchmark's whole directory, as a modeller running it by hand would.

    A MIN3P deck travels with auxiliary files (`.hyc`, `.lbc`, `.lay`) that the executable reads from
    the working directory, so the deck alone is not enough to run.
    """
    destination.mkdir(parents=True, exist_ok=True)

    for path in source.iterdir():
        if path.is_file():
            shutil.copy(path, destination / path.name)

    return destination


def _config(deck, number_of_files=1, **extra):
    """A config for one of the benchmark decks, with the database repointed.

    The benchmarks ship a Windows-style relative database path, which resolves nowhere on this
    machine; `database_directory` is what generate_inputs rewrites it to.
    """
    config = {
        'template': str(deck),
        'number_of_files': number_of_files,
        'timeout': 600,
        'database_directory': str(DATABASE),
    }
    config.update(extra)

    return config


def _run(input_file, directory, file_num=0, timeout=600):
    """Write and run one InputFile in its own directory, quietly."""
    from min3p import run as min3p_run

    input_file.path = Path(directory) / Path(input_file.path).name

    with contextlib.redirect_stdout(io.StringIO()):
        min3p_run.input_file(input_file, file_num, str(directory), timeout)

    return input_file


@pytest.fixture
def appelo(tmp_path):
    """The appelo batch benchmark (kinetic calcite dissolution), in a directory of its own."""
    return _copy_deck(APPELO, tmp_path / 'appelo')


@pytest.fixture
def dissol(tmp_path):
    """The dissol reactive-transport benchmark, which the shipped dissol_sweep example sweeps."""
    return _copy_deck(DISSOL, tmp_path / 'dissol')


@pytest.mark.skipif(not APPELO.is_dir(), reason='MIN3P appelo benchmark not available')
@needs_min3p
class TestMin3pRuns:
    """One real run, start to finish, through the code paths a sweep uses."""

    def _prepare(self, directory, **extra):
        from min3p import generate_inputs as gi
        from min3p.template import Template

        config = _config(directory / 'appelo.dat', **extra)
        template = Template(config)

        return gi.configure_input_files(template, str(directory))

    def test_the_shipped_deck_completes(self, appelo):
        input_file = _run(self._prepare(appelo)[0], appelo)

        assert input_file.error_code == 0, 'MIN3P did not complete'

    def test_it_writes_the_output_omphalos_parses(self, appelo):
        # The per-timestep output files are what results.nc is built from, so their absence is the
        # failure mode that matters even when MIN3P exits cleanly.
        input_file = _run(self._prepare(appelo)[0], appelo)

        written = {path.suffix.lstrip('.') for path in appelo.glob('appelo_*.*')}
        assert 'lbm' in written, sorted(written)
        assert set(input_file.results), 'the run completed but Omphalos parsed no output'


@pytest.mark.skipif(not APPELO.is_dir(), reason='MIN3P appelo benchmark not available')
@needs_min3p
class TestSweptDeckIsReadable:
    """A deck Omphalos wrote has to be one MIN3P reads, and reads the swept value from.

    Two clean exits prove only that the file parsed. What matters is that the token generate_inputs
    replaced reached the solver, which two different answers demonstrate and a passing parse does
    not.
    """

    def test_a_swept_value_reaches_the_solver(self, appelo, tmp_path):
        from min3p import generate_inputs as gi
        from min3p.template import Template

        config = _config(
            appelo / 'appelo.dat',
            number_of_files=2,
            modifications={
                'calcite_volume': {
                    'alias': 'calcite_volume',
                    'method': 'custom',
                    'params': [0.001, 0.05],
                },
            },
        )
        file_dict = gi.configure_input_files(Template(config), str(appelo))

        answers = []
        for file_num in sorted(file_dict):
            directory = _copy_deck(APPELO, tmp_path / f'run{file_num}')
            input_file = _run(file_dict[file_num], directory, file_num=file_num)
            assert input_file.error_code == 0, f'run {file_num} did not complete'
            answers.append(input_file.results['lbm']['pH'].values.ravel()[-1])

        assert answers[0] != answers[1], (
            f'both runs ended at pH {answers[0]}: the swept calcite volume never reached the solver'
        )


@pytest.mark.skipif(not DISSOL.is_dir(), reason='MIN3P dissol benchmark not available')
@needs_min3p
class TestTransportDeckRuns:
    """The transport blocks a 1-D sweep edits, put to the solver.

    appelo is a batch problem: it exercises none of the spatial discretisation, flow or
    reactive-transport blocks, and so none of the sub-keyword disambiguation (`concentration
    input#2`) that addressing a boundary zone depends on.
    """

    def _prepare(self, directory, **extra):
        from min3p import generate_inputs as gi
        from min3p.template import Template

        return gi.configure_input_files(
            Template(_config(directory / 'dissol.dat', **extra)), str(directory)
        )

    def test_an_edited_inflow_boundary_runs(self, dissol):
        # The modification the shipped dissol_sweep example makes: the inflow boundary's free H+.
        file_dict = self._prepare(
            dissol,
            modifications={
                'inflow_h': {
                    'block': 'boundary conditions - reactive transport',
                    'keyword': 'concentration input',
                    'line': 0,
                    'token': 0,
                    'method': 'custom',
                    'params': [1.98e-2],
                },
            },
        )
        input_file = _run(file_dict[0], dissol)

        assert input_file.error_code == 0, 'MIN3P did not complete'
        assert 'gsc' in input_file.results, sorted(input_file.results)

    def test_a_restart_chain_completes(self, dissol):
        """A chain has to hand its state on, which only the binary can confirm.

        `run_staged` promotes whichever of MIN3P's two rolling `restart.tmp` files is the more
        advanced to `restart.dat` between stages. Nothing about that is visible to a unit test: a
        chain that dropped its state would still exit cleanly, and would simply repeat stage 0.

        The stage times extend past the deck's 6-day output time rather than subdividing it, because
        MIN3P refuses a run whose final solution time falls short of a requested output time.
        """
        from min3p import generate_inputs as gi
        from min3p import run as min3p_run
        from min3p.template import Template

        config = _config(
            dissol / 'dissol.dat',
            restart_chain={'stages': 2, 'final_times': [6.0, 12.0], 'append': 'append results'},
        )
        staged = gi.configure_staged_input_files(Template(config), str(dissol))

        with contextlib.redirect_stdout(io.StringIO()):
            final = min3p_run.run_staged(staged[0], 0, str(dissol), 600)

        assert final.error_code == 0, 'the restart chain did not complete'

        # Stage 1 restarted rather than starting over: its appended spatial output carries times the
        # single-stage run above cannot reach.
        single = _run(self._prepare(_copy_deck(DISSOL, dissol.parent / 'single'))[0],
                      dissol.parent / 'single')
        assert final.results['gsc'].sizes['output'] > single.results['gsc'].sizes['output']
