"""Unit tests for omphalos/namelist.py."""

from pathlib import Path

import pytest

from omphalos.namelist import CrunchNameList

NML_PATH = Path(__file__).parent.parent / 'omphalos_test' / 'CatabolicPathways.in'
# f90nml lowercases all namelist keys on read.
LIST_NAME = 'catabolicpathway'


@pytest.fixture(scope='module')
def nml():
    return CrunchNameList(str(NML_PATH))


class TestFindReaction:
    def test_finds_ferrihydrite(self, nml):
        r = nml.find_reaction(LIST_NAME, 'Ferrihydrite_DIRB')
        assert r['name'] == 'Ferrihydrite_DIRB'

    def test_finds_goethite(self, nml):
        r = nml.find_reaction(LIST_NAME, 'Goethite_DIRB')
        assert r['name'] == 'Goethite_DIRB'

    def test_finds_uo2(self, nml):
        r = nml.find_reaction(LIST_NAME, 'UO2(s)')
        assert r['name'] == 'UO2(s)'

    def test_missing_reaction_raises_key_error(self, nml):
        with pytest.raises(KeyError, match='nonexistent_reaction'):
            nml.find_reaction(LIST_NAME, 'nonexistent_reaction')

    def test_does_not_raise_on_first_non_match(self, nml):
        # Regression: the old implementation returned None after the first
        # non-matching reaction. Verify all three reactions can be found
        # even though none is listed first.
        for name in ('Ferrihydrite_DIRB', 'Goethite_DIRB', 'UO2(s)'):
            r = nml.find_reaction(LIST_NAME, name)
            assert r is not None

    def test_ferrihydrite_keq(self, nml):
        r = nml.find_reaction(LIST_NAME, 'Ferrihydrite_DIRB')
        assert r['keq'] == pytest.approx(14.439875)

    def test_goethite_direction(self, nml):
        r = nml.find_reaction(LIST_NAME, 'Goethite_DIRB')
        assert r['direction'] == -1


class TestPrintRoundtrip:
    def test_print_creates_file(self, nml, tmp_path):
        out = tmp_path / 'out.in'
        nml.print(str(out))
        assert out.exists()
        assert out.stat().st_size > 0

    def test_roundtrip_preserves_reaction_names(self, nml, tmp_path):
        out = tmp_path / 'round.in'
        nml.print(str(out))
        reloaded = CrunchNameList(str(out))
        for name in ('Ferrihydrite_DIRB', 'Goethite_DIRB', 'UO2(s)'):
            r = reloaded.find_reaction(LIST_NAME, name)
            assert r['name'] == name
