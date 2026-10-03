"""Opening local structure files: every route a user can take to one.

A user reported (GitHub #19) that downloading a PDB works but local .pdb and
.mmCIF files "cannot be opened". The Import Local File button itself is
covered everywhere else (``H.import_local``), so this module pins the rest of
the surface that made local files look unopenable:

* dropping a file onto Blender and File > Import did nothing, because the
  only drop handler lived in MolecularNodes' own import classes, which
  ProteinBlender does not register;
* importing the same file twice silently replaced the first protein's wrapper,
  leaving two list rows with one identifier and an orphaned object.
"""

import gzip
import shutil

import bpy
import pytest

import helpers as H


def _copy(tmp_path, fixture, name=None):
    """Copy a bundled fixture, decompressing it when ``name`` is not a .gz."""
    name = name or fixture
    target = tmp_path / name
    if fixture.endswith(".gz") and not name.endswith(".gz"):
        with gzip.open(H.data_path(fixture)) as source:
            target.write_bytes(source.read())
    else:
        shutil.copy(H.data_path(fixture), target)
    return target


def _import(path, **kwargs):
    return bpy.ops.molecule.import_local("EXEC_DEFAULT", filepath=str(path), **kwargs)


def _drop(directory, *names):
    """Drop files exactly as Blender's window manager hands them to a handler."""
    window = bpy.context.window_manager.windows[0]
    area = next((a for a in window.screen.areas if a.type == "VIEW_3D"), window.screen.areas[0])
    region = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=window, area=area, region=region):
        return bpy.ops.wm.drop_import_file(
            "EXEC_DEFAULT", directory=str(directory), files=[{"name": n} for n in names])


def _row_objects(scene):
    return {row.identifier: row.object_ptr.name for row in scene.molecule_list_items}


# --------------------------------------------------------------------------
# Importing the same file more than once
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_importing_the_same_file_twice_loads_two_independent_proteins(tmp_path, scene, sm):
    path = _copy(tmp_path, "1ubq.pdb")
    assert _import(path) == {"FINISHED"}
    assert _import(path) == {"FINISHED"}

    ids = list(sm.molecules)
    assert len(ids) == 2 and len(set(ids)) == 2, f"expected two proteins, manager holds {ids}"
    rows = _row_objects(scene)
    assert sorted(rows) == sorted(ids), "list rows must be the manager's identifiers, once each"
    for identifier in ids:
        assert rows[identifier] == sm.molecules[identifier].object.name, (
            f"row {identifier!r} points at another protein's object")
    assert len(set(rows.values())) == 2, "both rows resolve to the same Blender object"


@pytest.mark.integration
def test_deleting_one_copy_of_a_twice_imported_file_leaves_the_other(tmp_path, scene, sm):
    path = _copy(tmp_path, "1ubq.pdb")
    _import(path)
    _import(path)
    first, second = list(sm.molecules)
    second_object = sm.molecules[second].object.name

    assert bpy.ops.molecule.delete(molecule_id=first) == {"FINISHED"}

    assert list(sm.molecules) == [second]
    assert [row.identifier for row in scene.molecule_list_items] == [second]
    assert second_object in bpy.data.objects, "deleting one protein removed the other's object"


@pytest.mark.integration
def test_an_explicit_identifier_never_replaces_a_loaded_protein(tmp_path, scene, sm):
    path = _copy(tmp_path, "1ubq.pdb")
    assert _import(path, identifier_override="held") == {"FINISHED"}
    original = sm.molecules["held"].object.name

    with pytest.raises(RuntimeError, match="already"):
        _import(path, identifier_override="held")

    assert list(sm.molecules) == ["held"]
    assert sm.molecules["held"].object.name == original
    assert [row.identifier for row in scene.molecule_list_items] == ["held"]


# --------------------------------------------------------------------------
# Several files at once (multi-select in the browser, or a multi-file drop)
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_several_files_import_in_one_call(tmp_path, scene, sm):
    _copy(tmp_path, "1ubq.pdb")
    _copy(tmp_path, "4ins.cif")
    result = bpy.ops.molecule.import_local(
        "EXEC_DEFAULT", directory=str(tmp_path),
        files=[{"name": "1ubq.pdb"}, {"name": "4ins.cif"}])
    assert result == {"FINISHED"}
    assert sorted(sm.molecules) == ["1ubq", "4ins"]
    assert sorted(_row_objects(scene)) == ["1ubq", "4ins"]


