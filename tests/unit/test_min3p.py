"""Unit tests for the MIN3P backend (min3p/)."""

import textwrap
from pathlib import Path

import pytest

from min3p.keyword_block import (
    Line,
    Min3pBlock,
    Min3pBlockModificationError,
    normalise,
    split_comment,
    tokenise,
)
from min3p.template import Template
from min3p import generate_inputs as gi
from min3p import file_methods as fm


# A small, self-contained MIN3P input file covering the tricky cases: a title
# with spaces, positional logicals with inline comments, sub-keywords with a
# count + name list, repeated 'number and name of zone', and quoted data values.
SAMPLE_DAT = textwrap.dedent(
    """\
    ! sample batch problem
    'global control parameters'
    'A title with spaces; and punctuation'
    .false.                       ;varsat_flow
    .true.                        ;reactive_transport
    'done'

    ! geochemical system
    'geochemical system'
    'database directory'
    '..\\..\\database\\default'
    'components'
    2
    'h+1'
    'ca+2'
    'done'

    'initial condition - local geochemistry'
    'number and name of zone'
    1
    'zone one'
    'mineral input'
    1.00d-2   .true. 'geometric'  ;phim, minequil, update_type
    'guess for ph'
    7.0
    'number and name of zone'
    2
    'zone two'
    'guess for ph'
    5.0
    'done'
    """
).replace('\n', '\r\n')


@pytest.fixture
def sample_path(tmp_path):
    """Write SAMPLE_DAT to a temp file and return its path."""
    p = tmp_path / 'sample.dat'
    p.write_text(SAMPLE_DAT, newline='')
    return p


@pytest.fixture
def sample_config(sample_path):
    return {'template': str(sample_path), 'number_of_files': 3}


# ---------------------------------------------------------------------------
# Low-level parsing helpers
# ---------------------------------------------------------------------------
class TestTokeniser:
    def test_normalise_strips_quotes_and_lowercases(self):
        assert normalise("'Geochemical System'") == 'geochemical system'
        assert normalise("  'a   b' ") == 'a b'

    def test_tokenise_preserves_quoted_spaces(self):
        toks = tokenise("'A title with spaces'")
        assert toks == ["'A title with spaces'"]

    def test_tokenise_mixed(self):
        toks = tokenise("1.00d-2   .true. 'geometric'")
        assert toks == ['1.00d-2', '.true.', "'geometric'"]

    def test_split_comment_basic(self):
        code, comment = split_comment('.false.   ;varsat_flow')
        assert code.strip() == '.false.'
        assert comment == 'varsat_flow'

    def test_split_comment_respects_quotes(self):
        # A ';' inside a quoted string must NOT start a comment.
        code, comment = split_comment("'A title; with semicolon'")
        assert comment is None
        assert tokenise(code) == ["'A title; with semicolon'"]

    def test_line_parse_classifies(self):
        assert Line.parse('! comment').kind == 'comment'
        assert Line.parse('   ').kind == 'blank'
        assert Line.parse('.true. ;x').kind == 'content'

    def test_line_norm_only_for_lone_quoted_token(self):
        assert Line.parse("'components'").norm == 'components'
        assert Line.parse("2.0e-3 'free'").norm is None


