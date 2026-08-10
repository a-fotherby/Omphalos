"""Unit tests for omphalos/restart_file.py.

The fixture is a real CrunchTope restart (see tests/restart_test/README.md). That matters: the
shapes these tests pin were all settled by matching against tecplot output, and a synthetic file
would pin whatever the code already does.

nx = 10 is deliberately small. Pure factorisation of the element counts is ambiguous at that size —
it prefers sp = (3, 10, 4, 4) over the true (ncomp+nspec, nx+2) — so a fixture this small is the
regression test for the declaration-driven layout.
"""

import struct

import numpy as np
import pytest

from omphalos import restart_file as rf

NX = 10
NCOMP = 23
NSPEC = 17
NGAS = 3
NRCT = 9
IKIN = 7


@pytest.fixture
def rst(restart_test_dir):
    """The 10-cell CrunchTope restart file."""
    return restart_test_dir / "sukinda10.rst"


@pytest.fixture
def deck(restart_test_dir):
    """The input deck that wrote the restart file."""
    return restart_test_dir / "sukinda_column.in"


@pytest.fixture
def dims(deck):
    """Model dimensions read from the deck."""
    return rf.model_dimensions(deck)


@pytest.fixture
def specs(rst, dims):
    """Inferred layout, keyed by record name."""
    return {s.name: s for s in rf.infer_layout(rst, NX, dims)}


class TestRecordContainer:
    """Tests for the Fortran unformatted sequential reader and writer."""

    def test_record_count(self, rst):
        _, records = rf.read_records(rst)
        assert len(records) == 52, 'no gas saturation and no erosion, so neither block fired'

    def test_round_trip(self, rst, tmp_path):
        buf, records = rf.read_records(rst)
        payloads = [buf[offset:offset + nbytes] for offset, nbytes in records]
        out = tmp_path / 'copy.rst'
        rf.write_records(out, payloads)

        assert out.read_bytes() == rst.read_bytes()

    def test_empty_file_raises(self, tmp_path):
        empty = tmp_path / 'empty.rst'
        empty.write_bytes(b'')

        with pytest.raises(rf.RstError, match='empty'):
            rf.read_records(empty)

    def test_truncated_file_raises(self, rst, tmp_path):
        truncated = tmp_path / 'truncated.rst'
        truncated.write_bytes(rst.read_bytes()[:-8])

        with pytest.raises(rf.RstError, match='past end of file'):
            rf.read_records(truncated)

    def test_marker_mismatch_raises(self, tmp_path):
        """A trailing marker that disagrees with the leading one means the file is not what we think.

        This is the check that catches a different marker width, which would otherwise be read as
        plausible garbage.
        """
        bad = tmp_path / 'mismatch.rst'
        bad.write_bytes(rf.MARKER.pack(8) + b'\x00' * 8 + rf.MARKER.pack(12))

        with pytest.raises(rf.RstError, match='marker mismatch'):
            rf.read_records(bad)

    def test_negative_marker_raises(self, tmp_path):
        bad = tmp_path / 'negative.rst'
        bad.write_bytes(rf.MARKER.pack(-8))

        with pytest.raises(rf.RstError, match='negative record length'):
            rf.read_records(bad)


class TestRecordNames:
    """Tests for mapping the record count onto the writer's conditional blocks."""

    @pytest.mark.parametrize('count', [52, 54, 56])
    def test_known_counts_resolve(self, count):
        assert len(rf._record_names(count)) == count

    def test_saturation_block(self):
        """54 records means one of the two conditional blocks fired."""
        names = rf._record_names(54)
        assert ('sgas' in names) or ('ssurf' in names)

    def test_both_blocks(self):
        names = rf._record_names(56)
        assert 'sgas' in names and 'ssurf' in names

    def test_unexpected_count_raises(self):
        """Refusing is the right failure mode: mis-parsing would corrupt silently."""
        with pytest.raises(rf.RstError, match='matches no expected CrunchTope layout'):
            rf._record_names(53)


