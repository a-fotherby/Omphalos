"""Unit tests for omphalos/template.py."""

import os
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import copy


class TestTemplateReadFile:
    """Tests for the Template.read_file static method."""

    def test_read_file_basic(self, tmp_path):
        """Test basic file reading."""
        from omphalos.template import Template

        # Create a test file
        test_file = tmp_path / "test.in"
        test_file.write_text("TITLE\nTest file\nEND\n")

        result = Template.read_file(str(test_file))

        assert isinstance(result, dict)
        assert 0 in result
        assert result[0] == 'TITLE'

    def test_read_file_skips_comments(self, tmp_path):
        """Test that commented lines are skipped."""
        from omphalos.template import Template

        test_file = tmp_path / "test.in"
        test_file.write_text("TITLE\n! This is a comment\nEND\n")

        result = Template.read_file(str(test_file))

        # Comment line should not be in result
        assert 'comment' not in str(result.values()).lower()

    def test_read_file_preserves_line_numbers(self, tmp_path):
        """Test that line numbers are preserved even with comments."""
        from omphalos.template import Template

        test_file = tmp_path / "test.in"
        test_file.write_text("LINE0\n! comment\nLINE2\n")

        result = Template.read_file(str(test_file))

        # Line 0 and 2 should be present, line 1 (comment) should not
        assert 0 in result
        assert 2 in result
        # Line 1 should not be in result (it's a comment)
        assert 1 not in result

    def test_read_file_strips_whitespace(self, tmp_path):
        """Test that trailing whitespace is stripped."""
        from omphalos.template import Template

        test_file = tmp_path / "test.in"
        test_file.write_text("TITLE   \nEND  \n")

        result = Template.read_file(str(test_file))

        assert result[0] == 'TITLE'
        assert result[1] == 'END'

    def test_read_file_handles_empty_lines(self, tmp_path):
        """Test handling of empty lines."""
        from omphalos.template import Template

        test_file = tmp_path / "test.in"
        test_file.write_text("TITLE\n\nEND\n")

        result = Template.read_file(str(test_file))

        assert 0 in result
        assert 1 in result  # Empty line still included
        assert 2 in result


class TestTemplateMakeDict:
    """Tests for the Template.make_dict method."""

    def test_make_dict_creates_correct_number(self, sample_template):
        """Test that make_dict creates correct number of InputFiles."""
        file_dict = sample_template.make_dict()

        expected_num = sample_template.config['number_of_files']
        assert len(file_dict) == expected_num

    def test_make_dict_assigns_file_numbers(self, sample_template):
        """Test that each InputFile has correct file_num."""
        file_dict = sample_template.make_dict()

        for i, file_num in enumerate(file_dict):
            assert file_dict[file_num].file_num == i

    def test_make_dict_creates_deep_copies(self, sample_template):
        """Test that InputFiles are deep copies (independent)."""
        file_dict = sample_template.make_dict()

        # Modify one file's condition
        if file_dict[0].condition_blocks:
            first_condition = list(file_dict[0].condition_blocks.keys())[0]
            if file_dict[0].condition_blocks[first_condition].concentrations:
                species = list(file_dict[0].condition_blocks[first_condition].concentrations.keys())[0]
                original_value = file_dict[1].condition_blocks[first_condition].concentrations[species][0]

                # Modify file 0
                file_dict[0].condition_blocks[first_condition].concentrations[species][0] = 'MODIFIED'

                # File 1 should be unchanged
                assert file_dict[1].condition_blocks[first_condition].concentrations[species][0] == original_value


class TestTemplateInit:
    """Tests for Template initialization."""

    def test_template_loads_config(self, omphalos_test_dir, sample_config):
        """Test that template loads configuration."""
        original_dir = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            from omphalos.template import Template
            import io
            import contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                template = Template(sample_config)

            assert template.config == sample_config
        finally:
            os.chdir(original_dir)

    def test_template_has_keyword_blocks(self, sample_template):
        """Test that template has keyword_blocks attribute."""
        assert hasattr(sample_template, 'keyword_blocks')
        assert isinstance(sample_template.keyword_blocks, dict)

    def test_template_has_condition_blocks(self, sample_template):
        """Test that template has condition_blocks attribute."""
        assert hasattr(sample_template, 'condition_blocks')
        assert isinstance(sample_template.condition_blocks, dict)

    def test_template_has_path(self, sample_template):
        """Test that template has path attribute."""
        assert hasattr(sample_template, 'path')

    def test_template_has_raw(self, sample_template):
        """Test that template has raw file content."""
        assert hasattr(sample_template, 'raw')
        assert isinstance(sample_template.raw, dict)