# ---------------------------------------------------------------------------
# Template parsing and round-trip
# ---------------------------------------------------------------------------
class TestTemplateParsing:
    def _content_tokens(self, text):
        return [l.tokens for l in map(Line.parse, text.split('\r\n')) if l.kind == 'content']

    def test_blocks_detected(self, sample_config):
        t = Template(sample_config)
        assert set(t.keyword_blocks) == {
            'global control parameters',
            'geochemical system',
            'initial condition - local geochemistry',
        }

    def test_round_trip_value_identical(self, sample_config, tmp_path):
        t = Template(sample_config)
        out = tmp_path / 'rt.dat'
        t.path = out
        t.print()
        original = self._content_tokens(SAMPLE_DAT)
        produced = self._content_tokens(out.read_text(newline='').replace('\n', '\r\n').replace('\r\r', '\r'))
        assert produced == original

    def test_newline_preserved(self, sample_config):
        t = Template(sample_config)
        assert t.newline == '\r\n'

    def test_header_group_holds_positional_lines(self, sample_config):
        t = Template(sample_config)
        gcp = t.keyword_blocks['global control parameters']
        # title + 2 logicals, no sub-keywords -> all under '_header'
        assert list(gcp.contents) == ['_header']
        assert len(gcp.contents['_header']) == 3

    def test_subkeyword_grouping(self, sample_config):
        t = Template(sample_config)
        gs = t.keyword_blocks['geochemical system']
        assert 'components' in gs.contents
        # 'components' owns the count line and the two species names.
        assert [l.tokens for l in gs.contents['components']] == [['2'], ["'h+1'"], ["'ca+2'"]]

    def test_repeated_subkeyword_disambiguated(self, sample_config):
        t = Template(sample_config)
        ic = t.keyword_blocks['initial condition - local geochemistry']
        keys = [k for k in ic.contents if k.startswith('number and name of zone')]
        assert keys == ['number and name of zone', 'number and name of zone#2']

    def test_unterminated_block_raises(self, tmp_path):
        bad = tmp_path / 'bad.dat'
        bad.write_text("'global control parameters'\n.false.\n", newline='')
        with pytest.raises(ValueError, match='Unterminated block'):
            Template.read_file(str(bad))

    def test_uncommented_banner_not_swallowed_as_block(self, tmp_path):
        # Regression: a comment banner missing its leading '!' (or a stray title)
        # must NOT be mistaken for a block opener, else the real block that
        # follows gets absorbed as its body. Only lone single-quoted lines open
        # blocks. (Found by auditing basin.dat / co2-seq.dat.)
        src = (
            '"A stray double-quoted title"\r\n'
            'Data Block 2: geochemical system\r\n'
            "'geochemical system'\r\n"
            "'components'\r\n"
            '1\r\n'
            "'done'\r\n"
        )
        p = tmp_path / 'banner.dat'
        p.write_text(src, newline='')
        t = Template({'template': str(p), 'number_of_files': 1})
        # The real block registers (and groups); the banner/title are not blocks.
        assert list(t.keyword_blocks) == ['geochemical system']
        assert 'components' in t.keyword_blocks['geochemical system'].contents

    def test_orphan_done_not_a_block(self, tmp_path):
        src = (
            "'geochemical system'\r\n'components'\r\n1\r\n'done'\r\n"
            "'done'\r\n"                       # orphan terminator
            "'output control'\r\n'done'\r\n"
        )
        p = tmp_path / 'orphan.dat'
        p.write_text(src, newline='')
        elements, kb, nl = Template.read_file(str(p))
        assert set(kb) == {'geochemical system', 'output control'}
        assert not any('done' in k for k in kb)

    def test_endash_block_name_matches_schema(self, tmp_path):
        # 'control parameters – variably saturated flow' (en-dash) must resolve
        # to the same vocabulary as the hyphen spelling.
        from min3p.schema import vocab_for
        assert 'mass balance' in vocab_for('control parameters – variably saturated flow')


# ---------------------------------------------------------------------------
# Modification
# ---------------------------------------------------------------------------
class TestModification:
    def test_modify_single_token(self, sample_config):
        t = Template(sample_config)
        gcp = t.keyword_blocks['global control parameters']
        gcp.modify('_header', 'newtitle', token_pos=0, line_index=0)
        assert gcp.contents['_header'][0].tokens[0] == 'newtitle'

    def test_modify_whole_line_with_list(self, sample_config):
        t = Template(sample_config)
        gs = t.keyword_blocks['geochemical system']
        gs.modify('components', ['3'], line_index=0)
        assert gs.contents['components'][0].tokens == ['3']

    def test_modify_bad_keyword_raises(self, sample_config):
        t = Template(sample_config)
        gcp = t.keyword_blocks['global control parameters']
        with pytest.raises(Min3pBlockModificationError):
            gcp.modify('nonexistent', 'x')

    def test_add_keyword_appends_before_done_and_groups(self, sample_config):
        t = Template(sample_config)
        gcp = t.keyword_blocks['global control parameters']
        gcp.vocab.add('restart')  # ensure recognised on regroup
        gcp.add_keyword('restart')
        assert 'restart' in gcp.contents
        rendered = gcp.render()
        assert rendered[-1] == "'done'"          # 'done' still last
        assert "'restart'" in rendered[-2]        # keyword sits just before it

    def test_add_keyword_idempotent(self, sample_config):
        t = Template(sample_config)
        gcp = t.keyword_blocks['global control parameters']
        gcp.vocab.add('restart')
        gcp.add_keyword('restart')
        n1 = len(gcp.body)
        gcp.add_keyword('restart')
        assert len(gcp.body) == n1               # second add is a no-op

    def test_make_dict_deepcopy_isolation(self, sample_config):
        t = Template(sample_config)
        fd = t.make_dict()
        fd[0].keyword_blocks['global control parameters'].modify('_header', 'changed', 0, 0)
        # Other files and the template are unaffected.
        assert fd[1].keyword_blocks['global control parameters'].contents['_header'][0].tokens[0] != 'changed'
        assert t.keyword_blocks['global control parameters'].contents['_header'][0].tokens[0] != 'changed'


