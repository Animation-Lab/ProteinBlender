"""
Test script for transparency functionality in ProteinBlender
"""

import bpy

def test_transparency():
    """Test that transparency is applied when alpha channel is changed"""
    
    print("=" * 50)
    print("Testing Transparency with Alpha Channel")
    print("=" * 50)
    
    # Check if visual_setup_color property exists
    if hasattr(bpy.context.scene, 'visual_setup_color'):
        print("✓ visual_setup_color property found")
        
        # Get current color value
        current_color = bpy.context.scene.visual_setup_color
        print(f"Current color: R={current_color[0]:.2f}, G={current_color[1]:.2f}, B={current_color[2]:.2f}, A={current_color[3]:.2f}")
        
        # Test different alpha values
        test_alphas = [1.0, 0.75, 0.5, 0.25, 0.1]
        
        print("\nTo test transparency:")
        print("1. Load a protein molecule")
        print("2. Select it in the ProteinBlender outliner")
        print("3. In the Visual Setup panel, adjust the Alpha slider in the color picker")
        print("4. The object should become transparent based on the alpha value")
        
        print("\nTest alpha values to try:")
        for alpha in test_alphas:
            print(f"  - Alpha = {alpha:.2f} ({int(alpha*100)}% opacity)")
        
        print("\nTransparency settings applied:")
        print("  - Material blend_method: ALPHA_BLEND")
        print("  - Backface culling: Disabled")
        print("  - Transparent back: Enabled")
        
        # Check for any molecular objects in the scene
        mol_objects = [obj for obj in bpy.data.objects if any(
            mod.type == 'NODES' and 'MolecularNodes' in mod.name 
            for mod in obj.modifiers
        )]
        
        if mol_objects:
            print(f"\n✓ Found {len(mol_objects)} molecular object(s) in scene")
            for obj in mol_objects[:3]:  # Show first 3
                print(f"  - {obj.name}")
                # Check if object has material
                if obj.data.materials:
                    mat = obj.data.materials[0]
                    if mat:
                        print(f"    Material: {mat.name}")
                        print(f"    Blend method: {mat.blend_method}")
                        if mat.use_nodes and mat.node_tree:
                            # Look for Principled BSDF
                            for node in mat.node_tree.nodes:
                                if node.type == 'BSDF_PRINCIPLED':
                                    alpha = node.inputs['Alpha'].default_value
                                    print(f"    Alpha value: {alpha:.2f}")
                                    break
                else:
                    print(f"    No material (will be created when color is applied)")
        else:
            print("\n⚠ No molecular objects found. Load a protein first.")
        
        print("\nIMPORTANT: Make sure you're in Material Preview or Rendered viewport shading mode")
        print("to see transparency effects (Solid shading doesn't show transparency)")
        
    else:
        print("✗ visual_setup_color property not found - ensure addon is registered")
    
    print("=" * 50)

if __name__ == "__main__":
    test_transparency()