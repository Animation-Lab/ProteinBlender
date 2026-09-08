"""Choose the proteins, chains and domains that affect one membrane."""

import json

import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UIList

from . import force_fields
from .membrane_geometry import MAX_PROTEIN_FFS
from ..core.outliner_targets import resolve_target, target_rows


class PB_MembraneForceFieldTarget(PropertyGroup):
    item_id: StringProperty()
    label: StringProperty()
    indent: IntProperty()
    selected: BoolProperty(name="Use Force Field")


class PROTEINBLENDER_UL_membrane_force_fields(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        row = layout.row(align=True)
        for _ in range(item.indent):
            row.separator(factor=1.5)
        row.prop(item, 'selected', text=item.label)


class PROTEINBLENDER_OT_membrane_force_fields(Operator):
    """Choose which items part the lipids of this membrane"""
    bl_idname = "proteinblender.membrane_force_fields"
    bl_label = "Add Force Field"
    bl_options = {'REGISTER', 'UNDO'}

    membrane_name: StringProperty(options={'SKIP_SAVE'})
    targets_json: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    targets: CollectionProperty(type=PB_MembraneForceFieldTarget)
    active_index: IntProperty(default=0, options={'SKIP_SAVE'})
    spacing: FloatProperty(name="Spacing (nm)", default=1.5, min=0.0, max=20.0)

    def invoke(self, context, event):
        root = bpy.data.objects.get(self.membrane_name)
        if root is None or not root.get('pb_is_membrane', False):
            self.report({'ERROR'}, "Membrane no longer exists")
            return {'CANCELLED'}
        selected = set(force_fields.membrane_target_ids(root))
        legacy = {o.name for o in force_fields.membrane_emitters(root, context.scene)}
        self.spacing = float(root.get(force_fields.SPACING_KEY, 1.5))
        self.targets.clear()
        for row in target_rows(context.scene):
            target = self.targets.add()
            target.item_id = row.item_id
            target.label = row.name
            target.name = row.name
            target.indent = row.indent_level
            target.selected = row.item_id in selected
            if force_fields.TARGETS_KEY not in root:
                _, objects = resolve_target(row.item_id)
                target.selected = bool(objects) and all(o.name in legacy for o in objects)
        return context.window_manager.invoke_props_dialog(self, width=450)

    def draw(self, context):
        self.layout.label(text=self.membrane_name, icon='FORCE_FORCE')
        self.layout.prop(self, 'spacing')
        self.layout.template_list(
            'PROTEINBLENDER_UL_membrane_force_fields', '', self, 'targets',
            self, 'active_index', rows=12)
        if not self.targets:
            self.layout.label(text="Import a protein to add force fields", icon='INFO')

    def execute(self, context):
        root = bpy.data.objects.get(self.membrane_name)
        if root is None or not root.get('pb_is_membrane', False):
            self.report({'ERROR'}, "Membrane no longer exists")
            return {'CANCELLED'}
        try:
            ids = (json.loads(self.targets_json) if self.targets_json else
                   [t.item_id for t in self.targets if t.selected])
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                raise ValueError("Expected a list of protein, chain or domain IDs")
            owners = set()
            for item_id in ids:
                molecule, objects = resolve_target(item_id)
                if molecule is None or not objects:
                    raise ValueError(f"Target no longer exists: {item_id}")
                owners.update(o.name for o in objects)
            if len(owners) > MAX_PROTEIN_FFS:
                raise ValueError(f"Choose at most {MAX_PROTEIN_FFS} force field objects")
        except (ValueError, TypeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        root[force_fields.TARGETS_KEY] = json.dumps(list(dict.fromkeys(ids)))
        root[force_fields.SPACING_KEY] = self.spacing
        force_fields.apply_to_all_membranes(context.scene)
        return {'FINISHED'}


CLASSES = [PB_MembraneForceFieldTarget, PROTEINBLENDER_UL_membrane_force_fields,
           PROTEINBLENDER_OT_membrane_force_fields]
