"""Pure-logic unit tests for the Protein Blender workspace layout decision.

Background (regression, 2026-07): commit 01a6473 changed
``ProteinWorkspaceManager`` to *keep* the duplicated default Layout's editors
instead of collapsing them to a single viewport. Consequence: the add-on
inherited the stock Layout right column — a native **Outliner** editor stacked
above a **narrow** Properties editor — instead of the single full-height ~30%
Properties column it is designed around. The user saw the Outliner on top and a
skinnier panel.

The *width and position* of real editor areas can only be measured in a GUI
Blender (a ``--background`` session has no window or screen), so that lives in
the integration lane and skips headlessly. What CAN be checked anywhere is the
**decision** that drives the fix: "does this set of editors still carry the
default Layout's foreign right-column editor (the Outliner), meaning the
workspace must be rebuilt?" The regression was precisely that this decision came
out False while an Outliner sat in the column.

Ground truth here is independent of the product code: hand-written lists of
editor types with the known-correct verdict. A layout that contains a native
OUTLINER must be flagged for repair; a consolidated one must not.
"""

import pytest

from proteinblender.layout.workspace_setup import ProteinWorkspaceManager

decide = ProteinWorkspaceManager._layout_needs_repair


# The exact shape produced by duplicating Blender's default "Layout" workspace:
# big viewport, Outliner top-right, Properties under it, timeline along the
# bottom. This is the regressed state the user is looking at.
DEFAULT_LAYOUT = ["VIEW_3D", "OUTLINER", "PROPERTIES", "DOPESHEET_EDITOR"]

# The shape the add-on builds after consolidation: one viewport, one Properties
# column (which hosts the *Protein* Outliner as a panel, not an editor), and a
# timeline. No native OUTLINER editor.
CONSOLIDATED_DOPESHEET = ["VIEW_3D", "PROPERTIES", "DOPESHEET_EDITOR"]
CONSOLIDATED_TIMELINE = ["VIEW_3D", "PROPERTIES", "TIMELINE"]


@pytest.mark.unit
def test_default_layout_is_flagged_for_repair():
    # The regression scenario: an Outliner sitting in the right column means the
    # workspace is still the un-consolidated default Layout and must be rebuilt.
    assert decide(DEFAULT_LAYOUT) is True


@pytest.mark.unit
@pytest.mark.parametrize("layout", [CONSOLIDATED_DOPESHEET, CONSOLIDATED_TIMELINE])
def test_consolidated_layout_is_left_alone(layout):
    # Once consolidated there is no native Outliner, so a later launch must NOT
    # tear the (possibly user-customised) workspace down again.
    assert decide(layout) is False


@pytest.mark.unit
def test_bare_viewport_and_properties_is_not_repaired():
    assert decide(["VIEW_3D", "PROPERTIES"]) is False


@pytest.mark.unit
def test_a_lone_outliner_still_triggers_repair():
    # Order/company of other editors is irrelevant — the Outliner alone is the
    # signature the fix keys on.
    assert decide(["VIEW_3D", "OUTLINER"]) is True


@pytest.mark.unit
def test_decision_is_order_independent():
    assert decide(DEFAULT_LAYOUT) == decide(list(reversed(DEFAULT_LAYOUT)))
