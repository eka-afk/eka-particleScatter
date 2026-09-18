import importlib.util
from pathlib import Path
import sys

import bpy
from mathutils import Quaternion


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "easy_mesh_scatter" / "__init__.py"
CAPTURE_EDIT_MASK = "--edit-mask" in sys.argv
SCREENSHOT_NAME = (
    "eka-particleScatter-density-mask.png"
    if CAPTURE_EDIT_MASK
    else "eka-particleScatter-ui.png"
)
SCREENSHOT_PATH = PROJECT_ROOT / "docs" / SCREENSHOT_NAME


def load_addon():
    spec = importlib.util.spec_from_file_location(
        "eka_particle_scatter_capture",
        ADDON_PATH,
        submodule_search_locations=[str(ADDON_PATH.parent)],
    )
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon.register()


def create_demo_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    bpy.ops.mesh.primitive_grid_add(x_subdivisions=20, y_subdivisions=20, size=8.0)
    target = bpy.context.object
    target.name = "Landscape Scatter Surface"

    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.18, location=(0.0, 0.0, 0.45))
    source = bpy.context.object
    source.name = "Grass Bush"
    source.scale = (0.35, 0.35, 2.5)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    target.select_set(True)
    source.select_set(False)
    bpy.context.view_layer.objects.active = target

    settings = target.easy_mesh_scatter
    settings.source_object = source
    settings.density = 2.0 if CAPTURE_EDIT_MASK else 7.5
    settings.seed = 42
    settings.scale_min = 0.65
    settings.scale_max = 1.35
    settings.rotation_min = (0.0, 0.0, 0.0)
    settings.rotation_max = (0.0, 0.0, 6.283185307179586)
    settings.use_mask = True
    settings.mask_name = "Grass Area"
    settings.keep_surface = True
    settings.realize_instances = False
    bpy.ops.easy_scatter.add_or_update()

    mask = target.vertex_groups.get(settings.mask_name)
    if CAPTURE_EDIT_MASK:
        for vertex in target.data.vertices:
            weight = max(0.0, min(1.0, (vertex.co.x + 4.0) / 8.0))
            mask.add([vertex.index], weight, "REPLACE")
        settings.mask_edit_weight = 0.5
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
    else:
        mask.add(range(len(target.data.vertices)), 1.0, "REPLACE")
    source.hide_set(True)
    target.update_tag()
    return target


def prepare_viewport(target):
    window = bpy.context.window
    screen = window.screen
    area = next(area for area in screen.areas if area.type == "VIEW_3D")
    window_region = next(region for region in area.regions if region.type == "WINDOW")
    with bpy.context.temp_override(window=window, area=area, region=window_region):
        bpy.ops.screen.screen_full_area()

    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    space = area.spaces.active
    space.show_region_ui = True
    space.overlay.show_weight = CAPTURE_EDIT_MASK
    space.overlay.show_floor = True
    space.overlay.show_axis_x = False
    space.overlay.show_axis_y = False
    space.shading.type = "MATERIAL"

    region_3d = space.region_3d
    region_3d.view_location = target.location
    region_3d.view_distance = 9.5
    region_3d.view_rotation = Quaternion((0.885, 0.255, 0.356, -0.155))

    return window, area


def scatter_tab_coordinates():
    window = bpy.context.window
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    sidebar = next(region for region in area.regions if region.type == "UI")
    tab_x = sidebar.x + sidebar.width - 14
    tab_y = sidebar.y + sidebar.height - 275
    return window, sidebar, tab_x, tab_y


def release_scatter_tab():
    window, sidebar, tab_x, tab_y = scatter_tab_coordinates()
    window.event_simulate(type="LEFTMOUSE", value="RELEASE", x=tab_x, y=tab_y)
    bpy.app.timers.register(capture, first_interval=1.0)
    return None


def press_scatter_tab():
    window, _sidebar, tab_x, tab_y = scatter_tab_coordinates()
    window.event_simulate(type="LEFTMOUSE", value="PRESS", x=tab_x, y=tab_y)
    bpy.app.timers.register(release_scatter_tab, first_interval=0.2)
    return None


def activate_scatter_tab():
    window, sidebar, tab_x, tab_y = scatter_tab_coordinates()
    window.cursor_warp(tab_x, tab_y)
    window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=tab_x, y=tab_y)
    print(f"UI_TAB_CLICK=({tab_x}, {tab_y}) SIDEBAR={sidebar.width}x{sidebar.height}")
    bpy.app.timers.register(press_scatter_tab, first_interval=0.2)
    return None


def dismiss_splash():
    window = bpy.context.window
    window.event_simulate(type="ESC", value="PRESS")
    window.event_simulate(type="ESC", value="RELEASE")
    bpy.app.timers.register(activate_scatter_tab, first_interval=0.75)
    return None


def capture():
    SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _window, sidebar, _tab_x, _tab_y = scatter_tab_coordinates()
    print(f"UI_ACTIVE_CATEGORY={sidebar.active_panel_category}")
    assert sidebar.active_panel_category == "eka-particleScatter"
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=3)
    result = bpy.ops.screen.screenshot(filepath=str(SCREENSHOT_PATH), check_existing=False)
    print(f"UI_CAPTURE_RESULT={result} PATH={SCREENSHOT_PATH}")
    bpy.ops.wm.quit_blender()
    return None


def main():
    load_addon()
    target = create_demo_scene()
    prepare_viewport(target)
    bpy.app.timers.register(dismiss_splash, first_interval=0.75)


main()