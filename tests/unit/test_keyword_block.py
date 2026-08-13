"""Unit tests for core/keyword_block.py."""

import pytest

from core.keyword_block import (
    KeywordBlock,
    ConditionBlock,
    KeywordBlockModificationError,
    ConditionBlockModificationError,
    resolve_entry,
    snapshot_key,
    snapshot_times,
    surface_area_position,
)


class TestKeywordBlock:
    """Tests for the KeywordBlock class."""

    def test_init(self):
        """Test KeywordBlock initialization."""
        block = KeywordBlock('RUNTIME')
        assert block.block_type == 'RUNTIME'
        assert block.contents == {}

    def test_init_different_types(self):
        """Test KeywordBlock with different block types."""
        for block_type in ['MINERALS', 'OUTPUT', 'DISCRETIZATION', 'TRANSPORT']:
            block = KeywordBlock(block_type)
            assert block.block_type == block_type

    def test_modify_single_value(self):
        """Test modifying a single value in KeywordBlock."""
        block = KeywordBlock('RUNTIME')
        block.contents = {'timestep_max': ['0.01']}

        block.modify('timestep_max', '0.001', 0)
        assert block.contents['timestep_max'][0] == '0.001'

    def test_modify_multiple_positions(self):
        """Test modifying different positions in an entry."""
        block = KeywordBlock('TEST')
        block.contents = {'entry': ['val1', 'val2', 'val3']}

        block.modify('entry', 'new_val', 1)
        assert block.contents['entry'] == ['val1', 'new_val', 'val3']

    def test_modify_with_float_converts_to_string(self):
        """Test that modify converts values to strings."""
        block = KeywordBlock('TEST')
        block.contents = {'value': ['1.0']}

        block.modify('value', 2.5, 0)
        assert block.contents['value'][0] == '2.5'
        assert isinstance(block.contents['value'][0], str)

    def test_modify_with_int_converts_to_string(self):
        """Test that modify converts integers to strings."""
        block = KeywordBlock('TEST')
        block.contents = {'value': ['1']}

        block.modify('value', 42, 0)
        assert block.contents['value'][0] == '42'
        assert isinstance(block.contents['value'][0], str)

    def test_modify_with_list_value(self):
        """Test modifying with a list value."""
        block = KeywordBlock('TEST')
        block.contents = {'entry': [['old1', 'old2']]}

        block.modify('entry', ['new1', 'new2'], 0)
        assert block.contents['entry'][0] == ['new1', 'new2']

    def test_modify_rejects_species_type(self):
        """Test that KeywordBlock.modify rejects species_type argument."""
        block = KeywordBlock('TEST')
        block.contents = {'entry': ['value']}

        with pytest.raises(KeywordBlockModificationError) as exc_info:
            block.modify('entry', 'new', 0, species_type='concentrations')
        assert "species_type" in str(exc_info.value)

    def test_modify_negative_index(self):
        """Test modifying with negative index."""
        block = KeywordBlock('TEST')
        block.contents = {'entry': ['val1', 'val2', 'val3']}

        block.modify('entry', 'new', -1)
        assert block.contents['entry'][-1] == 'new'


class TestConditionBlock:
    """Tests for the ConditionBlock class."""

    def test_init(self):
        """Test ConditionBlock initialization."""
        block = ConditionBlock()
        assert block.block_type == 'CONDITION'
        assert block.region == []
        assert block.gases == {}
        assert block.mineral_volumes == {}
        assert block.concentrations == {}
        assert block.parameters == {}

    def test_minerals_alias(self):
        """Test that minerals is an alias for mineral_volumes."""
        block = ConditionBlock()
        block.mineral_volumes = {'Calcite': ['0.01']}
        assert block.minerals == block.mineral_volumes

        block.minerals = {'Quartz': ['0.05']}
        assert block.mineral_volumes == {'Quartz': ['0.05']}

    def test_modify_concentrations(self):
        """Test modifying concentrations in ConditionBlock."""
        block = ConditionBlock()
        block.concentrations = {'SO4--': ['1.0', 'mM']}

        block.modify('SO4--', '2.0', 0, species_type='concentrations')
        assert block.concentrations['SO4--'][0] == '2.0'
        assert block.concentrations['SO4--'][1] == 'mM'  # Unchanged

    def test_modify_mineral_volumes(self):
        """Test modifying mineral volumes in ConditionBlock."""
        block = ConditionBlock()
        block.mineral_volumes = {'Calcite': ['0.01', '1.0']}

        block.modify('Calcite', '0.05', 0, species_type='mineral_volumes')
        assert block.mineral_volumes['Calcite'][0] == '0.05'

    def test_modify_mineral_ssa(self):
        """Test modifying mineral SSA (stored in mineral_volumes)."""
        block = ConditionBlock()
        block.mineral_volumes = {'Calcite': ['0.01', '1.0']}

        block.modify('Calcite', '2.0', 1, species_type='mineral_ssa')
        assert block.mineral_volumes['Calcite'][1] == '2.0'


