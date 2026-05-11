
import sys, json, bpy
out_path = sys.argv[sys.argv.index('--') + 1]
import bl_ext.vscode_development.proteinblender.utils.scene_manager as sm_mod
sm_mod.sync_molecule_list_after_undo()
mgr = sm_mod.ProteinBlenderScene.get_instance()
scene = bpy.context.scene
snap = {
    "blend": bpy.data.filepath,
    "manager_ids": sorted(mgr.molecules.keys()),
    "list_items": [
        {
            "id": it.identifier,
            "object_name": it.object_name,
            "style": getattr(it, "style", None),
            "n_domains": len(it.domains),
            "n_poses": len(it.poses),
            "n_keyframes": len(it.keyframes),
        }
        for it in scene.molecule_list_items
    ],
    "outliner_count": len(scene.outliner_items),
    "outliner_types": {},
    "linker_count": len(scene.pb2_linkers) if hasattr(scene, 'pb2_linkers') else 0,
    "linker_uids": [l.uid for l in scene.pb2_linkers] if hasattr(scene, 'pb2_linkers') else [],
    "nucleic_objs": sorted(o.name for o in bpy.data.objects if o.get("pb_is_nucleic_acid")),
    "puppet_count": sum(1 for it in scene.outliner_items if it.item_type == "PUPPET"),
}
for it in scene.outliner_items:
    snap["outliner_types"][it.item_type] = snap["outliner_types"].get(it.item_type, 0) + 1
open(out_path, "w").write(json.dumps(snap, indent=2, default=str))
