"""Observe and click mixed swatches in the actual PB Outliner."""

import time

import pytest


@pytest.mark.live
@pytest.mark.visual
@pytest.mark.parametrize('half', [0, 1], ids=['left', 'right'])
def test_segmented_swatches_and_click_to_recolor(blender, half):
    blender.call('''
import importlib
with R.view3d_override():
    mid = H.import_local('1ubq.pdb', 'Palette')
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
chain = next(r for r in bpy.context.scene.outliner_items if r.item_type == 'CHAIN')
cid = chain.item_id
dl = importlib.import_module(H.PKG + '.core.domain_layout')
lo, hi = dl.chain_residue_range(H.sm().molecules[mid], chain.chain_id)
spans = dl.even_split(lo, hi, 4)
colors = [(1,0,0,1), (0,1,0,1), (0,0,1,1), (1,1,0,1)]
payload = json.dumps([dict(name=f'Domain {i+1}', start=a, end=b,
                          domain_id='', color=color)
                      for i, ((a, b), color) in enumerate(zip(spans, colors))])
bpy.ops.proteinblender.edit_chain_domains(item_id=cid, layout_json=payload)
for row in bpy.context.scene.outliner_items:
    row.is_expanded = True
win = bpy.context.window
win.workspace = bpy.data.workspaces['Protein Blender']
win.event_simulate(type='ESC', value='PRESS')
win.event_simulate(type='ESC', value='RELEASE')
for area in win.screen.areas:
    area.tag_redraw()
with R.view3d_override():
    bpy.ops.ed.undo_push(message='Mixed palette before color pick')
return mid
''')
    time.sleep(0.5)
    # Pixels are read from a window screenshot, not from the preview buffer or
    # a layout recorder. The solid domain swatches cannot satisfy RGBY on one
    # scanline. Two separated bands prove the protein AND chain display it.
    position = blender.call('''
import tempfile, os, numpy as np
path = os.path.join(tempfile.gettempdir(), 'pb_palette_pixels.png')
bpy.ops.screen.screenshot(filepath=path)
img = bpy.data.images.load(path, check_existing=False)
w, h = img.size
pixels = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
bpy.app.driver_namespace['pb_palette_before_popup'] = pixels
bpy.data.images.remove(img)
os.remove(path)
area = next(a for a in bpy.context.window.screen.areas if a.type == 'PROPERTIES')
a = pixels[:, area.x:area.x+area.width, :3]
codes = np.full(a.shape[:2], -1)
for n, color in enumerate(((1,0,0), (0,1,0), (0,0,1), (1,1,0))):
    codes[np.max(np.abs(a-np.array(color)), axis=2) < 0.18] = n
hits = []
for y, line in enumerate(codes):
    xs = np.flatnonzero(line >= 0)
    if len(xs) < 4:
        continue
    values = line[xs]
    sequence = values[np.r_[True, np.diff(values) != 0]].tolist()
    if sequence == [0,1,2,3] and xs[-1]-xs[0] < 80:
        hits.append([int(xs[0])+area.x, int(xs[-1])+area.x, y])
assert hits, 'No actual segmented swatch pixels in the PB Outliner'
groups = [[hits[0]]]
for hit in hits[1:]:
    if hit[2] > groups[-1][-1][2] + 1:
        groups.append([])
    groups[-1].append(hit)
assert len(groups) == 2, f'Expected protein and chain palettes, found {len(groups)}'
x0, x1, y = groups[-1][len(groups[-1])//2]
# Compare the mixed rows to the actual solid domain swatches in the same
# screenshot. This catches a tiny icon inside a nominally full-width button.
solid_lines = []
for sy, line in enumerate(codes[:groups[0][0][2]]):
    xs = np.flatnonzero(line >= 0)
    if len(xs) >= 8 and len(set(line[xs])) == 1 and xs[-1]-xs[0] < 80:
        solid_lines.append([int(xs[0])+area.x, int(xs[-1])+area.x, sy])
assert solid_lines, 'No solid domain swatch pixels found for size comparison'
solid_width = max(right-left+1 for left, right, _ in solid_lines)
solid_heights = [1]
for previous, current in zip(solid_lines, solid_lines[1:]):
    if current[2] == previous[2]+1:
        solid_heights[-1] += 1
    else:
        solid_heights.append(1)
for group in groups:
    left, right, _ = group[len(group)//2]
    assert abs((right-left+1)-solid_width) <= 2, (
        f'Mixed swatch is {right-left+1}px wide; solid swatch is {solid_width}px')
    assert abs(len(group)-max(solid_heights)) <= 2, (
        f'Mixed swatch is {len(group)}px high; solid swatch is {max(solid_heights)}px')
return [(3*x0+x1)//4 if half == 0 else (x0+3*x1)//4, y]
''', half=half)
    blender.call('''
win = bpy.context.window
for kind, value in [('MOUSEMOVE','NOTHING'), ('LEFTMOUSE','PRESS'), ('LEFTMOUSE','RELEASE')]:
    win.event_simulate(type=kind, value=value, x=position[0], y=position[1])
''', position=position)
    time.sleep(0.4)
    try:
        # Choose a green point on the wheel opened by the actual icon click.
        # The popup is clamped to the screen edge, so find its green pixels
        # below the clicked row rather than hard-coding a screen coordinate.
        blender.call('''
import tempfile, os, numpy as np
row = next(r for r in bpy.context.scene.outliner_items if r.item_type == 'PROTEIN')
assert len(json.loads(row.row_palette_json)) == 4, 'Opening the picker recolored the protein'
path = os.path.join(tempfile.gettempdir(), 'pb_palette_picker.png')
bpy.ops.screen.screenshot(filepath=path)
img = bpy.data.images.load(path, check_existing=False)
w, h = img.size
pixels = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
bpy.data.images.remove(img)
os.remove(path)
scale = bpy.context.preferences.system.ui_scale
x, y = position
x0, x1 = max(0, x-int(300*scale)), min(w, x+int(80*scale))
y0, y1 = max(0, y-int(240*scale)), max(0, y-int(20*scale))
rgb = pixels[y0:y1, x0:x1, :3]
score = rgb[:,:,1] - rgb[:,:,0] - rgb[:,:,2]
before = bpy.app.driver_namespace.pop('pb_palette_before_popup')[y0:y1, x0:x1, :3]
# Native and operator pickers can open on either side of the clicked swatch.
# Exclude pre-existing green domain swatches and choose a partly saturated
# green, so the pick differs even when the clicked segment starts pure green.
changed = np.max(np.abs(rgb-before), axis=2) > 0.2
candidates = np.argwhere(changed & (score > 0.45) & (score < 0.65) & (rgb[:,:,1] > 0.7))
assert len(candidates), 'Clicking the swatch did not open a color wheel'
dy, dx = candidates[len(candidates)//2]
win = bpy.context.window
for kind, value in [('MOUSEMOVE','NOTHING'), ('LEFTMOUSE','PRESS'), ('LEFTMOUSE','RELEASE')]:
    win.event_simulate(type=kind, value=value, x=x0+int(dx), y=y0+int(dy))
''', position=position)
        time.sleep(0.4)
        blender.call('''
row = next(r for r in bpy.context.scene.outliner_items if r.item_type == 'PROTEIN')
assert len(json.loads(row.row_palette_json)) == 1, 'Picking a color did not resolve the palette'
# Independent truth: inspect the nodes feeding the visible Set Color input.
for mol in H.sm().molecules.values():
    for domain in mol.domains.values():
        tree = next(m.node_group for m in domain.object.modifiers if m.type == 'NODES')
        node = tree.nodes['Custom Combine Color']
        red, green, blue = [node.inputs[c].default_value for c in ('Red','Green','Blue')]
        assert green > red + 0.1 and green > blue + 0.1, (red, green, blue)
''')
    finally:
        blender.call('''
win = bpy.context.window
win.event_simulate(type='ESC', value='PRESS')
win.event_simulate(type='ESC', value='RELEASE')
''')
        time.sleep(0.2)
    blender.call('''
row = next(r for r in bpy.context.scene.outliner_items if r.item_type == 'PROTEIN')
assert len(json.loads(row.row_palette_json)) == 1, 'Closing the picker lost the shared color'
''')
    blender.call('''
with R.view3d_override():
    assert bpy.ops.ed.undo() == {'FINISHED'}
''')
    time.sleep(0.5)
    blender.call('''
row = next(r for r in bpy.context.scene.outliner_items if r.item_type == 'PROTEIN')
assert len(json.loads(row.row_palette_json)) == 4, 'Undo did not restore the mixed swatch'
''')
    blender.call('''
with R.view3d_override():
    assert bpy.ops.ed.redo() == {'FINISHED'}
''')
    time.sleep(0.5)
    blender.call('''
row = next(r for r in bpy.context.scene.outliner_items if r.item_type == 'PROTEIN')
assert len(json.loads(row.row_palette_json)) == 1, 'Redo did not restore the shared color'
''')
