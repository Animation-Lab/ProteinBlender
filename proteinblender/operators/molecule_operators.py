import bpy
from bpy.types import Operator
from bpy.props import StringProperty
from mathutils import Vector
from ..utils.scene_manager import (ProteinBlenderScene, build_outliner_hierarchy,
                                   delete_molecule_cascade,
                                   delete_molecule_if_empty,
                                   molecule_would_be_emptied,
                                   prune_emptied_puppets)
from ..utils.chain_utils import chain_match_tokens, copy_group_members
from ..core import domain_space

class MOLECULE_PB_OT_delete(Operator):
    bl_idname = "molecule.delete"
    bl_label = "Delete Molecule"
    bl_description = "Delete this molecule"
    bl_options = {'REGISTER', 'UNDO'}
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        delete_molecule_cascade(context, self.molecule_id)
        return {'FINISHED'}

class MOLECULE_PB_OT_update_identifier(Operator):
    bl_idname = "molecule.update_identifier"
    bl_label = "Update Identifier"
    bl_description = "Update the molecule's identifier"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        old_id = scene.selected_molecule_id
        new_id = scene.edit_molecule_identifier
        
        if old_id == new_id or not new_id:
            return {'CANCELLED'}
            
        # Update molecule identifier
        molecule = scene_manager.molecules[old_id]
        molecule.identifier = new_id
        scene_manager.molecules[new_id] = scene_manager.molecules.pop(old_id)
        
        # Update UI list
        for item in scene.molecule_list_items:
            if item.identifier == old_id:
                item.identifier = new_id
                break
                
        # Update selected molecule id
        scene.selected_molecule_id = new_id
        
        return {'FINISHED'}

class MOLECULE_PB_OT_snap_protein_pivot_center(bpy.types.Operator):
    bl_idname = "molecule.snap_protein_pivot_center"
    bl_label = "Snap Protein Pivot to Center"
    bl_description = "Snap the protein's origin to its bounding box center"

    molecule_id: bpy.props.StringProperty()

    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        if not molecule or not molecule.object:
            self.report({'ERROR'}, "Molecule object not found.")
            return {'CANCELLED'}
        obj = molecule.object
        try:
            # bound_box is the bounds of the object's *raw* mesh, which has not
            # been through the geometry-nodes pivot - a molecule object has no
            # evaluated bounds of its own to borrow, because it evaluates to an
            # empty point cloud and the atoms are drawn by its chain domains.
            # So map the corners with domain_space.local_to_world, not with
            # matrix_world: the latter is off by exactly the pivot, which put
            # this "centre" outside the molecule entirely (CLAUDE.md's first
            # silent-failure rule).
            corners = [domain_space.local_to_world(obj, Vector(c))
                       for c in obj.bound_box]
            center = sum(corners, Vector()) / len(corners)
            if not domain_space.set_pivot_world(obj, center):
                self.report({'ERROR'}, "Failed to snap pivot.")
                return {'CANCELLED'}
            self.report({'INFO'}, "Protein pivot snapped to bounding box center.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to snap pivot: {e}")
        return {'FINISHED'}

class MOLECULE_PB_OT_toggle_protein_pivot_edit(bpy.types.Operator):
    """Move a protein's pivot with a helper object. Click again to apply.

    The scripted entry point to Edit Pivot for a whole protein; the outliner
    row's button is the same session reached from the UI. Both go through
    ``pivot_operators.toggle_pivot_edit``, so enter-and-leave is implemented
    once. This used to carry its own copy of it, keyed on a class-level dict
    holding a live ``helper`` pointer - which a source reload emptied and a
    user deleting the helper turned into a pointer to freed memory.
    """

    bl_idname = "molecule.toggle_protein_pivot_edit"
    bl_label = "Move/Set Protein Pivot"
    bl_description = "Interactively move the protein's pivot using a helper object."

    molecule_id: bpy.props.StringProperty()

    def execute(self, context):
        from .pivot_operators import toggle_pivot_edit

        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        if not molecule or not molecule.object:
            self.report({'ERROR'}, "Molecule object not found.")
            return {'CANCELLED'}

        # The molecule object alone, not its domains: this is the protein's
        # own origin, and it is what the operator has always moved.
        return toggle_pivot_edit(self, context, f"protein:{self.molecule_id}",
                                 [molecule.object])

