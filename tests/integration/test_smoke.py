"""End-to-end tests that actually run CrunchTope.

Every unit test in this suite mocks the solver: `pexpect.spawn` is a `Mock`, so nothing verifies
that what Omphalos writes is a file CrunchTope will read. That gap is not theoretical. The bugs it
has hidden were all found by running the binary by hand:

- a mineral kinetics block appended after the section's trailing `+` separator, which made
  CrunchTope's `BreakFind` scan to end of file;
- `Quartztope` written on `30SiO2(aq)`, so a deck naming it needs the isotope pair declared;
- an `ISOTOPES` block that needs a `mineral` line per pair, without which two isotope minerals
  become independent phases;
- swept auxiliary files never reaching the run directories.

These skip where no CrunchTope binary is configured, which is the same pattern `test_min3p.py` uses
for its benchmark decks. They are slow by the standards of the rest of the suite -- seconds, not
milliseconds -- so they live apart from `tests/unit`.
"""

import contextlib
import io
import os
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

EXAMPLES = Path(__file__).parent.parent.parent / 'omphalos' / 'examples'


def crunchtope_binary():
    """The configured CrunchTope, or None where there is none to run."""
    try:
        from omphalos.settings import crunch_dir
    except ImportError:
        return None

    path = Path(crunch_dir)

    return path if path.is_file() and os.access(path, os.X_OK) else None


needs_crunchtope = pytest.mark.skipif(
    crunchtope_binary() is None,
    reason='no CrunchTope binary configured in omphalos/settings.py',
)


class _Stub:
    """The little of an InputFile that run.crunchtope touches.

    Deliberately not a real InputFile: building one needs a parsed deck, and what these tests are
    checking is the solver and the files, not the object model. `get_results` records that the parse
    was attempted, since a clean exit that writes nothing readable is a failure worth catching.
    """

    def __init__(self, deck):
        self.path = deck
        self.error_code = 0
        self.results = {}
        self.parsed = False

    def get_results(self, directory, file_offset=0):
        self.parsed = True


@pytest.fixture
def quartz_column(tmp_path):
    """The shipped quartz deck and database, in a directory of their own."""
    source = EXAMPLES / 'quartz_flow_sweep'
    for name in ('quartz_column.in', 'datacom.dbs'):
        shutil.copy(source / name, tmp_path / name)

    return tmp_path


@needs_crunchtope
class TestCrunchTopeRuns:
    """One real run, start to finish, through the code paths a sweep uses."""

    def _run(self, directory, deck='quartz_column.in'):
        from omphalos import run as run_module

        original = os.getcwd()
        os.chdir(directory)
        try:
            input_file = _Stub(directory / deck)
            with contextlib.redirect_stdout(io.StringIO()):
                run_module.crunchtope(input_file, 0, 600, str(directory))
            return input_file
        finally:
            os.chdir(original)

    def test_the_shipped_deck_completes(self, quartz_column):
        input_file = self._run(quartz_column)

        assert getattr(input_file, 'error_code', 0) == 0, 'CrunchTope did not complete'

    def test_it_writes_the_output_omphalos_parses(self, quartz_column):
        # The .tec files are what results.nc is built from, so their absence is the failure mode
        # that matters even when CrunchTope exits cleanly.
        input_file = self._run(quartz_column)

        written = {path.name for path in quartz_column.glob('*.tec')}
        assert 'totcon1.tec' in written, sorted(written)
        assert 'volume1.tec' in written, sorted(written)
        assert input_file.parsed, 'the run completed but Omphalos never read its output'


@needs_crunchtope
class TestGeneratedDatabaseIsReadable:
    """The database Omphalos writes has to be one CrunchTope reads.

    This is the check that the unit tests structurally cannot make. A row of the wrong width, a lost
    section separator or a mangled column would all pass every parser test and fail here.
    """

    def _write_and_run(self, directory, edit):
        import warnings

        from omphalos.database import Database

        database = Database(str(directory / 'datacom.dbs'))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            edit(database)
        database.print(str(directory / 'datacom.dbs'))

        from omphalos import run as run_module

        original = os.getcwd()
        os.chdir(directory)
        try:
            input_file = _Stub(directory / 'quartz_column.in')
            with contextlib.redirect_stdout(io.StringIO()):
                run_module.crunchtope(input_file, 0, 600, str(directory))
            return getattr(input_file, 'error_code', 0)
        finally:
            os.chdir(original)

    def test_a_surgically_edited_database_still_runs(self, quartz_column):
        def edit(database):
            database.modify('minerals', 'Quartz', 'log_k', [-3.5] * len(database.temp_field))

        assert self._write_and_run(quartz_column, edit) == 0

    def test_an_augmented_database_still_runs(self, quartz_column):
        # A row Omphalos wrote from scratch, rather than one it edited.
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        import io as io_module

        path = quartz_column / 'datacom.dbs'
        with io_module.open(path, newline='') as source:
            lines = source.readlines()
        with io_module.open(path, 'w', newline='') as target:
            target.writelines(line for line in lines if not line.startswith("'Anhydrite'"))

        def edit(database):
            from omphalos.logk import LogKCalculator
            LogKCalculator().add_species(database, {'minerals': ['Anhydrite']},
                                         on_unknown='leave')

        assert self._write_and_run(quartz_column, edit) == 0

    def test_a_database_with_an_isotope_added_still_runs(self, quartz_column):
        # The case that found the trailing '+' separator bug: adding a mineral kinetics block.
        def edit(database):
            from omphalos.isotopes import add_isotope
            add_isotope(database, 'S', '34', parents=['SO4--'],
                        species=['CaSO4(aq)', 'Anhydrite'],
                        names={'Anhydrite': 'Anhydrite34'})

        assert self._write_and_run(quartz_column, edit) == 0
