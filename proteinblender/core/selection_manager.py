"""Centralized selection management for ProteinBlender"""

import bpy
from typing import Set, List, Optional


# Global flag to prevent recursive updates
_updating_selection = False


class SelectionManager:
    """Manages selection state between outliner and viewport"""
    
    @staticmethod
    def select_item(scene, item_id: str, state: bool, sync_viewport: bool = True) -> None:
        """
        Select or deselect an item and handle cascading effects
        
        Args:
            scene: Blender scene
            item_id: ID of the item to select/deselect
            state: True to select, False to deselect
            sync_viewport: Whether to sync selection to viewport
        """
        global _updating_selection
        
        if _updating_selection:
            return
            
        item = SelectionManager._find_item(scene, item_id)
        if not item:
            return
        
        _updating_selection = True
        try:
            SelectionManager._select_item_internal(scene, item_id, state, sync_viewport)
            
            # Trigger UI redraw to update reference items
            for area in bpy.context.screen.areas:
                if area.type == 'PROPERTIES':
                    area.tag_redraw()
        finally:
            _updating_selection = False
    
    @staticmethod
    def _select_item_internal(scene, item_id: str, state: bool, sync_viewport: bool = True) -> None:
        """Internal selection logic"""
        item = SelectionManager._find_item(scene, item_id)
        if not item:
            return
        
        # Handle selection based on item type
        if item.item_type == 'PROTEIN':
            SelectionManager._select_protein(scene, item, state)
        elif item.item_type == 'CHAIN':
            SelectionManager._select_chain(scene, item, state)
        elif item.item_type == 'DOMAIN':
            SelectionManager._select_domain(scene, item, state)
        elif item.item_type == 'PUPPET':
            SelectionManager._toggle_group_members(scene, item)
            return  # Groups don't have their own selection state
        
        # Update references
        SelectionManager._update_references(scene, item_id, state)
    
    @staticmethod
    def _find_item(scene, item_id: str):
        """Find an item by ID"""
        for item in scene.outliner_items:
            if item.item_id == item_id:
                return item
        return None
    
    @staticmethod
    def _select_protein(scene, protein_item, state: bool) -> None:
        """Select/deselect a protein and all its children"""
        protein_item.is_selected = state
        
        # Sync protein to viewport
        SelectionManager._sync_to_viewport(scene, protein_item.item_id)
        
        # Select all children
        for item in scene.outliner_items:
            if item.parent_id == protein_item.item_id:
                if item.item_type == 'CHAIN':
                    SelectionManager._select_chain(scene, item, state)
                elif item.item_type == 'DOMAIN':
                    item.is_selected = state
                    SelectionManager._sync_to_viewport(scene, item.item_id)
    
    @staticmethod
    def _select_chain(scene, chain_item, state: bool) -> None:
        """Select/deselect a chain and handle domains"""
        # Get all domains for this chain
        domains = [item for item in scene.outliner_items 
                  if item.parent_id == chain_item.item_id and item.item_type == 'DOMAIN']
        
        if domains:
            # If chain has domains, selecting chain selects all domains
            for domain in domains:
                domain.is_selected = state
                SelectionManager._sync_to_viewport(scene, domain.item_id)
            # Chain is selected only if all domains are selected
            chain_item.is_selected = state
        else:
            # Simple selection for chains without domains
            chain_item.is_selected = state
        
        # Sync chain to viewport
        SelectionManager._sync_to_viewport(scene, chain_item.item_id)
    
    @staticmethod
    def _select_domain(scene, domain_item, state: bool) -> None:
        """Select/deselect a domain and update parent chain"""
        domain_item.is_selected = state
        
        # Sync domain to viewport
        SelectionManager._sync_to_viewport(scene, domain_item.item_id)
        
        # Update parent chain state
        if domain_item.parent_id:
            chain = SelectionManager._find_item(scene, domain_item.parent_id)
            if chain and chain.item_type == 'CHAIN':
                # Check if all sibling domains are selected
                domains = [item for item in scene.outliner_items 
                          if item.parent_id == chain.item_id and item.item_type == 'DOMAIN']
                
                all_selected = all(d.is_selected for d in domains)
                chain.is_selected = all_selected
                # Don't sync chain to viewport - it might not have an object
    
    @staticmethod
    def _toggle_group_members(scene, group_item) -> None:
        """Toggle selection of all group members"""
        member_ids = group_item.puppet_memberships.split(',') if group_item.puppet_memberships else []
        if not member_ids:
            return
        
        # Check current state of all members
        all_selected = True
        for member_id in member_ids:
            member = SelectionManager._find_item(scene, member_id)
            if member and not member.is_selected:
                all_selected = False
                break
        
        # Toggle to opposite state
        new_state = not all_selected
        
        # Update each member directly (bypass recursion check)
        for member_id in member_ids:
            member = SelectionManager._find_item(scene, member_id)
            if member:
                # Update the member's selection state
                if member.item_type == 'PROTEIN':
                    SelectionManager._select_protein(scene, member, new_state)
                elif member.item_type == 'CHAIN':
                    SelectionManager._select_chain(scene, member, new_state)
                elif member.item_type == 'DOMAIN':
                    SelectionManager._select_domain(scene, member, new_state)
                
                # Update references
                SelectionManager._update_references(scene, member_id, new_state)
                
                # Sync to viewport
                SelectionManager._sync_to_viewport(scene, member_id)
    
    @staticmethod
    def _update_references(scene, item_id: str, state: bool) -> None:
        """Update all reference items to match original"""
        for ref_item in scene.outliner_items:
            if "_ref_" in ref_item.item_id and ref_item.puppet_memberships == item_id:
                ref_item.is_selected = state
    
    @staticmethod
    def _sync_to_viewport(scene, item_id: str) -> None:
        """Sync outliner selection to Blender viewport"""
        item = SelectionManager._find_item(scene, item_id)
        if not item or not item.object_name:
            return
        
        obj = bpy.data.objects.get(item.object_name)
        if not obj:
            return
        
        # Simply set the selection state
        obj.select_set(item.is_selected)
        
        # Make active if selecting and no active object
        if item.is_selected and not bpy.context.view_layer.objects.active:
            bpy.context.view_layer.objects.active = obj
    
    @staticmethod
    def sync_from_viewport(scene) -> None:
        """Update outliner selection from viewport (used for external selection changes)"""
        global _updating_selection
        
        if _updating_selection:
            return
            
        _updating_selection = True
        try:
            view_layer = bpy.context.view_layer
            selected_objects = {obj.name for obj in bpy.context.selected_objects}
            
            # Update all items based on viewport selection
            for item in scene.outliner_items:
                if item.object_name:
                    item.is_selected = item.object_name in selected_objects
            
            # Update parent states based on children
            SelectionManager._update_parent_states(scene)
            
            # Update references
            for item in scene.outliner_items:
                if not "_ref_" in item.item_id:
                    SelectionManager._update_references(scene, item.item_id, item.is_selected)
        finally:
            _updating_selection = False
    
    @staticmethod
    def _update_parent_states(scene) -> None:
        """Update parent selection states based on children"""
        # Update chains based on domains
        for item in scene.outliner_items:
            if item.item_type == 'CHAIN':
                domains = [d for d in scene.outliner_items 
                          if d.parent_id == item.item_id and d.item_type == 'DOMAIN']
                if domains:
                    item.is_selected = all(d.is_selected for d in domains)
        
        # Update proteins based on chains
        for item in scene.outliner_items:
            if item.item_type == 'PROTEIN':
                children = [c for c in scene.outliner_items if c.parent_id == item.item_id]
                if children:
                    item.is_selected = all(c.is_selected for c in children)
    
    @staticmethod
    def is_group_fully_selected(scene, group_item) -> bool:
        """Check if all members of a group are selected"""
        member_ids = group_item.puppet_memberships.split(',') if group_item.puppet_memberships else []
        if not member_ids:
            return False
        
        for member_id in member_ids:
            member = SelectionManager._find_item(scene, member_id)
            if not member or not member.is_selected:
                return False
        
        return True