# Add operator to toggle visibility of molecule and its domains
class MOLECULE_PB_OT_toggle_visibility(Operator):
    bl_idname = "molecule.toggle_visibility"
    bl_label = "Toggle Molecule Visibility"
    bl_description = "Toggle visibility of this molecule and its domains"
    bl_options = {'REGISTER', 'UNDO'}

    molecule_id: StringProperty()

    def execute(self, context):
        # Get the molecule wrapper
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        if not molecule or not molecule.object:
            return {'CANCELLED'}
        # Determine new visibility state (False = visible, True = hidden).
        # Toggle all three Blender hide attributes so the outliner eye icon,
        # the camera icon, and the rendered output stay in sync.
        new_hidden = not molecule.object.hide_viewport

        def _apply(obj):
            obj.hide_viewport = new_hidden
            obj.hide_render = new_hidden
            try:
                obj.hide_set(new_hidden)
            except RuntimeError:
                # hide_set requires a valid view_layer context — skip if
                # invoked from a context that doesn't have one.
                pass

        _apply(molecule.object)
        for domain in getattr(molecule, 'domains', {}).values():
            if domain.object:
                _apply(domain.object)
        return {'FINISHED'}


class MOLECULE_PB_OT_center_protein(Operator):
    """Center protein at origin using center of mass"""
    bl_idname = "molecule.center_protein"
    bl_label = "Center Protein"
    bl_description = "Move protein pivot to center of mass and place at world origin"
    bl_options = {'REGISTER', 'UNDO'}

    molecule_id: StringProperty()

    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)

        if not molecule:
            self.report({'ERROR'}, "Molecule not found")
            return {'CANCELLED'}

        # Call the existing center of mass method
        success = molecule.set_protein_pivot_to_center_of_mass(context)

        if success:
            self.report({'INFO'}, f"Centered protein '{molecule.identifier}' at origin")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Failed to center protein")
            return {'CANCELLED'}


def _strip_inherited_domain_masks(node_group):
    """Drop the source molecule's per-domain mask nodes from a freshly copied
    GN tree.

    The duplicate re-creates every source domain against the new molecule, and
    those masks are keyed by the *new* domain ids — so the inherited pair per
    source domain is never reused, just left wired into the boolean join. It
    would keep hiding its residue range out of the copy's parent mesh after the
    domain that should own it is deleted, and it occupies join input slots that
    the copy's real masks need. The Join / Final NOT infrastructure is
    deliberately kept: it carries the molecule's pre-domain selection wiring,
    and MoleculeWrapper rebinds to it.
    """
    for node in list(node_group.nodes):
        if node.name.startswith(("Domain_Chain_Select_", "Domain_Res_Select_")):
            node_group.nodes.remove(node)


