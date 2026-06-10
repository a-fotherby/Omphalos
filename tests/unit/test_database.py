"""Unit tests for omphalos/database.py."""

from pathlib import Path

import pytest

from omphalos.database import Database, Reaction, Species

DB_PATH = Path(__file__).parent.parent / 'omphalos_test' / 'SukindaCr53.dbs'


@pytest.fixture(scope='module')
def db():
    return Database(str(DB_PATH))


class TestDatabase:
    def test_temperature_point_count(self, db):
        assert db.temp_points == 8

    def test_temperature_field_length(self, db):
        assert len(db.temp_field) == 8

    def test_primary_species_populated(self, db):
        assert len(db.primary_species) > 0

    def test_known_primary_species_present(self, db):
        assert 'H+' in db.primary_species
        assert 'Fe++' in db.primary_species

    def test_minerals_populated(self, db):
        assert len(db.minerals) > 0

    def test_known_mineral_present(self, db):
        assert 'Calcite' in db.minerals


class TestSpecies:
    def test_species_attributes(self, db):
        fe = db.primary_species['Fe++']
        assert fe.name == 'Fe++'
        assert fe.charge == pytest.approx(2.0)
        assert fe.dh_size == pytest.approx(6.0)
        assert fe.weight == pytest.approx(55.847, abs=0.01)

    def test_h_plus_charge(self, db):
        h = db.primary_species['H+']
        assert h.charge == pytest.approx(1.0)


class TestReaction:
    def test_calcite_has_expected_reactants(self, db):
        # Calcite: 3 species, -1.0 H+  1.0 Ca++  1.0 HCO3-
        r = db.minerals['Calcite'].reaction
        assert 'Calcite' in r.reactants
        assert 'H+' in r.reactants

    def test_calcite_has_expected_products(self, db):
        r = db.minerals['Calcite'].reaction
        assert 'Ca++' in r.products
        assert 'HCO3-' in r.products

    def test_stoichiometry_is_positive_in_dicts(self, db):
        r = db.minerals['Calcite'].reaction
        for coeff in r.reactants.values():
            assert coeff > 0
        for coeff in r.products.values():
            assert coeff > 0

    def test_odd_reaction_array_raises(self):
        with pytest.raises(Exception, match="Unpaired"):
            Reaction('Test', [-1.0, 'H+', 1.0])

    def test_zero_stoichiometry_raises(self):
        with pytest.raises(Exception, match="Stoichiometric coefficient = 0"):
            Reaction('Test', [0.0, 'H+', 1.0, 'Ca++'])


class TestMineral:
    def test_goethite_molar_volume(self, db):
        goethite = db.minerals['Goethite']
        assert goethite.molar_volume == pytest.approx(20.82, abs=0.01)

    def test_mineral_log_k_has_eight_values(self, db):
        assert len(db.minerals['Calcite'].log_k) == 8

    def test_mineral_reaction_type(self, db):
        assert isinstance(db.minerals['Calcite'].reaction, Reaction)
