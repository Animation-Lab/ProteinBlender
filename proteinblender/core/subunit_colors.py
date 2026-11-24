"""Coloring a filament's subunits one by one, and animating those colors.

A filament draws every subunit as an instance of one styled geometry, so all
of them share its color. A subunit colored on its own is picked out in the
assembly's node tree instead (``assembly._tint_stage``): each copy's point
carries a tint, and the copies with one are realized and painted. A filament
of hundreds with three subunits picked out realizes three.

**Where a color lives.** On the filament's molecule object, in
``Object.pb_filament.colors``, one entry per colored monomer, named
``"<site>:<chain>"`` - its place in the whole lattice
(``symmetry_builder.kept_sites``) and its chain letter - so the color stays
with that subunit as the filament grows, shrinks from either end or bends.
Blender keys an entry by its position (``pb_filament.colors[3].color``), not
its name, so entries are only ever appended, and removing one renumbers the
keys of those after it (:func:`clear`).

**What is drawn** is written into the point clouds as the ``pb_tint``
attribute (``assembly.write_tints``), whenever a color changes, whenever the
copies are re-placed, and on every frame for colors that are keyframed. A
transient overlay sits on top to highlight a subunit without touching anyone's
colors: the one whose row the mouse is over in the Subunits list.

**Hiding** a monomer lists it in ``Object.pb_filament.hidden``, by the same
name, and marks its copy's point ``pb_hidden`` (``assembly.write_hidden``),
which the node tree drops before anything is realized
(``assembly._hide_stage``). Its point stays, so it comes back where it was.

**A style of its own** - spheres in a surface filament, say - lists a
monomer in ``Object.pb_filament.styles``, by the same name, with the style.
Its copy's point carries the style's number as ``pb_style``
(``assembly.write_styles``), and the assembly's node tree draws the chain's
atoms in each style its subunits use and puts each copy in its own
(``assembly.sync_style_stage``). A monomer drawn as its chain is has no entry.

**The roster** (``Object.pb_filament.subunits``) is every monomer of the
filament as a row the Subunits list can show and select: disposable, rebuilt
when the lattice changes, and never keyed.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Iterable, List, Optional, Tuple

import bpy
import numpy as np
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from bpy.types import PropertyGroup

logger = logging.getLogger(__name__)

#: Where the colors live on the molecule object, under ``Object.pb_filament``.
COLORS_PATH = "pb_filament.colors"

#: The action group color keys are filed under in the Graph Editor.
GROUP = "Subunit Colors"

#: What the subunit under the mouse in the Cytoskeleton Subunits list is lit.
HOVER_TINT = (1.0, 0.85, 0.1, 1.0)


def key(site: int, chain: str) -> str:
    """The name a monomer's color and roster row go by: ``"<site>:<chain>"``."""
    return f"{int(site)}:{chain}"


def parse_key(name: str) -> Tuple[int, str]:
    site, _sep, chain = name.partition(":")
    return int(site), chain


#: Set while many entries change at once, so each is not drawn on its own.
_QUIET = False


def _changed(self, context):
    """A color was edited: draw it."""
    if _QUIET:
        return
    molecule = molecule_of_object(self.id_data)
    if molecule is not None:
        refresh(molecule)


class PBSubunitColor(PropertyGroup):
    """One monomer's own color. Named by :func:`key`."""

    site: IntProperty(name="Site", min=0)
    chain: StringProperty(name="Chain")
    color: FloatVectorProperty(
        name="Color", description="This subunit's own color",
        size=3, subtype="COLOR", min=0.0, max=1.0, default=(0.9, 0.2, 0.2),
        update=_changed)
    strength: FloatProperty(
        name="Strength",
        description=("How far this subunit is painted its own color: 0 is "
                     "the filament's color, 1 entirely its own. Key it to fade"),
        min=0.0, max=1.0, default=1.0, subtype="FACTOR", update=_changed)


class PBSubunitHidden(PropertyGroup):
    """One monomer taken out of the drawing. Named by :func:`key`."""

    site: IntProperty(name="Site", min=0)
    chain: StringProperty(name="Chain")


class PBSubunitStyle(PropertyGroup):
    """One monomer drawn in a style other than its chain's. Named by :func:`key`."""

    site: IntProperty(name="Site", min=0)
    chain: StringProperty(name="Chain")
    #: A style's identifier, as ``visual_style.REAL_STYLE_ITEMS`` lists them.
    style: StringProperty(name="Style")


