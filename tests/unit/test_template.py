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


class TestTemplateCommentsAndBlankLines:
    """Tests for comments and blank lines inside keyword blocks.

    read_file drops comment lines but preserves line numbers, so the line index has gaps; blank lines
    inside a block are legal CrunchTope input and carry no entry. Both are nothing to read, and used to
    be caught by a broad `except BaseException` that printed a warning, silently dropped an entry, or -
    in the ISOTOPES and FLOW parsers - abandoned the rest of the block.
    """

    @staticmethod
    def _template(tmp_path, body, capsys=None):
        """Build a Template from a minimal input file containing the given body."""
        from omphalos.template import Template

        path = tmp_path / 'test.in'
        path.write_text(body)
        template = Template({
            'template': str(path),
            'database': 'test.dbs',
            'aqueous_database': None,
            'catabolic_pathways': None,
            'conditions': None,
            'number_of_files': 1,
        })
        if capsys is not None:
            capsys.readouterr()      # discard the "keyword does not exist" notices
        return template

    BODY = """TITLE
Test
END

MINERALS
! a comment at column 1
   ! an indented comment

Calcite -label default -rate -9.0
END

ISOTOPES
! a comment
primary 30SiO2(aq) SiO2(aq) 0.0300

END

FLOW
! a comment

constant_flow 10.0
END

PRIMARY_SPECIES
H+
END

INITIAL_CONDITIONS
initial 1-10
END

CONDITION initial
! a comment
temperature 25.0

Calcite 0.1
END
"""

    def test_comments_and_blanks_do_not_become_entries(self, tmp_path):
        """Test that comments and blank lines never appear as block entries."""
        template = self._template(tmp_path, self.BODY)

        for name, block in template.keyword_blocks.items():
            # Checked by prefix, since the MINERALS parser would key a comment as '!&default'.
            assert not [k for k in block.contents if k.startswith('!')], f'comment parsed as an entry in {name}'
            if name == 'INITIAL_CONDITIONS':
                # This block is keyed by coordinate set, so its header line legitimately keys on ''.
                assert block.contents[''] == ['INITIAL_CONDITIONS']
                continue
            assert '' not in block.contents, f'blank line parsed as an entry in {name}'
        for name, condition in template.condition_blocks.items():
            assert not [k for k in condition.contents if k.startswith('!')], \
                f'comment parsed as an entry in condition {name}'
            assert '' not in condition.contents, f'blank line parsed as an entry in condition {name}'

    def test_real_entries_survive_a_comment(self, tmp_path):
        """Test that entries after a comment or blank line are still parsed."""
        template = self._template(tmp_path, self.BODY)

        assert 'Calcite&default' in template.keyword_blocks['MINERALS'].contents
        assert template.keyword_blocks['FLOW'].contents['constant_flow'] == ['10.0']
        assert 'temperature' in template.condition_blocks['initial'].contents

    def test_blank_line_does_not_abandon_isotopes_block(self, tmp_path):
        """Test that a blank line in ISOTOPES leaves the block parsed.

        The old handler let the IndexError escape to the block-level guard, which reported the keyword
        as missing and discarded everything parsed so far.
        """
        template = self._template(tmp_path, self.BODY)

        assert 'ISOTOPES' in template.keyword_blocks
        # The block is keyed on the rare isotope, with the major isotope kept in the entry.
        assert template.keyword_blocks['ISOTOPES'].contents['30SiO2(aq)'] == ['primary', 'SiO2(aq)', '0.0300']

    def test_no_warning_printed_for_comments(self, tmp_path, capsys):
        """Test that an ordinary template with comments parses without warnings."""
        self._template(tmp_path, self.BODY)

        out = capsys.readouterr().out
        assert 'BaseException' not in out
        assert 'gone really wrong' not in out

    def test_keyboard_interrupt_is_not_swallowed(self, tmp_path, monkeypatch):
        """Test that an interrupt during parsing propagates instead of being reported as a comment."""
        from omphalos.template import Template

        template = self._template(tmp_path, self.BODY)

        def boom(line_num):
            raise KeyboardInterrupt

        monkeypatch.setattr(template, 'block_line', boom)
        with pytest.raises(KeyboardInterrupt):
            Template.get_keyword_block(template, 'MINERALS')

    def test_block_line_returns_empty_for_gaps(self, tmp_path):
        """Test the helper directly: absent line numbers and blank lines both read as nothing."""
        template = self._template(tmp_path, self.BODY)
        template.raw = {0: 'MINERALS', 2: '', 3: '   ', 4: 'Calcite -rate -9.0'}

        assert template.block_line(1) == []      # comment line, dropped from the index
        assert template.block_line(2) == []      # blank line
        assert template.block_line(3) == []      # whitespace-only line
        assert template.block_line(4) == ['Calcite', '-rate', '-9.0']