class MOLECULE_PB_OT_duplicate_protein(Operator):
    """Create an exact duplicate of the protein with all domains and properties"""
    bl_idname = "molecule.duplicate_protein"
    bl_label = "Duplicate Protein"
    bl_description = "Create a complete copy of this protein including all domains, colors, styles, and transforms"
    bl_options = {'REGISTER', 'UNDO'}

    molecule_id: StringProperty()

    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        source_molecule = scene_manager.molecules.get(self.molecule_id)

        if not source_molecule or not source_molecule.object:
            self.report({'ERROR'}, "Source molecule not found")
            return {'CANCELLED'}

        try:
            # 1. Generate unique identifier for the duplicate
            base_id = source_molecule.identifier
            counter = 1
            new_identifier = f"{base_id}_copy_{counter}"
            while new_identifier in scene_manager.molecules:
                counter += 1
                new_identifier = f"{base_id}_copy_{counter}"

            print(f"Duplicating protein '{base_id}' as '{new_identifier}'")

            # 2. Duplicate the main protein object and its mesh data
            source_obj = source_molecule.object

            # Save source object's transform data before copying
            source_location = source_obj.location.copy()
            source_rotation = source_obj.rotation_euler.copy()
            source_scale = source_obj.scale.copy()

            new_protein_obj = source_obj.copy()
            new_protein_obj.data = source_obj.data.copy()
            new_protein_obj.name = f"{new_identifier}_protein"

            # Link to scene (use same collection as source)
            if source_obj.users_collection:
                source_obj.users_collection[0].objects.link(new_protein_obj)
            else:
                context.scene.collection.objects.link(new_protein_obj)

            # Ensure new protein has exact same transform as source
            new_protein_obj.location = source_location
            new_protein_obj.rotation_euler = source_rotation
            new_protein_obj.scale = source_scale

            # 3. Copy modifiers from source protein
            new_protein_obj.modifiers.clear()
            for mod in source_obj.modifiers:
                new_mod = new_protein_obj.modifiers.new(name=mod.name, type=mod.type)
                # Copy modifier properties
                for prop in mod.bl_rna.properties:
                    if not prop.is_readonly:
                        try:
                            setattr(new_mod, prop.identifier, getattr(mod, prop.identifier))
                        except Exception:
                            pass

                # `node_group` is a POINTER property, so the loop above aimed the
                # copy's modifier at the *source's* GN tree. That tree is not a
                # shared read-only asset: each molecule's domain masking lives as
                # nodes inside it (Domain_Boolean_Join / Domain_Final_Not, plus a
                # per-domain mask pair), so an aliased tree means the two
                # molecules read and write one set of masking nodes. Deleting
                # either one then tears that infrastructure out from under the
                # survivor, which renders its full atom mesh on top of its own
                # domain objects. Give the copy a private tree.
                # See test_delete_copy_leaves_original_domain_masking_intact.
                if mod.type == 'NODES' and mod.node_group is not None:
                    new_mod.node_group = mod.node_group.copy()
                    _strip_inherited_domain_masks(new_mod.node_group)

            # 3b. Carry over the pivot. The pivot lives on the modifier as a
            # geometry-nodes input value (not an RNA property), so the loop above
            # did not copy it - the fresh modifier defaults it to zero. Without
            # this the copy's parent renders its atoms at a different world
            # position than its (correctly copied) domains. That mismatch is
            # invisible because the parent is masked out, until a split creates a
            # domain that inherits the parent's wrong pivot and jumps.
            # See test_parent_pivot_matches_its_domains.
            domain_space.copy_pivot(source_obj, new_protein_obj)

            # 4. Create new MoleculeWrapper
            # We need to create a Molecule object first
            from ..utils.molecularnodes.entities.molecule.molecule import Molecule
            from ..core.molecule_wrapper import MoleculeWrapper

            # Create a minimal Molecule object wrapping the new protein
            new_mol_obj = Molecule(new_protein_obj.name)
            new_mol_obj.object = new_protein_obj
            new_mol_obj.array = source_molecule.molecule.array  # Share the same biotite array

            # Create MoleculeWrapper
            new_molecule = MoleculeWrapper(new_mol_obj, new_identifier)
            new_molecule.style = source_molecule.style

            # Move new protein to source location BEFORE creating domains
            # This ensures domains are created with correct relative positions
            new_protein_obj.location = source_location
            context.view_layer.update()

            print(f"  Temporarily positioned new protein at source location: {source_location}")

            # 6. Save source domain data (we'll use LOCAL transforms since parent will match)
            source_domain_data = {}
            for source_domain_id, source_domain in source_molecule.get_sorted_domains().items():
                if source_domain.object:
                    # Save domain properties and LOCAL transforms (relative to parent)
                    source_domain_data[source_domain_id] = {
                        'name': source_domain.name,
                        'chain_id': source_domain.chain_id,
                        'start': source_domain.start,
                        'end': source_domain.end,
                        'color': source_domain.color,
                        'style': source_domain.style,
                        'local_location': source_domain.object.location.copy(),
                        'local_rotation': source_domain.object.rotation_euler.copy(),
                        'local_scale': source_domain.object.scale.copy(),
                        'matrix_parent_inverse': source_domain.object.matrix_parent_inverse.copy(),
                    }

            # 7. Copy all domains with their properties
            domain_mapping = {}  # Maps source_domain_id -> new_domain_id

            for source_domain_id, domain_data in source_domain_data.items():
                source_domain = source_molecule.domains[source_domain_id]

                print(f"  Copying domain: {domain_data['name']}")

                # Create new domain with same parameters
                # Need to convert chain_id to numeric format for create_domain
                numeric_chain_id = str(domain_data['chain_id'])
                if not numeric_chain_id.isdigit():
                    # Find numeric equivalent
                    for num_id, auth_id in source_molecule.chain_mapping.items():
                        if auth_id == domain_data['chain_id']:
                            numeric_chain_id = str(num_id)
                            break

                # Copy the domain VERBATIM — do not auto-fill the rest of the
                # chain. create_domain()'s auto_fill_chain is for interactive
                # creation of a *partial* domain (fill the untouched remainder);
                # here we already replicate every source domain explicitly, so
                # auto-fill only fabricates spurious degenerate filler domains —
                # e.g. a 0-0 "prefix filler" for a full chain that starts at
                # residue 1, which reads to the user as "Chain A got split into
                # two domains" on copy. See test_duplicate_preserves_domain_structure.
                result = new_molecule._create_domain_with_params(
                    numeric_chain_id,
                    domain_data['start'],
                    domain_data['end'],
                    domain_data['name'],
                    auto_fill_chain=False,
                )

                # _create_domain_with_params may return a list of domain IDs; take the first one
                if not result:
                    print(f"    Warning: Failed to create domain {source_domain.name}")
                    continue

                # Handle both list and string return types
                if isinstance(result, list):
                    new_domain_id = result[0] if result else None
                else:
                    new_domain_id = result

                if not new_domain_id:
                    print(f"    Warning: No domain ID returned for {source_domain.name}")
                    continue

                domain_mapping[source_domain_id] = new_domain_id
                new_domain = new_molecule.domains[new_domain_id]

                # 8. Copy color and style properties
                new_domain.color = domain_data['color']
                new_domain.style = domain_data['style']

                # 9. Copy LOCAL transforms from source domain
                # Since both parent proteins are at the same location, local transforms should match
                new_domain.object.location = domain_data['local_location']
                new_domain.object.rotation_euler = domain_data['local_rotation']
                new_domain.object.scale = domain_data['local_scale']

                # Also copy the matrix_parent_inverse to ensure exact transform preservation
                new_domain.object.matrix_parent_inverse = domain_data['matrix_parent_inverse']

                # 10. Copy color from geometry nodes (RGB values and alpha)
                self._copy_domain_color(source_domain.object, new_domain.object)

                # 11. Apply style to the domain's node group
                if new_domain.style != 'ribbon':  # ribbon is default, only change if different
                    try:
                        from ..utils.molecularnodes.blender.nodes import styles_mapping, append, swap
                        # Find the style node in the new domain's node group
                        if new_domain.node_group:
                            for node in new_domain.node_group.nodes:
                                if (node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name):
                                    if new_domain.style in styles_mapping:
                                        style_node_name = styles_mapping[new_domain.style]
                                        swap(node, append(style_node_name))
                                    break
                    except Exception as e:
                        print(f"    Warning: Could not apply style {new_domain.style}: {e}")

                # 12. Copy custom properties
                if hasattr(source_domain, 'is_copy'):
                    new_domain.is_copy = source_domain.is_copy
                if hasattr(source_domain, 'copy_number'):
                    new_domain.copy_number = source_domain.copy_number
                if hasattr(source_domain, 'original_domain_id'):
                    new_domain.original_domain_id = source_domain.original_domain_id

                print(f"    ✓ Copied domain '{source_domain.name}' -> '{new_domain_id}'")

            # 13. Force scene update to ensure all objects are properly initialized
            context.view_layer.update()

            # 14. Final verification - protein should still be at source location
            print(f"✓ Duplicated protein '{new_identifier}' created at same location as source")
            print(f"  Source location: {source_location}")
            print(f"  New protein location: {new_protein_obj.location}")

            # Verify location is correct
            current_location = new_protein_obj.location.copy()
            if (current_location - source_location).length > 0.0001:
                print(f"  Warning: Small location drift detected ({(current_location - source_location).length:.6f} units)")
            else:
                print("  ✓ Location verified: exactly matches source")

            # 15. Force final scene update
            context.view_layer.update()

            # 16. Add to scene manager (directly to molecules dict since MoleculeManager doesn't have add_molecule)
            scene_manager.molecules[new_identifier] = new_molecule

            # 17. Rebuild outliner to show the new protein
            build_outliner_hierarchy(context)

            # 18. The copy is placed as an exact overlay of the source (steps 2
            # and 14 copy its transform verbatim, and 3b its pivot), so it is
            # already centred wherever the source is. Do NOT re-center here:
            # center_protein moves only the parent, and the domains already exist
            # by now, so it would desync the parent from its domains - the parent
            # would then hand a wrong pivot to any domain created later by a
            # split. See test_split_on_a_copy_does_not_move_the_split_chain.

            self.report({'INFO'}, f"Duplicated protein '{base_id}' with {len(domain_mapping)} domains")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to duplicate protein: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

    def _copy_domain_color(self, source_obj, target_obj):
        """Copy color from source domain's geometry nodes to target domain"""
        try:
            # Find source geometry nodes modifier
            source_mod = None
            for mod in source_obj.modifiers:
                if mod.type == 'NODES' and mod.node_group:
                    source_mod = mod
                    break

            # Find target geometry nodes modifier
            target_mod = None
            for mod in target_obj.modifiers:
                if mod.type == 'NODES' and mod.node_group:
                    target_mod = mod
                    break

            if not source_mod or not target_mod:
                return

            source_tree = source_mod.node_group
            target_tree = target_mod.node_group

            # Look for Custom Combine Color node in source
            source_color_node = None
            for node in source_tree.nodes:
                if node.name == "Custom Combine Color" and node.type == 'COMBINE_COLOR':
                    source_color_node = node
                    break

            # Look for or create Custom Combine Color node in target
            target_color_node = None
            for node in target_tree.nodes:
                if node.name == "Custom Combine Color" and node.type == 'COMBINE_COLOR':
                    target_color_node = node
                    break

            if source_color_node and target_color_node:
                # Copy RGB values
                target_color_node.inputs['Red'].default_value = source_color_node.inputs['Red'].default_value
                target_color_node.inputs['Green'].default_value = source_color_node.inputs['Green'].default_value
                target_color_node.inputs['Blue'].default_value = source_color_node.inputs['Blue'].default_value

            # Also copy alpha from material if present
            self._copy_material_alpha(source_obj, target_obj, source_tree, target_tree)

        except Exception as e:
            print(f"Warning: Could not copy domain color: {e}")

    def _copy_material_alpha(self, source_obj, target_obj, source_tree, target_tree):
        """Copy alpha value from source material to target material"""
        try:
            # Find Style node in both trees
            source_style_node = None
            target_style_node = None

            for node in source_tree.nodes:
                if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
                    source_style_node = node
                    break

            for node in target_tree.nodes:
                if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
                    target_style_node = node
                    break

            if not source_style_node or not target_style_node:
                return

            # Get materials
            source_mat_input = source_style_node.inputs.get("Material")
            target_mat_input = target_style_node.inputs.get("Material")

            if not source_mat_input or not target_mat_input:
                return

            source_mat = source_mat_input.default_value
            target_mat = target_mat_input.default_value

            if not source_mat or not target_mat:
                return

            # Find Principled BSDF in both materials
            if source_mat.use_nodes and target_mat.use_nodes:
                source_bsdf = None
                target_bsdf = None

                for node in source_mat.node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED':
                        source_bsdf = node
                        break

                for node in target_mat.node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED':
                        target_bsdf = node
                        break

                if source_bsdf and target_bsdf:
                    # Copy alpha value
                    target_bsdf.inputs['Alpha'].default_value = source_bsdf.inputs['Alpha'].default_value

        except Exception as e:
            print(f"Warning: Could not copy material alpha: {e}")