# ---------------------------------------------------------------------------
# generate_inputs
# ---------------------------------------------------------------------------
class TestGenerateInputs:
    def test_linspace_sweep_distinct_files(self, sample_config):
        sample_config['modifications'] = {
            'ph': {'block': 'initial condition - local geochemistry',
                   'keyword': 'guess for ph', 'line': 0, 'token': 0,
                   'method': 'linspace', 'params': [6.0, 8.0]}
        }
        t = Template(sample_config)
        fd = gi.configure_input_files(t, str(Path(sample_config['template']).parent))
        phs = [float(fd[i].keyword_blocks['initial condition - local geochemistry']
                     .contents['guess for ph'][0].tokens[0]) for i in fd]
        assert phs == pytest.approx([6.0, 7.0, 8.0])

    def test_database_directory_repointed(self, sample_config):
        sample_config['database_directory'] = '/abs/db'
        t = Template(sample_config)
        fd = gi.configure_input_files(t, '.')
        tok = fd[0].keyword_blocks['geochemical system'].contents['database directory'][0].tokens[0]
        assert tok == "'/abs/db'"

    def test_alias_resolution(self, sample_config):
        sample_config['modifications'] = {
            'ph': {'alias': 'ph_guess', 'method': 'constant', 'params': 9.0}
        }
        t = Template(sample_config)
        fd = gi.configure_input_files(t, '.')
        assert float(fd[0].keyword_blocks['initial condition - local geochemistry']
                     .contents['guess for ph'][0].tokens[0]) == 9.0


# ---------------------------------------------------------------------------
# Output parsing (self-contained TecPlot fixtures)
# ---------------------------------------------------------------------------
SPATIAL_GSP = (
    'title = "dataset test"\r\n'
    'variables = "x", "y", "z", "conc"\r\n'
    'zone t = "profile", i = 3, j = 1, k = 1, f=point\r\n'
    '  0.0  0.0  0.0  1.0\r\n'
    '  1.0  0.0  0.0  2.0\r\n'
    '  2.0  0.0  0.0  3.0\r\n'
)

BATCH_LBC = (
    'title = "dataset test"\r\n'
    'variables = "time","h+1","ca+2"\r\n'
    'zone t = "C_j, batch", f=point\r\n'
    '  0.0   1.0e-5  1.0e-11\r\n'
    '  1.0   2.0e-5  3.0e-6\r\n'
)