class TestTemplateSortConditionBlock:
    """Tests for condition block sorting."""

    def test_sort_condition_block_method_exists(self, sample_template):
        """Test that sort_condition_block method exists."""
        assert hasattr(sample_template, 'sort_condition_block')
        assert callable(sample_template.sort_condition_block)

    def test_sort_condition_block_sorts_by_species_type(self, sample_template):
        """Test that entries are sorted into minerals, primary species and parameters."""
        condition = next(iter(sample_template.condition_blocks))
        sample_template.sort_condition_block(condition)
        block = sample_template.condition_blocks[condition]

        minerals = [m.split('&')[0] for m in sample_template.keyword_blocks['MINERALS'].contents]
        primary = list(sample_template.keyword_blocks['PRIMARY_SPECIES'].contents)

        assert all(entry in minerals for entry in block.mineral_volumes)
        assert all(entry in primary for entry in block.concentrations)
        assert 'temperature' in block.parameters

    @pytest.mark.parametrize('absent_block', ['GASES', 'MINERALS', 'SECONDARY_SPECIES'])
    def test_sort_condition_block_tolerates_absent_block(self, sample_template, absent_block):
        """Test that an input file without a given keyword block can still be sorted.

        A problem with no gas chemistry has no GASES block, for instance; that block simply
        contributes no names to sort against, rather than raising.
        """
        template = copy.deepcopy(sample_template)
        template.keyword_blocks.pop(absent_block, None)
        condition = next(iter(template.condition_blocks))

        template.sort_condition_block(condition)   # must not raise

        block = template.condition_blocks[condition]
        if absent_block == 'GASES':
            assert block.gases == {}
        elif absent_block == 'MINERALS':
            # With no MINERALS block, mineral entries fall through to parameters.
            assert block.mineral_volumes == {}

    def test_sort_condition_block_without_gases_block_still_prints(self, sample_template, tmp_path):
        """Test that an input file with no GASES block can be written out."""
        template = copy.deepcopy(sample_template)
        template.keyword_blocks.pop('GASES', None)
        template.path = tmp_path / 'no_gases.in'

        template.print()   # print() sorts every condition block; must not raise

        assert template.path.exists()
        assert 'GASES' not in template.path.read_text()


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


# An input file exercising the parts of the CrunchTope input format where a keyword may repeat, where
# a line may be continued, and where a condition entry is neither a species nor a parameter.
MANUAL_FEATURES_BODY = """TITLE
Test
END

RUNTIME
time_units years
END

OUTPUT
time_units years
spatial_profile 100.0 200.0 &
300.0 400.0
time_series obs_a.out 10
time_series obs_b.out 50
END

DISCRETIZATION
xzones 10 1.0
END

PRIMARY_SPECIES
H+
Ca++
END

MINERALS
Calcite -label default
END

ION_EXCHANGE
exchange Xna- on Kaolinite
exchange Xca- on Kaolinite
convention Gaines-Thomas
END

SURFACE_COMPLEXATION
>FeOH_strong on Fe(OH)3
>FeOH_weak on Fe(OH)3
END

TRANSPORT
fix_diffusion 1.0e-9
D_25 H+ 9.31e-9
D_25 Ca++ 0.79e-9
END

INITIAL_CONDITIONS
initial 1-10
END

CONDITION initial
units mmol/kg
temperature 25.0
Ca++ 1.0
Calcite 0.1 specific_surface_area 2.0 0.0001
>FeOH_strong 3.8e-6
Xna- -cec 0.001
SolidDensity CalculateFromMinerals
END
"""