def _row_molecule(row):
    return molecule_of_object(row.id_data)


def _get_row_hidden(self):
    params = getattr(self.id_data, "pb_filament", None)
    return params is not None and self.name in params.hidden


def _set_row_hidden(self, value):
    molecule = _row_molecule(self)
    if molecule is not None:
        set_hidden(molecule, [self.name], bool(value))


def _get_row_color(self):
    molecule = _row_molecule(self)
    if molecule is None:
        return (0.8, 0.8, 0.8)
    return shown(molecule, self.name)[0]


def _set_row_color(self, value):
    molecule = _row_molecule(self)
    if molecule is not None:
        recolor(molecule, [self.name], tuple(value)[:3])


class PBSubunitRow(PropertyGroup):
    """One monomer as a row of the Subunits list. Named by :func:`key`.

    ``hide`` and ``color`` are views onto ``pb_filament.hidden`` and
    ``pb_filament.colors``, which outlive the roster: changing one writes
    there, so it stays with the subunit when the list is rebuilt. Neither is
    keyed here - a row's place in the list is not its subunit's - so a color
    is keyed on its ``pb_filament.colors`` entry by Create Keyframe.
    """

    site: IntProperty()
    chain: StringProperty()
    label: StringProperty()
    select: BoolProperty(
        name="Select",
        description=("Select this subunit. Point at the row to see where the "
                     "subunit is: it lights up yellow in the 3D Viewport"))
    hide: BoolProperty(
        name="Hide", description="Hide this subunit in the viewport and renders",
        get=_get_row_hidden, set=_set_row_hidden, options=set())
    color: FloatVectorProperty(
        name="Color",
        description=("This subunit's color. Changing it paints this subunit "
                     "alone; key it with the filament's row in Create Keyframe"),
        size=3, subtype="COLOR", min=0.0, max=1.0,
        get=_get_row_color, set=_set_row_color, options=set())


CLASSES = (PBSubunitColor, PBSubunitHidden, PBSubunitStyle, PBSubunitRow)


# ---------------------------------------------------------------------------
# Finding things
# ---------------------------------------------------------------------------

def owner(molecule):
    try:
        return molecule.object
    except (AttributeError, ReferenceError):
        return None


def molecule_of_object(obj):
    """The live molecule whose object is ``obj``, if any."""
    if obj is None:
        return None
    from ..utils.scene_manager import ProteinBlenderScene
    for molecule in ProteinBlenderScene.get_instance().molecules.values():
        try:
            if molecule.object == obj:
                return molecule
        except ReferenceError:
            continue
    return None


def _params(molecule):
    obj = owner(molecule)
    return getattr(obj, "pb_filament", None) if obj is not None else None


def chain_of(molecule, obj) -> Optional[str]:
    """The chain letter an object draws, if it draws one chain."""
    for domain in molecule.domains.values():
        if domain.object is not None and domain.object == obj:
            return str(domain.chain_id)
    return None


def chain_labels(molecule) -> Dict[str, str]:
    """``{chain letter: what the chain is called}``, as the PB Outliner calls it."""
    import json

    letters = sorted({str(d.chain_id) for d in molecule.domains.values()
                      if not getattr(d, "is_copy", False)})
    names = {letter: f"Chain {letter}" for letter in letters}
    index_of = {letter: index for index, letter
                in (getattr(molecule, "auth_chain_id_map", None) or {}).items()}
    item = next((it for it in bpy.context.scene.molecule_list_items
                 if it.identifier == molecule.identifier), None)
    custom = {}
    if item is not None and item.chain_custom_names:
        try:
            custom = json.loads(item.chain_custom_names)
        except ValueError:
            custom = {}
    for letter in letters:
        name = custom.get(str(index_of.get(letter)))
        if name:
            names[letter] = name
    return names


# ---------------------------------------------------------------------------
# What is drawn
# ---------------------------------------------------------------------------

#: Highlights laid over the colors, per molecule object:
#: ``{object session uid: {key: rgba}}``. Never saved; never keyed.
#: Keyed by the object's session uid, not its name: a filament deleted while
#: lit must not light the next one built under the same name.
_OVERLAY: Dict[int, Dict[str, Tuple[float, float, float, float]]] = {}


