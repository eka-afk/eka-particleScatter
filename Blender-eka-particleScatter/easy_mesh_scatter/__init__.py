import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty
from bpy.props import IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup


MODIFIER_NAME = "eka-particleScatter"
NODE_GROUP_NAME = "eka-particleScatter"
NODE_GROUP_TAG = "easy_mesh_scatter_node_group"
NODE_GROUP_VERSION = 2
DEFAULT_MASK_NAME = "Scatter Mask"


def _active_socket(sockets, *names):
    candidates = [socket for socket in sockets if socket.name in names]
    for socket in candidates:
        if socket.enabled and not socket.hide:
            return socket
    if candidates:
        return candidates[0]
    raise RuntimeError(f"Could not find node socket: {', '.join(names)}")


def _new_node(nodes, node_type, label, location):
    node = nodes.new(node_type)
    node.label = label
    node.name = label
    node.location = location
    return node


def _new_interface_socket(
    node_group,
    name,
    in_out,
    socket_type,
    *,
    default=None,
    minimum=None,
    maximum=None,
    subtype=None,
    description="",
):
    socket = node_group.interface.new_socket(
        name=name,
        in_out=in_out,
        socket_type=socket_type,
    )
    if default is not None and hasattr(socket, "default_value"):
        socket.default_value = default
    if minimum is not None and hasattr(socket, "min_value"):
        socket.min_value = minimum
    if maximum is not None and hasattr(socket, "max_value"):
        socket.max_value = maximum
    if subtype is not None and hasattr(socket, "subtype"):
        socket.subtype = subtype
    if description:
        socket.description = description
    if in_out == "INPUT" and socket_type != "NodeSocketGeometry":
        if hasattr(socket, "force_non_field"):
            socket.force_non_field = True
    return socket


