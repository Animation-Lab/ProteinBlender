"""Script to update all panels from VIEW_3D to PROPERTIES space"""

import os
import re

# Define the panel files to update
panel_files = [
    "proteinblender/panels/ui_panels.py",
    "proteinblender/panels/visual_setup_panel.py",
    "proteinblender/panels/domain_maker_panel.py",
    "proteinblender/panels/group_maker_panel.py",
    "proteinblender/panels/pose_library_panel.py",
    "proteinblender/panels/animate_scene_panel.py"
]

# Pattern to find panel class definitions with VIEW_3D
panel_pattern = re.compile(
    r"(class\s+VIEW3D_PT_[^(]+\(Panel\):[^}]*?)"
    r"(bl_space_type\s*=\s*['\"]VIEW_3D['\"])"
    r"([^}]*?)"
    r"(bl_region_type\s*=\s*['\"]UI['\"])"
    r"([^}]*?)"
    r"(bl_category\s*=\s*['\"][^'\"]+['\"])",
    re.DOTALL | re.MULTILINE
)

def update_panel_file(filepath):
    """Update a single panel file"""
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Count replacements
    replacements = 0
    
    def replace_panel(match):
        nonlocal replacements
        replacements += 1
        
        # Extract parts
        class_def = match.group(1)
        space_type = match.group(2)
        between1 = match.group(3)
        region_type = match.group(4)
        between2 = match.group(5)
        category = match.group(6)
        
        # Replace with PROPERTIES settings
        new_space_type = 'bl_space_type = \'PROPERTIES\''
        new_region_type = 'bl_region_type = \'WINDOW\''
        new_context = '\n    bl_context = "scene"'
        
        # Remove bl_category and add bl_context
        result = (
            class_def +
            new_space_type +
            between1 +
            new_region_type +
            new_context
        )
        
        return result
    
    # Apply replacements
    new_content = panel_pattern.sub(replace_panel, content)
    
    # Also update any remaining VIEW3D_PT panel classes that might have different formatting
    new_content = re.sub(
        r"bl_space_type\s*=\s*['\"]VIEW_3D['\"]",
        "bl_space_type = 'PROPERTIES'",
        new_content
    )
    new_content = re.sub(
        r"bl_region_type\s*=\s*['\"]UI['\"]",
        "bl_region_type = 'WINDOW'",
        new_content
    )
    
    # Add bl_context if not present for PROPERTIES panels
    lines = new_content.split('\n')
    new_lines = []
    in_panel_class = False
    has_context = False
    
    for i, line in enumerate(lines):
        new_lines.append(line)
        
        # Check if we're entering a panel class
        if 'class VIEW3D_PT_' in line and '(Panel):' in line:
            in_panel_class = True
            has_context = False
        
        # Check if we already have bl_context
        if in_panel_class and 'bl_context' in line:
            has_context = True
        
        # Add bl_context after bl_region_type if needed
        if in_panel_class and 'bl_region_type = \'WINDOW\'' in line and not has_context:
            # Check if bl_context is not in the next few lines
            context_found = False
            for j in range(i+1, min(i+5, len(lines))):
                if 'bl_context' in lines[j]:
                    context_found = True
                    break
            
            if not context_found:
                new_lines.append('    bl_context = "scene"')
        
        # Reset when we exit the class
        if in_panel_class and line.strip() and not line.startswith(' '):
            in_panel_class = False
    
    new_content = '\n'.join(new_lines)
    
    # Write back if changes were made
    if new_content != content:
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"Updated {filepath} - {replacements} panels modified")
    else:
        print(f"No changes needed in {filepath}")

# Run the updates
for filepath in panel_files:
    update_panel_file(filepath)

print("\nPanel update complete!")
print("\nNote: You may need to manually verify and adjust:")
print("1. Any panels that should remain in VIEW_3D")
print("2. Panel ordering (bl_order)")
print("3. Remove any bl_category lines that were missed")