def set_overlay(molecule, tints: Dict[str, Tuple[float, float, float, float]]) -> None:
    """Lay ``{key: rgba}`` over the filament's colors until cleared, and draw it."""
    obj = owner(molecule)
    if obj is None:
        return
    if tints:
        _OVERLAY[obj.session_uid] = dict(tints)
    else:
        _OVERLAY.pop(obj.session_uid, None)
    refresh(molecule)


def overlay(molecule) -> Dict[str, Tuple[float, float, float, float]]:
    """The highlights drawn over the filament."""
    obj = owner(molecule)
    return dict(_OVERLAY.get(obj.session_uid, {})) if obj is not None else {}


def clear_overlays() -> None:
    """Forget every highlight; a new file has none."""
    _OVERLAY.clear()
    _SET_ASIDE.clear()


#: Highlights taken off while a file is written, to put back afterwards.
_SET_ASIDE: Dict[int, Dict[str, Tuple[float, float, float, float]]] = {}


def _molecules_drawn_by(uids):
    from ..utils.scene_manager import ProteinBlenderScene
    found = []
    for molecule in ProteinBlenderScene.get_instance().molecules.values():
        obj = owner(molecule)
        try:
            if obj is not None and obj.session_uid in uids:
                found.append(molecule)
        except ReferenceError:
            continue
    return found


@persistent
def overlays_off_for_save(*_args) -> None:
    """A highlight is never saved: write the colors without it first.

    The tints live in the point clouds, so a file saved with the mouse over
    a row would otherwise keep that subunit yellow.
    """
    if not _OVERLAY:
        return
    _SET_ASIDE.clear()
    _SET_ASIDE.update(_OVERLAY)
    _OVERLAY.clear()
    for molecule in _molecules_drawn_by(set(_SET_ASIDE)):
        refresh(molecule)


@persistent
def overlays_on_after_save(*_args) -> None:
    if not _SET_ASIDE:
        return
    _OVERLAY.update(_SET_ASIDE)
    _SET_ASIDE.clear()
    for molecule in _molecules_drawn_by(set(_OVERLAY)):
        refresh(molecule)


@persistent
def overlays_off_for_load(*_args) -> None:
    clear_overlays()


#: ``(handler list name, handler)`` that keep highlights out of files.
HANDLERS = (("save_pre", overlays_off_for_save),
            ("save_post", overlays_on_after_save),
            ("load_pre", overlays_off_for_load))


def _color_curves(obj) -> dict:
    """``{(data path, index): fcurve}`` for the colors keyed on ``obj``."""
    animation = obj.animation_data if obj is not None else None
    if animation is None or animation.action is None:
        return {}
    from ..utils.animation import get_fcurves_from_action

    return {(fc.data_path, fc.array_index): fc
            for fc in get_fcurves_from_action(animation.action, animation)
            if fc.data_path.startswith(COLORS_PATH) and len(fc.keyframe_points)}


def _path(index: int, prop: str) -> str:
    return f"{COLORS_PATH}[{int(index)}].{prop}"


_KEYED = re.compile(r"^pb_filament\.colors\[(\d+)\]\.(\w+)$")


def _keyed_entry(path: str):
    """``(index, property)`` of a color key's data path, or None."""
    match = _KEYED.match(path)
    return (int(match.group(1)), match.group(2)) if match else None


def color_values(molecule, frame=None) -> Dict[str, Tuple[float, float, float, float]]:
    """``{key: (r, g, b, strength)}`` for every colored monomer.

    At ``frame``, read off the keys where they are keyed: an animation render
    evaluates into a depsgraph of its own and leaves the properties wherever
    the viewport last put them.
    """
    params = _params(molecule)
    if params is None or not len(params.colors):
        return {}
    curves = _color_curves(owner(molecule)) if frame is not None else {}

    def value(path, index, fallback):
        curve = curves.get((path, index))
        return float(curve.evaluate(frame)) if curve is not None else fallback

    values = {}
    for index, item in enumerate(params.colors):
        rgb = tuple(value(_path(index, "color"), i, item.color[i]) for i in range(3))
        strength = value(_path(index, "strength"), 0, item.strength)
        values[item.name] = (*rgb, min(max(strength, 0.0), 1.0))
    return values