class TestModelDimensions:
    """Tests for counting the species blocks that fix the leading axis sizes."""

    def test_counts_from_deck(self, dims):
        assert dims['PRIMARY_SPECIES'] == NCOMP
        assert dims['SECONDARY_SPECIES'] == NSPEC
        assert dims['GASES'] == NGAS
        assert dims['MINERALS'] == NRCT
        assert dims['AQUEOUS_KINETICS'] == IKIN

    def test_input_file_agrees_with_deck(self, deck, dims):
        """The parsed-InputFile route must give the same answer as re-reading the deck.

        The block's own name is the first key of contents, so a naive len() returns ncomp + 1 — the
        off-by-one that makes s decompose plausibly and wrongly.
        """
        from omphalos.template import Template

        config = {'template': str(deck), 'aqueous_database': None, 'catabolic_pathways': None,
                  'database': None, 'conditions': None, 'later_inputfiles': None}
        template = Template(config)

        assert rf.dims_from_input_file(template) == dims


class TestDeclaredLayout:
    """Tests that every record decomposes as its ALLOCATE declaration says it should.

    This is the table in the integration notes, evaluated for this model: 23 primary species, 17
    secondary, 3 gases, 9 minerals, 7 aqueous kinetic reactions, on 10 cells.
    """

    @pytest.mark.parametrize('name, shape, xaxis, pad', [
        ('keqaq', (NSPEC, NX), 1, 0),
        ('keqgas', (NGAS, NX), 1, 0),
        ('xgram', (NX + 3, 3, 3), 0, 3),
        ('spnO2', (NX,), 0, 0),
        ('sp', (NCOMP + NSPEC, NX + 2), 1, 2),
        ('sp10', (NCOMP + NSPEC, NX + 2), 1, 2),
        ('spold', (NCOMP + NSPEC, NX + 2), 1, 2),
        ('s', (NCOMP, NX + 2, 3), 1, 2),
        ('sn', (NCOMP, NX), 1, 0),
        ('gam', (NCOMP + NSPEC, NX), 1, 0),
        ('spgas', (NGAS, NX + 2), 1, 2),
        ('raq_tot', (IKIN, NX), 1, 0),
        ('keqmin', (NRCT, NX), 1, 0),
        ('volfx', (NRCT, NX + 1), 1, 1),
        ('t', (NX + 2,), 0, 2),
        ('por', (NX + 4, 5, 5), 0, 4),
        ('ro', (NX + 4, 5, 5), 0, 4),
        ('satliq', (NX + 4, 5, 5), 0, 4),
        ('pres', (NX + 2, 3, 3), 0, 2),
        ('qxgas', (NX + 1,), 0, 1),
        ('jinit', (NX,), 0, 0),
        ('ActiveCell', (NX,), 0, 0),
        ('Volsave', (NRCT, NX + 1), 1, 1),
    ])
    def test_shape(self, specs, name, shape, xaxis, pad):
        spec = specs[name]
        assert spec.shape == shape
        assert spec.xaxis == xaxis
        assert spec.pad == pad

    def test_every_record_comes_from_a_declaration(self, specs):
        """Nothing should be falling through to the factorisation guesser for this model."""
        guessed = [s.name for s in specs.values() if s.source == 'factorisation']
        assert guessed == []

    def test_nothing_ambiguous(self, specs):
        assert [s.name for s in specs.values() if s.ambiguous] == []

    def test_spold_drift_is_reported(self, specs):
        """spold is declared (ncomp+nspec, nx) but the shipped binary writes nx+2.

        The x extent is solved from the element count so the file still parses, but the mismatch
        against the source must be surfaced rather than absorbed silently.
        """
        notes = ' '.join(specs['spold'].notes)
        assert 'solved from the record' in notes
        assert 'declares 10' in notes

    def test_volsave_by_timestep_flattens_the_leading_axes(self, specs):
        """VolSaveByTimeStep is (101, nrct, 0:nx): the two leading axes collapse into one.

        Fortran is column-major, so (101, 9, 11) and (909, 11) are the same bytes with x in the
        same place. Pinning it guards the collapse, which is what makes the resample valid.
        """
        assert specs['VolSaveByTimeStep'].shape == (101 * NRCT, NX + 1)
        assert specs['VolSaveByTimeStep'].xaxis == 1

    def test_empty_records_are_grid_independent(self, specs):
        """Blocks the model does not use are written as zero-length records."""
        for name in ('keqsurf', 'spex', 'exchangesites', 'LogPotential'):
            assert not specs[name].grid_dependent
            assert specs[name].count == 0

    def test_nx_below_two_raises(self, rst, dims):
        with pytest.raises(rf.RstError, match='nx must be at least 2'):
            rf.infer_layout(rst, 1, dims)