def _build_template(tmp_path, body=MANUAL_FEATURES_BODY, name='test.in'):
    """Build a Template from an input file containing the given body."""
    import contextlib
    import io

    from omphalos.template import Template

    path = tmp_path / name
    path.write_text(body)
    with contextlib.redirect_stdout(io.StringIO()):
        return Template({
            'template': str(path),
            'database': 'test.dbs',
            'aqueous_database': None,
            'catabolic_pathways': None,
            'conditions': None,
            'number_of_files': 1,
        })


def _round_trip(template, tmp_path):
    """Write the template back out and return the text, as CrunchTope would receive it."""
    import contextlib
    import io

    out = tmp_path / 'out.in'
    template.path = str(out)
    with contextlib.redirect_stdout(io.StringIO()):
        template.print()

    return out.read_text()


class TestTemplateRepeatableEntries:
    """Tests for keywords CrunchTope allows to appear more than once in a block.

    Entries are keyed on the leftmost word, so these used to overwrite each other and everything but
    the last occurrence was silently dropped from the input file written for each run.
    """

    def test_every_time_series_is_kept(self, tmp_path):
        """Test that both time series survive, each with its own filename and node."""
        contents = _build_template(tmp_path).keyword_blocks['OUTPUT'].contents

        assert contents['time_series&obs_a.out'] == ['obs_a.out', '10']
        assert contents['time_series&obs_b.out'] == ['obs_b.out', '50']

    def test_every_exchanger_is_kept(self, tmp_path):
        """Test that a multi-exchanger ION_EXCHANGE block keeps all of its exchangers."""
        contents = _build_template(tmp_path).keyword_blocks['ION_EXCHANGE'].contents

        assert contents['exchange&Xna-'] == ['Xna-', 'on', 'Kaolinite']
        assert contents['exchange&Xca-'] == ['Xca-', 'on', 'Kaolinite']

    def test_every_diffusion_coefficient_is_kept(self, tmp_path):
        """Test that per-species D_25 lines all survive.

        The manual notes that even one D_25 entry switches GIMRT to the full Nernst-Planck solve, so
        losing these quietly reduces a multi-species setup to one species.
        """
        contents = _build_template(tmp_path).keyword_blocks['TRANSPORT'].contents

        assert contents['D_25&H+'] == ['H+', '9.31e-9']
        assert contents['D_25&Ca++'] == ['Ca++', '0.79e-9']

    def test_non_repeatable_keywords_keep_a_plain_key(self, tmp_path):
        """Test that only the repeatable keywords are given a composite key."""
        template = _build_template(tmp_path)

        assert template.keyword_blocks['TRANSPORT'].contents['fix_diffusion'] == ['1.0e-9']
        assert template.keyword_blocks['ION_EXCHANGE'].contents['convention'] == ['Gaines-Thomas']

    def test_round_trip_writes_every_line(self, tmp_path):
        """Test that the file written for a run carries all the repeated lines, not just the last."""
        template = _build_template(tmp_path)
        text = _round_trip(template, tmp_path)

        for line in ('time_series obs_a.out 10', 'time_series obs_b.out 50',
                     'exchange Xna- on Kaolinite', 'exchange Xca- on Kaolinite',
                     'D_25 H+ 9.31e-9', 'D_25 Ca++ 0.79e-9'):
            assert line in text, f'{line!r} was dropped on the way out'

    def test_a_bare_keyword_still_resolves_when_unique(self, tmp_path):
        """Test that a config naming the bare keyword works while only one such line exists."""
        template = _build_template(tmp_path)
        block = template.keyword_blocks['OUTPUT']
        del block.contents['time_series&obs_b.out']

        block.modify('time_series', 99, -1)

        assert block.contents['time_series&obs_a.out'] == ['obs_a.out', '99']

    def test_an_ambiguous_bare_keyword_is_reported(self, tmp_path):
        """Test that a bare keyword matching several lines asks which one is meant."""
        block = _build_template(tmp_path).keyword_blocks['TRANSPORT']

        with pytest.raises(KeyError, match='matches several entries'):
            block.modify('D_25', 1.0, -1)

    def test_a_specific_repeated_entry_can_be_modified(self, tmp_path):
        """Test that naming the composite key modifies just that line."""
        block = _build_template(tmp_path).keyword_blocks['TRANSPORT']

        block.modify('D_25&H+', 1.0, -1)

        assert block.contents['D_25&H+'] == ['H+', '1.0']
        assert block.contents['D_25&Ca++'] == ['Ca++', '0.79e-9']