def tints_for(molecule, obj, sites, frame=None, values=None):
    """The ``(n, 4)`` tints for the copies ``sites`` of ``obj``, or None for none."""
    chain = chain_of(molecule, obj)
    if chain is None:
        return None
    if values is None:
        values = color_values(molecule, frame)
    on_top = overlay(molecule)
    if not values and not on_top:
        return None
    tints = np.zeros((len(sites), 4), dtype=np.float32)
    painted = False
    for row, site in enumerate(sites):
        name = key(site, chain)
        tint = on_top.get(name) or values.get(name)
        if tint is not None and tint[3] > 0.0:
            tints[row] = tint
            painted = True
    return tints if painted else None


def hidden_keys(molecule) -> set:
    """The keys of the monomers taken out of the drawing."""
    params = _params(molecule)
    return set(params.hidden.keys()) if params is not None else set()


def hidden_for(molecule, obj, sites, hidden=None):
    """Which of the copies ``sites`` of ``obj`` are hidden, as a bool array, or None."""
    chain = chain_of(molecule, obj)
    if chain is None:
        return None
    if hidden is None:
        hidden = hidden_keys(molecule)
    if not hidden:
        return None
    flags = np.fromiter((key(site, chain) in hidden for site in sites),
                        dtype=bool, count=len(sites))
    return flags if flags.any() else None


def set_hidden(molecule, keys: Iterable[str], hidden: bool) -> int:
    """Hide or show these monomers. Returns how many changed."""
    params = _params(molecule)
    if params is None:
        return 0
    changed = 0
    for name in keys:
        index = params.hidden.find(name)
        if hidden and index < 0:
            item = params.hidden.add()
            item.name = name
            item.site, item.chain = parse_key(name)
            changed += 1
        elif not hidden and index >= 0:
            params.hidden.remove(index)
            changed += 1
    if changed:
        refresh(molecule)
    return changed


def refresh(molecule, frame=None) -> bool:
    """Write the filament's colors, and which subunits are hidden, into the
    copies it draws. Returns True if any copy is painted."""
    from . import assembly

    clouds = assembly.point_clouds_of(molecule)
    if not clouds:
        return False
    values = color_values(molecule, frame)
    hidden = hidden_keys(molecule)
    styles = style_overrides(molecule)
    if values or hidden or styles or overlay(molecule):
        ensure_paintable(molecule)
    # Before the points name a style, so no copy names one with nothing to draw it.
    assembly.sync_style_stage(molecule)
    painted = False
    for obj, points in clouds:
        mesh = points.data
        sites = assembly.point_sites(mesh)
        tints = tints_for(molecule, obj, sites, values=values)
        flags = hidden_for(molecule, obj, sites, hidden)
        numbers = styles_for(molecule, obj, sites, styles)
        if (tints is None and flags is None and numbers is None
                and mesh.attributes.get(assembly.TINT_ATTRIBUTE) is None
                and mesh.attributes.get(assembly.HIDDEN_ATTRIBUTE) is None
                and mesh.attributes.get(assembly.STYLE_ATTRIBUTE) is None):
            continue
        assembly.write_tints(mesh, tints)
        assembly.write_hidden(mesh, flags)
        assembly.write_styles(mesh, numbers)
        mesh.update()
        painted = painted or tints is not None
    return painted


def style_overrides(molecule) -> Dict[str, str]:
    """``{key: style}`` for the monomers drawn in a style of their own."""
    params = _params(molecule)
    return {item.name: item.style for item in params.styles} if params is not None else {}


def own_style(molecule, chain: str) -> Optional[str]:
    """The style the filament draws a chain in: its chain object's."""
    from .visual_style import get_object_style
    for domain in molecule.domains.values():
        if (str(domain.chain_id) == chain and domain.object is not None
                and not getattr(domain, "is_copy", False)):
            return get_object_style(domain.object)
    return None


def style_of(molecule, name: str) -> Optional[str]:
    """The style a monomer is drawn in: its own, else its chain's."""
    return style_overrides(molecule).get(name) or own_style(molecule, parse_key(name)[1])


def styles_for(molecule, obj, sites, overrides=None):
    """Which style each of the copies ``sites`` of ``obj`` is drawn in, as an
    int array of style numbers with 0 for the chain's own, or None for none."""
    chain = chain_of(molecule, obj)
    if chain is None:
        return None
    if overrides is None:
        overrides = style_overrides(molecule)
    if not overrides:
        return None
    from .visual_style import style_number
    numbers = np.fromiter(
        (style_number(overrides[key(site, chain)]) if key(site, chain) in overrides else 0
         for site in sites), dtype=np.int32, count=len(sites))
    return numbers if numbers.any() else None