class TestTemplateKeywordBlocks:
    """Tests for keyword block handling in Template."""

    def test_template_parses_runtime_block(self, sample_template):
        """Test that RUNTIME block is parsed."""
        assert 'RUNTIME' in sample_template.keyword_blocks

    def test_template_parses_discretization_block(self, sample_template):
        """Test that DISCRETIZATION block is parsed."""
        assert 'DISCRETIZATION' in sample_template.keyword_blocks

    def test_template_parses_minerals_block(self, sample_template):
        """Test that MINERALS block is parsed."""
        assert 'MINERALS' in sample_template.keyword_blocks

    def test_keyword_block_has_contents(self, sample_template):
        """Test that keyword blocks have contents."""
        for name, block in sample_template.keyword_blocks.items():
            assert hasattr(block, 'contents')
            assert isinstance(block.contents, dict)


class TestTemplateConditionBlocks:
    """Tests for condition block handling in Template."""

    def test_template_parses_conditions(self, sample_template):
        """Test that condition blocks are parsed."""
        assert len(sample_template.condition_blocks) > 0

    def test_condition_blocks_have_concentrations(self, sample_template):
        """Test that condition blocks have concentrations."""
        for name, block in sample_template.condition_blocks.items():
            assert hasattr(block, 'concentrations')

    def test_condition_blocks_have_minerals(self, sample_template):
        """Test that condition blocks have minerals."""
        for name, block in sample_template.condition_blocks.items():
            assert hasattr(block, 'minerals') or hasattr(block, 'mineral_volumes')


class TestTemplateInheritance:
    """Tests for Template inheritance from InputFile."""

    def test_template_inherits_from_inputfile(self):
        """Test that Template inherits from InputFile."""
        from omphalos.template import Template
        from omphalos.input_file import InputFile

        assert issubclass(Template, InputFile)

    def test_template_has_inputfile_methods(self, sample_template):
        """Test that Template has InputFile methods."""
        assert hasattr(sample_template, 'print')
        assert hasattr(sample_template, 'get_results')


class TestTemplateSortConditionBlock:
    """Tests for condition block sorting."""

    def test_sort_condition_block_method_exists(self, sample_template):
        """Test that sort_condition_block method exists."""
        assert hasattr(sample_template, 'sort_condition_block')
        assert callable(sample_template.sort_condition_block)


class TestTemplateErrorHandling:
    """Tests for Template error handling."""

    def test_template_missing_file_raises_error(self, tmp_path):
        """Test that missing template file raises error."""
        from omphalos.template import Template

        config = {
            'template': str(tmp_path / 'nonexistent.in'),
            'database': 'test.dbs',
            'number_of_files': 1,
        }

        with pytest.raises(FileNotFoundError):
            Template(config)

    def test_template_handles_missing_optional_blocks(self, sample_template):
        """Test that missing optional blocks don't cause errors."""
        # These blocks may not exist in test file - should not raise
        optional_blocks = ['ION_EXCHANGE', 'SURFACE_COMPLEXATION', 'PEST']
        for block in optional_blocks:
            # Should not raise, may or may not be present
            _ = sample_template.keyword_blocks.get(block)


class TestTemplateLaterInputs:
    """Tests for later_inputs (restart) handling."""

    def test_template_has_later_inputs_attribute(self, sample_template):
        """Test that template has later_inputs attribute."""
        assert hasattr(sample_template, 'later_inputs')

    def test_later_inputs_is_dict(self, sample_template):
        """Test that later_inputs is a dictionary."""
        assert isinstance(sample_template.later_inputs, dict)