class TestTemplateLineContinuation:
    """Tests for entries continued across lines with a trailing ampersand."""

    def test_a_continued_entry_becomes_one_entry(self, tmp_path):
        """Test that the continuation's values join the entry they continue."""
        contents = _build_template(tmp_path).keyword_blocks['OUTPUT'].contents

        assert contents['spatial_profile'] == ['100.0', '200.0', '300.0', '400.0']

    def test_the_continuation_leaves_no_bogus_entry(self, tmp_path):
        """Test that the continuation line does not become an entry keyed on its first value."""
        contents = _build_template(tmp_path).keyword_blocks['OUTPUT'].contents

        assert '300.0' not in contents
        for values in contents.values():
            assert '&' not in values

    def test_continuation_over_several_lines(self, tmp_path):
        """Test that an entry may be continued more than once."""
        from omphalos.template import Template

        joined = Template.join_continuations({
            0: 'OUTPUT',
            1: 'spatial_profile 1.0 &',
            2: '2.0 &',
            3: '3.0',
            4: 'END',
        })

        assert joined[1] == 'spatial_profile 1.0 2.0 3.0'
        assert 2 not in joined and 3 not in joined
        assert joined[4] == 'END'

    def test_continuation_skips_a_comment_gap(self, tmp_path):
        """Test that a comment between the two halves of an entry does not break the join.

        read_file drops comments but keeps their line numbers, so the continuation is not the very
        next key in the index.
        """
        template = _build_template(tmp_path, MANUAL_FEATURES_BODY.replace(
            'spatial_profile 100.0 200.0 &\n', 'spatial_profile 100.0 200.0 &\n! a comment\n'))

        assert template.keyword_blocks['OUTPUT'].contents['spatial_profile'] == \
            ['100.0', '200.0', '300.0', '400.0']

    def test_a_dangling_marker_does_not_swallow_the_end(self, tmp_path):
        """Test that a continuation marker with END next drops the marker and keeps the block.

        Joining END onto the entry would lose the block boundary and take the rest of the file with it.
        """
        from omphalos.template import Template

        joined = Template.join_continuations({0: 'OUTPUT', 1: 'spatial_profile 1.0 &', 2: 'END'})

        assert joined[1] == 'spatial_profile 1.0'
        assert joined[2] == 'END'

    def test_a_dangling_marker_at_end_of_file_is_dropped(self, tmp_path):
        """Test that a trailing marker with nothing after it leaves no stray token."""
        from omphalos.template import Template

        joined = Template.join_continuations({0: 'spatial_profile 1.0 &'})

        assert joined[0] == 'spatial_profile 1.0'

    def test_staged_restarts_can_offset_continued_times(self, tmp_path):
        """Test that a continued spatial_profile can drive a staged restart chain.

        The stray '&' token used to reach float() and raise, so no template using the documented
        continuation syntax could run staged restarts at all.
        """
        from omphalos import generate_inputs as gi

        template = _build_template(tmp_path)
        gi._auto_adjust_spatial_profile(template, 1)

        assert template.keyword_blocks['OUTPUT'].contents['spatial_profile'] == \
            ['500.0', '600.0', '700.0', '800.0']

    def test_a_short_continued_entry_is_written_on_one_line(self, tmp_path):
        """Test that an entry that fits is written without a continuation marker."""
        template = _build_template(tmp_path)
        text = _round_trip(template, tmp_path)

        assert 'spatial_profile 100.0 200.0 300.0 400.0' in text

    def test_a_long_entry_is_wrapped(self, tmp_path):
        """Test that an entry too long for CrunchTope's 132 character line is continued.

        Writing it as one line would have it silently truncated at 132 characters.
        """
        from omphalos.input_file import MAX_LINE_LENGTH

        template = _build_template(tmp_path)
        times = [str(float(t)) for t in range(1, 61)]
        template.keyword_blocks['OUTPUT'].contents['spatial_profile'] = times
        text = _round_trip(template, tmp_path)

        written = [line for line in text.splitlines() if line.startswith('spatial_profile')]
        assert len(written) == 1, 'the entry should start exactly one line'
        for line in text.splitlines():
            assert len(line) <= MAX_LINE_LENGTH, f'line exceeds the limit: {line!r}'

    def test_a_wrapped_entry_reads_back_unchanged(self, tmp_path):
        """Test that wrapping and re-reading is lossless, so a restart chain keeps its times."""
        template = _build_template(tmp_path)
        times = [str(float(t)) for t in range(1, 61)]
        template.keyword_blocks['OUTPUT'].contents['spatial_profile'] = times
        text = _round_trip(template, tmp_path)

        reread = _build_template(tmp_path, text, name='reread.in')

        assert reread.keyword_blocks['OUTPUT'].contents['spatial_profile'] == times