class TestFactorisationFallback:
    """Tests for the guesser that runs when a record has no declaration.

    It is kept only as a fallback, and these tests pin why: without the declarations it gets sp
    wrong at this nx, which is the failure the declaration table exists to prevent.
    """

    def test_without_declarations_sp_is_misread(self, rst, dims, monkeypatch):
        monkeypatch.setattr(rf, 'DECLARATIONS', {})
        specs = {s.name: s for s in rf.infer_layout(rst, NX, dims)}

        assert specs['sp'].shape != (NCOMP + NSPEC, NX + 2)
        assert specs['sp'].source == 'factorisation'

    def test_fallback_admits_it_is_guessing(self, rst, dims, monkeypatch):
        monkeypatch.setattr(rf, 'DECLARATIONS', {})
        specs = {s.name: s for s in rf.infer_layout(rst, NX, dims)}

        assert specs['sp'].ambiguous
        assert any('factorisation' in note for note in specs['sp'].notes)


class TestReference:
    """Tests comparing the parsed arrays against the tecplot output of the same run.

    This validates the reshape *and* the axis assignment on real data, which is the only way the
    layouts were established in the first place.
    """

    def test_all_checks_pass(self, rst, restart_test_dir, dims):
        results = rf.verify_reference(rst, NX, restart_test_dir, dims, file_num=5)

        assert results, 'no reference files found'
        for name, filename, err, status in results:
            assert err is not None, f'{name}: {filename} missing'
            assert status == 'ok', f'{name} vs {filename}: {status} (max rel err {err:.3e})'

    def test_porosity_is_exact(self, rst, restart_test_dir, dims):
        by_name = {r[0]: r for r in rf.verify_reference(rst, NX, restart_test_dir, dims,
                                                        file_num=5)}
        assert by_name['por'][2] < 1e-9

    def test_wrong_file_number_finds_nothing(self, rst, restart_test_dir, dims):
        """The restart is written at the end of the run, so output 1 is not the one to compare."""
        results = rf.verify_reference(rst, NX, restart_test_dir, dims, file_num=1)

        assert all(err is None for _, _, err, _ in results)


class TestIdentity:
    """The strongest single check on the parse/reshape/resample/write path."""

    def test_round_trip_is_byte_identical(self, rst, dims):
        assert rf.verify_identity(rst, NX, dims)

    def test_identity_leaves_no_temporary_behind(self, rst, dims):
        rf.verify_identity(rst, NX, dims)
        assert not list(rst.parent.glob('*.identity.tmp'))


class TestConsistencyReport:
    """Tests for the state invariants, and for the distinction between two kinds of them."""

    def test_log_linear_pair_holds_in_the_original(self, rst, dims):
        """sp10 == exp(sp) is a true invariant of any valid restart file."""
        report = rf.consistency_report(rst, NX, dims)

        assert report['sp10_vs_exp_sp'] == pytest.approx(0.0, abs=1e-12)

    def test_original_file_violates_the_start_conditions(self, rst, dims):
        """s == sn and spnO2 == spnnO2 are *not* invariants.

        A CrunchTope-written file holds two real time levels, so it legitimately violates them.
        Asserting them on an unmodified file would be misleading, and this pins that they are
        genuinely violated rather than vacuously satisfied.
        """
        report = rf.consistency_report(rst, NX, dims)

        assert report['s_vs_sn'] > 1e-4
        assert report['spnO2_vs_spnnO2'] > 0.0


