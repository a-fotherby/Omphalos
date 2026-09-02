"""Unit tests for omphalos/crunch_keywords.py.

The failure these guard against is silent: CrunchTope reads an unrecognised RUNTIME keyword with
``IF (parfind == ' ') THEN ... ! Use default`` (StartTope.F90), so a deck spelled for the other
generation runs to completion without the database it names, and produces a plausible wrong answer.
"""

import pytest

from omphalos import crunch_keywords as ck

OLD = {'aqueous': 'kinetic_database', 'catabolic': 'catabolic_database'}
NEW = {'aqueous': 'aqueousdatabase', 'catabolic': 'catabolicdatabase'}


def _binary(tmp_path, *strings, name='CrunchTope'):
    """A stand-in executable: the keyword strings are compiled into the real one."""
    path = tmp_path / name
    path.write_bytes(b'\x7fELF' + b'\x00' * 64 + ''.join(strings).encode() + b'\x00' * 64)
    return path


class TestProbeBinary:
    def test_old_generation_is_recognised(self, tmp_path):
        assert ck.probe_binary(_binary(tmp_path, 'kinetic_database', 'catabolic_database')) == OLD

    def test_new_generation_is_recognised(self, tmp_path):
        assert ck.probe_binary(_binary(tmp_path, 'aqueousdatabase', 'catabolicdatabase')) == NEW

    def test_a_binary_with_neither_is_unidentifiable(self, tmp_path):
        assert ck.probe_binary(_binary(tmp_path, 'something else entirely')) is None

    def test_a_partial_match_is_not_enough(self, tmp_path):
        # Both keywords of a generation have to be present before it is claimed.
        assert ck.probe_binary(_binary(tmp_path, 'kinetic_database')) is None

    def test_a_missing_binary_is_not_an_error(self, tmp_path):
        assert ck.probe_binary(tmp_path / 'no-such-file') is None


class TestDatabaseKeywords:
    def test_probes_the_binary_it_is_given(self, tmp_path):
        assert ck.database_keywords(_binary(tmp_path, *NEW.values())) == NEW

    def test_falls_back_to_the_older_spellings(self, tmp_path):
        # CrunchTope's own default behaviour assumes these, and most builds use them.
        assert ck.database_keywords(_binary(tmp_path, 'nothing useful')) == OLD

    def test_a_rebuild_is_not_missed(self, tmp_path):
        # The probe is cached, so the cache key has to include the build's modification time.
        path = _binary(tmp_path, *OLD.values())
        assert ck.database_keywords(path) == OLD

        import os
        path.write_bytes(b'\x00' * 32 + ''.join(NEW.values()).encode())
        os.utime(path, (0, 0))

        assert ck.database_keywords(path) == NEW


class TestDeckKeywords:
    def test_old_spellings_are_found(self):
        contents = {'database': ['x.dbs'], 'kinetic_database': ['aqueous.dbs'],
                    'catabolic_database': ['paths.in']}
        assert ck.deck_keywords(contents) == OLD

    def test_new_spellings_are_found(self):
        contents = {'aqueousdatabase': ['aqueous.dbs'], 'catabolicdatabase': ['paths.in']}
        assert ck.deck_keywords(contents) == NEW

    def test_a_deck_naming_neither_is_empty(self):
        assert ck.deck_keywords({'database': ['x.dbs']}) == {}

    def test_the_thermodynamic_database_keyword_is_not_one_of_these(self):
        # 'database' names the .dbs and is spelled the same in both generations.
        assert 'database' not in ck.ALL_KEYWORDS


