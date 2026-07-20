"""Integration: the interactive Domain Maker session (multi-domain split).

The old single-range "Split Chain" popup is replaced by a session that opens a
real split-window viewport plus a menu, lets the user build N contiguous
domains, and commits them. These tests drive the session's public operators
(build / create / cancel) headlessly - the window itself is a UI shell, so the
tests seed the session with the product's own ``seed_session`` and exercise the
planning + commit logic that actually creates domains.
"""

import pytest
import bpy

import helpers as H

from proteinblender.operators import domain_maker_session as dms


def _chainA_domains(mol):
    """(start, end, name) for every domain the molecule holds on chain A."""
    return sorted((d.start, d.end, d.name)
                  for d in mol.domains.values()
                  if str(d.chain_id) == "A")


@pytest.mark.integration
def test_build_lays_out_contiguous_domains(scene, sm):
    """Build N domains -> a gap-free, non-overlapping cover of the chain.

    Ground truth is the partition invariant (contiguous, covers the full span),
    asserted independently of how ``_even_ranges`` computes the boundaries.
    """
    mid = H.import_local("1atn.pdb", "1atn")
    info = H.start_domain_maker(mid, "A")
    assert info is not None

    state = bpy.context.window_manager.pb_domain_maker
    chain_start, chain_end = state.chain_start, state.chain_end
    state.num_domains = 5

    assert bpy.ops.proteinblender.domain_maker_build() == {'FINISHED'}
    ranges = [(d.start, d.end) for d in state.domains]

    assert len(ranges) == 5
    assert ranges[0][0] == chain_start
    assert ranges[-1][1] == chain_end
    for (sa, ea), (sb, eb) in zip(ranges, ranges[1:]):
        assert sb == ea + 1, f"gap/overlap between {(sa, ea)} and {(sb, eb)}"

    # Clean up the (headless) session.
    bpy.ops.proteinblender.domain_maker_cancel()
    assert state.active is False


@pytest.mark.integration
def test_create_commits_exactly_the_planned_ranges(scene, sm):
    """Create must produce domains whose spans equal the ones the user planned.

    Independent ground truth: the test hand-authors three explicit ranges (not
    derived from any product helper) and asserts the molecule ends up with
    exactly those chain-A domains.
    """
    mid = H.import_local("1atn.pdb", "1atn")
    H.start_domain_maker(mid, "A")
    state = bpy.context.window_manager.pb_domain_maker
    chain_end = state.chain_end

    # Hand-picked partition, entirely within the chain span.
    planned = [("Head", 1, 100), ("Middle", 101, 220), ("Tail", 221, chain_end)]
    state.built = True
    state.domains.clear()
    for name, s, e in planned:
        item = state.domains.add()
        item.name, item.start, item.end = name, s, e

    assert bpy.ops.proteinblender.domain_maker_create() == {'FINISHED'}

    mol = sm.molecules[mid]
    got = _chainA_domains(mol)
    expected = sorted((s, e, name) for name, s, e in planned)
    assert got == expected, f"created {got}, expected {expected}"

    # Every created domain has a live object (renderable), and the session ended.
    for d in mol.domains.values():
        if str(d.chain_id) == "A":
            assert d.object is not None
    assert state.active is False
    # No stray session window lingered from a headless run.
    assert len(bpy.context.window_manager.windows) == 1


@pytest.mark.integration
def test_create_rejects_overlapping_ranges(scene, sm):
    """Overlapping planned ranges must be refused and create nothing new."""
    mid = H.import_local("1atn.pdb", "1atn")
    H.start_domain_maker(mid, "A")
    state = bpy.context.window_manager.pb_domain_maker
    mol = sm.molecules[mid]
    before = _chainA_domains(mol)

    state.built = True
    state.domains.clear()
    for name, s, e in [("A", 1, 150), ("B", 100, 300)]:  # 100-150 overlaps
        item = state.domains.add()
        item.name, item.start, item.end = name, s, e

    # Reporting an operator ERROR makes bpy.ops raise; the point is that the
    # commit is refused and nothing is created.
    with pytest.raises(RuntimeError, match="overlap"):
        bpy.ops.proteinblender.domain_maker_create()
    # The chain's original single domain is untouched.
    assert _chainA_domains(mol) == before

    bpy.ops.proteinblender.domain_maker_cancel()


@pytest.mark.integration
def test_active_domain_drives_the_live_preview_range(scene, sm):
    """Selecting a domain row isolates that domain's residues in the viewport.

    The preview is implemented by pushing the active domain's [start, end] onto
    the chain object's "Select Res ID Range" node; asserting on those node
    inputs is reading data the node carries, not re-deriving it from the code
    that set it.
    """
    mid = H.import_local("1atn.pdb", "1atn")
    H.start_domain_maker(mid, "A")
    state = bpy.context.window_manager.pb_domain_maker
    state.num_domains = 4
    bpy.ops.proteinblender.domain_maker_build()

    obj = bpy.data.objects.get(state.preview_object)
    _mod, node = dms._find_res_range_node(obj)
    assert node is not None

    def node_range():
        return (node.inputs["Min"].default_value, node.inputs["Max"].default_value)

    # Row 0 active by default.
    d0 = state.domains[0]
    assert node_range() == (d0.start, d0.end)

    # Activate row 2 -> preview jumps to that domain.
    bpy.ops.proteinblender.domain_maker_select(index=2)
    d2 = state.domains[2]
    assert node_range() == (d2.start, d2.end)

    # Editing the active row's end updates the preview live.
    d2.end = d2.end - 7
    assert node_range() == (d2.start, d2.end)

    bpy.ops.proteinblender.domain_maker_cancel()
    # Cancel restores the object to its full residue span.
    assert node_range() == (state.chain_start, state.chain_end)