class TestOutputParsing:
    def _setup(self, tmp_path, name, ext, content):
        (tmp_path / 'root.dat').write_text('test\n')
        (tmp_path / f'{name}_1.{ext}').write_text(content, newline='')

    def test_read_run_name(self, tmp_path):
        (tmp_path / 'root.dat').write_text('myrun\n')
        assert fm._read_run_name(tmp_path) == 'myrun'

    def test_parse_spatial(self, tmp_path):
        self._setup(tmp_path, 'test', 'gsp', SPATIAL_GSP)
        ds = fm.parse_output(tmp_path, 'gsp', 1)
        assert 'x' in ds.coords
        assert ds['conc'].sizes['x'] == 3
        assert float(ds['conc'].sel(x=2.0, y=0.0, z=0.0)) == 3.0

    def test_parse_batch_time_indexed(self, tmp_path):
        self._setup(tmp_path, 'test', 'lbc', BATCH_LBC)
        ds = fm.parse_output(tmp_path, 'lbc', 1)
        assert 'time' in ds.coords
        assert float(ds['ca+2'].isel(time=-1)) == pytest.approx(3.0e-6)

    def test_data_cats_finds_both_families(self, tmp_path):
        (tmp_path / 'root.dat').write_text('test\n')
        (tmp_path / 'test_1.gsp').write_text(SPATIAL_GSP, newline='')
        (tmp_path / 'test_2.lbc').write_text(BATCH_LBC, newline='')
        assert fm.data_cats(tmp_path) == {'gsp', 'lbc'}

    def test_get_results_concats_over_output_index(self, tmp_path):
        from min3p.input_file import InputFile
        (tmp_path / 'root.dat').write_text('test\n')
        (tmp_path / 'test_1.gsp').write_text(SPATIAL_GSP, newline='')
        (tmp_path / 'test_2.gsp').write_text(SPATIAL_GSP, newline='')
        inp = InputFile('x', [], {})
        inp.get_results(str(tmp_path))
        assert 'gsp' in inp.results
        assert inp.results['gsp'].sizes['output'] == 2


# ---------------------------------------------------------------------------
# netCDF packaging (core.file_methods.dataset_to_netcdf min3p branch)
# ---------------------------------------------------------------------------
class TestDatasetToNetcdf:
    def _make_file(self, tmp_path, name, ext, content, file_num):
        from min3p.input_file import InputFile
        d = tmp_path / f'run{file_num}'
        d.mkdir()
        (d / 'root.dat').write_text('test\n')
        (d / f'test_1.{ext}').write_text(content, newline='')
        inp = InputFile('x', [], {})
        inp.file_num = file_num
        inp.get_results(str(d))
        return inp

    def test_min3p_branch_writes_groups(self, tmp_path, monkeypatch):
        import xarray as xr
        from core import file_methods as core_fm

        # Two ragged batch series (different step counts) + a spatial category.
        long_lbc = BATCH_LBC + '  2.0   3.0e-5  5.0e-6\r\n'
        dataset = {
            0: self._make_file(tmp_path, 'test', 'lbc', long_lbc, 0),
            1: self._make_file(tmp_path, 'test', 'lbc', BATCH_LBC, 1),
        }
        monkeypatch.chdir(tmp_path)
        core_fm.dataset_to_netcdf(dataset, simulator='min3p')

        g = xr.open_dataset(tmp_path / 'results.nc', group='lbc')
        assert g.sizes['file_num'] == 2
        # Positional concat -> real times kept as (file_num, step) coordinate.
        assert set(g['time'].dims) == {'file_num', 'step'}
        # File 0's data is intact at its own last valid step.
        import numpy as np
        ca0 = g['ca+2'].isel(file_num=0, output=0).values
        assert float(ca0[~np.isnan(ca0)][-1]) == pytest.approx(5.0e-6)

    def test_min3p_sanitises_slash_in_names(self, tmp_path, monkeypatch):
        import xarray as xr
        from core import file_methods as core_fm

        slashed = (
            'title = "dataset test"\r\n'
            'variables = "time","C-Alk [eq/L]"\r\n'
            'zone t = "batch", f=point\r\n'
            '  0.0   1.0\r\n  1.0   2.0\r\n'
        )
        dataset = {0: self._make_file(tmp_path, 'test', 'lbm', slashed, 0)}
        monkeypatch.chdir(tmp_path)
        core_fm.dataset_to_netcdf(dataset, simulator='min3p')
        g = xr.open_dataset(tmp_path / 'results.nc', group='lbm')
        assert 'C-Alk [eq_per_L]' in g.data_vars


