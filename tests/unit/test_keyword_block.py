"""Unit tests for core/keyword_block.py."""

import pytest

from core.keyword_block import (
    KeywordBlock,
    ConditionBlock,
    KeywordBlockModificationError,
    ConditionBlockModificationError,
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

    def test_modify_parameters(self):
        """Test modifying parameters in ConditionBlock."""
        block = ConditionBlock()
        block.parameters = {'temperature': ['25.0']}

        block.modify('temperature', '30.0', 0, species_type='parameters')
        assert block.parameters['temperature'][0] == '30.0'

    def test_modify_gases(self):
        """Test modifying gases in ConditionBlock."""
        block = ConditionBlock()
        block.gases = {'CO2(g)': ['1e-3']}

        block.modify('CO2(g)', '1e-2', 0, species_type='gases')
        assert block.gases['CO2(g)'][0] == '1e-2'

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
