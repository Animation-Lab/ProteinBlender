"""Shared, JSON-serializable scene snapshot for save/load round-trip tests.

Imported both by the in-process test (to capture the EXPECTED state before
saving) and by the subprocess verifier (to capture the ACTUAL state after
reopening the .blend in a fresh Blender). Keep it dependency-light and stable.
"""

from __future__ import annotations


def scene_snapshot():
    import bpy
    from proteinblender.utils.scene_manager import ProteinBlenderScene

    sm = ProteinBlenderScene.get_instance()
    scene = bpy.context.scene

    def _domain(d):
        return {
            "name": getattr(d, "name", ""),
            "chain_id": getattr(d, "chain_id", ""),
            "start": getattr(d, "start", -1),
            "end": getattr(d, "end", -1),
            "object_exists": (
                bpy.data.objects.get(d.object_name) is not None
                if getattr(d, "object_name", "") else False),
        }

    mols = {}
    for it in scene.molecule_list_items:
        mols[it.identifier] = {
            "style": it.style,
            "object_name": it.object_name,
            "object_exists": bpy.data.objects.get(it.object_name) is not None
            if it.object_name else False,
            "domain_count": len(it.domains),
            "domains": sorted((_domain(d) for d in it.domains),
                              key=lambda x: (x["chain_id"], x["start"], x["name"])),
            "pose_count": len(it.poses),
            "poses": sorted(p.name for p in it.poses),
            "keyframe_count": len(it.keyframes),
            "keyframes": sorted([k.name, int(k.frame)] for k in it.keyframes),
        }

    return {
        "molecule_ids": sorted(it.identifier for it in scene.molecule_list_items),
        "molecules": mols,
        "outliner_count": len(getattr(scene, "outliner_items", [])),
        "linker_count": len(getattr(scene, "pb2_linkers", [])),
        "wrapper_ids": sorted(sm.molecules.keys()),
    }