class TestSurfaceAreaPosition:
    """Tests for locating the surface area value in a condition block mineral entry.

    The manual's format is '<phase> <volume fraction> [<surface area keyword>] <value> [<threshold>]'.
    Both the keyword and the trailing nucleation threshold are optional, so the value's offset varies.
    """

    def test_bare_trailing_value(self):
        """Test the form with no keyword, which CrunchTope reads as a bulk surface area."""
        assert surface_area_position('Calcite', ['0.01', '1.0']) == 1

    @pytest.mark.parametrize('keyword', ['bulk_surface_area', 'bsa', 'specific_surface_area', 'ssa'])
    def test_each_surface_area_keyword(self, keyword):
        """Test that the value is found after any of the documented keywords."""
        assert surface_area_position('Calcite', ['0.01', keyword, '2.0']) == 2

    def test_trailing_threshold_is_not_mistaken_for_the_value(self):
        """Test the secondary mineral form, where indexing from the end lands on the threshold."""
        entry = ['0.0', 'specific_surface_area', '2.0', '0.0001']

        assert surface_area_position('Calcite', entry) == 2

    def test_volume_fraction_alone_is_reported(self):
        """Test that an entry with no surface area at all says so rather than corrupting the entry."""
        with pytest.raises(ConditionBlockModificationError, match='no surface area'):
            surface_area_position('Calcite', ['0.01'])

    def test_keyword_with_no_value_is_reported(self):
        """Test that a truncated entry is reported rather than indexed past the end."""
        with pytest.raises(ConditionBlockModificationError, match='no value after it'):
            surface_area_position('Calcite', ['0.01', 'ssa'])

    def test_modify_finds_the_value_not_the_threshold(self):
        """Test the whole path: a sweep of a secondary mineral's SSA leaves the threshold alone.

        Sweeping mineral_ssa used to overwrite the trailing token, so the surface area never changed
        and the nucleation threshold was set to the requested surface area instead.
        """
        block = ConditionBlock()
        block.mineral_volumes = {'Calcite': ['0.0', 'specific_surface_area', '2.0', '0.0001']}

        block.modify('Calcite', 99.0, -1, species_type='mineral_ssa')

        assert block.mineral_volumes['Calcite'] == ['0.0', 'specific_surface_area', '99.0', '0.0001']


class TestResolveEntry:
    """Tests for resolving a bare keyword to the composite key of a repeatable entry."""

    def test_exact_key_wins(self):
        """Test that an exact match is used as given."""
        contents = {'D_25&H+': ['H+', '1.0'], 'D_25': ['x']}

        assert resolve_entry(contents, 'D_25') == 'D_25'

    def test_unique_composite_key_is_found(self):
        """Test that a bare keyword resolves while only one such entry exists."""
        contents = {'fix_diffusion': ['1.0'], 'D_25&H+': ['H+', '1.0']}

        assert resolve_entry(contents, 'D_25') == 'D_25&H+'

    def test_ambiguous_keyword_is_reported(self):
        """Test that a bare keyword matching several entries asks which one is meant."""
        contents = {'D_25&H+': ['H+', '1.0'], 'D_25&Na+': ['Na+', '2.0']}

        with pytest.raises(KeyError, match='matches several entries'):
            resolve_entry(contents, 'D_25')

    def test_missing_entry_still_raises_keyerror(self):
        """Test that an unknown name behaves as a plain dictionary lookup would."""
        with pytest.raises(KeyError):
            resolve_entry({'fix_diffusion': ['1.0']}, 'gas_diffusion')