class TestRegrid:
    """Tests for resampling onto a different grid."""

    @pytest.fixture
    def refined(self, rst, deck, dims, tmp_path):
        out = tmp_path / 'refined.rst'
        rf.regrid(rst, NX, 25, out, dims, deck=deck)
        return out

    def test_refined_file_parses(self, refined, dims):
        specs = {s.name: s for s in rf.infer_layout(refined, 25, dims)}
        assert specs['sp'].shape == (NCOMP + NSPEC, 27)

    def test_refined_file_round_trips(self, refined, dims):
        assert rf.verify_identity(refined, 25, dims)

    def test_invariants_hold_after_refinement(self, refined, dims):
        """The regression test for the failure that took the first attempt down.

        Resampling each state array independently leaves a file that looks perfectly well formed
        and then fails Newton on step 1, because GIMRT's residual carries (s - sn)/delt.
        """
        report = rf.consistency_report(refined, 25, dims)

        assert report['sp10_vs_exp_sp'] < 1e-12
        assert report['s_vs_sn'] == pytest.approx(0.0, abs=1e-12)
        assert report['sp_vs_spold'] == pytest.approx(0.0, abs=1e-12)
        assert report['spnO2_vs_spnnO2'] == pytest.approx(0.0, abs=1e-12)

    def test_consistency_pass_reports_what_it_rewrote(self, rst, deck, dims, tmp_path):
        _, rewritten = rf.regrid(rst, NX, 25, tmp_path / 'out.rst', dims, deck=deck)

        assert set(rewritten) == {'sp10', 'sp', 'spold', 'sn', 'spnO2', 'spnnO2'}

    def test_consistency_can_be_turned_off(self, rst, deck, dims, tmp_path):
        _, rewritten = rf.regrid(rst, NX, 25, tmp_path / 'out.rst', dims, deck=deck,
                                 consistent=False)

        assert rewritten == []

    def test_consistency_leaves_ghost_cells_alone(self, rst, deck, dims, tmp_path):
        """The ghosts of sp and sp10 are 0.0 in a written file — not a consistent log/linear pair.

        Writing ln(1e-30) into them would be putting a made-up number into boundary storage.
        """
        raw = tmp_path / 'raw.rst'
        cooked = tmp_path / 'cooked.rst'
        rf.regrid(rst, NX, 25, raw, dims, deck=deck, consistent=False)
        rf.regrid(rst, NX, 25, cooked, dims, deck=deck, consistent=True)

        for name in ('sp', 'sp10'):
            before = _record(raw, 25, dims, name)
            after = _record(cooked, 25, dims, name)
            assert np.array_equal(before[:, 0], after[:, 0]), f'{name} leading ghost was written'
            assert np.array_equal(before[:, -1], after[:, -1]), f'{name} trailing ghost was written'

    def test_integer_labels_stay_integral(self, refined, dims, rst):
        """jinit and ActiveCell are labels, so they resample by nearest neighbour."""
        source = set(np.unique(_record(rst, NX, dims, 'jinit')))
        result = _record(refined, 25, dims, 'jinit')

        assert result.dtype == np.int32
        assert set(np.unique(result)) <= source

    def test_interior_is_interpolated_not_extrapolated(self, refined, rst, dims):
        """Refinement interpolates strictly within the source range."""
        source = _record(rst, NX, dims, 'gam')
        result = _record(refined, 25, dims, 'gam')

        assert result.min() >= source.min() - 1e-12
        assert result.max() <= source.max() + 1e-12

    def test_refine_then_coarsen_recovers_the_interior(self, rst, deck, dims, tmp_path):
        """Not a round trip — assert only that the interior survives within interpolation error."""
        fine = tmp_path / 'fine.rst'
        back = tmp_path / 'back.rst'
        rf.regrid(rst, NX, 50, fine, dims, deck=deck, consistent=False)
        rf.regrid(fine, 50, NX, back, dims, deck=deck, consistent=False)

        specs = {s.name: s for s in rf.infer_layout(rst, NX, dims)}
        original = rf.interior_profile(_record(rst, NX, dims, 'gam'), specs['gam'], NX)
        recovered = rf.interior_profile(_record(back, NX, dims, 'gam'), specs['gam'], NX)

        # The end cells see the boundary clamp, so compare the strict interior.
        assert np.allclose(original[1:-1], recovered[1:-1], rtol=1e-2)

    def test_unresolvable_record_refuses(self, rst, dims, tmp_path, monkeypatch):
        """Refusing beats writing a plausible file with a scrambled record."""
        monkeypatch.setattr(rf, 'DECLARATIONS', {})
        monkeypatch.setattr(rf, '_from_factorisation', lambda spec, nx, leads: False)

        with pytest.raises(rf.RstError, match='no x decomposition'):
            rf.regrid(rst, NX, 25, tmp_path / 'out.rst', dims)