# ---------------------------------------------------------------------------
# Round-trip on the real benchmark file, if present.
# ---------------------------------------------------------------------------
APPELO = Path('/Users/hjb62/MIN3P/Examples/Benchmarks/benchmarks_standard/batch/appelo/appelo.dat')
MCD2 = Path('/Users/hjb62/MIN3P/Examples/benchmarks_standard/reactran/MCD-2/min3p/test.dat')
ENERGY = Path('/Users/hjb62/MIN3P/Examples/Benchmarks/benchmarking_nwmo_report/'
              'nwmo_verification_examples_D4/d41_radial_flow_energy/radial-flow.dat')


def _content(text):
    return [l.tokens for l in map(Line.parse, text.split('\n')) if l.kind == 'content']


def _round_trip(path):
    elements, kb, nl = Template.read_file(str(path))
    rendered = []
    for e in elements:
        rendered.extend(e.render() if isinstance(e, Min3pBlock) else [e.render()])
    return _content(path.read_text(newline='', errors='replace')), _content(nl.join(rendered))


@pytest.mark.skipif(not APPELO.is_file(), reason='MIN3P benchmark not available')
class TestRealBenchmark:
    def test_appelo_round_trip(self):
        original, produced = _round_trip(APPELO)
        assert produced == original


@pytest.mark.skipif(not MCD2.is_file(), reason='MIN3P MCD-2 benchmark not available')
class TestTransportBenchmark:
    """Phase 2: 1-D reactive-transport block parsing (reactran/MCD-2)."""

    def test_mcd2_round_trip(self):
        original, produced = _round_trip(MCD2)
        assert produced == original

    def test_transport_blocks_detected(self):
        t = Template({'template': str(MCD2), 'number_of_files': 1})
        for name in ('spatial discretization', 'time step control - global system',
                     'control parameters - reactive transport',
                     'physical parameters - reactive transport',
                     'initial condition - reactive transport',
                     'boundary conditions - reactive transport'):
            assert name in t.keyword_blocks

    def test_concentration_input_grouped(self):
        t = Template({'template': str(MCD2), 'number_of_files': 1})
        ic = t.keyword_blocks['initial condition - reactive transport']
        conc = ic.contents['concentration input']
        # 4 components: h+1 (as pH), cl-1, na+1, no3-1.
        assert len(conc) == 4
        assert conc[0].tokens == ['6.0', "'ph'"]

    def test_boundary_zones_disambiguated(self):
        t = Template({'template': str(MCD2), 'number_of_files': 1})
        bc = t.keyword_blocks['boundary conditions - reactive transport']
        # Inflow (zone 1) and outflow (zone 2) each have a concentration input.
        assert bc.contents['concentration input'][0].tokens == ['4.0', "'ph'"]
        assert bc.contents['concentration input#2'][0].tokens == ['6.0', "'ph'"]

    def test_inflow_ph_sweep_modifies_zone1_only(self):
        cfg = {
            'template': str(MCD2), 'number_of_files': 3,
            'modifications': {
                'ph': {'block': 'boundary conditions - reactive transport',
                       'keyword': 'concentration input', 'line': 0, 'token': 0,
                       'method': 'custom', 'params': [3.0, 4.0, 5.0]},
            },
        }
        t = Template(cfg)
        fd = gi.configure_input_files(t, '.')
        bc = 'boundary conditions - reactive transport'
        inflow = [fd[i].keyword_blocks[bc].contents['concentration input'][0].tokens[0] for i in fd]
        outflow = [fd[i].keyword_blocks[bc].contents['concentration input#2'][0].tokens[0] for i in fd]
        assert inflow == ['3', '4', '5']
        # Outflow zone untouched by a modification targeting zone 1.
        assert outflow == ['6.0', '6.0', '6.0']


class TestRestartChain:
    """Phase 3: MIN3P restart chains (configure_staged_input_files)."""

    def test_staged_structure_and_restart_flags(self, sample_config):
        # SAMPLE_DAT has no time-step block, so drive the final-time coordinate
        # at the global-control header and check the restart directives.
        sample_config['restart_chain'] = {
            'stages': 3,
            'final_times': None,
            'append': 'append results',
        }
        t = Template(sample_config)
        staged = gi.configure_staged_input_files(t, '.')
        assert set(staged) == {0, 1, 2}
        assert set(staged[0]) == {0, 1, 2}
        for run_num in staged:
            gc0 = staged[run_num][0].keyword_blocks['global control parameters']
            assert 'restart' not in gc0.contents          # stage 0 never restarts
            for stage in (1, 2):
                gc = staged[run_num][stage].keyword_blocks['global control parameters']
                assert 'restart' in gc.contents
                assert 'append results' in gc.contents
                assert staged[run_num][stage].stage_num == stage

    def test_final_times_length_mismatch_raises(self, sample_config):
        sample_config['restart_chain'] = {'stages': 2, 'final_times': [100.0]}
        t = Template(sample_config)
        with pytest.raises(ValueError, match='must match'):
            gi.configure_staged_input_files(t, '.')