class TestCheckDeck:
    def test_a_matching_deck_passes(self, tmp_path):
        binary = _binary(tmp_path, *OLD.values())
        assert ck.check_deck({'kinetic_database': ['aqueous.dbs']}, binary) == OLD

    def test_a_deck_naming_no_auxiliary_databases_passes(self, tmp_path):
        assert ck.check_deck({'database': ['x.dbs']}, _binary(tmp_path, *NEW.values())) == NEW

    def test_an_old_deck_against_a_new_binary_fails(self, tmp_path):
        binary = _binary(tmp_path, *NEW.values())

        with pytest.raises(ValueError, match='keyword mismatch'):
            ck.check_deck({'kinetic_database': ['aqueous.dbs']}, binary)

    def test_the_error_names_the_substitution_required(self, tmp_path):
        binary = _binary(tmp_path, *NEW.values())

        with pytest.raises(ValueError) as error:
            ck.check_deck({'kinetic_database': ['aqueous.dbs']}, binary)

        assert "this binary wants 'aqueousdatabase'" in str(error.value)
        assert "the deck says 'kinetic_database'" in str(error.value)

    def test_a_new_deck_against_an_old_binary_fails(self, tmp_path):
        binary = _binary(tmp_path, *OLD.values())

        with pytest.raises(ValueError, match="wants 'kinetic_database'"):
            ck.check_deck({'aqueousdatabase': ['aqueous.dbs']}, binary)

    def test_both_keywords_are_reported_together(self, tmp_path):
        binary = _binary(tmp_path, *NEW.values())

        with pytest.raises(ValueError) as error:
            ck.check_deck(
                {'kinetic_database': ['aqueous.dbs'], 'catabolic_database': ['paths.in']}, binary
            )

        assert 'catabolicdatabase' in str(error.value)
        assert 'aqueousdatabase' in str(error.value)


class TestRealBuilds:
    """The spellings are compiled in, so the probe can be checked against actual executables."""

    def test_the_configured_build_is_identified(self):
        settings = pytest.importorskip(
            'omphalos.settings', reason='requires omphalos/settings.py (created by install.sh)'
        )
        keywords = ck.database_keywords(settings.crunch_dir)

        assert keywords in ck.KEYWORD_GENERATIONS


class TestUnidentifiableBuild:
    """Some builds recognise neither spelling.

    A CrunchTope that reads its aqueous kinetics by another route entirely -- one such build is on
    this machine -- ignores the deck's keyword and runs without the database, and a check that
    simply assumed the 1.x spellings would pass such a deck without comment.
    """

    def test_identify_build_says_so(self, tmp_path):
        assert ck.identify_build(_binary(tmp_path, 'no keywords here')) is None

    def test_database_keywords_still_falls_back(self, tmp_path):
        assert ck.database_keywords(_binary(tmp_path, 'no keywords here')) == OLD

    def test_a_deck_naming_a_database_warns(self, tmp_path):
        binary = _binary(tmp_path, 'no keywords here')

        with pytest.warns(UserWarning, match='Could not tell'):
            ck.check_deck({'kinetic_database': ['aqueous.dbs']}, binary)

    def test_a_deck_naming_none_is_silent(self, tmp_path, recwarn):
        ck.check_deck({'database': ['x.dbs']}, _binary(tmp_path, 'no keywords here'))

        assert not [w for w in recwarn if 'Could not tell' in str(w.message)]


class TestBinarySelection:
    """Which CrunchTope to run, and how a build comparison redirects it.

    The alternative to an environment variable is rewriting omphalos/settings.py per build, which is
    a global mutation an interrupted run would leave behind pointing at the wrong binary.
    """

    def test_the_environment_wins_over_settings(self, monkeypatch):
        monkeypatch.setenv('OMPHALOS_CRUNCH_DIR', '/somewhere/CrunchTope_v3_opt')

        assert ck.binary() == '/somewhere/CrunchTope_v3_opt'

    def test_it_is_read_on_each_call(self, monkeypatch):
        # Resolved per call, not at import, so setting it per subprocess works.
        monkeypatch.setenv('OMPHALOS_CRUNCH_DIR', '/first/CrunchTope')
        first = ck.binary()
        monkeypatch.setenv('OMPHALOS_CRUNCH_DIR', '/second/CrunchTope')

        assert (first, ck.binary()) == ('/first/CrunchTope', '/second/CrunchTope')

    def test_an_empty_override_falls_through_to_settings(self, monkeypatch):
        from omphalos import settings

        monkeypatch.setattr(settings, 'crunch_dir', '/from/settings/CrunchTope', raising=False)
        monkeypatch.setenv('OMPHALOS_CRUNCH_DIR', '')

        assert ck.binary() == '/from/settings/CrunchTope'

    def test_no_override_uses_settings(self, monkeypatch):
        from omphalos import settings

        monkeypatch.setattr(settings, 'crunch_dir', '/from/settings/CrunchTope', raising=False)
        monkeypatch.delenv('OMPHALOS_CRUNCH_DIR', raising=False)

        assert ck.binary() == '/from/settings/CrunchTope'

    def test_the_old_private_name_still_works(self):
        assert ck._configured_binary is ck.binary
