"""Registration + poll smoke test for every ProteinBlender UI panel.

Headless ``--background --factory-startup`` has no window/screen/area, so a
panel's ``draw()`` cannot be invoked — but ``poll()`` can, and registration can
be verified from ``bpy.types``. This module is the cheap regression net that
catches (a) a panel/UIList dropped from a module's registration list and (b) a
``poll`` classmethod that crashes on an empty scene.

The seven registered Panel classes and two UIList classes are listed by their
registered names (which equal both the Python class name and the ``bl_idname``
for every class here, so ``getattr(bpy.types, name)`` resolves them). Panels are
parametrized so a single missing registration shows up as one clearly-named
failing case rather than sinking the whole test.
"""

import bpy
import pytest


# The 7 registered Panel classes (name == bl_idname for all of these).
PANEL_NAMES = [
    "PROTEIN_PB_PT_import_protein",     # Importer            (panel_import_protein)
    "PROTEINBLENDER_PT_outliner",       # PB Outliner         (protein_outliner_panel)
    "PROTEINBLENDER_PT_puppet_maker",   # Puppet Maker        (group_maker_panel)
    "PROTEINBLENDER_PT_pose_library",   # Pose Library        (pose_library_panel)
    "PROTEINBLENDER_PT_animation",      # Animation           (animation_panel)
    "PB2_PT_linkers",                   # Flexible Linkers    (linkers/linker_panel)
    "PROTEINBLENDER_PT_builders",       # Builders            (dna_builder/dna_panel)
]

# The 2 registered UIList classes.
UILIST_NAMES = [
    "PROTEINBLENDER_UL_outliner",       # outliner rows
    "PROTEINBLENDER_UL_keyframes",      # animation keyframe rows
]


@pytest.mark.integration
@pytest.mark.parametrize("name", PANEL_NAMES)
def test_panel_is_registered(name):
    cls = getattr(bpy.types, name, None)
    assert cls is not None, f"Panel '{name}' is not registered on bpy.types"
    # Every panel must carry the Properties-editor placement the addon relies on.
    assert getattr(cls, "bl_space_type", None) == "PROPERTIES", \
        f"Panel '{name}' has unexpected bl_space_type {getattr(cls, 'bl_space_type', None)!r}"


@pytest.mark.integration
@pytest.mark.parametrize("name", UILIST_NAMES)
def test_uilist_is_registered(name):
    cls = getattr(bpy.types, name, None)
    assert cls is not None, f"UIList '{name}' is not registered on bpy.types"


@pytest.mark.integration
@pytest.mark.parametrize("name", PANEL_NAMES)
def test_panel_poll_does_not_crash(name):
    """If a panel defines its own poll() classmethod, calling it against the
    current (empty) context must return a bool without raising."""
    cls = getattr(bpy.types, name, None)
    assert cls is not None, f"Panel '{name}' is not registered"

    if "poll" not in cls.__dict__:
        pytest.skip(f"{name} defines no poll() of its own")

    try:
        result = cls.poll(bpy.context)
    except Exception as e:  # noqa: BLE001 - we want to name the offending panel
        pytest.fail(f"{name}.poll(context) raised {type(e).__name__}: {e}")

    assert isinstance(result, bool), \
        f"{name}.poll(context) returned non-bool: {result!r}"


@pytest.mark.integration
def test_all_expected_panels_present():
    """Belt-and-braces: the full set resolves, so a registration reshuffle that
    drops one is caught even if the parametrized cases are filtered out."""
    missing = [n for n in (PANEL_NAMES + UILIST_NAMES)
               if getattr(bpy.types, n, None) is None]
    assert not missing, f"missing registered UI classes: {missing}"