@pytest.mark.skipif(not MCD2.is_file(), reason='MIN3P MCD-2 benchmark not available')
class TestRestartChainRealTemplate:
    def test_final_time_set_per_stage(self):
        cfg = {
            'template': str(MCD2), 'number_of_files': 1,
            'restart_chain': {'stages': 2, 'final_times': [100.0, 200.0],
                              'append': 'append results'},
        }
        t = Template(cfg)
        staged = gi.configure_staged_input_files(t, '.')
        ts = 'time step control - global system'
        s0 = staged[0][0].keyword_blocks[ts].contents['_header'][2].tokens[0]
        s1 = staged[0][1].keyword_blocks[ts].contents['_header'][2].tokens[0]
        assert (s0, s1) == ('100', '200')
        # Stage 1 carries restart directives; stage 0 does not.
        assert 'restart' not in staged[0][0].keyword_blocks['global control parameters'].contents
        assert 'restart' in staged[0][1].keyword_blocks['global control parameters'].contents


class TestSpatialMultiCategory:
    """get_results/data_cats over several spatial categories (Phase 2/3)."""

    def test_data_cats_includes_all_families(self, tmp_path):
        (tmp_path / 'root.dat').write_text('test\n')
        # one of each family: spatial, breakthrough, batch
        (tmp_path / 'test_1.gsc').write_text(SPATIAL_GSP, newline='')
        (tmp_path / 'test_1.gsv').write_text(SPATIAL_GSP, newline='')   # new spatial
        (tmp_path / 'test_1.gbc').write_text(BATCH_LBC, newline='')     # breakthrough
        (tmp_path / 'test_1.lbc').write_text(BATCH_LBC, newline='')     # batch
        cats = fm.data_cats(tmp_path)
        assert {'gsc', 'gsv', 'gbc', 'lbc'} <= cats

    def test_parse_breakthrough_time_indexed(self, tmp_path):
        # gb* breakthrough files are time series at a point (leading col 'time'),
        # parsed the same way as batch lb* files.
        (tmp_path / 'root.dat').write_text('test\n')
        (tmp_path / 'test_1.gbc').write_text(BATCH_LBC, newline='')
        ds = fm.parse_output(tmp_path, 'gbc', 1)
        assert 'time' in ds.coords
        assert float(ds['ca+2'].isel(time=-1)) == pytest.approx(3.0e-6)


# ---------------------------------------------------------------------------
# Phase 3: advective flow (.vel output + flow-parameter modification)
# ---------------------------------------------------------------------------
VEL_FILE = (
    'title = "dataset test"\r\n'
    'variables = "x", "y", "z", "vx", "vy", "vz"\r\n'
    'zone t = "velocities, steady state" , i = 3, j = 1, k = 1, f=point\r\n'
    '  0.0  0.0  0.0  4.32e-4  0.0  0.0\r\n'
    '  0.5  0.0  0.0  4.32e-4  0.0  0.0\r\n'
    '  1.0  0.0  0.0  4.32e-4  0.0  0.0\r\n'
)