def set_style(molecule, keys: Iterable[str], style: str) -> int:
    """Draw these monomers in ``style``. Returns how many changed.

    A monomer given its chain's own style keeps nothing of its own, so it
    goes on following the filament when the filament is restyled.
    """
    params = _params(molecule)
    if params is None:
        return 0
    changed = 0
    for name in keys:
        site, chain = parse_key(name)
        index = params.styles.find(name)
        if style == own_style(molecule, chain):
            if index >= 0:
                params.styles.remove(index)
                changed += 1
        elif index < 0:
            item = params.styles.add()
            item.name = name
            item.site, item.chain, item.style = site, chain, style
            changed += 1
        elif params.styles[index].style != style:
            params.styles[index].style = style
            changed += 1
    if changed:
        refresh(molecule)
    return changed


def ensure_paintable(molecule) -> None:
    """Give a build made before subunits could be colored or hidden the means."""
    from . import assembly
    assembly.ensure_tint_stage(molecule)
    assembly.ensure_hide_stage(molecule)


# ---------------------------------------------------------------------------
# Changing colors
# ---------------------------------------------------------------------------

def _set_entries(molecule, keys: Iterable[str], color=None, strength=None,
                 add: bool = True) -> int:
    """Write the color and/or strength of these monomers, then draw them once.

    A monomer with no entry yet gets one (painted at full strength) when
    ``add``; otherwise it is left as it is. Returns how many were written.
    """
    global _QUIET
    params = _params(molecule)
    if params is None:
        return 0
    done = 0
    _QUIET = True
    try:
        for name in keys:
            item = params.colors.get(name)
            if item is None:
                if not add:
                    continue
                site, chain = parse_key(name)
                item = params.colors.add()
                item.name = name
                item.site, item.chain = site, chain
                item.color = own_color(molecule, chain)
                item.strength = 1.0
            if color is not None:
                item.color = tuple(color)[:3]
            if strength is not None:
                item.strength = strength
            done += 1
    finally:
        _QUIET = False
    refresh(molecule)
    return done


def paint(molecule, keys: Iterable[str], color, strength: float = 1.0) -> int:
    """Color these monomers. Returns how many."""
    return _set_entries(molecule, keys, color=color, strength=strength)


def recolor(molecule, keys: Iterable[str], color) -> int:
    """Give these monomers this color, each keeping its strength."""
    return _set_entries(molecule, keys, color=color)


def own_color(molecule, chain: str) -> Tuple[float, float, float]:
    """The color a chain is drawn in when none of its monomers is painted."""
    for domain in molecule.domains.values():
        if str(domain.chain_id) == chain and not getattr(domain, "is_copy", False):
            return tuple(domain.color)[:3]
    return (0.8, 0.8, 0.8)


def shown(molecule, name: str) -> Tuple[Tuple[float, float, float], float]:
    """``(color, strength)`` a monomer's row shows: its paint, else its chain's color."""
    params = _params(molecule)
    item = params.colors.get(name) if params is not None else None
    if item is not None:
        return tuple(item.color), float(item.strength)
    return own_color(molecule, parse_key(name)[1]), 1.0


def clear(molecule, keys: Iterable[str]) -> int:
    """Give these monomers back the filament's color, keys and all."""
    params = _params(molecule)
    obj = owner(molecule)
    if params is None:
        return 0
    wanted = set(keys)
    gone = [index for index, item in enumerate(params.colors) if item.name in wanted]
    for index in reversed(gone):
        params.colors.remove(index)
    _renumber_keys(obj, gone)
    refresh(molecule)
    return len(gone)


def forget(molecule) -> None:
    """Drop every subunit color, its keys, every hidden subunit and every
    subunit's own style.

    For a filament whose copies were realized: each realized protein now
    carries its own color, visibility and style, and the subunit list they were
    read from must not reach an assembly built later, whose copies would
    otherwise come up painted or missing with no Subunits list to undo it.
    """
    params = _params(molecule)
    if params is None:
        return
    _renumber_keys(owner(molecule), list(range(len(params.colors))))
    params.colors.clear()
    params.hidden.clear()
    params.styles.clear()
    params.subunits.clear()