class TestOverrides:
    """Tests for the scalars a restarted deck cannot set for itself."""

    def test_set_dtmax(self, rst, dims, tmp_path):
        """restart.F90 takes dtmax from the file, so the deck's timestep_max is ignored."""
        out = tmp_path / 'out.rst'
        rf.regrid(rst, NX, NX, out, dims, set_dtmax=0.5, consistent=False)

        assert _tsteps(out)[5] == pytest.approx(0.5)

    def test_set_dtold(self, rst, dims, tmp_path):
        out = tmp_path / 'out.rst'
        rf.regrid(rst, NX, NX, out, dims, set_dtold=1e-6, consistent=False)

        assert _tsteps(out)[1] == pytest.approx(1e-6)

    def test_other_timestep_scalars_are_untouched(self, rst, dims, tmp_path):
        """restart.F90 discards delt, tstep, deltmin and dtmaxcour, so leave them as they were."""
        out = tmp_path / 'out.rst'
        rf.regrid(rst, NX, NX, out, dims, set_dtmax=0.5, consistent=False)

        before, after = _tsteps(rst), _tsteps(out)
        assert [before[i] for i in (0, 2, 3, 4)] == [after[i] for i in (0, 2, 3, 4)]

    def test_set_time(self, rst, dims, tmp_path):
        out = tmp_path / 'out.rst'
        rf.regrid(rst, NX, NX, out, dims, set_time=3.5, consistent=False)

        buf, records = rf.read_records(out)
        assert struct.unpack_from('<d', buf, records[0][0])[0] == pytest.approx(3.5)


class TestInject:
    """Tests for overriding a field the restart would otherwise impose on the new grid."""

    def test_injected_porosity_appears_exactly(self, rst, deck, dims, tmp_path):
        """CALL restart runs after CALL StartTope, so the file beats read_PorosityFile."""
        wanted = np.linspace(0.2, 0.5, 25)
        out = tmp_path / 'out.rst'
        rf.regrid(rst, NX, 25, out, dims, deck=deck, inject={'por': wanted})

        specs = {s.name: s for s in rf.infer_layout(out, 25, dims)}
        profile = rf.interior_profile(_record(out, 25, dims, 'por'), specs['por'], 25)

        assert np.allclose(profile, wanted)

    def test_ghost_layers_are_edge_replicated(self, rst, deck, dims, tmp_path):
        wanted = np.linspace(0.2, 0.5, 25)
        out = tmp_path / 'out.rst'
        rf.regrid(rst, NX, 25, out, dims, deck=deck, inject={'por': wanted})

        # por is (-1:nx+2, ...), so two ghost cells at each end of the physical slice.
        por = _record(out, 25, dims, 'por')
        assert por[0, 2, 2] == pytest.approx(wanted[0])
        assert por[1, 2, 2] == pytest.approx(wanted[0])
        assert por[-1, 2, 2] == pytest.approx(wanted[-1])

    def test_wrong_length_refuses(self, rst, deck, dims, tmp_path):
        with pytest.raises(rf.RstError, match='expected 25'):
            rf.regrid(rst, NX, 25, tmp_path / 'out.rst', dims, deck=deck,
                      inject={'por': np.zeros(10)})


class TestMasterIndex:
    """Tests for locating the timestep-control master variable."""

    def test_explicit_keyword_wins(self, deck):
        """The deck says 'master H+', and H+ is the first primary species."""
        assert rf.master_index(deck) == 0

    def test_no_deck_gives_zero(self):
        """Not knowing only mis-aims a diagnostic; it does not change the equations."""
        assert rf.master_index(None) == 0


def _record(path, nx, dims, name):
    """Load one named record from a restart file."""
    specs = {s.name: s for s in rf.infer_layout(path, nx, dims)}
    buf, records = rf.read_records(path)
    spec = specs[name]
    return rf.load_record(buf, records[spec.index][0], spec)