class MOLECULE_PB_OT_delete_chain(Operator):
    """Delete a chain and all its domains from a protein"""
    bl_idname = "molecule.delete_chain"
    bl_label = "Delete Chain"
    bl_description = "Delete this chain and all its domains"
    bl_options = {'REGISTER', 'UNDO'}

    chain_id: StringProperty()
    molecule_id: StringProperty()

    def _domains_in_chain(self, molecule):
        """Domain ids belonging to this chain.

        ``self.chain_id`` arrives as the chain *index* ("2") from the outliner
        row while domains store the chain *letter* ("D"); match on any of the
        chain's identity forms.

        A chain *copy*'s row identifies itself by its primary domain id
        instead. It is still one chain-level thing to delete, so it resolves
        to every piece of that copy - deleting the copy of a split chain must
        not leave its other halves behind.
        """
        domain = molecule.domains.get(self.chain_id)
        if domain is not None:
            group_id = getattr(domain, 'copy_group_id', '')
            if group_id:
                return [member_id for member_id, _member
                        in copy_group_members(molecule, group_id)]
            return [self.chain_id]

        chain_tokens = chain_match_tokens(molecule, self.chain_id)
        return [domain_id for domain_id, domain in molecule.domains.items()
                if hasattr(domain, 'chain_id') and str(domain.chain_id) in chain_tokens]

    def _display_name(self, molecule):
        """What to call this row in a message.

        ``chain_id`` is a chain index ("2") or, for a chain copy, a domain id -
        neither belongs in a report the user reads.
        """
        domain = molecule.domains.get(self.chain_id) if molecule else None
        if domain is not None:
            return (getattr(domain, 'copy_group_name', '')
                    or getattr(domain, 'name', '') or self.chain_id)
        return f"chain {self.chain_id}"

    def invoke(self, context, event):
        # Deleting the protein's last chain deletes the protein itself, so say
        # so before the user commits to it: a confirmation that just reads
        # "Delete Chain" would understate what is about to happen.
        molecule = ProteinBlenderScene.get_instance().molecules.get(self.molecule_id)
        if molecule and molecule_would_be_emptied(molecule, self._domains_in_chain(molecule)):
            return context.window_manager.invoke_confirm(
                self, event,
                title="Delete Chain",
                message="This is the protein's last chain. Deleting it deletes "
                        "the whole protein, along with its puppets and poses.",
                confirm_text="Delete Protein")
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)

        if not molecule:
            self.report({'ERROR'}, "Molecule not found")
            return {'CANCELLED'}

        # Capture state for undo (reuse existing pattern)
        scene_manager.refresh_domain_refs_before_destructive_op(self.molecule_id)

        label = self._display_name(molecule)
        domains_to_delete = self._domains_in_chain(molecule)

        if not domains_to_delete:
            self.report({'WARNING'}, f"No domains found for {label}")
            return {'CANCELLED'}

        # Delete each domain using cleanup (reuse existing cleanup method)
        for domain_id in domains_to_delete:
            domain = molecule.domains[domain_id]
            # Call cleanup to remove object and node groups
            domain.cleanup()
            # Remove from molecule's domains dictionary
            del molecule.domains[domain_id]

        # Remove chain from puppet memberships
        self._remove_chain_from_puppets(context, self.molecule_id, self.chain_id,
                                        domains_to_delete)

        # A protein with no chains left is not a protein any more: delete it
        # outright so nothing (puppets, poses, keyframes, linkers) is left
        # holding on to an empty one.
        prune_emptied_puppets(context)
        if delete_molecule_if_empty(context, self.molecule_id):
            self.report({'INFO'}, f"Deleted {label} - the protein's last, "
                                  "so it was deleted too")
            return {'FINISHED'}

        # Rebuild outliner (reuse existing function)
        build_outliner_hierarchy(context)

        # Cascade: remove any linker left dangling by the chain deletion.
        try:
            from ..linkers.linker_handlers import prune_dangling_linkers
            prune_dangling_linkers(context.scene, "chain deleted")
        except Exception:
            pass

        self.report({'INFO'}, f"Deleted {label} and {len(domains_to_delete)} domain(s)")
        return {'FINISHED'}

    def _remove_chain_from_puppets(self, context, molecule_id, chain_id,
                                   domain_ids_in_chain):
        """Remove chain from any puppet group memberships.

        ``domain_ids_in_chain`` is captured before the deletion - by the time
        this runs the domains are gone from the molecule, so they can no
        longer be looked up. A chain copy's row is a domain id rather than a
        ``<molecule>_chain_<n>`` id, and it reaches puppets through that list.
        """
        # The chain's outliner ID is in the format "molecule_id_chain_X"
        chain_outliner_id = f"{molecule_id}_chain_{chain_id}"

        # Remove from puppet memberships
        for item in context.scene.outliner_items:
            if item.item_type == 'PUPPET' and item.puppet_memberships:
                members = set(item.puppet_memberships.split(','))
                modified = False

                # Remove chain outliner ID
                if chain_outliner_id in members:
                    members.remove(chain_outliner_id)
                    modified = True

                # Remove any domain IDs from this chain
                for domain_id in domain_ids_in_chain:
                    if domain_id in members:
                        members.remove(domain_id)
                        modified = True

                if modified:
                    item.puppet_memberships = ','.join(members) if members else ""