def _renumber_keys(obj, gone) -> None:
    """Drop the keys of removed entries and move the rest down with their entry."""
    animation = obj.animation_data if obj is not None else None
    if not gone or animation is None or animation.action is None:
        return
    from ..utils.animation import get_fcurves_from_action, remove_fcurve_from_action

    gone = sorted(gone)
    for curve in list(get_fcurves_from_action(animation.action, animation)):
        entry = _keyed_entry(curve.data_path)
        if entry is None:
            continue
        index, prop = entry
        if index in gone:
            remove_fcurve_from_action(animation.action, curve, animation)
            continue
        shift = sum(1 for removed in gone if removed < index)
        if shift:
            curve.data_path = _path(index - shift, prop)


# ---------------------------------------------------------------------------
# Keyframes
# ---------------------------------------------------------------------------

def keyframe(molecule, frame: int) -> int:
    """Key every colored monomer's color and strength. Returns how many keyed.

    Strength has had no control since 2026-11-03, but it is still keyed with
    the color, so a fade made before then keeps its shape.
    """
    params, obj = _params(molecule), owner(molecule)
    if params is None or obj is None:
        return 0
    keyed = 0
    for index in range(len(params.colors)):
        for prop in ("color", "strength"):
            if obj.keyframe_insert(data_path=_path(index, prop), frame=frame,
                                   group=GROUP):
                keyed += 1
    return keyed


def delete_keyframes(obj, frame: int) -> None:
    params = getattr(obj, "pb_filament", None) if obj is not None else None
    if params is None:
        return
    for index in range(len(params.colors)):
        for prop in ("color", "strength"):
            try:
                obj.keyframe_delete(data_path=_path(index, prop), frame=frame)
            except (RuntimeError, TypeError):
                pass  # not keyed at that frame


def is_animated(molecule) -> bool:
    return bool(_color_curves(owner(molecule)))


def follow(molecule, frame) -> bool:
    """Bring keyed colors to ``frame``. Does nothing when none are keyed."""
    if not is_animated(molecule):
        return False
    return refresh(molecule, frame)


# ---------------------------------------------------------------------------
# The roster
# ---------------------------------------------------------------------------

def _lattice(molecule):
    from . import assembly, symmetry_builder

    built = assembly.built_build_params(molecule) or {}
    count = min(int(built.get("count", 0) or 0), symmetry_builder.MAX_COUNT)
    strands = symmetry_builder.lattice_settings(built)["strands"]
    return count, strands, symmetry_builder.shrink_settings(built)


def present_sites(molecule) -> set:
    """The lattice sites the filament draws now, its shrunk ends left out."""
    from . import symmetry_builder

    count, strands, shrink = _lattice(molecule)
    if count <= 0:
        return set()
    return set(symmetry_builder.kept_sites(count, strands, **shrink))


def _roster_signature(molecule, count, strands, labels) -> str:
    return f"{count}|{strands}|" + "|".join(f"{c}={n}" for c, n in sorted(labels.items()))


def roster_stale(molecule) -> bool:
    params = _params(molecule)
    if params is None:
        return False
    count, strands, _shrink = _lattice(molecule)
    return params.roster_signature != _roster_signature(
        molecule, count, strands, chain_labels(molecule))


def sync_roster(molecule) -> bool:
    """Make the Subunits list one row per monomer of the filament as built.

    Ordered strand by strand and up each strand from the minus end, which is
    how a person counts them. Selection is kept for rows that are still there.
    Returns True if the rows changed.
    """
    params = _params(molecule)
    if params is None:
        return False
    count, strands, _shrink = _lattice(molecule)
    labels = chain_labels(molecule)
    signature = _roster_signature(molecule, count, strands, labels)
    if params.roster_signature == signature:
        return False

    selected = {row.name for row in params.subunits if row.select}
    params.subunits.clear()
    for strand in range(strands):
        for step in range(count):
            site = step * strands + strand
            for chain, name in labels.items():
                row = params.subunits.add()
                row.name = key(site, chain)
                row.site, row.chain = site, chain
                row.label = (f"{name} {step + 1}" if strands == 1
                             else f"{name} {step + 1} - Strand {strand + 1}")
                row.select = row.name in selected
    params.roster_signature = signature
    return True


def selected_keys(molecule) -> List[str]:
    """The selected rows that the filament still draws."""
    params = _params(molecule)
    if params is None:
        return []
    present = present_sites(molecule)
    return [row.name for row in params.subunits
            if row.select and row.site in present]