def _tsteps(path):
    """The six timestep scalars: delt, dtold, tstep, deltmin, dtmaxcour, dtmax."""
    buf, records = rf.read_records(path)
    return list(struct.unpack_from('<6d', buf, records[3][0]))


class TestGradedGrids:
    """Tests for grids whose cells are not all the same width.

    A refinement chain often wants to refine part of a column rather than all of it — coarse at the
    top, fine through the interval of interest, coarse again at the bottom. Resampling that by cell
    index rather than by position misplaces every value outside the uniform zone.
    """

    #: Coarse / fine / coarse: 4 + 12 + 4 = 20 cells.
    GRADED = ['4', '5.0', '12', '1.6667', '4', '5.0']
    UNIFORM = [str(NX), '10.0']

    def test_cell_widths(self):
        widths = rf.cell_widths(self.GRADED, 20)

        assert len(widths) == 20
        assert widths[0] == 5.0
        assert widths[10] == pytest.approx(1.6667)
        assert widths[-1] == 5.0

    def test_uniform_when_no_zones_given(self):
        assert np.array_equal(rf.cell_widths(None, 5), np.ones(5))

    def test_cell_count_disagreement_raises(self):
        """A zones list that does not add up to nx means one of the two is wrong."""
        with pytest.raises(rf.RstError, match='disagree'):
            rf.cell_widths(self.GRADED, 19)

    def test_centres_cluster_where_the_grid_is_fine(self):
        edges = rf._edges(20, self.GRADED)
        centres = 0.5 * (edges[:-1] + edges[1:])
        spacing = np.diff(centres)

        assert edges[0] == 0.0 and edges[-1] == pytest.approx(1.0)
        assert spacing[len(spacing) // 2] < spacing[0]

    def test_uniform_zones_match_the_default(self):
        """Stating a uniform grid explicitly must give exactly what assuming one gives."""
        assert np.allclose(rf._coords(NX, 2, 1, self.UNIFORM), rf._coords(NX, 2, 1, None))

    def test_ghosts_use_the_edge_cell_width(self):
        """A ghost sits one cell beyond the edge, and on a graded grid those cells differ."""
        coords = rf._coords(20, 2, 1, self.GRADED)
        edges = rf._edges(20, self.GRADED)
        centres = 0.5 * (edges[:-1] + edges[1:])

        assert coords[0] == pytest.approx(centres[0] - (edges[1] - edges[0]))
        assert coords[-1] == pytest.approx(centres[-1] + (edges[-1] - edges[-2]))

    def test_regrid_maps_by_position(self, rst, dims, tmp_path):
        """The grid-aware resample must reproduce interpolation at the real cell positions."""
        out = tmp_path / 'graded.rst'
        rf.regrid(rst, NX, 20, out, dims, consistent=False,
                  zones_in=self.UNIFORM, zones_out=self.GRADED)

        source = rf.interior_profile(_record(rst, NX, dims, 'gam'),
                                     _spec(rst, NX, dims, 'gam'), NX)
        src_x = _centres(NX, self.UNIFORM)
        expected = np.interp(_centres(20, self.GRADED), src_x, source)

        got = rf.interior_profile(_record(out, 20, dims, 'gam'),
                                  _spec(out, 20, dims, 'gam'), 20)

        assert np.allclose(got, expected)

    def test_ignoring_the_grading_gets_it_wrong(self, rst, dims, tmp_path):
        """Pins that the zones argument is doing work, not just being carried around."""
        aware, naive = tmp_path / 'aware.rst', tmp_path / 'naive.rst'
        rf.regrid(rst, NX, 20, aware, dims, consistent=False,
                  zones_in=self.UNIFORM, zones_out=self.GRADED)
        rf.regrid(rst, NX, 20, naive, dims, consistent=False)

        a = rf.interior_profile(_record(aware, 20, dims, 'gam'), _spec(aware, 20, dims, 'gam'), 20)
        n = rf.interior_profile(_record(naive, 20, dims, 'gam'), _spec(naive, 20, dims, 'gam'), 20)

        assert not np.allclose(a, n)

    def test_redistributing_cells_at_constant_nx(self, rst, dims, tmp_path):
        """Keeping nx and moving the cells is a real regrid, not a no-op."""
        out = tmp_path / 'same_nx.rst'
        graded_10 = ['2', '20.0', '6', '6.6667', '2', '20.0']
        rf.regrid(rst, NX, NX, out, dims, consistent=False,
                  zones_in=self.UNIFORM, zones_out=graded_10)

        assert out.read_bytes() != rst.read_bytes()


class TestGhostLayerCount:
    """Tests that the number of entries before cell 1 comes from the declaration.

    Assuming it is half the padding is right for every symmetric case, but (-1:nx+1) stores two
    entries before cell 1 and one after cell nx.
    """

    def test_symmetric_padding(self, specs):
        assert specs['sp'].lead_ghost == 1        # (0:nx+1)
        assert specs['por'].lead_ghost == 2       # (-1:nx+2)
        assert specs['sn'].lead_ghost == 0        # (nx)

    def test_asymmetric_padding(self, specs):
        """xgram is (-1:nx+1): three extra entries, two of them leading."""
        assert specs['xgram'].pad == 3
        assert specs['xgram'].lead_ghost == 2

    def test_solved_extent_falls_back_to_symmetric(self, specs):
        """spold is declared (ncomp+nspec,nx) and written with nx+2.

        The declaration is out of date for this array, so it says nothing about where the extra
        entries went; assuming they are split evenly recovers sp's layout, which is what the binary
        writes and what the consistency pass compares against.
        """
        assert specs['spold'].lead_ghost == specs['sp'].lead_ghost

    def test_interior_slice_uses_it(self, specs):
        """A wrong count would take the physical cells from one place and the ghosts from another."""
        assert rf._interior_slice(specs['xgram'], NX)[0] == slice(2, 2 + NX)


def _spec(path, nx, dims, name):
    """The RecordSpec for one named record."""
    return {s.name: s for s in rf.infer_layout(path, nx, dims)}[name]


def _centres(nx, zones):
    """Normalised cell-centre positions for a grid."""
    edges = rf._edges(nx, zones)
    return 0.5 * (edges[:-1] + edges[1:])


class TestZeroSizedDimensions:
    """A block the deck does not declare counts as zero, not as unknown.

    Regression test. Dropping an absent block left 'ncomp+nspec' unresolvable for a model with no
    secondary species, and an unresolvable leading axis is treated as free — which let a spurious
    decomposition win. On a 3-primary, 0-secondary column, sp came out as (nx+2, 3) with x on
    axis 0 instead of (3, nx+2) with x on axis 1, and the restart diverged to NaN on step 1.
    """

    DIMS = {'PRIMARY_SPECIES': 3, 'SECONDARY_SPECIES': 0, 'GASES': 0, 'MINERALS': 1,
            'AQUEOUS_KINETICS': 0, 'ION_EXCHANGE': 0, 'SURFACE_COMPLEXATION': 0}

    def test_zero_is_a_value(self):
        symbols = rf._symbol_values(self.DIMS)

        assert symbols['nspec'] == 0
        assert symbols['ncomp'] == 3

    def test_composite_symbol_resolves_through_a_zero(self):
        symbols = rf._symbol_values(self.DIMS)

        assert rf._symbol_product('ncomp+nspec', symbols) == 3

    def test_sp_keeps_x_on_the_component_axis(self):
        """(ncomp+nspec, 0:nx+1) with ncomp+nspec = 3 must not be read as (nx+2, 3)."""
        nx = 100
        spec = rf.RecordSpec(index=10, name='sp', nbytes=306 * 8, dtype=np.dtype(np.float64),
                             count=306)

        assert rf._from_declaration(spec, nx, rf._symbol_values(self.DIMS))
        assert spec.shape == (3, nx + 2)
        assert spec.xaxis == 1
        assert not spec.ambiguous

    def test_the_spurious_shape_is_what_an_unresolved_symbol_gives(self):
        """Pins the mechanism: with nspec missing, the wrong decomposition wins."""
        without_nspec = {k: v for k, v in rf._symbol_values(self.DIMS).items() if k != 'nspec'}
        spec = rf.RecordSpec(index=10, name='sp', nbytes=306 * 8, dtype=np.dtype(np.float64),
                             count=306)

        rf._from_declaration(spec, 100, without_nspec)

        assert spec.xaxis == 0, 'the bug this guards against no longer reproduces'
