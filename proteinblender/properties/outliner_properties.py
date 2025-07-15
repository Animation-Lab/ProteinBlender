import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty, CollectionProperty, PointerProperty
from ..utils.scene_manager import ProteinBlenderScene

# Global flag to prevent infinite loops during synchronization
_sync_in_progress = False

def update_selection(self, context):
    """Update the selection state of the corresponding Blender object."""
    global _sync_in_progress
    if _sync_in_progress:
        return
        
    try:
        _sync_in_progress = True
        scene_manager = ProteinBlenderScene.get_instance()
        
        if self.type == 'PROTEIN':
            molecule = scene_manager.molecules.get(self.identifier)
            if molecule and molecule.object:
                if molecule.object.select_get() != self.is_selected:
                    molecule.object.select_set(self.is_selected)
                    if self.is_selected:
                        context.view_layer.objects.active = molecule.object
                        
        elif self.type == 'DOMAIN':
            # Find the domain by searching through all molecules
            for mol in scene_manager.molecules.values():
                if hasattr(mol, 'domains') and self.identifier in mol.domains:
                    domain = mol.domains[self.identifier]
                    if domain and domain.object:
                        if domain.object.select_get() != self.is_selected:
                            domain.object.select_set(self.is_selected)
                            if self.is_selected:
                                context.view_layer.objects.active = domain.object
                    break
    finally:
        _sync_in_progress = False

def update_visibility(self, context):
    """Update the visibility state of the corresponding Blender object."""
    global _sync_in_progress
    if _sync_in_progress:
        return
        
    try:
        _sync_in_progress = True
        scene_manager = ProteinBlenderScene.get_instance()
        
        if self.type == 'PROTEIN':
            molecule = scene_manager.molecules.get(self.identifier)
            if molecule and molecule.object:
                if molecule.object.hide_get() == self.is_visible:
                    molecule.object.hide_set(not self.is_visible)
                    
        elif self.type == 'DOMAIN':
            # Find the domain by searching through all molecules
            for mol in scene_manager.molecules.values():
                if hasattr(mol, 'domains') and self.identifier in mol.domains:
                    domain = mol.domains[self.identifier]
                    if domain and domain.object:
                        if domain.object.hide_get() == self.is_visible:
                            domain.object.hide_set(not self.is_visible)
                    break
    finally:
        _sync_in_progress = False

class OutlinerListItem(bpy.types.PropertyGroup):
    """A single item in the Protein Outliner."""
    name: StringProperty(name="Name", description="Display name of the item")
    identifier: StringProperty(name="Identifier", description="Unique identifier for the item")
    type: EnumProperty(
        name="Type",
        items=[
            ('PROTEIN', "Protein", "A top-level protein/molecule"),
            ('CHAIN', "Chain", "A chain within a protein"),
            ('DOMAIN', "Domain", "A sub-region of a chain"),
            ('GROUP', "Group", "A collection of proteins/domains")
        ]
    )
    is_selected: BoolProperty(name="Selected", default=False, update=update_selection)
    is_visible: BoolProperty(name="Visible", default=True, update=update_visibility)
    is_expanded: BoolProperty(name="Expanded", default=True)
    depth: IntProperty(name="Depth", description="Indentation level in the outliner", default=0)

class ProteinOutlinerState(bpy.types.PropertyGroup):
    """State for the Protein Outliner."""
    items: CollectionProperty(type=OutlinerListItem)
    
def register():
    bpy.utils.register_class(OutlinerListItem)
    bpy.utils.register_class(ProteinOutlinerState)
    bpy.types.Scene.protein_outliner_state = PointerProperty(type=ProteinOutlinerState)

def unregister():
    del bpy.types.Scene.protein_outliner_state
    bpy.utils.unregister_class(ProteinOutlinerState)
    bpy.utils.unregister_class(OutlinerListItem) 