class TestConditionBlockSpeciesTypeFallback:
    """Tests that configs written before exchangers and surface complexes were split out still work."""

    def test_exchanger_named_as_a_parameter(self):
        """Test that an exchanger targeted through 'parameters' is still found."""
        block = ConditionBlock()
        block.exchangers = {'Xna-': ['-cec', '0.001']}

        block.modify('Xna-', 0.005, -1, species_type='parameters')

        assert block.exchangers['Xna-'] == ['-cec', '0.005']

    def test_surface_complex_named_as_a_parameter(self):
        """Test that a surface complex targeted through 'parameters' is still found."""
        block = ConditionBlock()
        block.surface_complexes = {'>FeOH_strong': ['3.8e-6']}

        block.modify('>FeOH_strong', 1.0e-5, -1, species_type='parameters')

        assert block.surface_complexes['>FeOH_strong'] == ['1e-05']

    def test_a_real_parameter_is_unaffected(self):
        """Test that the fallback does not interfere with an entry that is a parameter."""
        block = ConditionBlock()
        block.parameters = {'temperature': ['25.0']}
        block.exchangers = {'temperature': ['should not be touched']}

        block.modify('temperature', 30.0, 0, species_type='parameters')

        assert block.parameters['temperature'] == ['30.0']
        assert block.exchangers['temperature'] == ['should not be touched']

    def test_modify_parameters(self):
        """Test modifying parameters in ConditionBlock."""
        block = ConditionBlock()
        block.parameters = {'temperature': ['25.0']}

        block.modify('temperature', '30.0', 0, species_type='parameters')
        assert block.parameters['temperature'][0] == '30.0'

    def test_modify_gases(self):
        """Test modifying gas directly in gases dictionary."""
        block = ConditionBlock()
        block.gases = {'CO2(g)': ['1e-3']}

        block.modify('CO2(g)', '1e-2', 0, species_type='gases')
        assert block.gases['CO2(g)'][0] == '1e-2'

    def test_modify_gases_via_equilibration(self):
        """Test modifying gas partial pressure via aqueous species equilibration."""
        block = ConditionBlock()
        # CO2(aq) is equilibrated with CO2(g) at partial pressure 1e-3
        block.concentrations = {'CO2(aq)': ['CO2(g)', '1e-3']}

        # Modify the CO2(g) partial pressure
        block.modify('CO2(g)', '1e-2', -1, species_type='gases')
        assert block.concentrations['CO2(aq)'][-1] == '1e-2'

    def test_modify_requires_species_type(self):
        """Test that ConditionBlock.modify requires species_type."""
        block = ConditionBlock()
        block.concentrations = {'SO4--': ['1.0']}

        with pytest.raises(ConditionBlockModificationError) as exc_info:
            block.modify('SO4--', '2.0', 0)
        assert "species_type" in str(exc_info.value)

    def test_modify_requires_species_type_not_none(self):
        """Test that ConditionBlock.modify rejects None species_type."""
        block = ConditionBlock()
        block.concentrations = {'SO4--': ['1.0']}

        with pytest.raises(ConditionBlockModificationError):
            block.modify('SO4--', '2.0', 0, species_type=None)

    def test_modify_converts_to_string(self):
        """Test that values are converted to strings."""
        block = ConditionBlock()
        block.concentrations = {'Fe++': ['1e-6']}

        block.modify('Fe++', 2e-6, 0, species_type='concentrations')
        assert block.concentrations['Fe++'][0] == '2e-06'
        assert isinstance(block.concentrations['Fe++'][0], str)

    def test_region_assignment(self):
        """Test region assignment."""
        block = ConditionBlock()
        block.region = [[1, 10], [1, 1], [1, 5]]
        assert block.region == [[1, 10], [1, 1], [1, 5]]

    def test_inherits_from_keyword_block(self):
        """Test that ConditionBlock inherits from KeywordBlock."""
        assert issubclass(ConditionBlock, KeywordBlock)

        block = ConditionBlock()
        assert hasattr(block, 'block_type')
        assert hasattr(block, 'contents')


class TestExceptions:
    """Tests for exception classes."""

    def test_keyword_block_modification_error(self):
        """Test KeywordBlockModificationError."""
        with pytest.raises(KeywordBlockModificationError):
            raise KeywordBlockModificationError("Test error")

    def test_condition_block_modification_error(self):
        """Test ConditionBlockModificationError."""
        with pytest.raises(ConditionBlockModificationError):
            raise ConditionBlockModificationError("Test error")

    def test_exceptions_are_exception_subclasses(self):
        """Test that custom exceptions inherit from Exception."""
        assert issubclass(KeywordBlockModificationError, Exception)
        assert issubclass(ConditionBlockModificationError, Exception)

    def test_exception_messages_preserved(self):
        """Test that exception messages are preserved."""
        msg = "Custom error message"

        try:
            raise KeywordBlockModificationError(msg)
        except KeywordBlockModificationError as e:
            assert msg in str(e)

        try:
            raise ConditionBlockModificationError(msg)
        except ConditionBlockModificationError as e:
            assert msg in str(e)


class TestSnapshotTimeKeywords:
    """Tests for the two spellings of the OUTPUT block's snapshot times.

    StartTope.F90 passes 'spatial_profile' and 'spatial_profile_at_time' to the same reader, so they
    are synonyms to CrunchTope, and short-course decks use each. Reading only the first meant a deck
    using the second raised KeyError in get_results after the run had already finished.
    """

    def test_the_canonical_spelling_is_read(self):
        """Test that a deck using 'spatial_profile' is read."""
        assert snapshot_times({'spatial_profile': ['10.0', '90.0']}) == ['10.0', '90.0']

    def test_the_at_time_spelling_is_read(self):
        """Test that a deck using 'spatial_profile_at_time' is read too."""
        assert snapshot_times({'spatial_profile_at_time': ['90.0']}) == ['90.0']

    def test_a_block_with_neither_names_both_in_the_error(self):
        """Test that the failure is actionable rather than a bare key name."""
        with pytest.raises(KeyError) as excinfo:
            snapshot_times({'time_units': ['days']})

        message = str(excinfo.value)
        assert 'spatial_profile' in message
        assert 'spatial_profile_at_time' in message

    def test_the_key_reports_the_spelling_in_use(self):
        """Test that writers can preserve whichever spelling the deck used."""
        assert snapshot_key({'spatial_profile_at_time': ['90.0']}) == 'spatial_profile_at_time'
        assert snapshot_key({'spatial_profile': ['90.0']}) == 'spatial_profile'

    def test_the_key_defaults_to_canonical_when_absent(self):
        """Test that writing into a block with no times uses the canonical name."""
        assert snapshot_key({'time_units': ['days']}) == 'spatial_profile'