@pytest.mark.skipif(not ENERGY.is_file(), reason='MIN3P energy benchmark not available')
class TestEnergyBenchmark:
    """Phase 3: energy-balance (heat transport) block parsing and sweeps.

    NB: the shipped benchmark has a defect in its reactive-transport boundary
    block (``'extent of zone'Potranco``) that MIN3P itself rejects at run time;
    it does not affect parsing of the energy blocks exercised here, and Omphalos
    round-trips the file faithfully regardless.
    """

    def test_energy_blocks_detected(self):
        t = Template({'template': str(ENERGY), 'number_of_files': 1})
        for name in ('control parameters - energy balance',
                     'physical parameters - energy balance',
                     'initial condition - energy balance',
                     'boundary conditions - energy balance'):
            assert name in t.keyword_blocks

    def test_global_control_energy_flag_grouped(self):
        t = Template({'template': str(ENERGY), 'number_of_files': 1})
        gcp = t.keyword_blocks['global control parameters']
        assert 'energy balance' in gcp.contents
        assert 'density dependent flow' in gcp.contents

    def test_thermal_conductivity_addressable(self):
        t = Template({'template': str(ENERGY), 'number_of_files': 1})
        pe = t.keyword_blocks['physical parameters - energy balance']
        assert pe.contents['solid thermal conductivity in x-direction'][0].tokens == ['3.5d0']

    def test_inflow_temperature_sweep(self):
        cfg = {
            'template': str(ENERGY), 'number_of_files': 3,
            'modifications': {
                't': {'block': 'boundary conditions - energy balance',
                      'keyword': 'boundary type', 'line': 0, 'token': 1,
                      'method': 'linspace', 'params': [10.0, 30.0]},
            },
        }
        t = Template(cfg)
        fd = gi.configure_input_files(t, '.')
        bc = 'boundary conditions - energy balance'
        temps = [fd[i].keyword_blocks[bc].contents['boundary type'][0].tokens[1] for i in fd]
        kinds = [fd[i].keyword_blocks[bc].contents['boundary type'][0].tokens[0] for i in fd]
        assert temps == ['10', '20', '30']
        assert kinds == ["'free'", "'free'", "'free'"]


class TestVelocityOutput:
    def test_parse_vel(self, tmp_path):
        (tmp_path / 'root.dat').write_text('test\n')
        (tmp_path / 'test_1.vel').write_text(VEL_FILE, newline='')
        ds = fm.parse_output(tmp_path, 'vel', 1)
        assert set(('vx', 'vy', 'vz')).issubset(ds.data_vars)
        assert float(ds['vx'].sel(x=0.5, y=0.0, z=0.0)) == pytest.approx(4.32e-4)


MCD2_ADV = Path('/Users/hjb62/MIN3P/Examples/benchmarks_standard/'
                'reactran/MCD-2-advection/min3p/test.dat')


@pytest.mark.skipif(not MCD2_ADV.is_file(), reason='MIN3P advection benchmark not available')
class TestFlowBenchmark:
    """Phase 3: advective-flow block parsing and flow-parameter sweeps."""

    def test_advection_round_trip(self):
        original, produced = _round_trip(MCD2_ADV)
        assert produced == original

    def test_hydraulic_conductivity_addressable(self):
        t = Template({'template': str(MCD2_ADV), 'number_of_files': 1})
        pf = t.keyword_blocks['physical parameters - variably saturated flow']
        assert pf.contents['hydraulic conductivity in x-direction'][0].tokens == ['5.0d-7']

    def test_outflow_head_sweep(self):
        cfg = {
            'template': str(MCD2_ADV), 'number_of_files': 3,
            'modifications': {
                'head': {'block': 'boundary conditions - variably saturated flow',
                         'keyword': 'boundary type#2', 'line': 0, 'token': 1,
                         'method': 'custom', 'params': [0.99, 0.95, 0.90]},
            },
        }
        t = Template(cfg)
        fd = gi.configure_input_files(t, '.')
        bc = 'boundary conditions - variably saturated flow'
        # Zone-2 (outflow) head varied; token 0 ('first') and zone-1 untouched.
        heads = [fd[i].keyword_blocks[bc].contents['boundary type#2'][0].tokens[1] for i in fd]
        types = [fd[i].keyword_blocks[bc].contents['boundary type#2'][0].tokens[0] for i in fd]
        inflow = [fd[i].keyword_blocks[bc].contents['boundary type'][0].tokens[1] for i in fd]
        assert heads == ['0.99', '0.95', '0.9']
        assert types == ["'first'", "'first'", "'first'"]
        assert inflow == ['1.0', '1.0', '1.0']