@pytest.mark.integration
def test_a_bad_file_among_several_does_not_stop_the_good_ones(tmp_path, scene, sm):
    _copy(tmp_path, "1ubq.pdb")
    (tmp_path / "notes.pdb").write_text("this is not a structure\n")
    with pytest.raises(RuntimeError, match="notes"):
        bpy.ops.molecule.import_local(
            "EXEC_DEFAULT", directory=str(tmp_path),
            files=[{"name": "notes.pdb"}, {"name": "1ubq.pdb"}])
    assert list(sm.molecules) == ["1ubq"], "the readable file must still import"


# --------------------------------------------------------------------------
# Drag and drop
# --------------------------------------------------------------------------

DROPPED = [
    ("1ubq.pdb", "1ubq.pdb"),
    ("4ins.cif", "4ins.cif"),
    ("4ins.cif", "4ins.mmcif"),
    ("1ubq.pdb", "1UBQ.PDB"),
    ("1ubq.pdb", "1ubq.ent"),
    ("1d3z.pdb.gz", "1d3z.pdb"),      # NMR ensemble
    ("1d3z.cif.gz", "1d3z.cif"),
    ("1out.pdb1.gz", "1out.pdb1"),    # RCSB biological-assembly file
]


@pytest.mark.integration
@pytest.mark.parametrize("fixture,name", DROPPED)
def test_dropping_a_structure_file_imports_it(tmp_path, scene, sm, fixture, name):
    _copy(tmp_path, fixture, name)
    result = _drop(tmp_path, name)
    assert result == {"FINISHED"}, f"drop of {name} returned {result}"
    assert len(sm.molecules) == 1, f"dropping {name} imported {list(sm.molecules)}"
    stem = name.split(".")[0]
    assert next(iter(sm.molecules)) == stem
    assert [row.identifier for row in scene.molecule_list_items] == [stem]


@pytest.mark.integration
def test_a_dropped_file_loads_every_chain_the_file_contains(tmp_path, scene, sm):
    """The right file is read, whole: chains come from the text, not the add-on."""
    path = _copy(tmp_path, "4hhb.pdb")
    chains = {line[21] for line in path.read_text().splitlines()
              if line.startswith("ATOM")}
    assert chains == {"A", "B", "C", "D"}  # what the fixture really contains

    assert _drop(tmp_path, "4hhb.pdb") == {"FINISHED"}

    molecule = sm.molecules["4hhb"]
    assert len(molecule.domains) == len(chains)
    assert len(H.list_item("4hhb").domains) == len(chains)
    drawn = H.evaluated_atom_positions(
        [molecule.object, *(d.object for d in molecule.domains.values())])
    assert len(drawn) > 4000, "a four-chain hemoglobin draws thousands of atoms"


@pytest.mark.integration
def test_dropping_several_structure_files_imports_all(tmp_path, scene, sm):
    _copy(tmp_path, "1ubq.pdb")
    _copy(tmp_path, "4ins.cif")
    assert _drop(tmp_path, "1ubq.pdb", "4ins.cif") == {"FINISHED"}
    assert sorted(sm.molecules) == ["1ubq", "4ins"]


@pytest.mark.integration
def test_dropping_an_unrelated_file_is_left_alone(tmp_path, scene, sm):
    """The handler claims structure extensions only, not whatever is dropped."""
    (tmp_path / "notes.xyzzy").write_text("not a structure\n")
    assert _drop(tmp_path, "notes.xyzzy") == {"CANCELLED"}
    assert not sm.molecules


@pytest.mark.integration
def test_the_drop_handler_claims_every_extension_the_browser_lists():
    """The file browser filter and the drop handler describe one set of files."""
    handler = getattr(bpy.types, "MOLECULE_FH_import_structure", None)
    assert handler is not None, "no drop handler registered for structure files"
    assert handler.bl_import_operator == "molecule.import_local"
    from proteinblender.operators.operator_import_local import BROWSER_FILTER, DROP_EXTENSIONS
    claimed = {ext.lower() for ext in handler.bl_file_extensions.split(";")}
    assert claimed == set(DROP_EXTENSIONS), "Blender truncated or altered the extension list"
    for pattern in BROWSER_FILTER.split(";"):
        suffix = pattern.removeprefix("*")
        if suffix == ".gz" or "[" in suffix:
            continue  # compressed files and the .pdbN family: see DROP_EXTENSIONS
        assert suffix in claimed, f"{suffix} is browsable but cannot be dropped"
    assert {".pdb", ".cif", ".mmcif", ".ent", ".pdb1"} <= claimed


# --------------------------------------------------------------------------
# File > Import
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_file_import_menu_offers_structure_files():
    drawers = bpy.types.TOPBAR_MT_file_import._dyn_ui_initialize()
    ours = [fn for fn in drawers if getattr(fn, "__module__", "").startswith("proteinblender")]
    assert ours, "File > Import has no ProteinBlender entry"