class TestTemplateConditionSpeciesTypes:
    """Tests for sorting condition entries that are neither species nor condition-wide parameters."""

    def test_exchanger_cec_is_sorted_as_an_exchanger(self, tmp_path):
        """Test that a cation exchange capacity is recognised from the ION_EXCHANGE block."""
        template = _build_template(tmp_path)
        template.check_condition_sort('initial')
        block = template.condition_blocks['initial']

        assert block.exchangers == {'Xna-': ['-cec', '0.001']}
        assert 'Xna-' not in block.parameters

    def test_surface_site_density_is_sorted_as_a_surface_complex(self, tmp_path):
        """Test that a surface hydroxyl site density is recognised from SURFACE_COMPLEXATION."""
        template = _build_template(tmp_path)
        template.check_condition_sort('initial')
        block = template.condition_blocks['initial']

        assert block.surface_complexes == {'>FeOH_strong': ['3.8e-6']}
        assert '>FeOH_strong' not in block.parameters

    def test_condition_wide_parameters_are_left_alone(self, tmp_path):
        """Test that genuine condition parameters stay where they were."""
        template = _build_template(tmp_path)
        template.check_condition_sort('initial')
        parameters = template.condition_blocks['initial'].parameters

        for entry in ('units', 'temperature', 'SolidDensity'):
            assert entry in parameters

    def test_species_are_unaffected(self, tmp_path):
        """Test that the split does not disturb the concentrations or mineral volumes."""
        template = _build_template(tmp_path)
        template.check_condition_sort('initial')
        block = template.condition_blocks['initial']

        assert 'Ca++' in block.concentrations
        assert 'Calcite' in block.mineral_volumes

    def test_round_trip_keeps_them(self, tmp_path):
        """Test that entries moved out of parameters are still written to the input file."""
        template = _build_template(tmp_path)
        text = _round_trip(template, tmp_path)

        assert 'Xna- -cec 0.001' in text
        assert '>FeOH_strong 3.8e-6' in text


