import importlib.util
import math
from pathlib import Path
import sys

import bpy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "easy_mesh_scatter" / "__init__.py"


def load_addon():
    spec = importlib.util.spec_from_file_location(
        "easy_mesh_scatter_test",
        ADDON_PATH,
        submodule_search_locations=[str(ADDON_PATH.parent)],
    )
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    return addon


def create_mesh_object(name, vertices, faces, collection):
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def modifier_input(addon, modifier, name):
    socket = addon._interface_input(modifier.node_group, name)
    if getattr(modifier, "properties", None) is not None:
        return getattr(modifier.properties.inputs, socket.identifier).value
    return modifier[socket.identifier]


def evaluated_vertex_count(target):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    evaluated = target.evaluated_get(depsgraph)
    evaluated_mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        return len(evaluated_mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def evaluated_minimum_z(target):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    evaluated = target.evaluated_get(depsgraph)
    evaluated_mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        return min(vertex.co.z for vertex in evaluated_mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon = load_addon()
    addon.register()

    scene_collection = bpy.context.scene.collection
    target = create_mesh_object(
        "Scatter Target",
        ((-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)),
        ((0, 1, 2, 3),),
        scene_collection,
    )
    source = create_mesh_object(
        "Grass Source",
        ((-0.05, 0.0, 0.0), (0.05, 0.0, 0.0), (0.0, 0.0, 0.5)),
        ((0, 1, 2),),
        scene_collection,
    )

    target.select_set(True)
    source.select_set(False)
    bpy.context.view_layer.objects.active = target

    settings = target.easy_mesh_scatter
    settings.source_object = source
    settings.density = 50.0
    settings.seed = 17
    settings.scale_min = 0.6
    settings.scale_max = 1.4
    settings.rotation_min = (-0.1, -0.2, 0.0)
    settings.rotation_max = (0.1, 0.2, math.tau)

    legacy_group = bpy.data.node_groups.new("Legacy eka-particleScatter", "GeometryNodeTree")
    addon._build_node_group(legacy_group)
    legacy_group[addon.NODE_GROUP_TAG] = 1
    legacy_modifier = target.modifiers.new(addon.MODIFIER_NAME, "NODES")
    legacy_modifier.node_group = legacy_group
    settings.density = 51.0
    assert "Upgrade Scatter" in settings.sync_error

    assert bpy.ops.easy_scatter.add_or_update() == {"FINISHED"}
    modifier = addon._find_scatter_modifier(target)
    assert modifier is not None
    assert modifier == legacy_modifier
    assert modifier.node_group.get(addon.NODE_GROUP_TAG) == addon.NODE_GROUP_VERSION
    assert len([item for item in target.modifiers if addon._is_scatter_node_group(item.node_group)]) == 1
    assert settings.sync_error == ""
    assert modifier.show_viewport and modifier.show_render
    assert modifier.show_in_editmode
    assert modifier_input(addon, modifier, "Instance Object") == source
    assert modifier_input(addon, modifier, "Density") == 51.0
    assert modifier_input(addon, modifier, "Viewport Scale") == 1.0
    assert modifier_input(addon, modifier, "Minimum Distance") == 0.0
    assert modifier_input(addon, modifier, "Surface Offset") == 0.0
    assert modifier_input(addon, modifier, "Seed") == 17
    assert bpy.ops.easy_scatter.next_seed() == {"FINISHED"}
    assert settings.seed == 18
    assert modifier_input(addon, modifier, "Seed") == 18

    expected_node_types = {
        "GeometryNodeCollectionInfo",
        "GeometryNodeDistributePointsOnFaces",
        "GeometryNodeInputNamedAttribute",
        "GeometryNodeInstanceOnPoints",
        "GeometryNodeIsViewport",
        "GeometryNodeObjectInfo",
        "GeometryNodeRealizeInstances",
        "GeometryNodeRotateInstances",
        "GeometryNodeSetPosition",
    }
    actual_node_types = {node.bl_idname for node in modifier.node_group.nodes}
    assert expected_node_types <= actual_node_types

    settings.density = 75.0
    settings.seed = 29
    assert modifier_input(addon, modifier, "Density") == 75.0
    assert modifier_input(addon, modifier, "Seed") == 29

    settings.use_mask = True
    settings.realize_instances = True
    assert bpy.ops.easy_scatter.add_or_update() == {"FINISHED"}
    mask = target.vertex_groups.get(settings.mask_name)
    assert mask is not None
    assert target.mode == "OBJECT"
    assert bpy.ops.easy_scatter.toggle_mask_paint() == {"FINISHED"}
    assert target.mode == "WEIGHT_PAINT"
    assert bpy.ops.easy_scatter.toggle_mask_paint() == {"FINISHED"}
    assert target.mode == "OBJECT"

    assert bpy.ops.easy_scatter.toggle_mask_edit() == {"FINISHED"}
    assert target.mode == "EDIT"
    bpy.ops.mesh.select_all(action="SELECT")
    assert bpy.ops.easy_scatter.assign_mask_weight(weight=0.0) == {"FINISHED"}
    assert target.mode == "EDIT"
    assert any(
        area.spaces.active.overlay.show_weight
        for area in bpy.context.screen.areas
        if area.type == "VIEW_3D"
    )
    assert bpy.ops.easy_scatter.toggle_mask_edit() == {"FINISHED"}
    assert target.mode == "OBJECT"
    blue_mask_count = evaluated_vertex_count(target)
    assert blue_mask_count == 4, blue_mask_count

    settings.mask_edit_weight = 0.5
    assert bpy.ops.easy_scatter.toggle_mask_edit() == {"FINISHED"}
    bpy.ops.mesh.select_all(action="SELECT")
    assert bpy.ops.easy_scatter.assign_mask_weight() == {"FINISHED"}
    assert bpy.ops.easy_scatter.toggle_mask_edit() == {"FINISHED"}
    mid_mask_count = evaluated_vertex_count(target)

    assert bpy.ops.easy_scatter.toggle_mask_edit() == {"FINISHED"}
    bpy.ops.mesh.select_all(action="SELECT")
    assert bpy.ops.easy_scatter.assign_mask_weight(weight=1.0) == {"FINISHED"}
    assert bpy.ops.easy_scatter.toggle_mask_edit() == {"FINISHED"}
    red_mask_count = evaluated_vertex_count(target)
    assert blue_mask_count < mid_mask_count < red_mask_count, (
        blue_mask_count,
        mid_mask_count,
        red_mask_count,
    )
    assert all(abs(mask.weight(index) - 1.0) < 1e-6 for index in range(4))

    settings.viewport_percentage = 0.0
    viewport_zero_count = evaluated_vertex_count(target)
    assert viewport_zero_count == 4, viewport_zero_count
    settings.viewport_percentage = 100.0

    settings.minimum_distance = 0.4
    spaced_count = evaluated_vertex_count(target)
    assert 4 < spaced_count < red_mask_count, (spaced_count, red_mask_count)
    settings.minimum_distance = 0.0

    settings.keep_surface = False
    settings.surface_offset = 1.0
    assert evaluated_minimum_z(target) > 0.75
    settings.surface_offset = 0.0
    settings.keep_surface = True

    source_collection = bpy.data.collections.new("Scatter Sources")
    scene_collection.children.link(source_collection)
    second_source = create_mesh_object(
        "Second Grass Source",
        ((-0.04, 0.0, 0.0), (0.04, 0.0, 0.0), (0.0, 0.0, 0.35)),
        ((0, 1, 2),),
        source_collection,
    )
    assert second_source.name in source_collection.objects
    settings.source_type = "COLLECTION"
    settings.source_collection = source_collection
    assert bpy.ops.easy_scatter.add_or_update() == {"FINISHED"}
    assert len([item for item in target.modifiers if addon._is_scatter_node_group(item.node_group)]) == 1
    assert modifier_input(addon, modifier, "Use Collection") is True
    assert modifier_input(addon, modifier, "Instance Collection") == source_collection

    assert bpy.ops.easy_scatter.remove() == {"FINISHED"}
    assert addon._find_scatter_modifier(target) is None

    failure_target = create_mesh_object(
        "Failure Target",
        ((-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)),
        ((0, 1, 2, 3),),
        scene_collection,
    )
    target.select_set(False)
    failure_target.select_set(True)
    bpy.context.view_layer.objects.active = failure_target
    failure_target.easy_mesh_scatter.source_object = source
    original_ensure_node_group = addon._ensure_node_group

    def fail_node_group_creation():
        raise RuntimeError("synthetic graph failure")

    addon._ensure_node_group = fail_node_group_creation
    try:
        try:
            result = bpy.ops.easy_scatter.add_or_update()
        except RuntimeError as error:
            assert "synthetic graph failure" in str(error)
        else:
            assert result == {"CANCELLED"}
    finally:
        addon._ensure_node_group = original_ensure_node_group
    assert addon._find_scatter_modifier(failure_target) is None
    assert "synthetic graph failure" in failure_target.easy_mesh_scatter.sync_error

    addon.unregister()
    assert not hasattr(bpy.types.Object, "easy_mesh_scatter")

    print(
        "EASY_MESH_SCATTER_SMOKE_TEST_PASS "
        f"blue={blue_mask_count} mid={mid_mask_count} red={red_mask_count} "
        f"spaced={spaced_count}"
    )


if __name__ == "__main__":
    main()