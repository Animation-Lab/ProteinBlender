"""What ProteinBlender registers when its Python dependencies are broken.

Imported by the package ``__init__`` only when the core packages cannot be
imported, in place of the whole add-on. It stands in for it with a sidebar tab
that says what is broken and offers a retry, so a broken install is never just
a missing tab.

Never read ``bl_info`` here: Blender deletes it from an extension's module
before it calls ``register()``. The old fallback ``register()`` read
``bl_info['name']``, so a broken install raised NameError, Blender dropped the
add-on, and the tester was left with no tab and no explanation.
"""
import platform
import time

import bpy

from . import (
    REQUIRED_PACKAGES,
    _can_import_core_packages,
    _clear_install_attempt,
    _flush_popups,
    _last_install_attempt,
    _pending_popups,
    _record_install_attempt,
    _show_error_popup,
    ensure_packages,
)

_ADDON_NAME = "ProteinBlender"


def dependency_problem() -> str:
    """One line on what is broken, for the panel and the popup."""
    from . import _import_problem
    return _import_problem or "Required Python packages are missing."


def _wrap(context, text):
    """Break ``text`` into labels that fit the region, measured in its font.

    Blender labels do not wrap; a too-long one is cut down with "...", so
    a fixed character count is wrong at every sidebar width but one.
    """
    import blf
    system = context.preferences.system
    try:
        points = context.preferences.ui_styles[0].widget.points
    except Exception:
        points = 11
    blf.size(0, points * system.ui_scale)
    region = context.region
    if region is not None and region.type == 'UI':
        region_width = region.width
    else:  # a popover: its width comes from bl_ui_units_x (20 px a unit)
        region_width = PROTEINBLENDER_PT_dependency_problem.bl_ui_units_x * 20 * system.ui_scale
    width = max(60.0, (region_width - 40 * system.ui_scale) * 0.95)
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if line and blf.dimensions(0, candidate)[0] > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    return lines + [line] if line else (lines or [""])


class PROTEINBLENDER_OT_retry_dependency_install(bpy.types.Operator):
    """Try again to install ProteinBlender's Python packages"""
    bl_idname = "proteinblender.retry_dependency_install"
    bl_label = "Retry Install"

    def execute(self, context):
        _record_install_attempt()
        ok = ensure_packages(REQUIRED_PACKAGES) and _can_import_core_packages()
        if ok:
            _clear_install_attempt()
            self.report({'INFO'}, "Packages repaired. Restart Blender to load ProteinBlender.")
            return {'FINISHED'}
        self.report({'ERROR'}, f"Still broken - {dependency_problem()}")
        return {'CANCELLED'}


class PROTEINBLENDER_PT_dependency_problem(bpy.types.Panel):
    """Stands in for the whole add-on, so the tab is never just gone."""
    bl_label = "ProteinBlender could not load"
    bl_idname = "PROTEINBLENDER_PT_dependency_problem"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ProteinBlender"
    bl_ui_units_x = 14

    def draw_header(self, context):
        self.layout.label(icon='ERROR')

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        for line in _wrap(context, "Some of the Python packages it needs cannot be imported:"):
            col.label(text=line)
        box = layout.box().column(align=True)
        for line in _wrap(context, dependency_problem()):
            box.label(text=line)
        last = _last_install_attempt()
        if last is not None:
            # The record is ignored after a day, so "today"/"yesterday" covers it.
            then = time.localtime(last)
            day = "today" if then.tm_yday == time.localtime().tm_yday else "yesterday"
            col = layout.column(align=True)
            for line in _wrap(context, f"An automatic repair at {time.strftime('%H:%M', then)} "
                                       f"{day} did not fix it."):
                col.label(text=line)
        layout.operator(PROTEINBLENDER_OT_retry_dependency_install.bl_idname, icon='FILE_REFRESH')
        if platform.system() == "Windows":
            layout.operator("wm.console_toggle", text="Show System Console", icon='CONSOLE')
        col = layout.column(align=True)
        for line in _wrap(context, "If Retry does not help, reinstall ProteinBlender from "
                          "Preferences > Get Extensions, then restart Blender."):
            col.label(text=line)


CLASSES = (
    PROTEINBLENDER_OT_retry_dependency_install,
    PROTEINBLENDER_PT_dependency_problem,
)


def register() -> None:
    """Register only the panel that says what is broken and offers a retry."""
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _show_error_popup(f"{_ADDON_NAME} could not load - {dependency_problem()}")


def unregister() -> None:
    for cls in reversed(CLASSES):
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)
    if bpy.app.timers.is_registered(_flush_popups):
        bpy.app.timers.unregister(_flush_popups)
    _pending_popups.clear()