class TestFlowZoneEntryCase:
    """Tests that FLOW zone entries are recognised whichever way the deck capitalises them.

    CrunchTope reads these keywords case insensitively and the short-course exercises use both
    spellings. Testing the raw token against a lowercase-only set meant a deck writing
    'permeability_X' got no coordinate key, so every repeated line overwrote the one before it and
    only the last survived - silently replacing a heterogeneous permeability field with one value.
    """

    BODY = """TITLE
Test
END

FLOW
distance_units meters
calculate_flow true
permeability_X 1.0E-12 default
permeability_X 1.0E-13 zone 22-33 1-42 1-1
permeability_X 0.0 zone 0-0 1-42 1-1
permeability_Y 1.0E-13 zone 22-33 1-42 1-1
PRESSURE 30.0 zone 0-0 1-41 1-1 fix
END

PRIMARY_SPECIES
H+
END

INITIAL_CONDITIONS
initial 1-10
END

CONDITION initial
temperature 25.0
END
"""

    @staticmethod
    def _template(tmp_path, body):
        from omphalos.template import Template

        path = tmp_path / 'flow_case.in'
        path.write_text(body)
        return Template({
            'template': str(path),
            'database': 'test.dbs',
            'aqueous_database': None,
            'catabolic_pathways': None,
            'conditions': None,
            'number_of_files': 1,
        })

    def test_capitalised_zone_entries_are_all_kept(self, tmp_path):
        """Test that repeated capitalised permeability entries do not overwrite each other."""
        contents = self._template(tmp_path, self.BODY).keyword_blocks['FLOW'].contents

        assert 'permeability_X 22-33 1-42 1-1' in contents
        assert 'permeability_X 0-0 1-42 1-1' in contents
        assert 'permeability_Y 22-33 1-42 1-1' in contents
        assert contents['permeability_X 22-33 1-42 1-1'][0] == '1.0E-13'
        assert contents['permeability_X 0-0 1-42 1-1'][0] == '0.0'

    def test_the_default_entry_keeps_the_bare_keyword(self, tmp_path):
        """Test that an entry without a zone is still keyed on the keyword alone."""
        contents = self._template(tmp_path, self.BODY).keyword_blocks['FLOW'].contents

        assert contents['permeability_X'] == ['1.0E-12', 'default']

    def test_an_upper_case_keyword_is_keyed_too(self, tmp_path):
        """Test that the case insensitivity is not specific to permeability."""
        contents = self._template(tmp_path, self.BODY).keyword_blocks['FLOW'].contents

        assert 'PRESSURE 0-0 1-41 1-1' in contents

    def test_round_trip_writes_every_zone_line(self, tmp_path):
        """Test that all of the zone entries survive being written back out."""
        template = self._template(tmp_path, self.BODY)
        out = tmp_path / 'written.in'
        template.path = out
        template.print()
        text = out.read_text()

        assert text.count('permeability_X') == 3
        assert '1.0E-13 zone 22-33 1-42 1-1' in text


class TestSurfaceSiteNames:
    """The deck is the only place the `surface` output's missing column names can come from.

    CrunchTope writes a column per free surface site before the columns its header names, so those
    names have to be supplied from outside the file. SURFACE_COMPLEXATION lists them in the order the
    output uses.
    """

    def _template(self, tmp_path, block):
        import contextlib
        import io

        deck = tmp_path / 'deck.in'
        deck.write_text(
            'TITLE\ntest\nEND\n\n'
            'RUNTIME\ndatabase  d.dbs\nEND\n\n'
            'OUTPUT\nspatial_profile  365\nEND\n\n'
            'PRIMARY_SPECIES\nH+\nEND\n\n'
            f'{block}'
            'DISCRETIZATION\nxzones  1  1.0\nEND\n\n'
            'Condition initial\ntemperature  25.0\nEND\n\n'
            'INITIAL_CONDITIONS\ninitial  1-1  1-1  1-1\nEND\n'
        )

        from omphalos.template import Template

        with contextlib.redirect_stdout(io.StringIO()):
            return Template({'template': str(deck), 'database': None, 'aqueous_database': None,
                             'catabolic_pathways': None, 'number_of_files': 1, 'timeout': 60,
                             'conditions': None})

    def test_the_sites_are_returned_in_deck_order(self, tmp_path):
        template = self._template(
            tmp_path,
            'SURFACE_COMPLEXATION\n>FeOH_strong  on Fe(OH)3\n>FeOH_weak  on Fe(OH)3\nEND\n\n',
        )

        assert template._surface_sites() == ('>FeOH_strong', '>FeOH_weak')

    def test_a_deck_without_the_block_offers_no_names(self, tmp_path):
        # Most decks have no surface complexation at all, and must not be made to look as if they do.
        template = self._template(tmp_path, '')

        assert template._surface_sites() == ()