def _build_node_group(node_group):
    node_group.nodes.clear()
    node_group.interface.clear()
    node_group.description = "Render-ready surface scattering with a vertex-group mask"
    if hasattr(node_group, "is_modifier"):
        node_group.is_modifier = True

    _new_interface_socket(node_group, "Geometry", "INPUT", "NodeSocketGeometry")
    _new_interface_socket(node_group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    _new_interface_socket(node_group, "Instance Object", "INPUT", "NodeSocketObject")
    _new_interface_socket(node_group, "Instance Collection", "INPUT", "NodeSocketCollection")
    _new_interface_socket(node_group, "Use Collection", "INPUT", "NodeSocketBool", default=False)
    _new_interface_socket(
        node_group,
        "Density",
        "INPUT",
        "NodeSocketFloat",
        default=10.0,
        minimum=0.0,
        maximum=1000000.0,
        description="Average number of points per square meter",
    )
    _new_interface_socket(
        node_group,
        "Viewport Scale",
        "INPUT",
        "NodeSocketFloat",
        default=1.0,
        minimum=0.0,
        maximum=1.0,
        subtype="FACTOR",
        description="Fraction of render density shown in the viewport",
    )
    _new_interface_socket(
        node_group,
        "Minimum Distance",
        "INPUT",
        "NodeSocketFloat",
        default=0.0,
        minimum=0.0,
        maximum=1000.0,
        subtype="DISTANCE",
        description="Minimum spacing between scattered points; zero allows natural clumping",
    )
    _new_interface_socket(
        node_group,
        "Seed",
        "INPUT",
        "NodeSocketInt",
        default=0,
        minimum=0,
        maximum=1000000,
    )
    _new_interface_socket(
        node_group,
        "Scale Min",
        "INPUT",
        "NodeSocketFloat",
        default=0.8,
        minimum=0.001,
        maximum=1000.0,
    )
    _new_interface_socket(
        node_group,
        "Scale Max",
        "INPUT",
        "NodeSocketFloat",
        default=1.2,
        minimum=0.001,
        maximum=1000.0,
    )
    _new_interface_socket(
        node_group,
        "Rotation Min",
        "INPUT",
        "NodeSocketVector",
        default=(0.0, 0.0, 0.0),
        minimum=-math.tau,
        maximum=math.tau,
        subtype="EULER",
    )
    _new_interface_socket(
        node_group,
        "Rotation Max",
        "INPUT",
        "NodeSocketVector",
        default=(0.0, 0.0, math.tau),
        minimum=-math.tau,
        maximum=math.tau,
        subtype="EULER",
    )
    _new_interface_socket(
        node_group,
        "Surface Offset",
        "INPUT",
        "NodeSocketFloat",
        default=0.0,
        minimum=-1000.0,
        maximum=1000.0,
        subtype="DISTANCE",
        description="Move points along the target surface normal",
    )
    _new_interface_socket(node_group, "Use Mask", "INPUT", "NodeSocketBool", default=False)
    _new_interface_socket(
        node_group,
        "Mask Name",
        "INPUT",
        "NodeSocketString",
        default=DEFAULT_MASK_NAME,
    )
    _new_interface_socket(node_group, "Invert Mask", "INPUT", "NodeSocketBool", default=False)
    _new_interface_socket(node_group, "Keep Surface", "INPUT", "NodeSocketBool", default=True)
    _new_interface_socket(node_group, "Realize Instances", "INPUT", "NodeSocketBool", default=False)

    nodes = node_group.nodes
    links = node_group.links

    group_input = _new_node(nodes, "NodeGroupInput", "Scatter Controls", (-1100, 120))
    group_output = _new_node(nodes, "NodeGroupOutput", "Scatter Output", (1180, 120))
    group_output.is_active_output = True

    object_info = _new_node(nodes, "GeometryNodeObjectInfo", "Object Source", (-1100, 520))
    if hasattr(object_info, "transform_space"):
        object_info.transform_space = "ORIGINAL"
    links.new(
        _active_socket(group_input.outputs, "Instance Object"),
        _active_socket(object_info.inputs, "Object"),
    )
    _active_socket(object_info.inputs, "As Instance").default_value = True

    collection_info = _new_node(nodes, "GeometryNodeCollectionInfo", "Collection Source", (-1100, 760))
    if hasattr(collection_info, "transform_space"):
        collection_info.transform_space = "ORIGINAL"
    links.new(
        _active_socket(group_input.outputs, "Instance Collection"),
        _active_socket(collection_info.inputs, "Collection"),
    )
    _active_socket(collection_info.inputs, "Separate Children").default_value = True
    _active_socket(collection_info.inputs, "Reset Children").default_value = True

    source_switch = _new_node(nodes, "GeometryNodeSwitch", "Choose Source", (-700, 600))
    source_switch.input_type = "GEOMETRY"
    links.new(
        _active_socket(group_input.outputs, "Use Collection"),
        _active_socket(source_switch.inputs, "Switch"),
    )
    links.new(
        _active_socket(object_info.outputs, "Geometry"),
        _active_socket(source_switch.inputs, "False"),
    )
    links.new(
        _active_socket(collection_info.outputs, "Instances"),
        _active_socket(source_switch.inputs, "True"),
    )

    named_mask = _new_node(nodes, "GeometryNodeInputNamedAttribute", "Read Painted Mask", (-1100, -460))
    named_mask.data_type = "FLOAT"
    links.new(
        _active_socket(group_input.outputs, "Mask Name"),
        _active_socket(named_mask.inputs, "Name"),
    )

    invert_math = _new_node(nodes, "ShaderNodeMath", "Invert Mask", (-840, -480))
    invert_math.operation = "SUBTRACT"
    _active_socket(invert_math.inputs, "Value").default_value = 1.0
    links.new(
        _active_socket(named_mask.outputs, "Attribute"),
        invert_math.inputs[1],
    )

    invert_switch = _new_node(nodes, "GeometryNodeSwitch", "Mask Direction", (-580, -400))
    invert_switch.input_type = "FLOAT"
    links.new(
        _active_socket(group_input.outputs, "Invert Mask"),
        _active_socket(invert_switch.inputs, "Switch"),
    )
    links.new(
        _active_socket(named_mask.outputs, "Attribute"),
        _active_socket(invert_switch.inputs, "False"),
    )
    links.new(
        _active_socket(invert_math.outputs, "Value"),
        _active_socket(invert_switch.inputs, "True"),
    )

    mask_switch = _new_node(nodes, "GeometryNodeSwitch", "Enable Mask", (-320, -300))
    mask_switch.input_type = "FLOAT"
    _active_socket(mask_switch.inputs, "False").default_value = 1.0
    links.new(
        _active_socket(group_input.outputs, "Use Mask"),
        _active_socket(mask_switch.inputs, "Switch"),
    )
    links.new(
        _active_socket(invert_switch.outputs, "Output"),
        _active_socket(mask_switch.inputs, "True"),
    )

    viewport_density = _new_node(nodes, "ShaderNodeMath", "Viewport Density", (-320, 80))
    viewport_density.operation = "MULTIPLY"
    links.new(
        _active_socket(group_input.outputs, "Density"),
        viewport_density.inputs[0],
    )
    links.new(
        _active_socket(group_input.outputs, "Viewport Scale"),
        viewport_density.inputs[1],
    )

    is_viewport = _new_node(nodes, "GeometryNodeIsViewport", "Viewport Evaluation", (-320, 220))
    density_switch = _new_node(nodes, "GeometryNodeSwitch", "Viewport or Render Density", (-40, 120))
    density_switch.input_type = "FLOAT"
    links.new(
        _active_socket(is_viewport.outputs, "Is Viewport"),
        _active_socket(density_switch.inputs, "Switch"),
    )
    links.new(
        _active_socket(group_input.outputs, "Density"),
        _active_socket(density_switch.inputs, "False"),
    )
    links.new(
        _active_socket(viewport_density.outputs, "Value"),
        _active_socket(density_switch.inputs, "True"),
    )

    distribute = _new_node(nodes, "GeometryNodeDistributePointsOnFaces", "Scatter Points", (180, 120))
    distribute.distribute_method = "POISSON"
    links.new(
        _active_socket(group_input.outputs, "Geometry"),
        _active_socket(distribute.inputs, "Mesh"),
    )
    links.new(
        _active_socket(group_input.outputs, "Minimum Distance"),
        _active_socket(distribute.inputs, "Distance Min"),
    )
    links.new(
        _active_socket(density_switch.outputs, "Output"),
        _active_socket(distribute.inputs, "Density Max"),
    )
    links.new(
        _active_socket(mask_switch.outputs, "Output"),
        _active_socket(distribute.inputs, "Density Factor", "Density"),
    )
    links.new(
        _active_socket(group_input.outputs, "Seed"),
        _active_socket(distribute.inputs, "Seed"),
    )

    random_scale = _new_node(nodes, "FunctionNodeRandomValue", "Random Uniform Scale", (-300, 700))
    random_scale.data_type = "FLOAT"
    links.new(
        _active_socket(group_input.outputs, "Scale Min"),
        _active_socket(random_scale.inputs, "Min"),
    )
    links.new(
        _active_socket(group_input.outputs, "Scale Max"),
        _active_socket(random_scale.inputs, "Max"),
    )
    links.new(
        _active_socket(group_input.outputs, "Seed"),
        _active_socket(random_scale.inputs, "Seed"),
    )

    combine_scale = _new_node(nodes, "ShaderNodeCombineXYZ", "Uniform XYZ Scale", (-20, 700))
    for axis in ("X", "Y", "Z"):
        links.new(
            _active_socket(random_scale.outputs, "Value"),
            _active_socket(combine_scale.inputs, axis),
        )

    normal_offset = _new_node(nodes, "ShaderNodeVectorMath", "Normal Surface Offset", (180, -180))
    normal_offset.operation = "SCALE"
    links.new(
        _active_socket(distribute.outputs, "Normal"),
        _active_socket(normal_offset.inputs, "Vector"),
    )
    links.new(
        _active_socket(group_input.outputs, "Surface Offset"),
        _active_socket(normal_offset.inputs, "Scale"),
    )

    set_position = _new_node(nodes, "GeometryNodeSetPosition", "Offset Scatter Points", (440, 20))
    links.new(
        _active_socket(distribute.outputs, "Points"),
        _active_socket(set_position.inputs, "Geometry"),
    )
    links.new(
        _active_socket(normal_offset.outputs, "Vector"),
        _active_socket(set_position.inputs, "Offset"),
    )

    instance_points = _new_node(nodes, "GeometryNodeInstanceOnPoints", "Instance on Points", (460, 280))
    links.new(
        _active_socket(set_position.outputs, "Geometry"),
        _active_socket(instance_points.inputs, "Points"),
    )
    links.new(
        _active_socket(source_switch.outputs, "Output"),
        _active_socket(instance_points.inputs, "Instance"),
    )
    links.new(
        _active_socket(group_input.outputs, "Use Collection"),
        _active_socket(instance_points.inputs, "Pick Instance"),
    )
    links.new(
        _active_socket(distribute.outputs, "Rotation"),
        _active_socket(instance_points.inputs, "Rotation"),
    )
    links.new(
        _active_socket(combine_scale.outputs, "Vector"),
        _active_socket(instance_points.inputs, "Scale"),
    )

    random_rotation = _new_node(nodes, "FunctionNodeRandomValue", "Random XYZ Rotation", (180, -500))
    random_rotation.data_type = "FLOAT_VECTOR"
    links.new(
        _active_socket(group_input.outputs, "Rotation Min"),
        _active_socket(random_rotation.inputs, "Min"),
    )
    links.new(
        _active_socket(group_input.outputs, "Rotation Max"),
        _active_socket(random_rotation.inputs, "Max"),
    )
    links.new(
        _active_socket(group_input.outputs, "Seed"),
        _active_socket(random_rotation.inputs, "Seed"),
    )

    rotate_instances = _new_node(nodes, "GeometryNodeRotateInstances", "Local Random Rotation", (700, 260))
    links.new(
        _active_socket(instance_points.outputs, "Instances"),
        _active_socket(rotate_instances.inputs, "Instances"),
    )
    links.new(
        _active_socket(random_rotation.outputs, "Value"),
        _active_socket(rotate_instances.inputs, "Rotation"),
    )
    _active_socket(rotate_instances.inputs, "Local Space").default_value = True

    realize = _new_node(nodes, "GeometryNodeRealizeInstances", "Optional Realize", (700, 20))
    links.new(
        _active_socket(rotate_instances.outputs, "Instances"),
        _active_socket(realize.inputs, "Geometry"),
    )

    realize_switch = _new_node(nodes, "GeometryNodeSwitch", "Realize for Output", (920, 200))
    realize_switch.input_type = "GEOMETRY"
    links.new(
        _active_socket(group_input.outputs, "Realize Instances"),
        _active_socket(realize_switch.inputs, "Switch"),
    )
    links.new(
        _active_socket(rotate_instances.outputs, "Instances"),
        _active_socket(realize_switch.inputs, "False"),
    )
    links.new(
        _active_socket(realize.outputs, "Geometry"),
        _active_socket(realize_switch.inputs, "True"),
    )

    surface_switch = _new_node(nodes, "GeometryNodeSwitch", "Keep Target Surface", (700, -180))
    surface_switch.input_type = "GEOMETRY"
    links.new(
        _active_socket(group_input.outputs, "Keep Surface"),
        _active_socket(surface_switch.inputs, "Switch"),
    )
    links.new(
        _active_socket(group_input.outputs, "Geometry"),
        _active_socket(surface_switch.inputs, "True"),
    )

    join_geometry = _new_node(nodes, "GeometryNodeJoinGeometry", "Surface and Scatter", (960, 20))
    links.new(
        _active_socket(surface_switch.outputs, "Output"),
        _active_socket(join_geometry.inputs, "Geometry"),
    )
    links.new(
        _active_socket(realize_switch.outputs, "Output"),
        _active_socket(join_geometry.inputs, "Geometry"),
    )
    links.new(
        _active_socket(join_geometry.outputs, "Geometry"),
        _active_socket(group_output.inputs, "Geometry"),
    )

    node_group[NODE_GROUP_TAG] = NODE_GROUP_VERSION


def _ensure_node_group():
    for node_group in bpy.data.node_groups:
        if (
            node_group.bl_idname == "GeometryNodeTree"
            and node_group.get(NODE_GROUP_TAG) == NODE_GROUP_VERSION
        ):
            return node_group

    node_group = bpy.data.node_groups.new(NODE_GROUP_NAME, "GeometryNodeTree")
    try:
        _build_node_group(node_group)
    except Exception:
        bpy.data.node_groups.remove(node_group)
        raise
    return node_group


def _is_scatter_node_group(node_group):
    return (
        node_group is not None
        and node_group.bl_idname == "GeometryNodeTree"
        and NODE_GROUP_TAG in node_group
    )


def _find_scatter_modifier(target):
    if target is None:
        return None
    for modifier in target.modifiers:
        if (
            modifier.type == "NODES"
            and _is_scatter_node_group(modifier.node_group)
        ):
            return modifier
    return None


def _interface_input(node_group, name):
    for item in node_group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == name:
            return item
    raise RuntimeError(f"Missing eka-particleScatter input: {name}")


def _set_modifier_input(modifier, name, value):
    socket = _interface_input(modifier.node_group, name)
    if getattr(modifier, "properties", None) is not None:
        input_wrapper = getattr(modifier.properties.inputs, socket.identifier)
        input_wrapper.value = value
    else:
        modifier[socket.identifier] = value


def _sync_modifier(target):
    modifier = _find_scatter_modifier(target)
    if modifier is None or modifier.node_group is None:
        return ""

    if modifier.node_group.get(NODE_GROUP_TAG) != NODE_GROUP_VERSION:
        return "Click Upgrade Scatter to update this setup"

    settings = target.easy_mesh_scatter
    rotation_min = tuple(
        min(minimum, maximum)
        for minimum, maximum in zip(settings.rotation_min, settings.rotation_max)
    )
    rotation_max = tuple(
        max(minimum, maximum)
        for minimum, maximum in zip(settings.rotation_min, settings.rotation_max)
    )

    values = {
        "Instance Object": settings.source_object,
        "Instance Collection": settings.source_collection,
        "Use Collection": settings.source_type == "COLLECTION",
        "Density": settings.density,
        "Viewport Scale": settings.viewport_percentage / 100.0,
        "Minimum Distance": settings.minimum_distance,
        "Seed": settings.seed,
        "Scale Min": min(settings.scale_min, settings.scale_max),
        "Scale Max": max(settings.scale_min, settings.scale_max),
        "Rotation Min": rotation_min,
        "Rotation Max": rotation_max,
        "Surface Offset": settings.surface_offset,
        "Use Mask": settings.use_mask,
        "Mask Name": settings.mask_name,
        "Invert Mask": settings.invert_mask,
        "Keep Surface": settings.keep_surface,
        "Realize Instances": settings.realize_instances,
    }
    for name, value in values.items():
        _set_modifier_input(modifier, name, value)
    target.update_tag()
    return ""


def _settings_changed(settings, _context):
    target = settings.id_data
    if not isinstance(target, bpy.types.Object):
        return
    try:
        settings.sync_error = _sync_modifier(target)
    except (KeyError, RuntimeError, TypeError, ValueError) as error:
        settings.sync_error = f"Update failed: {error}"
        print(f"eka-particleScatter {settings.sync_error}")


def _poll_source_object(settings, candidate):
    return candidate != settings.id_data


class EASYSCATTER_PG_settings(PropertyGroup):
    sync_error: StringProperty(options={"HIDDEN"})
    show_advanced_distribution: BoolProperty(
        name="Advanced Distribution",
        description="Show viewport performance, spacing, and surface placement controls",
        default=False,
    )
    source_type: EnumProperty(
        name="Source Type",
        items=(
            ("OBJECT", "Object", "Scatter one object", "OBJECT_DATA", 0),
            ("COLLECTION", "Collection", "Randomly scatter objects from a collection", "OUTLINER_COLLECTION", 1),
        ),
        default="OBJECT",
        update=_settings_changed,
    )
    source_object: PointerProperty(
        name="Object",
        description="Object to instance on the target surface",
        type=bpy.types.Object,
        poll=_poll_source_object,
        update=_settings_changed,
    )
    source_collection: PointerProperty(
        name="Collection",
        description="Collection whose child objects are randomly instanced",
        type=bpy.types.Collection,
        update=_settings_changed,
    )
    density: FloatProperty(
        name="Density",
        description="Average points per square meter before masking",
        default=10.0,
        min=0.0,
        soft_max=10000.0,
        update=_settings_changed,
    )
    viewport_percentage: FloatProperty(
        name="Viewport Density",
        description="Percentage of the full render density shown while working in the viewport",
        default=100.0,
        min=0.0,
        max=100.0,
        subtype="PERCENTAGE",
        update=_settings_changed,
    )
    minimum_distance: FloatProperty(
        name="Minimum Distance",
        description="Minimum spacing between points; increase this to reduce clumps and overlap",
        default=0.0,
        min=0.0,
        soft_max=10.0,
        subtype="DISTANCE",
        unit="LENGTH",
        update=_settings_changed,
    )
    seed: IntProperty(
        name="Seed",
        description="Change the random placement, scale, and rotation",
        default=0,
        min=0,
        max=1000000,
        update=_settings_changed,
    )
    scale_min: FloatProperty(
        name="Minimum",
        description="Smallest uniform instance scale",
        default=0.8,
        min=0.001,
        soft_max=10.0,
        update=_settings_changed,
    )
    scale_max: FloatProperty(
        name="Maximum",
        description="Largest uniform instance scale",
        default=1.2,
        min=0.001,
        soft_max=10.0,
        update=_settings_changed,
    )
    rotation_min: FloatVectorProperty(
        name="Minimum",
        description="Minimum local rotation on the X, Y, and Z axes",
        size=3,
        subtype="EULER",
        unit="ROTATION",
        default=(0.0, 0.0, 0.0),
        soft_min=-math.tau,
        soft_max=math.tau,
        update=_settings_changed,
    )
    rotation_max: FloatVectorProperty(
        name="Maximum",
        description="Maximum local rotation on the X, Y, and Z axes",
        size=3,
        subtype="EULER",
        unit="ROTATION",
        default=(0.0, 0.0, math.tau),
        soft_min=-math.tau,
        soft_max=math.tau,
        update=_settings_changed,
    )
    surface_offset: FloatProperty(
        name="Surface Offset",
        description="Move instances outward or inward along the target surface normal",
        default=0.0,
        soft_min=-10.0,
        soft_max=10.0,
        subtype="DISTANCE",
        unit="LENGTH",
        update=_settings_changed,
    )
    use_mask: BoolProperty(
        name="Use Density Mask",
        description="Multiply point density by vertex weights: blue is 0 and red is 1",
        default=False,
        update=_settings_changed,
    )
    mask_name: StringProperty(
        name="Vertex Group",
        description="Vertex group used as the scatter density mask",
        default=DEFAULT_MASK_NAME,
        update=_settings_changed,
    )
    invert_mask: BoolProperty(
        name="Invert",
        description="Scatter in the unpainted area instead",
        default=False,
        update=_settings_changed,
    )
    mask_edit_weight: FloatProperty(
        name="Density Weight",
        description="Weight for selected vertices: 0 is blue with no density, 1 is red with full density",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    keep_surface: BoolProperty(
        name="Keep Surface",
        description="Include the original target mesh in the modifier output",
        default=True,
        update=_settings_changed,
    )
    realize_instances: BoolProperty(
        name="Realize Instances",
        description="Convert instances to geometry; leave disabled for faster rendering",
        default=False,
        update=_settings_changed,
    )


def _source_is_valid(target, settings):
    if settings.source_type == "OBJECT":
        if settings.source_object is None:
            return False, "Choose an object to scatter"
        if settings.source_object == target:
            return False, "The target mesh cannot scatter itself"
        return True, ""

    if settings.source_collection is None:
        return False, "Choose a collection to scatter"
    if settings.source_collection.all_objects.get(target.name) == target:
        return False, "Move the target mesh outside the source collection"
    if len(settings.source_collection.all_objects) == 0:
        return False, "The source collection is empty"
    return True, ""


def _ensure_mask(target, settings):
    name = settings.mask_name.strip() or DEFAULT_MASK_NAME
    vertex_group = target.vertex_groups.get(name)
    if vertex_group is None:
        vertex_group = target.vertex_groups.new(name=name)
    if settings.mask_name != vertex_group.name:
        settings.mask_name = vertex_group.name
    target.vertex_groups.active_index = vertex_group.index
    return vertex_group


def _show_edit_mask_weights(context):
    if context.screen is None:
        return
    for area in context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.overlay.show_weight = True


class EASYSCATTER_OT_add_or_update(Operator):
    bl_idname = "easy_scatter.add_or_update"
    bl_label = "Add Scatter"
    bl_description = "Add or update the Geometry Nodes scatter modifier"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        target = context.object
        settings = target.easy_mesh_scatter
        valid, message = _source_is_valid(target, settings)
        if not valid:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        if settings.use_mask:
            _ensure_mask(target, settings)

        modifier = None
        created_modifier = False
        modifier = _find_scatter_modifier(target)
        try:
            node_group = _ensure_node_group()
            if modifier is None:
                modifier = target.modifiers.new(MODIFIER_NAME, "NODES")
                created_modifier = True
            modifier.node_group = node_group
            modifier.show_viewport = True
            modifier.show_render = True
            modifier.show_in_editmode = True
            settings.sync_error = _sync_modifier(target)
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            if created_modifier and modifier is not None:
                target.modifiers.remove(modifier)
            settings.sync_error = f"Setup failed: {error}"
            self.report({"ERROR"}, settings.sync_error)
            return {"CANCELLED"}

        self.report({"INFO"}, "eka-particleScatter is ready")
        return {"FINISHED"}


class EASYSCATTER_OT_remove(Operator):
    bl_idname = "easy_scatter.remove"
    bl_label = "Remove Scatter"
    bl_description = "Remove the eka-particleScatter modifier from this object"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _find_scatter_modifier(context.object) is not None

    def execute(self, context):
        modifier = _find_scatter_modifier(context.object)
        context.object.modifiers.remove(modifier)
        context.object.easy_mesh_scatter.sync_error = ""
        self.report({"INFO"}, "Scatter modifier removed")
        return {"FINISHED"}


class EASYSCATTER_OT_next_seed(Operator):
    bl_idname = "easy_scatter.next_seed"
    bl_label = "New Seed"
    bl_description = "Advance to a new deterministic scatter pattern"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        settings = context.object.easy_mesh_scatter
        settings.seed = (settings.seed + 1) % 1000001
        return {"FINISHED"}


class EASYSCATTER_OT_toggle_mask_paint(Operator):
    bl_idname = "easy_scatter.toggle_mask_paint"
    bl_label = "Paint Density"
    bl_description = "Paint the density mask: blue is no density and red is full density"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        target = context.object
        if target.mode == "WEIGHT_PAINT":
            bpy.ops.object.mode_set(mode="OBJECT")
            return {"FINISHED"}

        settings = target.easy_mesh_scatter
        settings.use_mask = True
        _ensure_mask(target, settings)
        if target.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
        return {"FINISHED"}


class EASYSCATTER_OT_toggle_mask_edit(Operator):
    bl_idname = "easy_scatter.toggle_mask_edit"
    bl_label = "Edit Density Weights"
    bl_description = "Edit the density mask with selected mesh vertices and weight colors"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        target = context.object
        if target.mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
            return {"FINISHED"}

        settings = target.easy_mesh_scatter
        settings.use_mask = True
        if target.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        _ensure_mask(target, settings)
        bpy.ops.object.mode_set(mode="EDIT")
        _show_edit_mask_weights(context)
        return {"FINISHED"}


class EASYSCATTER_OT_assign_mask_weight(Operator):
    bl_idname = "easy_scatter.assign_mask_weight"
    bl_label = "Assign Density Weight"
    bl_description = "Assign a density weight to the selected mesh vertices"
    bl_options = {"REGISTER", "UNDO"}

    weight: FloatProperty(
        name="Weight",
        default=-1.0,
        min=-1.0,
        max=1.0,
        options={"HIDDEN", "SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return (
            context.object is not None
            and context.object.type == "MESH"
            and context.object.mode == "EDIT"
        )

    def execute(self, context):
        target = context.object
        settings = target.easy_mesh_scatter
        vertex_group = _ensure_mask(target, settings)

        edit_mesh = bmesh.from_edit_mesh(target.data)
        selected_indices = [vertex.index for vertex in edit_mesh.verts if vertex.select]
        if not selected_indices:
            self.report({"WARNING"}, "Select at least one vertex, edge, or face")
            return {"CANCELLED"}

        weight = settings.mask_edit_weight if self.weight < 0.0 else self.weight
        bpy.ops.object.mode_set(mode="OBJECT")
        try:
            vertex_group.add(selected_indices, weight, "REPLACE")
        finally:
            bpy.ops.object.mode_set(mode="EDIT")

        _show_edit_mask_weights(context)
        target.data.update()
        target.update_tag()
        self.report({"INFO"}, f"Assigned density weight {weight:.2f}")
        return {"FINISHED"}


class EASYSCATTER_PT_main(Panel):
    bl_label = "eka-particleScatter"
    bl_idname = "EASYSCATTER_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "eka-particleScatter"

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        target = context.object
        settings = target.easy_mesh_scatter
        modifier = _find_scatter_modifier(target)

        source_box = layout.box()
        source_box.label(text="Instance Source", icon="OUTLINER_OB_GROUP_INSTANCE")
        source_box.prop(settings, "source_type", expand=True)
        if settings.source_type == "OBJECT":
            source_box.prop(settings, "source_object")
        else:
            source_box.prop(settings, "source_collection")

        amount_box = layout.box()
        amount_box.label(text="Distribution", icon="PARTICLES")
        amount_box.prop(settings, "density")
        seed_row = amount_box.row(align=True)
        seed_row.prop(settings, "seed")
        seed_row.operator("easy_scatter.next_seed", text="", icon="FILE_REFRESH")
        advanced_row = amount_box.row()
        advanced_icon = "TRIA_DOWN" if settings.show_advanced_distribution else "TRIA_RIGHT"
        advanced_row.prop(
            settings,
            "show_advanced_distribution",
            text="Advanced",
            icon=advanced_icon,
            emboss=False,
        )
        if settings.show_advanced_distribution:
            amount_box.prop(settings, "viewport_percentage")
            amount_box.prop(settings, "minimum_distance")
            amount_box.prop(settings, "surface_offset")

        scale_box = layout.box()
        scale_box.label(text="Random Scale", icon="FULLSCREEN_ENTER")
        scale_box.prop(settings, "scale_min")
        scale_box.prop(settings, "scale_max")

        rotation_box = layout.box()
        rotation_box.label(text="Local Random Rotation", icon="ORIENTATION_GIMBAL")
        rotation_box.prop(settings, "rotation_min")
        rotation_box.prop(settings, "rotation_max")

        mask_box = layout.box()
        mask_box.label(text="Density Mask", icon="WPAINT_HLT")
        mask_box.prop(settings, "use_mask")
        if settings.use_mask:
            mask_box.prop_search(settings, "mask_name", target, "vertex_groups", text="Vertex Group")
            mask_box.prop(settings, "invert_mask")
            if target.mode == "WEIGHT_PAINT":
                mask_box.operator("easy_scatter.toggle_mask_paint", text="Finish Painting", icon="CHECKMARK")
            elif target.mode == "EDIT":
                mask_box.prop(settings, "mask_edit_weight", slider=True)
                mask_box.operator(
                    "easy_scatter.assign_mask_weight",
                    text="Assign to Selected",
                    icon="GROUP_VERTEX",
                )
                presets = mask_box.row(align=True)
                presets.operator("easy_scatter.assign_mask_weight", text="Blue 0").weight = 0.0
                presets.operator("easy_scatter.assign_mask_weight", text="Mid 0.5").weight = 0.5
                presets.operator("easy_scatter.assign_mask_weight", text="Red 1").weight = 1.0
                mask_box.operator("easy_scatter.toggle_mask_edit", text="Finish Editing", icon="CHECKMARK")
            else:
                modes = mask_box.row(align=True)
                modes.operator("easy_scatter.toggle_mask_paint", text="Paint Density", icon="BRUSH_DATA")
                modes.operator("easy_scatter.toggle_mask_edit", text="Edit Weights", icon="EDITMODE_HLT")

        output_box = layout.box()
        output_box.label(text="Output", icon="GEOMETRY_NODES")
        output_box.prop(settings, "keep_surface")
        output_box.prop(settings, "realize_instances")
        if settings.realize_instances:
            warning = output_box.row()
            warning.alert = True
            warning.label(text="Realizing dense scatters can use significant memory", icon="ERROR")
        if modifier is not None:
            visibility = output_box.row(align=True)
            visibility.prop(modifier, "show_viewport", text="Viewport", toggle=True)
            visibility.prop(modifier, "show_render", text="Render", toggle=True)

        valid, message = _source_is_valid(target, settings)
        if not valid:
            warning = layout.row()
            warning.alert = True
            warning.label(text=message, icon="ERROR")

        if settings.sync_error:
            sync_warning = layout.row()
            sync_warning.alert = True
            sync_warning.label(text=settings.sync_error, icon="ERROR")

        action = layout.row(align=True)
        action.scale_y = 1.3
        needs_upgrade = (
            modifier is not None
            and modifier.node_group.get(NODE_GROUP_TAG) != NODE_GROUP_VERSION
        )
        button_label = "Upgrade Scatter" if needs_upgrade else "Update Scatter" if modifier else "Add Scatter"
        button_icon = "FILE_REFRESH" if modifier is not None else "ADD"
        action.operator("easy_scatter.add_or_update", text=button_label, icon=button_icon)
        if modifier is not None:
            action.operator("easy_scatter.remove", text="", icon="TRASH")


CLASSES = (
    EASYSCATTER_PG_settings,
    EASYSCATTER_OT_add_or_update,
    EASYSCATTER_OT_remove,
    EASYSCATTER_OT_next_seed,
    EASYSCATTER_OT_toggle_mask_paint,
    EASYSCATTER_OT_toggle_mask_edit,
    EASYSCATTER_OT_assign_mask_weight,
    EASYSCATTER_PT_main,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.easy_mesh_scatter = PointerProperty(type=EASYSCATTER_PG_settings)


def unregister():
    del bpy.types.Object.easy_mesh_scatter
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()