bl_info = {
    "name": "SeanIXz Pro 分件助手",
    "author": "SeanIXz / ChatGPT",
    "version": (1, 5, 9),
    "blender": (5, 1, 0),
    "location": "View3D > N 面板 > SeanIXz Pro",
    "description": "商业化包装的 SeanIXz Pro 分件助手：完整分件流程、可打印活动关节一体式分离切刀、独立关节切刀集合与显隐、球头连接件、双球头/双转轴、布尔与收尾处理。",
    "category": "Object",
}

import math
import bpy
import bmesh
from bpy.app.handlers import persistent
from mathutils import Vector

ADDON_NAME = "SeanIXz Pro 分件助手"
DEFAULT_MM_TO_BU = 0.001
ADDON_VERSION_TEXT = "v1.5.9 Pro"
ADDON_SUBTITLE = "3D打印商业级分件流程工具"
ADDON_COPYRIGHT = "(c) SeanIXz"

BOOL_MOD_PREFIX = "SeanIXz_Pro_Bool_"
BOOL_RAW_MOD_PREFIX = "SeanIXz_Pro_RawBool_"
TEMP_SOLID_CUTTER_TAG = "_SeanIXz_Temp_Boolean_Cutter"
CUTTER_PREVIEW_SOLIDIFY = "SeanIXz_Pro_切刀实体化预览"
BACKUP_COLLECTION_NAME = "SeanIXz_Pro_Backups"
CUTTER_COLLECTION_NAME = "SeanIXz_Pro_Cutters"
JOINT_COLLECTION_NAME = "SeanIXz_Pro_Joint_Pairs"
JOINT_CUTTER_COLLECTION_NAME = "SeanIXz_Pro_Joint_Cutters"
ND_PREVIEW_COLLECTION = "SeanIXz_Pro_非破坏拆件预览"
ND_PREVIEW_NODE_GROUP = "SeanIXz_Pro_按孤岛预览"
ND_PREVIEW_MODIFIER = "SeanIXz_Pro_非破坏拆件预览"
ND_PREVIEW_OBJECT_TAG = "seanixz_pro_nondestructive_preview"
ND_PREVIEW_SOURCE_TAG = "seanixz_pro_preview_source"
ND_PREVIEW_INDEX_TAG = "seanixz_pro_preview_island_index"
ND_PREVIEW_NODE_VERSION = 6
BACKUP_OBJECT_TAG = "seanixz_pro_backup_object"
BACKUP_EYE_POLL_INTERVAL = 0.25

# 全局撤销恢复 Scene 属性、对象和修改器时，禁止预览回调再修改数据。
_SEANIXZ_PRO_UNDO_IN_PROGRESS = False
_SEANIXZ_PRO_BACKUP_EYE_SYNC_ACTIVE = False

# -----------------------------------------------------------------------------
# 基础工具
# -----------------------------------------------------------------------------

def mesh_objects_from_selection(context):
    return [obj for obj in context.selected_objects if obj and obj.type == 'MESH']

def active_mesh_object(context):
    obj = context.active_object
    return obj if obj and obj.type == 'MESH' else None

def show_popup(message="", title="提示", icon='INFO'):
    def draw(self, context):
        for line in str(message).split('\n'):
            self.layout.label(text=line)

    try:
        bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)
    except Exception:
        pass

def ensure_object_mode():
    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        try:
            if bpy.ops.object.mode_set.poll():
                bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

def ensure_edit_mode(obj=None):
    try:
        if obj is not None and bpy.context.view_layer.objects.active != obj:
            bpy.context.view_layer.objects.active = obj

        if bpy.context.object and bpy.context.object.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
    except Exception:
        pass

def mm_to_bu(scene):
    try:
        scale_length = scene.unit_settings.scale_length
        if scale_length > 0:
            return 0.001 / scale_length
    except Exception:
        pass

    return DEFAULT_MM_TO_BU

def bu_to_mm(scene, value_bu):
    """Convert Blender units back to millimeters using the current scene unit scale."""
    try:
        unit = mm_to_bu(scene)
        if unit > 0:
            return value_bu / unit
    except Exception:
        pass
    return value_bu / DEFAULT_MM_TO_BU

def set_view_clip_start_mm(context, clip_start_mm=1.0):
    """Set 3D View clipping start to a millimeter value for easier small-detail modeling."""
    scene = getattr(context, "scene", None)
    clip_start_bu = max(float(clip_start_mm) * mm_to_bu(scene), 1e-6)
    changed = 0

    try:
        screen = context.screen
        if screen:
            for area in screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        try:
                            space.clip_start = clip_start_bu
                            changed += 1
                        except Exception:
                            pass
    except Exception:
        pass

    return changed, clip_start_bu

def evaluated_face_count(context, obj):
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = None

    try:
        mesh = eval_obj.to_mesh()
        return len(mesh.polygons)
    except Exception:
        return len(obj.data.polygons) if obj and obj.data else 0
    finally:
        if mesh:
            try:
                eval_obj.to_mesh_clear()
            except Exception:
                pass

def selected_face_count(context, evaluated=False):
    total = 0

    for obj in mesh_objects_from_selection(context):
        if evaluated:
            total += evaluated_face_count(context, obj)
        else:
            total += len(obj.data.polygons)

    return total

def ensure_decimate_percent_compatible(scene):
    """兼容 v1.3.0 以前保存的精简比例。

    旧版本可能把 10% 保存为 0.1；新版界面直接显示 10%。
    这里只在真正有 scene 上下文时处理，避免 Blender 启用插件时的 _RestrictData 报错。
    """
    if not scene:
        return

    try:
        if bool(scene.get("_seanixz_pro_decimate_percent_migrated_v132", False)):
            return

        value = float(scene.seanixz_pro_decimate_percent)

        if 0.0 < value <= 1.0:
            scene.seanixz_pro_decimate_percent = value * 100.0

        scene["_seanixz_pro_decimate_percent_migrated_v132"] = True
    except Exception:
        pass

def get_or_create_collection(name):
    coll = bpy.data.collections.get(name)

    if not coll:
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)

    return coll

def move_to_collection(obj, coll_name):
    coll = get_or_create_collection(coll_name)

    if obj.name not in coll.objects:
        coll.objects.link(obj)

    for c in list(obj.users_collection):
        if c != coll:
            try:
                c.objects.unlink(obj)
            except Exception:
                pass

def duplicate_backup(obj, suffix="_SeanIXz_Backup"):
    backup = obj.copy()
    backup.data = obj.data.copy()
    backup.name = obj.name + suffix

    backup_collection = get_or_create_collection(BACKUP_COLLECTION_NAME)
    backup_collection.hide_viewport = False
    backup_collection.objects.link(backup)
    backup[BACKUP_OBJECT_TAG] = True

    # 小眼睛仍是用户唯一需要点击的开关；后台同时暂停隐藏备份的
    # 依赖图求值，轮询器会在小眼睛打开后自动解除暂停。
    backup.hide_render = True

    try:
        backup.hide_set(True)
    except Exception:
        pass

    backup.hide_viewport = True

    return backup


def managed_backup_eye_object(obj):
    if not obj or bool(obj.get("seanixz_pro_temp_boolean_cutter", False)):
        return False

    if bool(obj.get(BACKUP_OBJECT_TAG, False)):
        return True

    return any(
        collection and collection.name in {BACKUP_COLLECTION_NAME, CUTTER_COLLECTION_NAME}
        for collection in obj.users_collection
    )


def backup_eye_sync_blocked():
    if _SEANIXZ_PRO_UNDO_IN_PROGRESS:
        return True

    try:
        return bool(bpy.context.window_manager.is_interface_locked)
    except Exception:
        return False


def unlock_backup_eye_control():
    """让小眼睛控制显示，同时让眼睛关闭的备份停止后台求值。"""
    global _SEANIXZ_PRO_BACKUP_EYE_SYNC_ACTIVE

    if _SEANIXZ_PRO_BACKUP_EYE_SYNC_ACTIVE or backup_eye_sync_blocked():
        return 0

    _SEANIXZ_PRO_BACKUP_EYE_SYNC_ACTIVE = True
    changed = 0

    try:
        for collection_name in (BACKUP_COLLECTION_NAME, CUTTER_COLLECTION_NAME):
            collection = bpy.data.collections.get(collection_name)

            if not collection:
                continue

            collection.hide_viewport = False

            for obj in collection.objects:
                if not managed_backup_eye_object(obj):
                    continue

                try:
                    eye_hidden = bool(obj.hide_get())
                except Exception:
                    eye_hidden = bool(obj.hide_viewport)

                if bool(obj.hide_viewport) != eye_hidden:
                    obj.hide_viewport = eye_hidden
                    changed += 1

                obj.hide_render = True
    finally:
        _SEANIXZ_PRO_BACKUP_EYE_SYNC_ACTIVE = False

    return changed


def backup_eye_visibility_poller():
    """低频检查小眼睛状态，避免在依赖图回调中遍历备份。"""
    try:
        unlock_backup_eye_control()
    except Exception:
        pass

    return BACKUP_EYE_POLL_INTERVAL


@persistent
def seanixz_pro_backup_eye_load_post(_dummy):
    unlock_backup_eye_control()


def apply_modifier(context, obj, modifier_name):
    ensure_object_mode()

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj

    try:
        bpy.ops.object.modifier_apply(modifier=modifier_name)
        return True
    except Exception as exc:
        print(f"SeanIXz apply modifier failed: {modifier_name}: {exc}")
        return False

def configure_boolean_modifier(mod, scene, operation=None, cutter=None):
    if operation:
        try:
            mod.operation = operation
        except Exception:
            pass

    try:
        mod.operand_type = 'OBJECT'
    except Exception:
        pass

    if cutter:
        try:
            mod.object = cutter
        except Exception:
            pass

    try:
        mod.solver = scene.seanixz_pro_boolean_solver
    except Exception:
        pass

    try:
        # 限位车轴母槽由轴孔、入口槽和圆弧轨道构成，内部存在有意的重叠体。
        # 对该专用切刀自动开启自相交求解，避免默认布尔把目标整体清空。
        needs_self_intersection = bool(
            cutter
            and cutter.get("seanixz_pro_joint_type") == 'LIMITED_AXLE'
            and cutter.get("seanixz_pro_joint_role") == 'FEMALE_CUTTER'
        )
        mod.use_self = scene.seanixz_pro_boolean_use_self or needs_self_intersection
    except Exception:
        pass

    try:
        mod.use_hole_tolerant = scene.seanixz_pro_boolean_hole_tolerant
    except Exception:
        pass

def recalc_mesh_normals(obj):
    if not obj or obj.type != 'MESH':
        return

    bm = bmesh.new()

    try:
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()

        if bm.faces:
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

        bm.to_mesh(obj.data)
        obj.data.update()
    except Exception:
        pass
    finally:
        bm.free()

def remove_loose_and_interior(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    before_v = len(bm.verts)
    before_f = len(bm.faces)

    loose_edges = [e for e in bm.edges if len(e.link_faces) == 0]
    if loose_edges:
        bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')

    loose_verts = [v for v in bm.verts if len(v.link_edges) == 0]
    if loose_verts:
        bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    degenerate = [f for f in bm.faces if f.calc_area() <= 1e-14]
    if degenerate:
        bmesh.ops.delete(bm, geom=degenerate, context='FACES')

    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

    after_v = len(obj.data.vertices)
    after_f = len(obj.data.polygons)

    return before_v - after_v, before_f - after_f


def remove_floating_face_islands(obj):
    """Remove detached face islands and keep the largest connected face island.

    This is useful for cutters/boolean helpers that accidentally contain tiny
    floating cap faces or leftover face sheets. It keeps the largest island by
    total face area first, then by face count.
    """
    if not obj or obj.type != 'MESH' or not obj.data:
        return 0, 0

    bm = bmesh.new()
    deleted_faces = 0
    deleted_verts = 0

    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        if len(bm.faces) <= 1:
            bm.to_mesh(obj.data)
            obj.data.update()
            return 0, 0

        unvisited = set(bm.faces)
        islands = []

        while unvisited:
            start = unvisited.pop()
            stack = [start]
            faces = [start]
            area = 0.0

            while stack:
                face = stack.pop()
                try:
                    area += face.calc_area()
                except Exception:
                    pass

                for edge in face.edges:
                    for linked_face in edge.link_faces:
                        if linked_face in unvisited:
                            unvisited.remove(linked_face)
                            stack.append(linked_face)
                            faces.append(linked_face)

            islands.append((area, len(faces), faces))

        if len(islands) <= 1:
            bm.to_mesh(obj.data)
            obj.data.update()
            return 0, 0

        islands.sort(key=lambda item: (item[0], item[1]), reverse=True)
        delete_faces = []

        for _area, _count, faces in islands[1:]:
            delete_faces.extend([face for face in faces if face.is_valid])

        deleted_faces = len(delete_faces)

        if delete_faces:
            bmesh.ops.delete(bm, geom=delete_faces, context='FACES')

        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        loose_edges = [edge for edge in bm.edges if edge.is_valid and len(edge.link_faces) == 0]
        if loose_edges:
            bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')

        loose_verts = [vert for vert in bm.verts if vert.is_valid and len(vert.link_edges) == 0 and len(vert.link_faces) == 0]
        deleted_verts = len(loose_verts)
        if loose_verts:
            bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')

        if bm.faces:
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

        bm.to_mesh(obj.data)
        obj.data.update()
        return deleted_faces, deleted_verts
    except Exception:
        try:
            bm.to_mesh(obj.data)
            obj.data.update()
        except Exception:
            pass
        return 0, 0
    finally:
        bm.free()

def cleanup_boolean_preview_objects(context, target=None):
    if target and target.type == 'MESH':
        for mod in list(target.modifiers):
            if mod.type == 'BOOLEAN' and (mod.name.startswith(BOOL_MOD_PREFIX) or mod.name.startswith(BOOL_RAW_MOD_PREFIX)):
                try:
                    target.modifiers.remove(mod)
                except Exception:
                    pass

    for obj in list(bpy.data.objects):
        if not obj or obj.type != 'MESH':
            continue

        if bool(obj.get("seanixz_pro_temp_boolean_cutter", False)):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass

def cleanup_temp_boolean_cutters():
    for obj in list(bpy.data.objects):
        if obj and obj.type == 'MESH' and bool(obj.get("seanixz_pro_temp_boolean_cutter", False)):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass

def get_selected_real_cutters(context, target):
    cutters = []

    for obj in mesh_objects_from_selection(context):
        if obj == target:
            continue

        if bool(obj.get("seanixz_pro_temp_boolean_cutter", False)):
            continue

        cutters.append(obj)

    return cutters

def set_cutter_display_mode(cutter, mode='WIRE'):
    if not cutter or cutter.type != 'MESH':
        return

    move_to_collection(cutter, CUTTER_COLLECTION_NAME)

    if mode == 'PLANE':
        cutter.display_type = 'TEXTURED'
        cutter.show_in_front = False

        # 平面模式用于观察切刀面与模型的真实相交位置，避免实体化预览干扰判断。
        mod = cutter.modifiers.get(CUTTER_PREVIEW_SOLIDIFY)
        if mod:
            try:
                mod.show_viewport = False
            except Exception:
                pass
    else:
        cutter.display_type = 'WIRE'
        cutter.show_in_front = True

    cutter.hide_viewport = False
    cutter.hide_render = True

    try:
        cutter.hide_set(False)
    except Exception:
        pass

def setup_cutter_display(cutter):
    set_cutter_display_mode(cutter, 'WIRE')


def configure_cutter_solidify_modifier(mod, thickness_bu, show_viewport=True):
    """Configure Solidify for cutter boolean use.

    Default is Complex / Fixed thickness when Blender exposes those properties.
    Attribute names differ slightly across Blender versions, so every advanced
    setting is applied defensively.
    """
    if not mod:
        return

    try:
        mod.thickness = thickness_bu
        mod.offset = 0.0
        mod.show_viewport = show_viewport
        mod.show_render = False
    except Exception:
        pass

    # Solidify mode: Complex / Non-Manifold is more stable for messy cutter faces.
    for attr_name in ("mode", "solidify_mode"):
        try:
            setattr(mod, attr_name, 'NON_MANIFOLD')
            break
        except Exception:
            pass

    # Thickness mode: Fixed. Blender versions may expose different property names.
    for attr_name in ("nonmanifold_thickness_mode", "thickness_mode"):
        try:
            setattr(mod, attr_name, 'FIXED')
            break
        except Exception:
            pass

    try:
        mod.use_even_offset = True
    except Exception:
        pass

    try:
        mod.use_quality_normals = True
    except Exception:
        pass

    try:
        mod.use_rim_only = False
    except Exception:
        pass

def ensure_cutter_preview_solidify(cutter, scene):
    if not cutter or cutter.type != 'MESH':
        return None

    thickness_mm = abs(scene.seanixz_pro_cutter_tolerance_mm)

    if thickness_mm <= 0:
        thickness_mm = 0.001

    thickness_bu = thickness_mm * mm_to_bu(scene)

    mod = cutter.modifiers.get(CUTTER_PREVIEW_SOLIDIFY)

    if not mod:
        mod = cutter.modifiers.new(CUTTER_PREVIEW_SOLIDIFY, 'SOLIDIFY')

    configure_cutter_solidify_modifier(mod, thickness_bu, show_viewport=True)

    return mod

def create_temp_boolean_cutter(context, cutter, scene):
    if not cutter or cutter.type != 'MESH':
        return None

    thickness_mm = abs(scene.seanixz_pro_cutter_tolerance_mm)

    if thickness_mm <= 0:
        thickness_mm = 0.001

    thickness_bu = thickness_mm * mm_to_bu(scene)

    mesh_copy = cutter.data.copy()

    temp_obj = bpy.data.objects.new(cutter.name + TEMP_SOLID_CUTTER_TAG, mesh_copy)
    temp_obj.matrix_world = cutter.matrix_world.copy()
    context.scene.collection.objects.link(temp_obj)

    temp_obj["seanixz_pro_temp_boolean_cutter"] = True

    solid_mod = temp_obj.modifiers.new("SeanIXz_Pro_临时实体化布尔切刀", 'SOLIDIFY')
    configure_cutter_solidify_modifier(solid_mod, thickness_bu, show_viewport=True)

    applied = apply_modifier(context, temp_obj, solid_mod.name)

    if not applied:
        try:
            bpy.data.objects.remove(temp_obj, do_unlink=True)
        except Exception:
            pass
        return None

    recalc_mesh_normals(temp_obj)

    temp_obj.display_type = 'WIRE'
    temp_obj.show_in_front = False
    temp_obj.hide_render = True
    temp_obj.hide_viewport = True

    try:
        temp_obj.hide_set(True)
    except Exception:
        pass

    move_to_collection(temp_obj, CUTTER_COLLECTION_NAME)
    return temp_obj

# -----------------------------------------------------------------------------
# 切刀绘制核心工具
# -----------------------------------------------------------------------------

def selected_bm_loop(bm):
    edges = [e for e in bm.edges if e.select]

    if len(edges) < 3:
        return None, None

    adjacency = {}

    for edge in edges:
        v1 = edge.verts[0]
        v2 = edge.verts[1]
        adjacency.setdefault(v1, []).append(v2)
        adjacency.setdefault(v2, []).append(v1)

    if not adjacency:
        return None, None

    for vert, neighbors in adjacency.items():
        if len(neighbors) != 2:
            return None, None

    start = next(iter(adjacency.keys()))
    ordered = [start]
    previous = None
    current = start

    while True:
        neighbors = adjacency[current]
        next_vert = neighbors[0] if neighbors[0] != previous else neighbors[1]

        if next_vert == start:
            break

        if next_vert in ordered:
            return None, None

        ordered.append(next_vert)
        previous = current
        current = next_vert

        if len(ordered) > len(adjacency):
            return None, None

    if len(ordered) != len(adjacency):
        return None, None

    return ordered, edges

def newell_normal_from_coords(coords):
    normal = Vector((0.0, 0.0, 0.0))
    count = len(coords)

    for i in range(count):
        c1 = coords[i]
        c2 = coords[(i + 1) % count]
        normal.x += (c1.y - c2.y) * (c1.z + c2.z)
        normal.y += (c1.z - c2.z) * (c1.x + c2.x)
        normal.z += (c1.x - c2.x) * (c1.y + c2.y)

    if normal.length < 1e-8:
        return Vector((0.0, 0.0, 1.0))

    normal.normalize()
    return normal

def newell_normal(loop_verts):
    return newell_normal_from_coords([v.co.copy() for v in loop_verts])

def centroid_from_verts(verts):
    center = Vector((0.0, 0.0, 0.0))

    for vert in verts:
        center += vert.co

    return center / max(len(verts), 1)

def centroid_from_coords(coords):
    center = Vector((0.0, 0.0, 0.0))

    for co in coords:
        center += co

    return center / max(len(coords), 1)

def face_center(face):
    center = Vector((0.0, 0.0, 0.0))

    for vert in face.verts:
        center += vert.co

    return center / max(len(face.verts), 1)

def scale_point_in_plane(co, center, normal, scale):
    offset = co - center
    planar = offset - normal * offset.dot(normal)
    return center + planar * scale

def flatten_verts_to_plane(verts, plane_point, plane_normal):
    plane_normal = plane_normal.normalized()
    plane_d = plane_normal.dot(plane_point)

    for vert in verts:
        distance = plane_normal.dot(vert.co) - plane_d
        vert.co = vert.co - plane_normal * distance

def chaikin_closed(coords, iterations=2, keep_shrink_compensation=True):
    if len(coords) < 3:
        return coords

    result = [co.copy() for co in coords]
    original_center = centroid_from_coords(result)

    for _ in range(max(iterations, 1)):
        new_coords = []
        count = len(result)

        for i in range(count):
            p0 = result[i]
            p1 = result[(i + 1) % count]

            q = p0.lerp(p1, 0.25)
            r = p0.lerp(p1, 0.75)

            new_coords.append(q)
            new_coords.append(r)

        result = new_coords

    if keep_shrink_compensation:
        new_center = centroid_from_coords(result)

        original_radius = sum((co - original_center).length for co in coords) / max(len(coords), 1)
        new_radius = sum((co - new_center).length for co in result) / max(len(result), 1)

        if new_radius > 1e-8 and original_radius > 1e-8:
            factor = original_radius / new_radius
            result = [original_center + (co - new_center) * factor for co in result]

    return result

def catmull_rom_point(p0, p1, p2, p3, t):
    """Catmull-Rom interpolation that passes through p1 and p2 without moving original points."""
    t2 = t * t
    t3 = t2 * t
    return (
        (p1 * 2.0) +
        (p2 - p0) * t +
        (p0 * 2.0 - p1 * 5.0 + p2 * 4.0 - p3) * t2 +
        (-p0 + p1 * 3.0 - p2 * 3.0 + p3) * t3
    ) * 0.5

def rebuild_selected_loop_as_smooth_curve(obj, scene):
    """
    Preserve every original selected loop vertex exactly in place.
    Only remove the original straight edges and insert extra Catmull-Rom curve points between neighboring vertices.
    This improves edge flow without shifting anchor points or re-projecting the loop plane.
    """
    bm = bmesh.from_edit_mesh(obj.data)

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    loop_verts, loop_edges = selected_bm_loop(bm)

    if not loop_verts:
        return False, "请先在编辑模式选中一个闭合边环。"

    count = len(loop_verts)

    if count < 3:
        return False, "闭合边环至少需要 3 个点。"

    # “拟合圆滑次数”现在作为每条原始边之间的插点密度使用。
    # 例如 3 表示每两个原始点之间插入 3 个过渡点；原始点不移动。
    insert_count = max(int(scene.seanixz_pro_fit_smooth_repeat), 1)

    original_positions = [v.co.copy() for v in loop_verts]

    # 删除原有直线边，但保留所有原始顶点不动。
    for edge in list(loop_edges):
        if edge.is_valid:
            try:
                bm.edges.remove(edge)
            except Exception:
                try:
                    bmesh.ops.delete(bm, geom=[edge], context='EDGES')
                except Exception:
                    return False, "旧边删除失败。"

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    ordered_path = []
    inserted_verts = []

    for i in range(count):
        v_current = loop_verts[i]

        if not v_current.is_valid:
            return False, "原始顶点状态异常，拟合中止。"

        ordered_path.append(v_current)

        p0 = original_positions[(i - 1) % count]
        p1 = original_positions[i]
        p2 = original_positions[(i + 1) % count]
        p3 = original_positions[(i + 2) % count]

        for j in range(1, insert_count + 1):
            t = j / (insert_count + 1)
            co = catmull_rom_point(p0, p1, p2, p3, t)

            try:
                new_vert = bm.verts.new(co)
                new_vert.select = True
                inserted_verts.append(new_vert)
                ordered_path.append(new_vert)
            except ValueError:
                pass

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    new_edges = []
    path_count = len(ordered_path)

    for i in range(path_count):
        v1 = ordered_path[i]
        v2 = ordered_path[(i + 1) % path_count]

        if not v1.is_valid or not v2.is_valid or v1 == v2:
            continue

        try:
            edge = bm.edges.new((v1, v2))
        except ValueError:
            edge = bm.edges.get((v1, v2))

        if edge:
            edge.select = True
            new_edges.append(edge)

    # 保留原始点位置不变，同时选中新生成的完整曲线轮廓，方便继续卡榫/闭合/线框操作。
    for v in bm.verts:
        v.select = v in ordered_path

    for e in bm.edges:
        e.select = e in new_edges

    for f in bm.faces:
        f.select = False

    bmesh.update_edit_mesh(obj.data)
    obj.data.update()

    return True, f"拟合完成：原始 {count} 个点保持不动，每段插入 {insert_count} 个曲线点，共 {len(ordered_path)} 个点。"

def bevel_closed_polyline_coords(coords, bevel_distance):
    """Return a single closed outline with chamfered corners, without creating thickness or side faces."""
    if len(coords) < 3 or bevel_distance <= 0:
        return [co.copy() for co in coords]

    result = []
    count = len(coords)

    for i in range(count):
        prev_co = coords[(i - 1) % count]
        co = coords[i]
        next_co = coords[(i + 1) % count]

        to_prev = prev_co - co
        to_next = next_co - co
        prev_len = to_prev.length
        next_len = to_next.length

        if prev_len <= 1e-8 or next_len <= 1e-8:
            result.append(co.copy())
            continue

        distance = min(bevel_distance, prev_len * 0.45, next_len * 0.45)

        if distance <= 1e-8:
            result.append(co.copy())
            continue

        result.append(co + to_prev.normalized() * distance)
        result.append(co + to_next.normalized() * distance)

    return result

def face_from_ordered_verts(bm, ordered_verts):
    """Create or find a face from an ordered closed loop."""
    if len(ordered_verts) < 3:
        return None

    try:
        return bm.faces.new(ordered_verts)
    except ValueError:
        target = set(ordered_verts)
        for face in bm.faces:
            if len(face.verts) == len(ordered_verts) and set(face.verts) == target:
                return face

        try:
            return bm.faces.new(list(reversed(ordered_verts)))
        except ValueError:
            return None


def create_scaled_outline_from_loop(bm, loop_verts, center, normal, scale):
    """Simulate E + S on a selected closed loop, but keep only the enlarged outline.

    Important: do NOT create the filled ring surface between the original loop and
    the enlarged loop. That extra coplanar ring face can break boolean cutting and
    later cleanup may treat it as loose/interior geometry.
    """
    scaled_verts = []

    for vert in loop_verts:
        new_co = scale_point_in_plane(vert.co.copy(), center, normal, scale)
        scaled_verts.append(bm.verts.new(new_co))

    bm.verts.ensure_lookup_table()
    created_edges = []
    count = len(scaled_verts)

    for i in range(count):
        v1 = scaled_verts[i]
        v2 = scaled_verts[(i + 1) % count]

        try:
            created_edges.append(bm.edges.new((v1, v2)))
        except ValueError:
            pass

    bm.edges.ensure_lookup_table()
    return scaled_verts, created_edges


def extrude_face_region_get_top(bm, face, normal, move_distance=0.0, planar_scale=1.0):
    """Extrude a face, optionally scale the new top face in-plane, then move it along normal."""
    if not face:
        return None, [], []

    ret = bmesh.ops.extrude_face_region(bm, geom=[face])
    new_geom = ret.get("geom", [])
    new_verts = [ele for ele in new_geom if isinstance(ele, bmesh.types.BMVert)]
    new_faces = [ele for ele in new_geom if isinstance(ele, bmesh.types.BMFace)]

    if not new_verts:
        return None, [], []

    # Top face is the duplicated face whose verts all belong to the newly extruded region.
    top_candidates = []
    new_vert_set = set(new_verts)

    for f in new_faces:
        if all(v in new_vert_set for v in f.verts):
            top_candidates.append(f)

    if not top_candidates:
        top_candidates = new_faces

    top_face = None
    if top_candidates:
        base_center = face_center(face)
        top_face = max(top_candidates, key=lambda f: (face_center(f) - base_center).dot(normal))

    if top_face:
        top_center = face_center(top_face)
        scale = max(planar_scale, 0.0001)

        if abs(scale - 1.0) > 1e-8:
            for vert in top_face.verts:
                vert.co = scale_point_in_plane(vert.co.copy(), top_center, normal, scale)

        if abs(move_distance) > 1e-12:
            move_vec = normal * move_distance
            for vert in top_face.verts:
                vert.co += move_vec

            # Move side/top connected newly created vertices that are part of the same extruded top loop.
            top_vert_set = set(top_face.verts)
            for vert in new_verts:
                if vert in top_vert_set:
                    continue

    return top_face, new_verts, new_faces


def select_geometry(bm, verts=None, edges=None, faces=None):
    verts = set(verts or [])
    edges = set(edges or [])
    faces = set(faces or [])

    for v in bm.verts:
        v.select = v in verts

    for e in bm.edges:
        e.select = e in edges

    for f in bm.faces:
        f.select = f in faces


def recalc_bmesh_normals(bm):
    try:
        bm.faces.ensure_lookup_table()
        if bm.faces:
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    except Exception:
        pass


def bevel_face_edges_if_enabled(bm, scene, face):
    if not face or not scene.seanixz_pro_use_bevel:
        return []

    bevel = scene.seanixz_pro_bevel_mm * mm_to_bu(scene)
    if bevel <= 0:
        return []

    try:
        ret = bmesh.ops.bevel(
            bm,
            geom=list(face.edges),
            offset=max(bevel, 0.000001),
            offset_type='OFFSET',
            segments=max(scene.seanixz_pro_bevel_segments, 1),
            profile=0.5,
            affect='EDGES',
            clamp_overlap=True,
        )
        return ret.get('faces', []) + ret.get('geom', [])
    except Exception:
        return []


def edge_between_verts(v1, v2):
    """Find an existing edge between two BMVerts."""
    if not v1 or not v2:
        return None

    try:
        for edge in v1.link_edges:
            if v2 in edge.verts:
                return edge
    except Exception:
        pass

    return None


def ensure_edge_between(bm, v1, v2):
    """Create or return an edge between two vertices."""
    edge = edge_between_verts(v1, v2)

    if edge:
        return edge

    try:
        return bm.edges.new((v1, v2))
    except ValueError:
        return edge_between_verts(v1, v2)


def create_loop_edges(bm, ordered_verts):
    """Ensure a closed edge loop exists for ordered verts and return those edges."""
    edges = []
    count = len(ordered_verts)

    for i in range(count):
        edge = ensure_edge_between(bm, ordered_verts[i], ordered_verts[(i + 1) % count])
        if edge:
            edges.append(edge)

    return edges


def create_faces_between_loops(bm, inner_verts, outer_verts):
    """Create quad band faces between two ordered closed loops."""
    faces = []
    count = min(len(inner_verts), len(outer_verts))

    if count < 3:
        return faces

    for i in range(count):
        v1 = inner_verts[i]
        v2 = inner_verts[(i + 1) % count]
        v3 = outer_verts[(i + 1) % count]
        v4 = outer_verts[i]
        face = face_from_ordered_verts(bm, [v1, v2, v3, v4])
        if face:
            faces.append(face)

    return faces


def scale_loop_from_source(bm, source_verts, center, normal, scale, normal_offset=0.0):
    """Create a new loop scaled in the source plane, with optional normal offset."""
    new_verts = []
    offset_vec = normal * normal_offset
    scaled_center = center + offset_vec

    for vert in source_verts:
        source_co = vert.co.copy() + offset_vec
        new_co = scale_point_in_plane(source_co, scaled_center, normal, scale)
        new_verts.append(bm.verts.new(new_co))

    bm.verts.ensure_lookup_table()
    edges = create_loop_edges(bm, new_verts)
    bm.edges.ensure_lookup_table()
    return new_verts, edges


def bevel_edges_if_enabled(bm, scene, edges):
    """Apply Ctrl+B style bevel to the supplied edges when the bevel toggle is enabled."""
    if not scene.seanixz_pro_use_bevel:
        return []

    valid_edges = [e for e in edges if e and e.is_valid]
    if not valid_edges:
        return []

    bevel = scene.seanixz_pro_bevel_mm * mm_to_bu(scene)
    if bevel <= 0:
        return []

    try:
        ret = bmesh.ops.bevel(
            bm,
            geom=valid_edges,
            offset=max(bevel, 0.000001),
            offset_type='OFFSET',
            segments=max(scene.seanixz_pro_bevel_segments, 1),
            profile=0.5,
            affect='EDGES',
            clamp_overlap=True,
        )
        return ret.get('geom', []) + ret.get('faces', [])
    except Exception:
        return []


def selected_edges_or_edges_from_selected_verts(bm):
    """Return selected edges; if only verts are selected, return edges whose both ends are selected."""
    selected_edges = [e for e in bm.edges if e.select]

    if selected_edges:
        return selected_edges

    selected_verts = {v for v in bm.verts if v.select}
    if not selected_verts:
        return []

    return [e for e in bm.edges if e.verts[0] in selected_verts and e.verts[1] in selected_verts]


def select_edges_only(bm, edges):
    edge_set = {e for e in edges if e and e.is_valid}
    vert_set = set()

    for edge in edge_set:
        vert_set.update([v for v in edge.verts if v.is_valid])

    for f in bm.faces:
        f.select = False

    for e in bm.edges:
        e.select = e in edge_set

    for v in bm.verts:
        v.select = v in vert_set


def collect_valid_faces_edges_verts(faces=None, edges=None, verts=None, extra_geom=None):
    face_set = set()
    edge_set = set()
    vert_set = set()

    for face in faces or []:
        if isinstance(face, bmesh.types.BMFace) and face.is_valid:
            face_set.add(face)
            for edge in face.edges:
                if edge.is_valid:
                    edge_set.add(edge)
            for vert in face.verts:
                if vert.is_valid:
                    vert_set.add(vert)

    for edge in edges or []:
        if isinstance(edge, bmesh.types.BMEdge) and edge.is_valid:
            edge_set.add(edge)
            for vert in edge.verts:
                if vert.is_valid:
                    vert_set.add(vert)

    for vert in verts or []:
        if isinstance(vert, bmesh.types.BMVert) and vert.is_valid:
            vert_set.add(vert)

    for ele in extra_geom or []:
        if isinstance(ele, bmesh.types.BMFace) and ele.is_valid:
            face_set.add(ele)
            for edge in ele.edges:
                if edge.is_valid:
                    edge_set.add(edge)
            for vert in ele.verts:
                if vert.is_valid:
                    vert_set.add(vert)
        elif isinstance(ele, bmesh.types.BMEdge) and ele.is_valid:
            edge_set.add(ele)
            for vert in ele.verts:
                if vert.is_valid:
                    vert_set.add(vert)
        elif isinstance(ele, bmesh.types.BMVert) and ele.is_valid:
            vert_set.add(ele)

    return face_set, edge_set, vert_set


def fill_loop_face_and_flatten(bm, ordered_verts, normal):
    """Simulate F fill on a selected loop, then flatten the filled top face to one plane.

    The flattening is done on the plane perpendicular to the loop normal, which is
    the stable code equivalent of making the filled cap perfectly flat after the
    manual S/Z/0 step.
    """
    if not ordered_verts or len(ordered_verts) < 3:
        return None

    face = face_from_ordered_verts(bm, ordered_verts)

    if not face:
        return None

    top_center = face_center(face)
    flatten_verts_to_plane(list(face.verts), top_center, normal)
    return face


def make_simple_tenon_geometry(obj, scene):
    """
    简单卡榫 1：
    选闭合圈线 -> E,S 外扩 1.2 -> 选中内圈 -> 沿内圈法向 E 拉出 5mm ->
    S 缩放 0.9 -> F 充填顶部 -> S,Z,0 拉平 -> 可选 Ctrl+B 倒角。

    只在顶部执行 F 充填，不在原始内圈/底部生成中心盖面。
    """
    bm = bmesh.from_edit_mesh(obj.data)

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    loop_verts, loop_edges = selected_bm_loop(bm)

    if not loop_verts:
        return False, "请先在编辑模式选中一个闭合边环。"

    center = centroid_from_verts(loop_verts)
    normal = newell_normal(loop_verts)

    if getattr(scene, "seanixz_pro_tenon_reverse_direction", False):
        normal = -normal

    depth = scene.seanixz_pro_tenon_depth_mm * mm_to_bu(scene)

    # 1) E,S 外扩 1.2：保留手工 E,S 会生成的外扩环带面。
    outer_verts, outer_edges = scale_loop_from_source(
        bm,
        loop_verts,
        center,
        normal,
        max(scene.seanixz_pro_outer_scale, 0.0001),
        normal_offset=0.0
    )
    outer_band_faces = create_faces_between_loops(bm, loop_verts, outer_verts)

    # 2) 选中内圈，沿内圈法向 E 拉出 5mm。
    extruded_verts, extruded_edges = scale_loop_from_source(
        bm,
        loop_verts,
        center,
        normal,
        1.0,
        normal_offset=depth
    )
    side_faces = create_faces_between_loops(bm, loop_verts, extruded_verts)

    # 3) 顶部 S 缩放 0.9。
    top_center = centroid_from_verts(extruded_verts)
    top_scale = max(scene.seanixz_pro_inner_scale, 0.0001)
    for vert in extruded_verts:
        vert.co = scale_point_in_plane(vert.co.copy(), top_center, normal, top_scale)

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    # 4) F 充填顶部，并 S,Z,0 拉平。这里只填顶部，不填底部中心面。
    top_face = fill_loop_face_and_flatten(bm, extruded_verts, normal)
    top_edges = create_loop_edges(bm, extruded_verts)

    # 5) 可选 Ctrl+B 倒角，默认对顶部圈线倒角。
    bevel_geom = bevel_edges_if_enabled(bm, scene, top_edges)

    recalc_bmesh_normals(bm)

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    if bevel_geom:
        face_set, edge_set, vert_set = collect_valid_faces_edges_verts(extra_geom=bevel_geom)
        if not edge_set:
            edge_set = {e for e in top_edges if e and e.is_valid}
            for e in edge_set:
                vert_set.update([v for v in e.verts if v.is_valid])
        select_geometry(bm, verts=vert_set, edges=edge_set, faces=face_set)
    else:
        # 未倒角时保留顶部圈线选中，方便用户继续点“一键倒角”。
        select_edges_only(bm, top_edges)

    bmesh.update_edit_mesh(obj.data)
    obj.data.update()

    bevel_text = "，已倒角" if scene.seanixz_pro_use_bevel and scene.seanixz_pro_bevel_mm > 0 else "，未倒角，顶部圈线已选中"
    return True, (
        f"简单卡榫1完成：E,S 外扩 {scene.seanixz_pro_outer_scale:.3f}，"
        f"内圈法向拉出 {scene.seanixz_pro_tenon_depth_mm:.3f} mm，"
        f"顶部缩放 {scene.seanixz_pro_inner_scale:.3f}，"
        f"顶部已 F 充填并拉平{bevel_text}。"
    )


def make_simple_tenon2_geometry(obj, scene):
    """
    简单卡榫 2：
    选闭合圈线 -> E,S 外扩 1.2 -> 选中内圈 -> E,S 缩放 0.8 ->
    沿法向拉出 5mm -> F 充填顶部 -> S,Z,0 拉平 -> 可选 Ctrl+B 倒角。

    只在顶部执行 F 充填，不在原始内圈/底部生成中心盖面。
    """
    bm = bmesh.from_edit_mesh(obj.data)

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    loop_verts, loop_edges = selected_bm_loop(bm)

    if not loop_verts:
        return False, "请先在编辑模式选中一个闭合边环。"

    center = centroid_from_verts(loop_verts)
    normal = newell_normal(loop_verts)

    if getattr(scene, "seanixz_pro_tenon_reverse_direction", False):
        normal = -normal

    depth = scene.seanixz_pro_tenon_depth_mm * mm_to_bu(scene)

    # 1) E,S 外扩 1.2：保留手工 E,S 会生成的外扩环带面。
    outer_verts, outer_edges = scale_loop_from_source(
        bm,
        loop_verts,
        center,
        normal,
        max(scene.seanixz_pro_outer_scale, 0.0001),
        normal_offset=0.0
    )
    outer_band_faces = create_faces_between_loops(bm, loop_verts, outer_verts)

    # 2) 选中内圈，E,S 缩放 0.8。
    shoulder_verts, shoulder_edges = scale_loop_from_source(
        bm,
        loop_verts,
        center,
        normal,
        max(scene.seanixz_pro_tenon2_scale, 0.0001),
        normal_offset=0.0
    )
    shoulder_faces = create_faces_between_loops(bm, loop_verts, shoulder_verts)

    # 3) 沿缩放后的内圈法向拉出 5mm。
    shoulder_center = centroid_from_verts(shoulder_verts)
    top_verts, top_edges = scale_loop_from_source(
        bm,
        shoulder_verts,
        shoulder_center,
        normal,
        1.0,
        normal_offset=depth
    )
    side_faces = create_faces_between_loops(bm, shoulder_verts, top_verts)

    # 4) F 充填顶部，并 S,Z,0 拉平。这里只填顶部，不填底部中心面。
    top_face = fill_loop_face_and_flatten(bm, top_verts, normal)
    top_edges = create_loop_edges(bm, top_verts)

    # 5) 可选 Ctrl+B 倒角，默认倒角 1mm，段数 1。
    bevel_geom = bevel_edges_if_enabled(bm, scene, top_edges)

    recalc_bmesh_normals(bm)

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    if bevel_geom:
        face_set, edge_set, vert_set = collect_valid_faces_edges_verts(extra_geom=bevel_geom)
        if not edge_set:
            edge_set = {e for e in top_edges if e and e.is_valid}
            for e in edge_set:
                vert_set.update([v for v in e.verts if v.is_valid])
        select_geometry(bm, verts=vert_set, edges=edge_set, faces=face_set)
    else:
        # 未倒角时保留顶部圈线选中，方便用户继续点“一键倒角”。
        select_edges_only(bm, top_edges)

    bmesh.update_edit_mesh(obj.data)
    obj.data.update()

    bevel_text = "，已倒角" if scene.seanixz_pro_use_bevel and scene.seanixz_pro_bevel_mm > 0 else "，未倒角，顶部圈线已选中"
    return True, (
        f"简单卡榫2完成：E,S 外扩 {scene.seanixz_pro_outer_scale:.3f}，"
        f"内圈 E,S 缩放 {scene.seanixz_pro_tenon2_scale:.3f}，"
        f"法向拉出 {scene.seanixz_pro_tenon_depth_mm:.3f} mm，"
        f"顶部已 F 充填并拉平{bevel_text}。"
    )



# -----------------------------------------------------------------------------
# 卡榫防呆锁止结构核心工具
# -----------------------------------------------------------------------------

def selected_surface_frame_local(obj):
    """Return a local-space frame from the selected face or closed loop.

    优先使用当前选中的面作为“卡榫表面”。如果没有选中面，则使用闭合圈线。
    这样初学者可以直接选中卡榫顶部面或顶部圈线来添加防呆锁止结构。
    """
    if not obj or obj.mode != 'EDIT':
        return None, None, "请先选中卡榫对象，进入编辑模式，并选中顶部面或闭合圈线。"

    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    selected_faces = [f for f in bm.faces if f.select]

    if selected_faces:
        # 选择面积最大的面，避免误选小倒角面时尺寸异常。
        face = max(selected_faces, key=lambda f: f.calc_area())
        verts = list(face.verts)
        boundary_verts = list(face.verts)
        boundary_edges = list(face.edges)
        selected_face = face
        center = face_center(face)
        normal = face.normal.copy()
        if normal.length <= 1e-8:
            normal = newell_normal(verts)
        else:
            normal.normalize()
    else:
        verts, edges = selected_bm_loop(bm)
        if not verts:
            return None, None, "没有找到顶部面或闭合圈线。请选中卡榫顶部面，或选中完整闭合边环。"
        boundary_verts = verts
        boundary_edges = edges
        selected_face = None
        center = centroid_from_verts(verts)
        normal = newell_normal(verts)

    # 从所选区域内找最长方向作为 X 方向，另一个方向作为 Y 方向。
    tangent = None
    max_dist = 0.0
    positions = [v.co.copy() for v in verts]

    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            delta = positions[j] - positions[i]
            planar = delta - normal * delta.dot(normal)
            dist = planar.length
            if dist > max_dist:
                max_dist = dist
                tangent = planar

    if not tangent or tangent.length <= 1e-8:
        tangent, _ = orthonormal_basis_from_axis(normal)
    else:
        tangent.normalize()

    bitangent = normal.cross(tangent)
    if bitangent.length <= 1e-8:
        _, bitangent = orthonormal_basis_from_axis(normal)
    else:
        bitangent.normalize()

    tangent_values = []
    bitangent_values = []
    for co in positions:
        offset = co - center
        planar = offset - normal * offset.dot(normal)
        tangent_values.append(planar.dot(tangent))
        bitangent_values.append(planar.dot(bitangent))

    major_extent = max(tangent_values) - min(tangent_values) if tangent_values else 0.0
    minor_extent = max(bitangent_values) - min(bitangent_values) if bitangent_values else 0.0
    if major_extent < minor_extent:
        tangent, bitangent = bitangent, tangent
        major_extent, minor_extent = minor_extent, major_extent

    frame = {
        "center": center,
        "normal": normal,
        "tangent": tangent,
        "bitangent": bitangent,
        "major_extent_bu": max(major_extent, 0.000001),
        "minor_extent_bu": max(minor_extent, 0.000001),
        "boundary_verts": boundary_verts,
        "boundary_edges": boundary_edges,
        "selected_face": selected_face,
    }
    return bm, frame, ""


def lock_size_values(scene, frame):
    unit = mm_to_bu(scene)
    height = max(scene.seanixz_pro_lock_height_mm * unit, 0.000001)
    major = frame.get("major_extent_bu", 1.0)
    minor = frame.get("minor_extent_bu", 1.0)

    if scene.seanixz_pro_lock_size_mm > 0:
        base = scene.seanixz_pro_lock_size_mm * unit
    else:
        base = min(major, minor) * max(scene.seanixz_pro_lock_size_factor, 0.05)
        min_size = scene.seanixz_pro_lock_min_size_mm * unit
        max_size = min(major, minor) * 0.82
        if max_size > min_size:
            base = min(max(base, min_size), max_size)
        else:
            base = max(base, min_size)

    length = max(base * 1.25, 0.000001)
    width = max(base * 0.70, 0.000001)
    return length, width, height


def create_prism_from_base_points(bm, base_points, normal, height, create_bottom=False):
    """Create an open-bottom prism for lock/cutter structures.

    create_bottom is intentionally False by default: the contact face against the
    tenon/top plane stays empty, so the generated shape can be used as a clean
    double-sided boolean cutter or open-bottom registration feature without an
    extra coplanar face causing boolean/cleanup errors.
    """
    bottom = [bm.verts.new(co.copy()) for co in base_points]
    top = [bm.verts.new(co + normal * height) for co in base_points]
    bm.verts.ensure_lookup_table()

    faces = []
    if create_bottom:
        bottom_face = face_from_ordered_verts(bm, list(reversed(bottom)))
        if bottom_face:
            faces.append(bottom_face)

    top_face = face_from_ordered_verts(bm, top)
    if top_face:
        faces.append(top_face)

    count = len(bottom)
    for i in range(count):
        face = face_from_ordered_verts(bm, [bottom[i], bottom[(i + 1) % count], top[(i + 1) % count], top[i]])
        if face:
            faces.append(face)

    edges = []
    for face in faces:
        for edge in face.edges:
            if edge not in edges:
                edges.append(edge)

    verts = bottom + top
    return verts, edges, faces


def create_wedge_lock_geometry(bm, frame, scene):
    center = frame["center"]
    normal = frame["normal"]
    t = frame["tangent"]
    b = frame["bitangent"]
    length, width, height = lock_size_values(scene, frame)

    # 矩形底面，顶部做成一边低一边高的楔形，方向明显，装配时不容易装反。
    base = [
        center - t * (length * 0.5) - b * (width * 0.5),
        center + t * (length * 0.5) - b * (width * 0.5),
        center + t * (length * 0.5) + b * (width * 0.5),
        center - t * (length * 0.5) + b * (width * 0.5),
    ]
    low = height * 0.12
    top = [
        base[0] + normal * low,
        base[1] + normal * height,
        base[2] + normal * height,
        base[3] + normal * low,
    ]

    verts = [bm.verts.new(co) for co in base + top]
    bm.verts.ensure_lookup_table()
    faces = []
    face_defs = [
        # 底面故意不生成：与卡榫表面的接触面保持为空，避免产生共面充填面。
        [verts[4], verts[5], verts[6], verts[7]],  # 斜顶面
        [verts[0], verts[1], verts[5], verts[4]],
        [verts[1], verts[2], verts[6], verts[5]],
        [verts[2], verts[3], verts[7], verts[6]],
        [verts[3], verts[0], verts[4], verts[7]],
    ]
    for fverts in face_defs:
        face = face_from_ordered_verts(bm, fverts)
        if face:
            faces.append(face)

    edges = []
    for face in faces:
        for edge in face.edges:
            if edge not in edges:
                edges.append(edge)

    return verts, edges, faces, length, width, height


def create_triangle_lock_geometry(bm, frame, scene):
    center = frame["center"]
    normal = frame["normal"]
    t = frame["tangent"]
    b = frame["bitangent"]
    length, width, height = lock_size_values(scene, frame)

    base = [
        center + t * (length * 0.58),
        center - t * (length * 0.42) + b * (width * 0.58),
        center - t * (length * 0.42) - b * (width * 0.58),
    ]
    verts, edges, faces = create_prism_from_base_points(bm, base, normal, height)
    return verts, edges, faces, length, width, height


def create_hex_lock_geometry(bm, frame, scene):
    center = frame["center"]
    normal = frame["normal"]
    t = frame["tangent"]
    b = frame["bitangent"]
    length, width, height = lock_size_values(scene, frame)
    radius = min(length, width) * 0.55

    base = []
    for i in range(6):
        angle = math.pi * 2.0 * i / 6.0 + math.pi / 6.0
        base.append(center + t * math.cos(angle) * radius + b * math.sin(angle) * radius)

    verts, edges, faces = create_prism_from_base_points(bm, base, normal, height)
    return verts, edges, faces, length, width, height


def create_square_lock_geometry(bm, frame, scene):
    center = frame["center"]
    normal = frame["normal"]
    t = frame["tangent"]
    b = frame["bitangent"]
    length, width, height = lock_size_values(scene, frame)
    size = min(length, width)

    base = [
        center - t * (size * 0.5) - b * (size * 0.5),
        center + t * (size * 0.5) - b * (size * 0.5),
        center + t * (size * 0.5) + b * (size * 0.5),
        center - t * (size * 0.5) + b * (size * 0.5),
    ]
    verts, edges, faces = create_prism_from_base_points(bm, base, normal, height)
    return verts, edges, faces, size, size, height


def create_diamond_lock_geometry(bm, frame, scene):
    center = frame["center"]
    normal = frame["normal"]
    t = frame["tangent"]
    b = frame["bitangent"]
    length, width, height = lock_size_values(scene, frame)
    size = min(length, width)

    base = [
        center + t * (size * 0.62),
        center + b * (size * 0.62),
        center - t * (size * 0.62),
        center - b * (size * 0.62),
    ]
    verts, edges, faces = create_prism_from_base_points(bm, base, normal, height)
    return verts, edges, faces, size, size, height


def lock_base_points_for_type(frame, scene, lock_type='WEDGE'):
    """Return ordered footprint points for a lock feature placed on the selected cutter surface."""
    center = frame["center"]
    normal = frame["normal"]
    t = frame["tangent"]
    b = frame["bitangent"]
    length, width, height = lock_size_values(scene, frame)

    if lock_type == 'TRIANGLE':
        name = "三角防呆一体切刀结构"
        base = [
            center + t * (length * 0.58),
            center - t * (length * 0.42) + b * (width * 0.58),
            center - t * (length * 0.42) - b * (width * 0.58),
        ]
    elif lock_type == 'HEX':
        name = "六边定位一体切刀结构"
        radius = min(length, width) * 0.55
        base = []
        for i in range(6):
            angle = math.pi * 2.0 * i / 6.0 + math.pi / 6.0
            base.append(center + t * math.cos(angle) * radius + b * math.sin(angle) * radius)
        length = width = radius * 2.0
    elif lock_type == 'SQUARE':
        name = "方形定位一体切刀结构"
        size = min(length, width)
        base = [
            center - t * (size * 0.5) - b * (size * 0.5),
            center + t * (size * 0.5) - b * (size * 0.5),
            center + t * (size * 0.5) + b * (size * 0.5),
            center - t * (size * 0.5) + b * (size * 0.5),
        ]
        length = width = size
    elif lock_type == 'DIAMOND':
        name = "菱形防呆一体切刀结构"
        size = min(length, width)
        base = [
            center + t * (size * 0.62),
            center + b * (size * 0.62),
            center - t * (size * 0.62),
            center - b * (size * 0.62),
        ]
        length = width = size
    else:
        name = "楔形锁止一体切刀结构"
        base = [
            center - t * (length * 0.5) - b * (width * 0.5),
            center + t * (length * 0.5) - b * (width * 0.5),
            center + t * (length * 0.5) + b * (width * 0.5),
            center - t * (length * 0.5) + b * (width * 0.5),
        ]

    return base, length, width, height, name


def point_in_polygon_2d(point, polygon):
    """2D ray-casting point in polygon test."""
    if not polygon or len(polygon) < 3:
        return False

    x, y = point
    inside = False
    j = len(polygon) - 1

    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) if abs(yj - yi) > 1e-12 else 1e-12) + xi)
        if intersects:
            inside = not inside
        j = i

    return inside


def project_to_lock_2d(co, frame):
    offset = co - frame["center"]
    return (offset.dot(frame["tangent"]), offset.dot(frame["bitangent"]))


def integrate_lock_footprint_into_surface(bm, frame, base_verts, base_edges):
    """Cut an open footprint into the selected cutter surface and connect it to the lock walls.

    The original selected surface face is replaced by a triangulated surface with
    a hole at the lock footprint. The lock side walls share the footprint edges,
    so the lock is part of the cutter surface instead of a loose separate part.
    """
    selected_face = frame.get("selected_face")
    boundary_edges = [e for e in frame.get("boundary_edges", []) if e and e.is_valid]
    base_edges = [e for e in base_edges if e and e.is_valid]

    if selected_face and selected_face.is_valid:
        try:
            bm.faces.remove(selected_face)
        except Exception:
            try:
                bmesh.ops.delete(bm, geom=[selected_face], context='FACES_ONLY')
            except Exception:
                pass

    if not boundary_edges or not base_edges:
        return []

    created_faces = []
    try:
        ret = bmesh.ops.triangle_fill(
            bm,
            edges=boundary_edges + base_edges,
            use_beauty=True,
        )
        created_faces = [g for g in ret.get('geom', []) if isinstance(g, bmesh.types.BMFace) and g.is_valid]
    except Exception:
        created_faces = []

    # Some fill operations may also fill the footprint itself. Delete those
    # triangles so the contact/base face remains open.
    base_poly_2d = [project_to_lock_2d(v.co, frame) for v in base_verts]
    removed = 0
    for face in list(created_faces):
        if not face.is_valid:
            continue
        center_2d = project_to_lock_2d(face_center(face), frame)
        if point_in_polygon_2d(center_2d, base_poly_2d):
            try:
                bm.faces.remove(face)
                removed += 1
            except Exception:
                pass

    remaining_faces = [f for f in created_faces if f and f.is_valid]

    # If triangulation fails, at least connect the footprint to the nearest
    # existing boundary vertices so it is not a fully loose object. This is a
    # fallback; normally triangle_fill creates the clean integrated surface.
    if not remaining_faces:
        boundary_verts = [v for v in frame.get("boundary_verts", []) if v and v.is_valid]
        for bv in base_verts:
            nearest = None
            best = 1e100
            for ov in boundary_verts:
                d = (ov.co - bv.co).length_squared
                if d < best:
                    best = d
                    nearest = ov
            if nearest:
                ensure_edge_between(bm, bv, nearest)

    return remaining_faces


def create_integrated_lock_from_base(bm, frame, base_points, height, lock_type='WEDGE', scene=None):
    """Create a lock prism integrated into the selected cutter surface.

    新版逻辑：
    - 底部接触面保持开口，不额外生成共面底面；
    - 顶部按“斜角缩放”向中心收缩，默认 0.8；
    - 因此锁止结构两端和两侧都会形成斜面，更利于装配导入；
    - 正/反向由 frame["normal"] 决定，base 仍然嵌入当前切刀面。
    """
    normal = frame["normal"]
    tangent = frame["tangent"]
    center = frame["center"]

    taper_scale = 0.8
    if scene is not None:
        try:
            taper_scale = float(scene.seanixz_pro_lock_taper_scale)
        except Exception:
            taper_scale = 0.8
    taper_scale = max(min(taper_scale, 1.0), 0.05)

    base_verts = [bm.verts.new(co.copy()) for co in base_points]
    bm.verts.ensure_lookup_table()
    base_edges = create_loop_edges(bm, base_verts)

    surface_faces = integrate_lock_footprint_into_surface(bm, frame, base_verts, base_edges)

    # Top loop. Wedge keeps a directional slope; all shapes taper in-plane for smoother assembly.
    tangent_values = [(v.co - center).dot(tangent) for v in base_verts]
    min_t = min(tangent_values) if tangent_values else 0.0
    max_t = max(tangent_values) if tangent_values else 1.0
    span = max(max_t - min_t, 1e-8)

    top_verts = []
    for v, tv in zip(base_verts, tangent_values):
        if lock_type == 'WEDGE':
            factor = (tv - min_t) / span
            local_height = height * (0.12 + 0.88 * factor)
        else:
            local_height = height

        offset = v.co - center
        planar = offset - normal * offset.dot(normal)
        top_co = center + planar * taper_scale + normal * local_height
        top_verts.append(bm.verts.new(top_co))

    bm.verts.ensure_lookup_table()

    faces = []
    top_face = face_from_ordered_verts(bm, top_verts)
    if top_face:
        faces.append(top_face)

    count = len(base_verts)
    for i in range(count):
        face = face_from_ordered_verts(bm, [base_verts[i], base_verts[(i + 1) % count], top_verts[(i + 1) % count], top_verts[i]])
        if face:
            faces.append(face)

    all_edges = set(base_edges)
    for face in faces + surface_faces:
        if face and face.is_valid:
            for edge in face.edges:
                if edge.is_valid:
                    all_edges.add(edge)

    return base_verts + top_verts, list(all_edges), faces + surface_faces


def add_tenon_lock_geometry(obj, scene, lock_type='WEDGE'):
    bm, frame, error = selected_surface_frame_local(obj)
    if not frame:
        return False, error

    # 锁止结构可独立正/反向：方向不对时不用重做卡榫，只需切换锁止方向后重新生成锁止结构。
    reverse_lock = False
    try:
        reverse_lock = bool(scene.seanixz_pro_lock_reverse_direction)
    except Exception:
        reverse_lock = False

    if reverse_lock:
        frame = dict(frame)
        frame["normal"] = -frame["normal"]

    base_points, length, width, height, name = lock_base_points_for_type(frame, scene, lock_type)
    verts, edges, faces = create_integrated_lock_from_base(bm, frame, base_points, height, lock_type, scene=scene)

    recalc_bmesh_normals(bm)
    select_geometry(bm, verts=verts, edges=edges, faces=faces)
    bmesh.update_edit_mesh(obj.data)
    obj.data.update()

    direction_text = "反向" if reverse_lock else "正向"
    taper = getattr(scene, 'seanixz_pro_lock_taper_scale', 0.8)
    return True, (
        f"{name}已生成：约 {bu_to_mm(scene, length):.2f} × {bu_to_mm(scene, width):.2f} mm，"
        f"凸起 {bu_to_mm(scene, height):.2f} mm，方向：{direction_text}，斜角缩放 {taper:.2f}。\n"
        "用途：结构已嵌入当前切刀面，底部接触面保持开口；作为同一个切刀整体参与布尔后，分件两侧会形成可直接对接耦合的互补定位结构。"
    )


# -----------------------------------------------------------------------------
# 活动关节切刀核心工具
# -----------------------------------------------------------------------------

def safe_normalized(vec, fallback=Vector((0.0, 0.0, 1.0))):
    try:
        if vec.length > 1e-8:
            return vec.normalized()
    except Exception:
        pass
    return fallback.copy()


def orthonormal_basis_from_axis(axis):
    axis = safe_normalized(axis)
    helper = Vector((0.0, 0.0, 1.0))

    if abs(axis.dot(helper)) > 0.92:
        helper = Vector((1.0, 0.0, 0.0))

    u = axis.cross(helper)

    if u.length <= 1e-8:
        u = Vector((1.0, 0.0, 0.0))
    else:
        u.normalize()

    v = axis.cross(u)

    if v.length <= 1e-8:
        v = Vector((0.0, 1.0, 0.0))
    else:
        v.normalize()

    return u, v


def create_mesh_object_from_data(context, name, verts, faces, display_mode='WIRE'):
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    context.scene.collection.objects.link(obj)
    obj["seanixz_pro_joint_cutter"] = True

    move_to_collection(obj, JOINT_CUTTER_COLLECTION_NAME)
    set_cutter_display_mode(obj, display_mode)
    recalc_mesh_normals(obj)
    return obj


def create_joint_pair_object(context, name, verts, faces, role, joint_type, side):
    """创建 Hi3D 风格的公连接件或母槽切刀，并保留成对关系元数据。"""
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    context.scene.collection.objects.link(obj)
    target_collection = JOINT_CUTTER_COLLECTION_NAME if role == "FEMALE_CUTTER" else JOINT_COLLECTION_NAME
    move_to_collection(obj, target_collection)

    obj["seanixz_pro_joint_pair"] = True
    obj["seanixz_pro_joint_role"] = role
    obj["seanixz_pro_joint_type"] = joint_type
    obj["seanixz_pro_joint_side"] = side
    obj.hide_viewport = False
    obj.hide_render = role == "FEMALE_CUTTER"

    if role == "FEMALE_CUTTER":
        obj["seanixz_pro_joint_cutter"] = True
        obj.display_type = 'WIRE'
        obj.show_in_front = True
        obj.color = (0.15, 0.55, 1.0, 0.45)
    else:
        obj.display_type = 'TEXTURED'
        obj.show_in_front = False
        obj.color = (0.25, 0.8, 0.3, 1.0)

    try:
        obj.hide_set(False)
    except Exception:
        pass

    recalc_mesh_normals(obj)
    return obj


def cylinder_mesh_data(center, axis, radius, length, segments=32, cap=True):
    axis = safe_normalized(axis)
    radius = max(radius, 0.000001)
    length = max(abs(length), 0.000001)
    segments = max(int(segments), 8)

    u, v = orthonormal_basis_from_axis(axis)
    half = axis * (length * 0.5)
    c1 = center - half
    c2 = center + half

    verts = []
    faces = []

    for base in (c1, c2):
        for i in range(segments):
            angle = (math.pi * 2.0) * i / segments
            verts.append(base + u * math.cos(angle) * radius + v * math.sin(angle) * radius)

    for i in range(segments):
        j = (i + 1) % segments
        faces.append((i, j, segments + j, segments + i))

    if cap:
        bottom_center_index = len(verts)
        verts.append(c1)
        top_center_index = len(verts)
        verts.append(c2)

        for i in range(segments):
            j = (i + 1) % segments
            faces.append((bottom_center_index, j, i))
            faces.append((top_center_index, segments + i, segments + j))

    return verts, faces



def cone_frustum_mesh_data(center, axis, radius1, radius2, length, segments=32, cap=True):
    """Create a truncated cone along axis.

    radius1 is at center - axis * length/2, radius2 is at center + axis * length/2.
    Useful for assembly lead-in chamfers on pin holes and joint cutters.
    """
    axis = safe_normalized(axis)
    radius1 = max(radius1, 0.000001)
    radius2 = max(radius2, 0.000001)
    length = max(abs(length), 0.000001)
    segments = max(int(segments), 8)

    u, v = orthonormal_basis_from_axis(axis)
    half = axis * (length * 0.5)
    c1 = center - half
    c2 = center + half

    verts = []
    faces = []

    for i in range(segments):
        angle = (math.pi * 2.0) * i / segments
        direction = u * math.cos(angle) + v * math.sin(angle)
        verts.append(c1 + direction * radius1)

    for i in range(segments):
        angle = (math.pi * 2.0) * i / segments
        direction = u * math.cos(angle) + v * math.sin(angle)
        verts.append(c2 + direction * radius2)

    for i in range(segments):
        j = (i + 1) % segments
        faces.append((i, j, segments + j, segments + i))

    if cap:
        bottom_center_index = len(verts)
        verts.append(c1)
        top_center_index = len(verts)
        verts.append(c2)
        for i in range(segments):
            j = (i + 1) % segments
            faces.append((bottom_center_index, j, i))
            faces.append((top_center_index, segments + i, segments + j))

    return verts, faces

def sphere_mesh_data(center, radius, segments=32, rings=16):
    radius = max(radius, 0.000001)
    segments = max(int(segments), 8)
    rings = max(int(rings), 6)

    verts = [center + Vector((0.0, 0.0, radius))]
    faces = []

    for r in range(1, rings):
        phi = math.pi * r / rings
        z = math.cos(phi) * radius
        ring_radius = math.sin(phi) * radius

        for s in range(segments):
            theta = math.pi * 2.0 * s / segments
            verts.append(center + Vector((math.cos(theta) * ring_radius, math.sin(theta) * ring_radius, z)))

    bottom_index = len(verts)
    verts.append(center + Vector((0.0, 0.0, -radius)))

    # 顶部三角面
    first_ring = 1
    for s in range(segments):
        faces.append((0, first_ring + s, first_ring + ((s + 1) % segments)))

    # 中间四边面
    for r in range(rings - 2):
        ring_a = 1 + r * segments
        ring_b = ring_a + segments

        for s in range(segments):
            faces.append((
                ring_a + s,
                ring_a + ((s + 1) % segments),
                ring_b + ((s + 1) % segments),
                ring_b + s,
            ))

    # 底部三角面
    last_ring = 1 + (rings - 2) * segments
    for s in range(segments):
        faces.append((bottom_index, last_ring + ((s + 1) % segments), last_ring + s))

    return verts, faces


def transform_sphere_mesh_data(verts, center, axis):
    """Rotate the default Z-axis sphere orientation so its neck direction can align with axis when combined.

    A pure sphere is rotation-independent, so this helper currently returns verts unchanged.
    It is kept for readability and future extension.
    """
    return verts


def append_mesh_data(base_verts, base_faces, add_verts, add_faces):
    offset = len(base_verts)
    base_verts.extend(add_verts)
    base_faces.extend([tuple(idx + offset for idx in face) for face in add_faces])


def selected_loop_world_frame(context):
    obj = active_mesh_object(context)

    if not obj or obj.mode != 'EDIT':
        return None, "请先选中切刀对象，进入编辑模式，并选中一个闭合圈线作为关节中心。"

    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    loop_verts, loop_edges = selected_bm_loop(bm)

    if not loop_verts:
        return None, "没有找到闭合圈线。请在编辑模式中选中一个完整闭合边环。"

    local_center = centroid_from_verts(loop_verts)
    local_normal = newell_normal(loop_verts)

    world_positions = [obj.matrix_world @ v.co for v in loop_verts]
    world_center = obj.matrix_world @ local_center
    world_normal = obj.matrix_world.to_3x3() @ local_normal
    world_normal = safe_normalized(world_normal)

    # 用闭合圈线中距离最远的两个点作为横向参考方向，适合合页轴槽自动判断方向。
    tangent = None
    max_dist = 0.0
    for i in range(len(world_positions)):
        for j in range(i + 1, len(world_positions)):
            delta = world_positions[j] - world_positions[i]
            # 去掉法向分量，保证 tangent 尽量落在圈线平面内。
            planar = delta - world_normal * delta.dot(world_normal)
            dist = planar.length
            if dist > max_dist:
                max_dist = dist
                tangent = planar

    if not tangent or tangent.length <= 1e-8:
        tangent, _ = orthonormal_basis_from_axis(world_normal)
    else:
        tangent.normalize()

    bitangent = world_normal.cross(tangent)
    bitangent = safe_normalized(bitangent)

    avg_radius = 0.0
    tangent_values = []
    bitangent_values = []

    for co in world_positions:
        offset = co - world_center
        planar = offset - world_normal * offset.dot(world_normal)
        avg_radius += planar.length
        tangent_values.append(planar.dot(tangent))
        bitangent_values.append(planar.dot(bitangent))

    avg_radius = avg_radius / max(len(world_positions), 1)
    tangent_extent = (max(tangent_values) - min(tangent_values)) if tangent_values else avg_radius * 2.0
    bitangent_extent = (max(bitangent_values) - min(bitangent_values)) if bitangent_values else avg_radius * 2.0
    major_extent = max(tangent_extent, bitangent_extent, avg_radius * 2.0)
    minor_extent = max(min(tangent_extent, bitangent_extent), avg_radius * 0.25)

    frame = {
        "source_object": obj,
        "center": world_center,
        "normal": world_normal,
        "tangent": tangent,
        "bitangent": bitangent,
        "avg_radius_bu": avg_radius,
        "avg_diameter_bu": avg_radius * 2.0,
        "tangent_extent_bu": tangent_extent,
        "bitangent_extent_bu": bitangent_extent,
        "major_extent_bu": major_extent,
        "minor_extent_bu": minor_extent,
        "loop_count": len(loop_verts),
    }
    return frame, ""


def frame_dimension_summary_mm(scene, frame):
    avg_radius_mm = bu_to_mm(scene, frame.get("avg_radius_bu", 0.0))
    avg_diameter_mm = bu_to_mm(scene, frame.get("avg_diameter_bu", 0.0))
    major_mm = bu_to_mm(scene, frame.get("major_extent_bu", 0.0))
    minor_mm = bu_to_mm(scene, frame.get("minor_extent_bu", 0.0))
    return avg_radius_mm, avg_diameter_mm, major_mm, minor_mm


def joint_auto_mode_text(scene):
    return "自动尺寸" if getattr(scene, "seanixz_pro_joint_auto_size", True) else "手动尺寸"


def calculate_joint_pin_values_mm(scene, frame):
    avg_radius_mm, avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)

    if scene.seanixz_pro_joint_auto_size:
        base_radius = max(avg_radius_mm, min(major_mm, minor_mm) * 0.5, 0.1)
        length = max(
            avg_diameter_mm * scene.seanixz_pro_joint_auto_depth_factor,
            scene.seanixz_pro_joint_depth_mm,
            base_radius * 4.0,
            1.0,
        ) + scene.seanixz_pro_joint_assembly_margin_mm * 2.0
    else:
        base_radius = scene.seanixz_pro_joint_pin_radius_mm
        length = scene.seanixz_pro_joint_depth_mm

    cutter_radius = max(base_radius + scene.seanixz_pro_joint_clearance_mm, 0.001)
    length = max(length, 0.001)
    return base_radius, cutter_radius, length


def calculate_joint_disc_values_mm(scene, frame):
    avg_radius_mm, avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)

    if scene.seanixz_pro_joint_auto_size:
        base_radius = max(avg_radius_mm, major_mm * 0.5, 0.1)
        disc_thickness = max(
            avg_diameter_mm * 0.35,
            scene.seanixz_pro_joint_clearance_mm * 2.0 + scene.seanixz_pro_joint_assembly_margin_mm,
            1.0,
        )
    else:
        base_radius = scene.seanixz_pro_joint_disc_radius_mm
        disc_thickness = scene.seanixz_pro_joint_disc_thickness_mm

    cutter_radius = max(base_radius + scene.seanixz_pro_joint_clearance_mm, 0.001)
    cutter_thickness = max(disc_thickness + scene.seanixz_pro_joint_clearance_mm * 2.0 + scene.seanixz_pro_joint_assembly_margin_mm * 2.0, 0.001)
    return base_radius, cutter_radius, disc_thickness, cutter_thickness


def calculate_joint_hinge_values_mm(scene, frame):
    avg_radius_mm, avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)

    if scene.seanixz_pro_joint_auto_size:
        base_radius = max(minor_mm * 0.5, avg_radius_mm * 0.45, 0.1)
        length = max(
            major_mm + scene.seanixz_pro_joint_assembly_margin_mm * 2.0,
            base_radius * 4.0,
            scene.seanixz_pro_joint_hinge_length_mm,
            1.0,
        )
    else:
        base_radius = scene.seanixz_pro_joint_hinge_radius_mm
        length = scene.seanixz_pro_joint_hinge_length_mm

    cutter_radius = max(base_radius + scene.seanixz_pro_joint_clearance_mm, 0.001)
    return base_radius, cutter_radius, max(length, 0.001)


def calculate_joint_ball_values_mm(scene, frame):
    avg_radius_mm, avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)

    if scene.seanixz_pro_joint_auto_size:
        base_radius = max(avg_radius_mm, major_mm * 0.5, 0.1)
        neck_base_radius = max(base_radius * 0.55, scene.seanixz_pro_joint_clearance_mm + 0.2)
        neck_length = max(base_radius * 1.45, scene.seanixz_pro_joint_assembly_margin_mm * 2.0, 1.0)
    else:
        base_radius = scene.seanixz_pro_joint_ball_radius_mm
        neck_base_radius = scene.seanixz_pro_joint_ball_neck_radius_mm
        neck_length = scene.seanixz_pro_joint_ball_neck_length_mm

    cutter_radius = max(base_radius + scene.seanixz_pro_joint_clearance_mm, 0.001)
    neck_radius = max(neck_base_radius + scene.seanixz_pro_joint_clearance_mm, 0.001)
    neck_length = max(neck_length + scene.seanixz_pro_joint_assembly_margin_mm, 0.001)
    return base_radius, cutter_radius, neck_base_radius, neck_radius, neck_length


def select_created_cutter(context, obj):
    ensure_object_mode()
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj
    context.view_layer.update()


def make_joint_pin_cutter(context):
    scene = context.scene
    frame, error = selected_loop_world_frame(context)

    if not frame:
        return None, error

    base_radius_mm, cutter_radius_mm, length_mm = calculate_joint_pin_values_mm(scene, frame)
    # 装配导入口：在孔两端增加轻微喇叭口，打印后的轴更容易插入。
    lead_mm = max(min(scene.seanixz_pro_joint_assembly_margin_mm + scene.seanixz_pro_joint_clearance_mm, length_mm * 0.18), 0.0)
    lead_radius_mm = cutter_radius_mm + scene.seanixz_pro_joint_assembly_margin_mm

    radius = cutter_radius_mm * mm_to_bu(scene)
    length = length_mm * mm_to_bu(scene)
    lead = lead_mm * mm_to_bu(scene)
    lead_radius = lead_radius_mm * mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments

    center = frame["center"]
    axis = frame["normal"]
    verts = []
    faces = []
    cyl_verts, cyl_faces = cylinder_mesh_data(center, axis, radius, length, segments, cap=True)
    append_mesh_data(verts, faces, cyl_verts, cyl_faces)

    if lead > 0:
        upper_center = center + axis * (length * 0.5 - lead * 0.5)
        upper_verts, upper_faces = cone_frustum_mesh_data(upper_center, axis, radius, lead_radius, lead, segments, cap=True)
        append_mesh_data(verts, faces, upper_verts, upper_faces)

        lower_center = center - axis * (length * 0.5 - lead * 0.5)
        lower_verts, lower_faces = cone_frustum_mesh_data(lower_center, axis, lead_radius, radius, lead, segments, cap=True)
        append_mesh_data(verts, faces, lower_verts, lower_faces)

    obj = create_mesh_object_from_data(context, "SeanIXz_Joint_PinHole_Cutter", verts, faces, display_mode='WIRE')
    obj["seanixz_pro_joint_cutter_type"] = "pin_hole"
    select_created_cutter(context, obj)

    avg_radius_mm, avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)
    msg = (
        f"圆轴孔切刀完成（{joint_auto_mode_text(scene)}）：圈线约 {major_mm:.2f}×{minor_mm:.2f} mm，"
        f"基础轴半径 {base_radius_mm:.2f} mm，切刀半径 {cutter_radius_mm:.2f} mm，长度 {length_mm:.2f} mm。\n"
        f"已加入装配导入口约 {lead_mm:.2f} mm，方便插入轴件。"
    )
    return obj, msg


def make_joint_disc_clearance_cutter(context):
    scene = context.scene
    frame, error = selected_loop_world_frame(context)

    if not frame:
        return None, error

    base_radius_mm, cutter_radius_mm, disc_thickness_mm, cutter_thickness_mm = calculate_joint_disc_values_mm(scene, frame)
    # 大范围活动空间：在自动/手动半径基础上按摆动空间系数放大切刀半径。
    swing_radius_mm = max(cutter_radius_mm * scene.seanixz_pro_joint_swing_room_factor, cutter_radius_mm)

    radius = swing_radius_mm * mm_to_bu(scene)
    length = cutter_thickness_mm * mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments

    center = frame["center"]
    axis = frame["normal"]
    verts, faces = cylinder_mesh_data(center, axis, radius, length, segments, cap=True)

    # 在最长方向上额外叠加一个圆柱，形成更接近“胶囊状/长圆形”的活动槽，摆臂有更大活动范围。
    slot_length_mm = max(swing_radius_mm * 2.0, frame_dimension_summary_mm(scene, frame)[2] + scene.seanixz_pro_joint_assembly_margin_mm * 2.0)
    slot_verts, slot_faces = cylinder_mesh_data(center, frame["tangent"], radius * 0.55, slot_length_mm * mm_to_bu(scene), segments, cap=True)
    append_mesh_data(verts, faces, slot_verts, slot_faces)

    obj = create_mesh_object_from_data(context, "SeanIXz_Joint_Disc_Clearance_Cutter", verts, faces, display_mode='WIRE')
    obj["seanixz_pro_joint_cutter_type"] = "disc_clearance"
    select_created_cutter(context, obj)

    avg_radius_mm, avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)
    msg = (
        f"圆盘活动间隙切刀完成（{joint_auto_mode_text(scene)}）：圈线约 {major_mm:.2f}×{minor_mm:.2f} mm，"
        f"基础圆盘半径 {base_radius_mm:.2f} mm，活动切刀半径 {swing_radius_mm:.2f} mm，厚度 {cutter_thickness_mm:.2f} mm。\n"
        "已额外加入长圆形摆动间隙，适合让关节获得更大转动/摆动范围。"
    )
    return obj, msg


def make_joint_hinge_barrel_cutter(context):
    scene = context.scene
    frame, error = selected_loop_world_frame(context)

    if not frame:
        return None, error

    base_radius_mm, cutter_radius_mm, length_mm = calculate_joint_hinge_values_mm(scene, frame)
    swing_radius_mm = max(cutter_radius_mm * scene.seanixz_pro_joint_swing_room_factor, cutter_radius_mm)

    radius = swing_radius_mm * mm_to_bu(scene)
    length = length_mm * mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments

    center = frame["center"]
    axis = frame["tangent"]
    verts, faces = cylinder_mesh_data(center, axis, radius, length, segments, cap=True)

    # 合页轴槽常需要一点开口活动量：沿法向增加一个浅槽，让铰链摆动时不容易顶死。
    opening_depth_mm = max(cutter_radius_mm * scene.seanixz_pro_joint_swing_room_factor, cutter_radius_mm + scene.seanixz_pro_joint_clearance_mm)
    open_center = center + frame["normal"] * (opening_depth_mm * 0.35 * mm_to_bu(scene))
    open_verts, open_faces = cylinder_mesh_data(open_center, axis, radius * 0.72, length, segments, cap=True)
    append_mesh_data(verts, faces, open_verts, open_faces)

    obj = create_mesh_object_from_data(context, "SeanIXz_Joint_Hinge_Barrel_Cutter", verts, faces, display_mode='WIRE')
    obj["seanixz_pro_joint_cutter_type"] = "hinge_barrel"
    select_created_cutter(context, obj)

    avg_radius_mm, avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)
    msg = (
        f"横向合页轴槽切刀完成（{joint_auto_mode_text(scene)}）：圈线约 {major_mm:.2f}×{minor_mm:.2f} mm，"
        f"基础轴半径 {base_radius_mm:.2f} mm，切刀半径 {swing_radius_mm:.2f} mm，长度 {length_mm:.2f} mm。\n"
        "方向按所选圈线最长方向自动判断，并加入浅开口活动量，减少大角度摆动时顶死。"
    )
    return obj, msg


def make_joint_ball_socket_cutter(context):
    scene = context.scene
    frame, error = selected_loop_world_frame(context)

    if not frame:
        return None, error

    base_radius_mm, cutter_radius_mm, neck_base_radius_mm, neck_radius_mm, neck_length_mm = calculate_joint_ball_values_mm(scene, frame)
    swing_radius_mm = max(cutter_radius_mm * scene.seanixz_pro_joint_swing_room_factor, cutter_radius_mm)
    swing_channel_radius_mm = max(neck_radius_mm, cutter_radius_mm * 0.46)

    radius = cutter_radius_mm * mm_to_bu(scene)
    swing_radius = swing_radius_mm * mm_to_bu(scene)
    neck_radius = neck_radius_mm * mm_to_bu(scene)
    neck_length = neck_length_mm * mm_to_bu(scene)
    swing_channel_radius = swing_channel_radius_mm * mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments

    center = frame["center"]
    axis = frame["normal"]

    verts = []
    faces = []
    sphere_verts, sphere_faces = sphere_mesh_data(center, radius, segments=segments, rings=max(8, segments // 2))
    append_mesh_data(verts, faces, sphere_verts, sphere_faces)

    # 装配开口：沿法向给球头进入空间。
    neck_center = center + axis * (neck_length * 0.5)
    neck_verts, neck_faces = cylinder_mesh_data(neck_center, axis, neck_radius, neck_length + radius, segments, cap=True)
    append_mesh_data(verts, faces, neck_verts, neck_faces)

    # 大范围活动间隙：横向切出两个交叉摆动通道，让球头或摆臂有更大偏转角。
    swing_len = swing_radius * 2.2
    t_verts, t_faces = cylinder_mesh_data(center, frame["tangent"], swing_channel_radius, swing_len, segments, cap=True)
    append_mesh_data(verts, faces, t_verts, t_faces)
    b_verts, b_faces = cylinder_mesh_data(center, frame["bitangent"], swing_channel_radius * 0.82, swing_len * 0.92, segments, cap=True)
    append_mesh_data(verts, faces, b_verts, b_faces)

    obj = create_mesh_object_from_data(context, "SeanIXz_Joint_BallSocket_Cutter", verts, faces, display_mode='WIRE')
    obj["seanixz_pro_joint_cutter_type"] = "ball_socket"
    select_created_cutter(context, obj)

    avg_radius_mm, avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)
    msg = (
        f"球窝关节切刀完成（{joint_auto_mode_text(scene)}）：圈线约 {major_mm:.2f}×{minor_mm:.2f} mm，"
        f"基础球半径 {base_radius_mm:.2f} mm，切刀球窝半径 {cutter_radius_mm:.2f} mm，开口半径 {neck_radius_mm:.2f} mm。\n"
        "已加入装配开口和交叉摆动通道，适合需要更大活动角度的球窝/摆动关节。"
    )
    return obj, msg


def oriented_box_mesh_data(center, axis_x, axis_y, axis_z, length, width, height):
    """Create a rectangular box with local X/Y/Z axes."""
    x = safe_normalized(axis_x, Vector((1.0, 0.0, 0.0))) * (max(length, 0.000001) * 0.5)
    y = safe_normalized(axis_y, Vector((0.0, 1.0, 0.0))) * (max(width, 0.000001) * 0.5)
    z = safe_normalized(axis_z, Vector((0.0, 0.0, 1.0))) * (max(height, 0.000001) * 0.5)
    verts = [
        center - x - y - z,
        center + x - y - z,
        center + x + y - z,
        center - x + y - z,
        center - x - y + z,
        center + x - y + z,
        center + x + y + z,
        center - x + y + z,
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    ]
    return verts, faces


def oriented_box_frustum_mesh_data(
    center,
    axis_x,
    axis_y,
    axis_z,
    bottom_length,
    bottom_width,
    top_length,
    top_width,
    height,
):
    """创建沿 axis_z 延伸的四边锥台，用于可打印的榫头和带导角的榫槽。"""
    x_axis = safe_normalized(axis_x, Vector((1.0, 0.0, 0.0)))
    y_axis = safe_normalized(axis_y, Vector((0.0, 1.0, 0.0)))
    z_axis = safe_normalized(axis_z, Vector((0.0, 0.0, 1.0)))
    half_h = max(height, 0.000001) * 0.5
    bottom_center = center - z_axis * half_h
    top_center = center + z_axis * half_h
    bx = x_axis * (max(bottom_length, 0.000001) * 0.5)
    by = y_axis * (max(bottom_width, 0.000001) * 0.5)
    tx = x_axis * (max(top_length, 0.000001) * 0.5)
    ty = y_axis * (max(top_width, 0.000001) * 0.5)

    verts = [
        bottom_center - bx - by,
        bottom_center + bx - by,
        bottom_center + bx + by,
        bottom_center - bx + by,
        top_center - tx - ty,
        top_center + tx - ty,
        top_center + tx + ty,
        top_center - tx + ty,
    ]
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return verts, faces


def calculate_hi3d_joint_values_mm(scene, frame):
    """把参考页面的尺寸/松紧度/连接深度映射到当前圈线的真实毫米尺寸。"""
    _avg_radius_mm, _avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)

    if scene.seanixz_pro_joint_auto_size:
        size_mm = max(
            min(major_mm, minor_mm) * scene.seanixz_pro_joint_size_factor,
            getattr(scene, "seanixz_pro_joint_min_print_size_mm", 3.0),
        )
    else:
        size_mm = max(scene.seanixz_pro_joint_size_mm, 0.2)

    clearance_mm = max(scene.seanixz_pro_joint_clearance_mm, 0.0)
    depth_mm = max(scene.seanixz_pro_joint_connection_depth_mm, size_mm * 0.55, 0.5)
    angle_deg = max(min(scene.seanixz_pro_joint_angle_deg, 80.0), 5.0)
    return size_mm, clearance_mm, depth_mm, angle_deg, major_mm, minor_mm


def append_integrated_joint_separation_cutter(scene, frame, verts, faces, size_mm, clearance_mm):
    """把接缝分离薄片并入关节母槽切刀，使一次布尔同时完成分件和关节腔。"""
    unit = mm_to_bu(scene)
    center = frame["center"]
    normal = safe_normalized(frame["normal"])
    tangent = safe_normalized(frame["tangent"])
    bitangent = safe_normalized(frame["bitangent"])

    expand_factor = max(getattr(scene, "seanixz_pro_joint_split_expand_factor", 1.08), 1.0)
    expand_mm = max(getattr(scene, "seanixz_pro_joint_split_expand_mm", 1.0), 0.0)
    activity_extra_mm = max(
        (getattr(scene, "seanixz_pro_joint_swing_room_factor", 1.0) - 1.0) * size_mm * 0.25,
        0.0,
    )
    tangent_extent = max(frame.get("tangent_extent_bu", 0.0), size_mm * 1.25 * unit)
    bitangent_extent = max(frame.get("bitangent_extent_bu", 0.0), size_mm * 1.25 * unit)
    split_length = tangent_extent * expand_factor + (expand_mm + activity_extra_mm) * 2.0 * unit
    split_width = bitangent_extent * expand_factor + (expand_mm + activity_extra_mm) * 2.0 * unit
    split_thickness_mm = max(
        getattr(scene, "seanixz_pro_joint_split_thickness_mm", 0.8),
        clearance_mm * 2.0 + 0.25,
    )
    split_verts, split_faces = oriented_box_mesh_data(
        center,
        tangent,
        bitangent,
        normal,
        split_length,
        split_width,
        split_thickness_mm * unit,
    )
    append_mesh_data(verts, faces, split_verts, split_faces)
    return (
        bu_to_mm(scene, split_length),
        bu_to_mm(scene, split_width),
        split_thickness_mm,
    )


def fuse_integrated_joint_cutter(context, obj, scene, clearance_mm):
    """用细体素把相交的分离片、关节腔和装配入口融合为真正单一的流形切刀。"""
    if not getattr(scene, "seanixz_pro_joint_fuse_integrated_cutter", True):
        return False
    ensure_object_mode()
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj
    voxel_mm = min(max(clearance_mm / 3.0, 0.06), 0.15)
    modifier = obj.modifiers.new("SeanIXz_一体式切刀融合", 'REMESH')
    modifier.mode = 'VOXEL'
    modifier.voxel_size = max(voxel_mm * mm_to_bu(scene), 0.000001)
    modifier.adaptivity = 0.0
    fused = apply_modifier(context, obj, modifier.name)
    obj["seanixz_pro_integrated_cutter_fused"] = bool(fused)
    obj["seanixz_pro_integrated_cutter_voxel_mm"] = voxel_mm
    return fused


def union_joint_split_slab(context, target, slab_verts, slab_faces):
    """把保持精确平面的分离薄片并入已融合的关节腔，避免体素边缘在接缝产生碎屑。"""
    mesh = bpy.data.meshes.new("SeanIXz_临时分离薄片_Mesh")
    mesh.from_pydata([tuple(v) for v in slab_verts], [], slab_faces)
    mesh.update()
    slab = bpy.data.objects.new("SeanIXz_临时分离薄片", mesh)
    context.scene.collection.objects.link(slab)
    modifier = target.modifiers.new("SeanIXz_并入精确分离薄片", 'BOOLEAN')
    modifier.operation = 'UNION'
    modifier.solver = 'EXACT'
    modifier.object = slab
    success = apply_modifier(context, target, modifier.name)
    bpy.data.objects.remove(slab, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    target["seanixz_pro_split_slab_unioned"] = bool(success)
    return success


def fuse_print_ready_joint_connector(context, obj, scene, clearance_mm):
    """融合连接件中相交的球头、杆、插销或转轴，输出可直接切片的单一流形网格。"""
    if not getattr(scene, "seanixz_pro_joint_fuse_print_connector", True):
        return False
    ensure_object_mode()
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj
    voxel_mm = min(max(clearance_mm / 3.0, 0.06), 0.12)
    modifier = obj.modifiers.new("SeanIXz_可打印连接件融合", 'REMESH')
    modifier.mode = 'VOXEL'
    modifier.voxel_size = max(voxel_mm * mm_to_bu(scene), 0.000001)
    modifier.adaptivity = 0.0
    fused = apply_modifier(context, obj, modifier.name)
    obj["seanixz_pro_print_connector_fused"] = bool(fused)
    obj["seanixz_pro_print_connector_voxel_mm"] = voxel_mm
    return fused


def hi3d_joint_direction(frame, scene):
    if scene.seanixz_pro_joint_direction == 'B_TO_A':
        return -frame["normal"], "B", "A"

    return frame["normal"], "A", "B"


def build_hi3d_ball_joint_meshes(scene, frame, axis, size_mm, clearance_mm, depth_mm, angle_deg):
    unit = mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments
    center = frame["center"]
    tangent = frame["tangent"]
    bitangent = frame["bitangent"]

    ball_radius = size_mm * 0.5 * unit
    clearance = clearance_mm * unit
    socket_radius = ball_radius + clearance
    stem_radius = max(size_mm * 0.2, 0.35) * unit
    center_offset = max(depth_mm, size_mm * 0.62) * unit
    anchor_depth = max(size_mm * 0.24, 0.6) * unit
    ball_center = center + axis * center_offset

    male_verts = []
    male_faces = []
    stem_start = center - axis * anchor_depth
    stem_length = (ball_center - stem_start).length
    stem_center = (ball_center + stem_start) * 0.5
    stem_verts, stem_faces = cylinder_mesh_data(
        stem_center,
        axis,
        stem_radius,
        stem_length,
        segments,
        cap=True,
    )
    append_mesh_data(male_verts, male_faces, stem_verts, stem_faces)
    ball_verts, ball_faces = sphere_mesh_data(
        ball_center,
        ball_radius,
        segments=segments,
        rings=max(8, segments // 2),
    )
    append_mesh_data(male_verts, male_faces, ball_verts, ball_faces)
    base_verts, base_faces = cylinder_mesh_data(
        center - axis * (anchor_depth * 0.45),
        axis,
        ball_radius * 0.76,
        anchor_depth,
        segments,
        cap=True,
    )
    append_mesh_data(male_verts, male_faces, base_verts, base_faces)

    female_verts = []
    female_faces = []
    socket_verts, socket_faces = sphere_mesh_data(
        ball_center,
        socket_radius,
        segments=segments,
        rings=max(8, segments // 2),
    )
    append_mesh_data(female_verts, female_faces, socket_verts, socket_faces)

    # 角度设置：从球心向装配面生成锥形摆动空间。
    channel_length = max(center_offset + socket_radius * 0.2, socket_radius)
    channel_center = ball_center - axis * (channel_length * 0.5)
    throat_radius = max(stem_radius + clearance, ball_radius * 0.34)
    opening_radius = max(
        throat_radius + math.tan(math.radians(angle_deg)) * channel_length,
        throat_radius + clearance,
    )
    swing_verts, swing_faces = cone_frustum_mesh_data(
        channel_center,
        -axis,
        throat_radius,
        opening_radius,
        channel_length,
        segments,
        cap=True,
    )
    append_mesh_data(female_verts, female_faces, swing_verts, swing_faces)

    # 两个轻量横向释放槽，避免球杆在对角摆动时卡住。
    relief_radius = max(stem_radius + clearance, socket_radius * 0.27)
    relief_length = socket_radius * 2.15
    t_verts, t_faces = cylinder_mesh_data(ball_center, tangent, relief_radius, relief_length, segments, cap=True)
    b_verts, b_faces = cylinder_mesh_data(ball_center, bitangent, relief_radius, relief_length, segments, cap=True)
    append_mesh_data(female_verts, female_faces, t_verts, t_faces)
    append_mesh_data(female_verts, female_faces, b_verts, b_faces)
    return male_verts, male_faces, female_verts, female_faces


def build_figure_ball_link_joint_meshes(scene, frame, axis, size_mm, clearance_mm, depth_mm, angle_deg):
    """生成可独立打印的球头连接件，以及球窝、固定插孔和接缝切刀所需腔体。

    球头位于 B 侧，带导入倒角的固定插销位于 A 侧。布尔后先把插销压入或粘入
    A 侧零件，再把 B 侧球窝压到球头上，避免要求用户把球头永久并集到肢体。
    """
    unit = mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments
    center = frame["center"]
    axis = safe_normalized(axis)

    ball_radius = max(size_mm * 0.5, 0.2) * unit
    clearance = max(clearance_mm, 0.0) * unit
    assembly_margin = max(scene.seanixz_pro_joint_assembly_margin_mm, 0.0) * unit
    socket_radius = ball_radius + clearance
    stem_radius = max(size_mm * 0.20, 0.55) * unit
    peg_radius = max(size_mm * 0.27, 0.75) * unit
    ball_offset = max(depth_mm * 0.48, size_mm * 0.68, 1.0) * unit
    peg_length = max(depth_mm * 0.62, size_mm * 0.78, 1.5) * unit
    ball_center = center + axis * ball_offset
    peg_center = center - axis * (peg_length * 0.50)

    male_verts = []
    male_faces = []
    link_start = center - axis * peg_length
    link_length = (ball_center - link_start).length
    link_center = (ball_center + link_start) * 0.5
    stem_verts, stem_faces = cylinder_mesh_data(
        link_center, axis, stem_radius, link_length, segments, cap=True
    )
    append_mesh_data(male_verts, male_faces, stem_verts, stem_faces)
    ball_verts, ball_faces = sphere_mesh_data(
        ball_center, ball_radius, segments=segments, rings=max(8, segments // 2)
    )
    append_mesh_data(male_verts, male_faces, ball_verts, ball_faces)
    peg_verts, peg_faces = cone_frustum_mesh_data(
        peg_center,
        axis,
        max(peg_radius * 0.90, stem_radius),
        peg_radius,
        peg_length,
        segments,
        cap=True,
    )
    append_mesh_data(male_verts, male_faces, peg_verts, peg_faces)
    collar_length = max(size_mm * 0.12, 0.45) * unit
    collar_verts, collar_faces = cylinder_mesh_data(
        center - axis * (collar_length * 0.5),
        axis,
        max(peg_radius * 1.18, ball_radius * 0.62),
        collar_length,
        segments,
        cap=True,
    )
    append_mesh_data(male_verts, male_faces, collar_verts, collar_faces)

    female_verts = []
    female_faces = []
    socket_verts, socket_faces = sphere_mesh_data(
        ball_center, socket_radius, segments=segments, rings=max(8, segments // 2)
    )
    append_mesh_data(female_verts, female_faces, socket_verts, socket_faces)
    channel_length = max(ball_offset + socket_radius * 0.18, socket_radius)
    throat_radius = max(
        stem_radius + clearance,
        ball_radius * scene.seanixz_pro_joint_lock_throat_factor + clearance,
    )
    opening_radius = min(
        max(
            throat_radius + math.tan(math.radians(angle_deg)) * min(channel_length, socket_radius * 1.35),
            throat_radius + assembly_margin,
        ),
        socket_radius * 1.38,
    )
    swing_verts, swing_faces = cone_frustum_mesh_data(
        ball_center - axis * (channel_length * 0.5),
        -axis,
        throat_radius,
        opening_radius,
        channel_length,
        segments,
        cap=True,
    )
    append_mesh_data(female_verts, female_faces, swing_verts, swing_faces)

    peg_socket_radius = peg_radius + clearance + assembly_margin * 0.35
    peg_socket_length = peg_length + assembly_margin + clearance * 2.0
    peg_socket_verts, peg_socket_faces = cylinder_mesh_data(
        center - axis * (peg_socket_length * 0.5),
        axis,
        peg_socket_radius,
        peg_socket_length,
        segments,
        cap=True,
    )
    append_mesh_data(female_verts, female_faces, peg_socket_verts, peg_socket_faces)
    lead_length = max(assembly_margin * 1.8, 0.6 * unit)
    lead_verts, lead_faces = cone_frustum_mesh_data(
        center - axis * (lead_length * 0.5),
        axis,
        peg_socket_radius + assembly_margin,
        peg_socket_radius,
        lead_length,
        segments,
        cap=True,
    )
    append_mesh_data(female_verts, female_faces, lead_verts, lead_faces)
    return male_verts, male_faces, female_verts, female_faces


def build_figure_double_ball_joint_meshes(scene, frame, axis, size_mm, clearance_mm, depth_mm, angle_deg):
    """生成可动手办常用的双球头连杆和两端球窝组合切刀。

    两颗球头分布在装配面两侧，中间以短杆连接；蓝色母槽对象包含两端球窝，
    可分别对上、下或左、右两个肢体零件执行布尔差集。
    """
    unit = mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments
    center = frame["center"]
    axis = safe_normalized(axis)

    ball_radius = max(size_mm * 0.5, 0.2) * unit
    clearance = max(clearance_mm, 0.0) * unit
    socket_radius = ball_radius + clearance
    stem_radius = max(size_mm * 0.19, 0.35) * unit
    center_distance = max(depth_mm, size_mm * 1.55, 1.0) * unit
    half_distance = center_distance * 0.5
    ball_centers = (
        center - axis * half_distance,
        center + axis * half_distance,
    )

    male_verts = []
    male_faces = []
    link_verts, link_faces = cylinder_mesh_data(
        center,
        axis,
        stem_radius,
        center_distance,
        segments,
        cap=True,
    )
    append_mesh_data(male_verts, male_faces, link_verts, link_faces)

    collar_radius = max(stem_radius * 1.35, ball_radius * 0.48)
    collar_length = max(ball_radius * 0.30, 0.35 * unit)
    for ball_center in ball_centers:
        ball_verts, ball_faces = sphere_mesh_data(
            ball_center,
            ball_radius,
            segments=segments,
            rings=max(8, segments // 2),
        )
        append_mesh_data(male_verts, male_faces, ball_verts, ball_faces)

        sign_axis = safe_normalized(ball_center - center, axis)
        collar_center = ball_center - sign_axis * (ball_radius * 0.58)
        collar_verts, collar_faces = cylinder_mesh_data(
            collar_center,
            sign_axis,
            collar_radius,
            collar_length,
            segments,
            cap=True,
        )
        append_mesh_data(male_verts, male_faces, collar_verts, collar_faces)

    female_verts = []
    female_faces = []
    swing_angle = math.radians(max(min(angle_deg, 75.0), 5.0))
    channel_length = max(half_distance, socket_radius * 0.95)
    throat_radius = max(stem_radius + clearance, ball_radius * 0.36)
    opening_radius = max(
        throat_radius + math.tan(swing_angle) * min(channel_length, socket_radius * 1.45),
        throat_radius + clearance,
    )
    opening_radius = min(opening_radius, socket_radius * 1.45)

    for ball_center in ball_centers:
        socket_verts, socket_faces = sphere_mesh_data(
            ball_center,
            socket_radius,
            segments=segments,
            rings=max(8, segments // 2),
        )
        append_mesh_data(female_verts, female_faces, socket_verts, socket_faces)

        sign_axis = safe_normalized(ball_center - center, axis)
        channel_center = ball_center - sign_axis * (channel_length * 0.5)
        swing_verts, swing_faces = cone_frustum_mesh_data(
            channel_center,
            -sign_axis,
            throat_radius,
            opening_radius,
            channel_length,
            segments,
            cap=True,
        )
        append_mesh_data(female_verts, female_faces, swing_verts, swing_faces)

    return male_verts, male_faces, female_verts, female_faces


def build_figure_double_hinge_joint_meshes(scene, frame, axis, size_mm, clearance_mm, depth_mm):
    """生成肘、膝常用的双转轴中央连杆与两端活动腔切刀。

    绿色对象是独立打印的中央连接器；蓝色对象同时包含两个转轴孔和朝装配面
    打开的摆动槽，可分别用于上、下肢体零件的布尔差集。
    """
    unit = mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments
    center = frame["center"]
    assembly_axis = safe_normalized(axis)
    if scene.seanixz_pro_joint_hinge_axis == 'SHORT':
        hinge_axis = safe_normalized(frame["bitangent"])
    else:
        hinge_axis = safe_normalized(frame["tangent"])
    cross_axis = safe_normalized(hinge_axis.cross(assembly_axis))

    size = max(size_mm, 0.2) * unit
    clearance = max(clearance_mm, 0.0) * unit
    pivot_distance = max(depth_mm, size_mm * 1.55, 1.0) * unit
    half_distance = pivot_distance * 0.5
    pin_radius = max(size * 0.18, 0.35 * unit)
    pin_length = max(size * 1.05, depth_mm * 0.72 * unit, 1.0 * unit)
    bridge_width = max(pin_length * 0.48, size * 0.62)
    bridge_thickness = max(pin_radius * 1.55, 0.55 * unit)
    pivot_centers = (
        center - assembly_axis * half_distance,
        center + assembly_axis * half_distance,
    )

    male_verts = []
    male_faces = []
    bridge_verts, bridge_faces = oriented_box_mesh_data(
        center,
        assembly_axis,
        hinge_axis,
        cross_axis,
        pivot_distance,
        bridge_width,
        bridge_thickness,
    )
    append_mesh_data(male_verts, male_faces, bridge_verts, bridge_faces)

    flange_radius = max(pin_radius * 1.55, size * 0.33)
    flange_thickness = max(size * 0.12, 0.30 * unit)
    for pivot_center in pivot_centers:
        pin_verts, pin_faces = cylinder_mesh_data(
            pivot_center,
            hinge_axis,
            pin_radius,
            pin_length,
            segments,
            cap=True,
        )
        append_mesh_data(male_verts, male_faces, pin_verts, pin_faces)

        for sign in (-1.0, 1.0):
            flange_center = pivot_center + hinge_axis * sign * (pin_length * 0.5 - flange_thickness * 0.5)
            flange_verts, flange_faces = cylinder_mesh_data(
                flange_center,
                hinge_axis,
                flange_radius,
                flange_thickness,
                segments,
                cap=True,
            )
            append_mesh_data(male_verts, male_faces, flange_verts, flange_faces)

    female_verts = []
    female_faces = []
    bore_radius = pin_radius + clearance
    bore_length = pin_length + clearance * 2.0 + max(0.2 * unit, clearance)
    # 径向 C 形装配入口：开口贯穿轴向宽度，入口略小于轴径，既能侧向压入又保留锁口。
    slot_width = bore_length
    throat_factor = max(min(scene.seanixz_pro_joint_lock_throat_factor, 0.94), 0.58)
    slot_height = max(
        pin_radius * 2.0 * throat_factor + clearance * 2.0,
        bridge_thickness + clearance * 2.0,
    )
    slot_length = half_distance + bore_radius * scene.seanixz_pro_joint_swing_room_factor

    for pivot_center in pivot_centers:
        bore_verts, bore_faces = cylinder_mesh_data(
            pivot_center,
            hinge_axis,
            bore_radius,
            bore_length,
            segments,
            cap=True,
        )
        append_mesh_data(female_verts, female_faces, bore_verts, bore_faces)

        toward_center = safe_normalized(center - pivot_center, assembly_axis)
        slot_center = pivot_center + toward_center * (slot_length * 0.5)
        slot_verts, slot_faces = oriented_box_mesh_data(
            slot_center,
            toward_center,
            hinge_axis,
            cross_axis,
            slot_length,
            slot_width,
            slot_height,
        )
        append_mesh_data(female_verts, female_faces, slot_verts, slot_faces)

        relief_radius = flange_radius + clearance
        relief_length = flange_thickness + clearance * 2.0 + max(0.15 * unit, clearance)
        for sign in (-1.0, 1.0):
            flange_center = pivot_center + hinge_axis * sign * (pin_length * 0.5 - flange_thickness * 0.5)
            relief_verts, relief_faces = cylinder_mesh_data(
                flange_center,
                hinge_axis,
                relief_radius,
                relief_length,
                segments,
                cap=True,
            )
            append_mesh_data(female_verts, female_faces, relief_verts, relief_faces)

    return male_verts, male_faces, female_verts, female_faces


def build_hi3d_rivet_joint_meshes(scene, frame, axis, size_mm, clearance_mm, depth_mm):
    unit = mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments
    center = frame["center"]
    head_radius = size_mm * 0.5 * unit
    shaft_radius = max(size_mm * 0.22, 0.3) * unit
    clearance = clearance_mm * unit
    depth = max(depth_mm, size_mm * 0.8) * unit
    anchor_depth = max(size_mm * 0.22, 0.5) * unit
    bulb_center = center + axis * depth

    male_verts = []
    male_faces = []
    shaft_start = center - axis * anchor_depth
    shaft_center = (shaft_start + bulb_center) * 0.5
    shaft_verts, shaft_faces = cylinder_mesh_data(
        shaft_center,
        axis,
        shaft_radius,
        (bulb_center - shaft_start).length,
        segments,
        cap=True,
    )
    append_mesh_data(male_verts, male_faces, shaft_verts, shaft_faces)
    bulb_verts, bulb_faces = sphere_mesh_data(
        bulb_center,
        head_radius,
        segments=segments,
        rings=max(8, segments // 2),
    )
    append_mesh_data(male_verts, male_faces, bulb_verts, bulb_faces)
    base_verts, base_faces = cylinder_mesh_data(
        center - axis * (anchor_depth * 0.45),
        axis,
        head_radius * 0.86,
        anchor_depth,
        segments,
        cap=True,
    )
    append_mesh_data(male_verts, male_faces, base_verts, base_faces)

    female_verts = []
    female_faces = []
    cavity_radius = head_radius + clearance
    cavity_verts, cavity_faces = sphere_mesh_data(
        bulb_center,
        cavity_radius,
        segments=segments,
        rings=max(8, segments // 2),
    )
    append_mesh_data(female_verts, female_faces, cavity_verts, cavity_faces)
    hole_radius = shaft_radius + clearance
    hole_length = depth + cavity_radius * 0.45
    hole_center = center + axis * (hole_length * 0.5)
    hole_verts, hole_faces = cylinder_mesh_data(
        hole_center,
        axis,
        hole_radius,
        hole_length,
        segments,
        cap=True,
    )
    append_mesh_data(female_verts, female_faces, hole_verts, hole_faces)

    lead_length = max(scene.seanixz_pro_joint_assembly_margin_mm, 0.25) * unit
    lead_center = center + axis * (lead_length * 0.5)
    lead_verts, lead_faces = cone_frustum_mesh_data(
        lead_center,
        axis,
        hole_radius + clearance + lead_length * 0.4,
        hole_radius,
        lead_length,
        segments,
        cap=True,
    )
    append_mesh_data(female_verts, female_faces, lead_verts, lead_faces)
    return male_verts, male_faces, female_verts, female_faces


def build_hi3d_tenon_joint_meshes(scene, frame, axis, size_mm, clearance_mm, depth_mm):
    unit = mm_to_bu(scene)
    center = frame["center"]
    tangent = frame["tangent"]
    bitangent = frame["bitangent"]
    size = size_mm * unit
    clearance = clearance_mm * unit
    depth = max(depth_mm, size_mm * 0.65) * unit
    anchor_depth = max(size_mm * 0.2, 0.5) * unit
    taper = 0.78

    male_center = center + axis * (depth * 0.5)
    male_verts, male_faces = oriented_box_frustum_mesh_data(
        male_center,
        tangent,
        bitangent,
        axis,
        size,
        size * 0.82,
        size * taper,
        size * 0.82 * taper,
        depth,
    )
    anchor_verts, anchor_faces = oriented_box_mesh_data(
        center - axis * (anchor_depth * 0.45),
        tangent,
        bitangent,
        axis,
        size * 1.14,
        size * 0.96,
        anchor_depth,
    )
    append_mesh_data(male_verts, male_faces, anchor_verts, anchor_faces)

    female_bottom_length = size + clearance * 2.0
    female_bottom_width = size * 0.82 + clearance * 2.0
    female_top_length = size * taper + clearance * 2.0
    female_top_width = size * 0.82 * taper + clearance * 2.0
    female_verts, female_faces = oriented_box_frustum_mesh_data(
        male_center,
        tangent,
        bitangent,
        axis,
        female_bottom_length,
        female_bottom_width,
        female_top_length,
        female_top_width,
        depth + clearance * 1.5,
    )

    lead_depth = max(scene.seanixz_pro_joint_assembly_margin_mm, 0.25) * unit
    lead_verts, lead_faces = oriented_box_mesh_data(
        center + axis * (lead_depth * 0.5),
        tangent,
        bitangent,
        axis,
        female_bottom_length + lead_depth,
        female_bottom_width + lead_depth,
        lead_depth,
    )
    append_mesh_data(female_verts, female_faces, lead_verts, lead_faces)
    return male_verts, male_faces, female_verts, female_faces


def build_limited_axle_joint_meshes(scene, frame, axis, size_mm, clearance_mm, depth_mm):
    """生成视频所示的“对位插入、旋转锁止、挡块限位”可拆卸车轴连接对。

    公件由底座、轴杆和径向锁片组成；母槽切刀由轴孔、轴向插入槽和
    周向限位轨道组成。锁片必须先与入口槽对齐才能装入或拆出，装入后
    旋转进入轨道，并在轨道末端停止。
    """
    unit = mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments
    center = frame["center"]
    tangent = safe_normalized(frame["tangent"])
    bitangent = safe_normalized(frame["bitangent"])

    size = max(size_mm, 0.2) * unit
    clearance = max(clearance_mm, 0.0) * unit
    depth = max(depth_mm, size_mm * 0.8, 0.5) * unit
    tab_count = max(2, min(int(scene.seanixz_pro_joint_axle_tab_count), 6))
    requested_limit = max(10.0, min(float(scene.seanixz_pro_joint_axle_limit_deg), 170.0))
    # 相邻轨道之间保留实体挡块，避免多个轨道在大角度时相互贯通。
    max_limit = max(10.0, 360.0 / tab_count - 12.0)
    limit_deg = min(requested_limit, max_limit)

    shaft_radius = size * 0.23
    base_radius = size * 0.52
    base_depth = max(size * 0.24, 0.55 * unit)
    tab_radial_length = max(size * 0.25, 0.6 * unit)
    tab_tangent_width = max(size * 0.18, 0.5 * unit)
    tab_axial_height = max(size * 0.18, 0.5 * unit)
    tab_center_radius = shaft_radius + tab_radial_length * 0.48
    tab_plane = center + axis * (depth - tab_axial_height * 0.72)

    male_verts = []
    male_faces = []

    # 位于装配面一侧的止推底座，防止车轴继续穿入。
    base_center = center - axis * (base_depth * 0.42)
    base_verts, base_faces = cylinder_mesh_data(
        base_center, axis, base_radius, base_depth, segments, cap=True
    )
    append_mesh_data(male_verts, male_faces, base_verts, base_faces)

    shaft_start = center - axis * base_depth
    shaft_end = center + axis * (depth + tab_axial_height * 0.35)
    shaft_center = (shaft_start + shaft_end) * 0.5
    shaft_verts, shaft_faces = cylinder_mesh_data(
        shaft_center, axis, shaft_radius, (shaft_end - shaft_start).length, segments, cap=True
    )
    append_mesh_data(male_verts, male_faces, shaft_verts, shaft_faces)

    # 径向锁片：对齐入口槽后插入，随后旋转进入周向轨道。
    for index in range(tab_count):
        angle = math.tau * index / tab_count
        radial = tangent * math.cos(angle) + bitangent * math.sin(angle)
        tangential = -tangent * math.sin(angle) + bitangent * math.cos(angle)
        tab_center = tab_plane + radial * tab_center_radius
        tab_verts, tab_faces = oriented_box_mesh_data(
            tab_center,
            radial,
            tangential,
            axis,
            tab_radial_length,
            tab_tangent_width,
            tab_axial_height,
        )
        append_mesh_data(male_verts, male_faces, tab_verts, tab_faces)

    female_verts = []
    female_faces = []

    bore_radius = shaft_radius + clearance
    bore_length = depth + tab_axial_height + max(clearance, 0.2 * unit)
    bore_center = center + axis * (bore_length * 0.5)
    bore_verts, bore_faces = cylinder_mesh_data(
        bore_center, axis, bore_radius, bore_length, segments, cap=True
    )
    append_mesh_data(female_verts, female_faces, bore_verts, bore_faces)

    slot_radial_length = tab_radial_length + clearance * 2.0
    slot_tangent_width = tab_tangent_width + clearance * 2.0
    slot_axial_length = depth + tab_axial_height + max(clearance, 0.2 * unit)
    track_height = tab_axial_height + clearance * 2.0
    track_radial_length = slot_radial_length
    track_radius = tab_center_radius

    for index in range(tab_count):
        base_angle = math.tau * index / tab_count
        radial = tangent * math.cos(base_angle) + bitangent * math.sin(base_angle)
        tangential = -tangent * math.sin(base_angle) + bitangent * math.cos(base_angle)

        # 从装配面直达锁片高度的入口槽。
        entry_center = center + axis * (slot_axial_length * 0.5) + radial * tab_center_radius
        entry_verts, entry_faces = oriented_box_mesh_data(
            entry_center,
            radial,
            tangential,
            axis,
            slot_radial_length,
            slot_tangent_width,
            slot_axial_length,
        )
        append_mesh_data(female_verts, female_faces, entry_verts, entry_faces)

        # 用连续重叠的小切块形成圆弧轨道；末端不再延伸，实体边界即为限位挡块。
        arc_radius = max(track_radius, shaft_radius + track_radial_length * 0.45)
        arc_length = math.radians(limit_deg) * arc_radius
        sample_step = max(slot_tangent_width * 0.60, arc_radius * math.radians(5.0))
        sample_count = max(3, min(48, int(math.ceil(arc_length / max(sample_step, 1e-8))) + 1))
        tangent_piece = max(
            slot_tangent_width,
            arc_length / max(sample_count - 1, 1) * 1.35,
        )

        for step in range(sample_count):
            fraction = step / max(sample_count - 1, 1)
            angle = base_angle + math.radians(limit_deg) * fraction
            track_radial = tangent * math.cos(angle) + bitangent * math.sin(angle)
            track_tangent = -tangent * math.sin(angle) + bitangent * math.cos(angle)
            track_center = tab_plane + track_radial * arc_radius
            track_verts, track_faces = oriented_box_mesh_data(
                track_center,
                track_radial,
                track_tangent,
                axis,
                track_radial_length,
                tangent_piece,
                track_height,
            )
            append_mesh_data(female_verts, female_faces, track_verts, track_faces)

    values = {
        "tab_count": tab_count,
        "requested_limit_deg": requested_limit,
        "effective_limit_deg": limit_deg,
    }
    return male_verts, male_faces, female_verts, female_faces, values


def build_damped_hinge_joint_meshes(scene, frame, axis, size_mm, clearance_mm, depth_mm):
    """生成横向阻尼转轴和带间隙、可选齿槽定位的母槽切刀。

    转轴沿所选圈线的长轴或短轴布置，装配方向仍由 A→B / B→A 控制。
    阻尼齿位于一端止推盘的端面；母槽切刀只在对应角度加深形成定位槽，
    避免把整个阻尼面完全挖空而失去摩擦和分度效果。
    """
    unit = mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments
    center = frame["center"]
    assembly_axis = safe_normalized(axis)
    if scene.seanixz_pro_joint_hinge_axis == 'SHORT':
        hinge_axis = safe_normalized(frame["bitangent"])
    else:
        hinge_axis = safe_normalized(frame["tangent"])
    cross_axis = safe_normalized(hinge_axis.cross(assembly_axis))

    size = max(size_mm, 0.2) * unit
    clearance = max(clearance_mm, 0.0) * unit
    shaft_length = max(depth_mm, size_mm * 1.4, 1.0) * unit
    shaft_radius = max(size * 0.20, 0.35 * unit)
    flange_radius = max(size * 0.46, shaft_radius + 0.55 * unit)
    flange_thickness = max(size * 0.16, 0.45 * unit)
    anchor_depth = max(size * 0.24, 0.55 * unit)
    anchor_length = max(shaft_length * 0.44, size * 0.75)

    male_verts = []
    male_faces = []

    shaft_verts, shaft_faces = cylinder_mesh_data(
        center, hinge_axis, shaft_radius, shaft_length, segments, cap=True
    )
    append_mesh_data(male_verts, male_faces, shaft_verts, shaft_faces)

    # 公件底座朝公件一侧埋入，保证转轴和原模型有足够的并集接触面积。
    anchor_center = center - assembly_axis * (anchor_depth * 0.42)
    anchor_verts, anchor_faces = oriented_box_mesh_data(
        anchor_center,
        hinge_axis,
        cross_axis,
        assembly_axis,
        anchor_length,
        flange_radius * 1.35,
        anchor_depth,
    )
    append_mesh_data(male_verts, male_faces, anchor_verts, anchor_faces)

    half_length = shaft_length * 0.5
    end_centers = (
        center - hinge_axis * (half_length - flange_thickness * 0.5),
        center + hinge_axis * (half_length - flange_thickness * 0.5),
    )
    for end_center in end_centers:
        flange_verts, flange_faces = cylinder_mesh_data(
            end_center, hinge_axis, flange_radius, flange_thickness, segments, cap=True
        )
        append_mesh_data(male_verts, male_faces, flange_verts, flange_faces)

    damping_enabled = bool(scene.seanixz_pro_joint_hinge_damping)
    tooth_count = max(6, min(int(scene.seanixz_pro_joint_hinge_tooth_count), 36))
    tooth_height = max(float(scene.seanixz_pro_joint_hinge_tooth_height_mm), 0.0) * unit
    tooth_radial_length = max(flange_radius - shaft_radius * 1.35, 0.35 * unit)
    tooth_center_radius = shaft_radius * 1.25 + tooth_radial_length * 0.5
    tooth_tangent_width = max(
        math.tau * tooth_center_radius / tooth_count * 0.42,
        0.18 * unit,
    )
    damping_face = center + hinge_axis * half_length

    if damping_enabled and tooth_height > 0.0:
        for index in range(tooth_count):
            angle = math.tau * index / tooth_count
            radial = assembly_axis * math.cos(angle) + cross_axis * math.sin(angle)
            tangential = -assembly_axis * math.sin(angle) + cross_axis * math.cos(angle)
            tooth_center = (
                damping_face
                + hinge_axis * (tooth_height * 0.5)
                + radial * tooth_center_radius
            )
            tooth_verts, tooth_faces = oriented_box_mesh_data(
                tooth_center,
                radial,
                tangential,
                hinge_axis,
                tooth_radial_length,
                tooth_tangent_width,
                tooth_height,
            )
            append_mesh_data(male_verts, male_faces, tooth_verts, tooth_faces)

    female_verts = []
    female_faces = []
    bore_radius = shaft_radius + clearance
    bore_length = shaft_length + clearance * 2.0 + max(0.2 * unit, clearance)
    bore_verts, bore_faces = cylinder_mesh_data(
        center, hinge_axis, bore_radius, bore_length, segments, cap=True
    )
    append_mesh_data(female_verts, female_faces, bore_verts, bore_faces)

    relief_radius = flange_radius + clearance
    relief_length = flange_thickness + clearance * 2.0 + max(0.12 * unit, clearance * 0.5)
    for end_center in end_centers:
        relief_verts, relief_faces = cylinder_mesh_data(
            end_center, hinge_axis, relief_radius, relief_length, segments, cap=True
        )
        append_mesh_data(female_verts, female_faces, relief_verts, relief_faces)

    # 端面齿槽比基础止推盘空腔更深，形成可感知的分度定位与阻尼。
    if damping_enabled and tooth_height > 0.0:
        groove_height = tooth_height + clearance + max(0.08 * unit, clearance * 0.35)
        groove_radial_length = tooth_radial_length + clearance * 2.0
        groove_tangent_width = tooth_tangent_width + clearance * 1.4
        for index in range(tooth_count):
            angle = math.tau * index / tooth_count
            radial = assembly_axis * math.cos(angle) + cross_axis * math.sin(angle)
            tangential = -assembly_axis * math.sin(angle) + cross_axis * math.cos(angle)
            groove_center = (
                damping_face
                + hinge_axis * (groove_height * 0.5)
                + radial * tooth_center_radius
            )
            groove_verts, groove_faces = oriented_box_mesh_data(
                groove_center,
                radial,
                tangential,
                hinge_axis,
                groove_radial_length,
                groove_tangent_width,
                groove_height,
            )
            append_mesh_data(female_verts, female_faces, groove_verts, groove_faces)

    values = {
        "axis": scene.seanixz_pro_joint_hinge_axis,
        "damping": damping_enabled and tooth_height > 0.0,
        "tooth_count": tooth_count,
        "tooth_height_mm": tooth_height / unit,
    }
    return male_verts, male_faces, female_verts, female_faces, values


def make_joint_magnet_pocket_pair(context):
    """在装配面两侧各生成一个磁铁孔切刀，分别用于 A、B 部件差集。"""
    scene = context.scene
    frame, error = selected_loop_world_frame(context)
    if not frame:
        return None, None, error

    axis, negative_side, positive_side = hi3d_joint_direction(frame, scene)
    unit = mm_to_bu(scene)
    magnet_diameter_mm = max(scene.seanixz_pro_joint_magnet_diameter_mm, 0.2)
    magnet_depth_mm = max(scene.seanixz_pro_joint_magnet_depth_mm, 0.2)
    fit_mm = max(scene.seanixz_pro_joint_magnet_clearance_mm, 0.0)
    radius = (magnet_diameter_mm * 0.5 + fit_mm) * unit
    length = (magnet_depth_mm + fit_mm) * unit
    segments = scene.seanixz_pro_joint_segments
    center = frame["center"]

    cutter_negative_verts, cutter_negative_faces = cylinder_mesh_data(
        center - axis * (length * 0.5), axis, radius, length, segments, cap=True
    )
    cutter_positive_verts, cutter_positive_faces = cylinder_mesh_data(
        center + axis * (length * 0.5), axis, radius, length, segments, cap=True
    )
    cutter_negative = create_joint_pair_object(
        context,
        f"SeanIXz_Magnet_{negative_side}_Cutter",
        cutter_negative_verts,
        cutter_negative_faces,
        "FEMALE_CUTTER",
        "MAGNET_POCKET",
        negative_side,
    )
    cutter_positive = create_joint_pair_object(
        context,
        f"SeanIXz_Magnet_{positive_side}_Cutter",
        cutter_positive_verts,
        cutter_positive_faces,
        "FEMALE_CUTTER",
        "MAGNET_POCKET",
        positive_side,
    )
    cutter_negative["seanixz_pro_joint_partner"] = cutter_positive.name
    cutter_positive["seanixz_pro_joint_partner"] = cutter_negative.name
    for obj in (cutter_negative, cutter_positive):
        obj["seanixz_pro_joint_magnet_diameter_mm"] = magnet_diameter_mm
        obj["seanixz_pro_joint_magnet_depth_mm"] = magnet_depth_mm
        obj["seanixz_pro_joint_magnet_clearance_mm"] = fit_mm

    ensure_object_mode()
    bpy.ops.object.select_all(action='DESELECT')
    cutter_negative.select_set(True)
    cutter_positive.select_set(True)
    context.view_layer.objects.active = cutter_negative
    context.view_layer.update()
    msg = (
        f"成对磁铁孔切刀已生成：磁铁 {magnet_diameter_mm:.2f}×{magnet_depth_mm:.2f} mm，"
        f"单边配合余量 {fit_mm:.2f} mm。\n"
        "A、B 蓝色线框分别向装配面两侧延伸，请各自与对应部件执行布尔差集。"
    )
    return cutter_negative, cutter_positive, msg


def make_hi3d_joint_pair(context):
    scene = context.scene
    frame, error = selected_loop_world_frame(context)

    if not frame:
        return None, None, error

    size_mm, clearance_mm, depth_mm, angle_deg, major_mm, minor_mm = calculate_hi3d_joint_values_mm(scene, frame)
    axis, male_side, female_side = hi3d_joint_direction(frame, scene)
    joint_type = scene.seanixz_pro_joint_type

    axle_values = None
    hinge_values = None
    if joint_type == 'BALL':
        male_verts, male_faces, female_verts, female_faces = build_hi3d_ball_joint_meshes(
            scene, frame, axis, size_mm, clearance_mm, depth_mm, angle_deg
        )
        type_label = "球关节"
        slug = "Ball"
    elif joint_type == 'BALL_LINK':
        male_verts, male_faces, female_verts, female_faces = build_figure_ball_link_joint_meshes(
            scene, frame, axis, size_mm, clearance_mm, depth_mm, angle_deg
        )
        type_label = "独立球头连接件"
        slug = "BallLink"
    elif joint_type == 'DOUBLE_BALL':
        male_verts, male_faces, female_verts, female_faces = build_figure_double_ball_joint_meshes(
            scene, frame, axis, size_mm, clearance_mm, depth_mm, angle_deg
        )
        type_label = "双球头连杆"
        slug = "DoubleBall"
    elif joint_type == 'RIVET':
        male_verts, male_faces, female_verts, female_faces = build_hi3d_rivet_joint_meshes(
            scene, frame, axis, size_mm, clearance_mm, depth_mm
        )
        type_label = "铆钉"
        slug = "Rivet"
    elif joint_type == 'TENON':
        male_verts, male_faces, female_verts, female_faces = build_hi3d_tenon_joint_meshes(
            scene, frame, axis, size_mm, clearance_mm, depth_mm
        )
        type_label = "榫卯"
        slug = "Tenon"
    elif joint_type == 'LIMITED_AXLE':
        male_verts, male_faces, female_verts, female_faces, axle_values = build_limited_axle_joint_meshes(
            scene, frame, axis, size_mm, clearance_mm, depth_mm
        )
        type_label = "限位可拆卸车轴"
        slug = "LimitedAxle"
    elif joint_type == 'DAMPED_HINGE':
        male_verts, male_faces, female_verts, female_faces, hinge_values = build_damped_hinge_joint_meshes(
            scene, frame, axis, size_mm, clearance_mm, depth_mm
        )
        type_label = "阻尼转轴"
        slug = "DampedHinge"
    else:
        male_verts, male_faces, female_verts, female_faces = build_figure_double_hinge_joint_meshes(
            scene, frame, axis, size_mm, clearance_mm, depth_mm
        )
        type_label = "肘膝双转轴"
        slug = "DoubleHinge"

    split_info = None
    split_mesh_data = None
    if getattr(scene, "seanixz_pro_joint_integrated_split_cutter", True):
        split_verts = []
        split_faces = []
        split_info = append_integrated_joint_separation_cutter(
            scene,
            frame,
            split_verts,
            split_faces,
            size_mm,
            clearance_mm,
        )
        split_mesh_data = (split_verts, split_faces)

    male = create_joint_pair_object(
        context,
        f"SeanIXz_{slug}_{male_side}_Male",
        male_verts,
        male_faces,
        "MALE",
        joint_type,
        male_side,
    )
    female = create_joint_pair_object(
        context,
        f"SeanIXz_{slug}_{female_side}_Integrated_Cutter" if split_info else f"SeanIXz_{slug}_{female_side}_Female_Cutter",
        female_verts,
        female_faces,
        "FEMALE_CUTTER",
        joint_type,
        female_side,
    )
    male["seanixz_pro_joint_partner"] = female.name
    female["seanixz_pro_joint_partner"] = male.name
    male["seanixz_pro_joint_size_mm"] = size_mm
    female["seanixz_pro_joint_clearance_mm"] = clearance_mm
    male["seanixz_pro_print_ready_connector"] = joint_type in {'BALL_LINK', 'DOUBLE_BALL', 'DOUBLE_HINGE'}
    if male["seanixz_pro_print_ready_connector"]:
        fuse_print_ready_joint_connector(context, male, scene, clearance_mm)
    if split_info:
        female["seanixz_pro_integrated_split_cutter"] = True
        female["seanixz_pro_split_length_mm"] = split_info[0]
        female["seanixz_pro_split_width_mm"] = split_info[1]
        female["seanixz_pro_split_thickness_mm"] = split_info[2]
        fuse_integrated_joint_cutter(context, female, scene, clearance_mm)
        union_joint_split_slab(context, female, split_mesh_data[0], split_mesh_data[1])
    if axle_values:
        for obj in (male, female):
            obj["seanixz_pro_joint_axle_tab_count"] = axle_values["tab_count"]
            obj["seanixz_pro_joint_axle_limit_deg"] = axle_values["effective_limit_deg"]
    if hinge_values:
        for obj in (male, female):
            obj["seanixz_pro_joint_hinge_axis"] = hinge_values["axis"]
            obj["seanixz_pro_joint_hinge_damping"] = hinge_values["damping"]
            obj["seanixz_pro_joint_hinge_tooth_count"] = hinge_values["tooth_count"]
            obj["seanixz_pro_joint_hinge_tooth_height_mm"] = hinge_values["tooth_height_mm"]

    ensure_object_mode()
    bpy.ops.object.select_all(action='DESELECT')
    male.select_set(True)
    female.select_set(True)
    context.view_layer.objects.active = male
    context.view_layer.update()

    direction_text = f"{male_side} → {female_side}"
    angle_text = f"，摆动角 {angle_deg:.1f}°" if joint_type in {'BALL', 'BALL_LINK', 'DOUBLE_BALL'} else ""
    if axle_values:
        angle_text = (
            f"，锁片 {axle_values['tab_count']} 个，实际限位角 {axle_values['effective_limit_deg']:.1f}°"
        )
    elif hinge_values:
        hinge_axis_text = "圈线短轴" if hinge_values["axis"] == 'SHORT' else "圈线长轴"
        if hinge_values["damping"]:
            angle_text = (
                f"，沿{hinge_axis_text}，阻尼齿 {hinge_values['tooth_count']} 个，"
                f"齿高 {hinge_values['tooth_height_mm']:.2f} mm"
            )
        else:
            angle_text = f"，沿{hinge_axis_text}，自由转动"
    elif joint_type == 'DOUBLE_HINGE':
        hinge_axis_text = "圈线短轴" if scene.seanixz_pro_joint_hinge_axis == 'SHORT' else "圈线长轴"
        angle_text = f"，沿{hinge_axis_text}生成两级转轴"
    mode_text = "按圈线自动尺寸" if scene.seanixz_pro_joint_auto_size else "手动尺寸"
    split_text = ""
    if split_info:
        split_text = (
            f"；已并入 {split_info[0]:.2f}×{split_info[1]:.2f}×{split_info[2]:.2f} mm 接缝分离切刀"
        )
    msg = (
        f"{type_label}连接对已生成（{direction_text}，{mode_text}）：圈线约 {major_mm:.2f}×{minor_mm:.2f} mm，"
        f"尺寸 {size_mm:.2f} mm，组装间隙 {clearance_mm:.2f} mm，连接深度 {depth_mm:.2f} mm{angle_text}{split_text}。\n"
        "绿色件为独立打印连接件；蓝色一体式切刀一次布尔即可同时切开接缝、形成关节腔和装配入口。"
    )
    return male, female, msg


def calculate_joint_snap_ball_values_mm(scene, frame):
    avg_radius_mm, avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)

    if scene.seanixz_pro_joint_auto_size:
        ball_diameter = max(
            min(major_mm, minor_mm) * scene.seanixz_pro_joint_size_factor,
            1.2,
        )
        ball_radius = ball_diameter * 0.5
    else:
        ball_radius = max(scene.seanixz_pro_joint_size_mm * 0.5, 0.1)

    socket_radius = max(ball_radius + scene.seanixz_pro_joint_clearance_mm, 0.001)
    throat_factor = max(min(scene.seanixz_pro_joint_lock_throat_factor, 0.95), 0.35)
    throat_radius = max(ball_radius * throat_factor + scene.seanixz_pro_joint_clearance_mm, 0.2)
    throat_radius = min(throat_radius, socket_radius * 0.94)

    socket_depth = max(
        scene.seanixz_pro_joint_connection_depth_mm,
        socket_radius * 0.75,
        0.5,
    )
    retention_length = max(socket_radius * 0.55, 0.4)
    outside_extension = max(socket_radius * 0.35, scene.seanixz_pro_joint_assembly_margin_mm, 0.25)
    flare_length = max(socket_depth + outside_extension - retention_length, 0.25)
    swing_angle = math.radians(max(min(scene.seanixz_pro_joint_angle_deg, 80.0), 5.0))
    effective_swing_length = min(flare_length, socket_radius * 0.90)
    entry_radius = max(
        throat_radius + scene.seanixz_pro_joint_assembly_margin_mm,
        throat_radius + math.tan(swing_angle) * effective_swing_length,
    )
    entry_radius = min(entry_radius, socket_radius * 1.30)
    return (
        ball_radius,
        socket_radius,
        throat_radius,
        entry_radius,
        socket_depth,
        retention_length,
        outside_extension,
    )


def make_joint_snap_ball_socket_cutter(context):
    """Generate a print-oriented ball-socket Boolean cutter from a selected loop.

    The cutter keeps a short cylindrical retaining throat next to the spherical
    cavity, then expands only toward the exterior.  This provides angular room
    without cutting cross channels through the retaining lip.
    """
    scene = context.scene
    frame, error = selected_loop_world_frame(context)

    if not frame:
        return None, error

    (
        ball_radius_mm,
        socket_radius_mm,
        throat_radius_mm,
        entry_radius_mm,
        socket_depth_mm,
        retention_length_mm,
        outside_extension_mm,
    ) = calculate_joint_snap_ball_values_mm(scene, frame)

    socket_radius = socket_radius_mm * mm_to_bu(scene)
    throat_radius = throat_radius_mm * mm_to_bu(scene)
    entry_radius = entry_radius_mm * mm_to_bu(scene)
    socket_depth = socket_depth_mm * mm_to_bu(scene)
    retention_length = retention_length_mm * mm_to_bu(scene)
    outside_extension = outside_extension_mm * mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments

    surface_center = frame["center"]
    normal = frame["normal"]
    if scene.seanixz_pro_joint_direction == 'B_TO_A':
        normal = -normal
    ball_center = surface_center + normal * socket_depth

    verts = []
    faces = []

    # 1) 球形活动腔：球头半径 + 打印装配间隙。
    sphere_verts, sphere_faces = sphere_mesh_data(
        ball_center,
        socket_radius,
        segments=segments,
        rings=max(8, segments // 2),
    )
    append_mesh_data(verts, faces, sphere_verts, sphere_faces)

    # 2) 球腔外侧先保留一小段等径锁口，避免摆动锥口直接吃掉卡持边。
    throat_center = ball_center - normal * (retention_length * 0.5)
    throat_verts, throat_faces = cylinder_mesh_data(
        throat_center,
        normal,
        throat_radius,
        retention_length,
        segments,
        cap=True,
    )
    append_mesh_data(verts, faces, throat_verts, throat_faces)

    # 3) 从锁口向模型表面外扩成圆锥通道：角度越大，球杆可摆动范围越大。
    total_exit_length = socket_depth + outside_extension
    flare_length = max(total_exit_length - retention_length, 0.000001)
    flare_center = ball_center - normal * (retention_length + flare_length * 0.5)
    flare_verts, flare_faces = cone_frustum_mesh_data(
        flare_center,
        -normal,
        throat_radius,
        entry_radius,
        flare_length,
        segments,
        cap=True,
    )
    append_mesh_data(verts, faces, flare_verts, flare_faces)

    obj = create_mesh_object_from_data(
        context,
        "SeanIXz_BallJoint_Socket_Cutter",
        verts,
        faces,
        display_mode='WIRE',
    )
    obj["seanixz_pro_joint_cutter_type"] = "print_ball_socket"
    obj["seanixz_pro_ball_diameter_mm"] = ball_radius_mm * 2.0
    obj["seanixz_pro_socket_radius_mm"] = socket_radius_mm
    obj["seanixz_pro_throat_radius_mm"] = throat_radius_mm
    obj["seanixz_pro_swing_angle_deg"] = scene.seanixz_pro_joint_angle_deg
    obj["seanixz_pro_connection_depth_mm"] = socket_depth_mm
    obj["seanixz_pro_direction"] = scene.seanixz_pro_joint_direction
    select_created_cutter(context, obj)

    avg_radius_mm, avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)
    direction_text = "法向" if scene.seanixz_pro_joint_direction == 'A_TO_B' else "反法向"
    msg = (
        f"球形关节球窝切刀完成（{joint_auto_mode_text(scene)}，{direction_text}）："
        f"圈线约 {major_mm:.2f}×{minor_mm:.2f} mm，球头直径 {ball_radius_mm * 2.0:.2f} mm，"
        f"球窝半径 {socket_radius_mm:.2f} mm，锁口半径 {throat_radius_mm:.2f} mm。\n"
        f"球心深度 {socket_depth_mm:.2f} mm，摆动半角约 {scene.seanixz_pro_joint_angle_deg:.1f}°，"
        f"入口半径 {entry_radius_mm:.2f} mm。请把蓝色线框切刀与承接球头的部件执行布尔差集。"
    )
    return obj, msg


def calculate_joint_snap_hinge_values_mm(scene, frame):
    avg_radius_mm, avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)

    if scene.seanixz_pro_joint_auto_size:
        pin_radius = max(minor_mm * 0.42, avg_radius_mm * 0.45, 0.7)
        length = max(major_mm + scene.seanixz_pro_joint_assembly_margin_mm * 2.0, pin_radius * 4.0, 3.0)
    else:
        pin_radius = scene.seanixz_pro_joint_hinge_radius_mm
        length = scene.seanixz_pro_joint_hinge_length_mm

    cavity_radius = max(pin_radius + scene.seanixz_pro_joint_clearance_mm, 0.001)
    throat_factor = max(min(scene.seanixz_pro_joint_lock_throat_factor, 0.95), 0.35)
    slot_width = max(cavity_radius * 2.0 * throat_factor, scene.seanixz_pro_joint_clearance_mm * 2.0 + 0.4)
    slot_depth = max(cavity_radius * 2.4, cavity_radius + scene.seanixz_pro_joint_assembly_margin_mm)
    swing_depth = max(cavity_radius * scene.seanixz_pro_joint_swing_room_factor * 1.6, cavity_radius * 1.25)
    return pin_radius, cavity_radius, length, slot_width, slot_depth, swing_depth


def make_joint_snap_hinge_cutter(context):
    """Generate a self-locking snap hinge / C-clip style joint cutter from a selected loop."""
    scene = context.scene
    frame, error = selected_loop_world_frame(context)

    if not frame:
        return None, error

    pin_radius_mm, cavity_radius_mm, length_mm, slot_width_mm, slot_depth_mm, swing_depth_mm = calculate_joint_snap_hinge_values_mm(scene, frame)

    cavity_radius = cavity_radius_mm * mm_to_bu(scene)
    length = length_mm * mm_to_bu(scene)
    slot_width = slot_width_mm * mm_to_bu(scene)
    slot_depth = slot_depth_mm * mm_to_bu(scene)
    swing_depth = swing_depth_mm * mm_to_bu(scene)
    segments = scene.seanixz_pro_joint_segments

    center = frame["center"]
    axis = frame["tangent"]
    normal = frame["normal"]
    bitangent = frame["bitangent"]

    verts = []
    faces = []

    cyl_verts, cyl_faces = cylinder_mesh_data(center, axis, cavity_radius, length, segments, cap=True)
    append_mesh_data(verts, faces, cyl_verts, cyl_faces)

    # Narrow snap opening: smaller than the full round cavity. After boolean, it leaves a C-clip style retaining lip.
    slot_center = center + normal * (cavity_radius * 0.78)
    slot_verts, slot_faces = oriented_box_mesh_data(slot_center, axis, bitangent, normal, length * 1.04, slot_width, slot_depth)
    append_mesh_data(verts, faces, slot_verts, slot_faces)

    # Movement relief: a slightly wider outer clearance so the hinge arm has room to rotate.
    relief_center = center + normal * (cavity_radius + swing_depth * 0.48)
    relief_width = max(slot_width, cavity_radius * 2.0 * 0.86)
    relief_verts, relief_faces = oriented_box_mesh_data(relief_center, axis, bitangent, normal, length * 1.04, relief_width, swing_depth)
    append_mesh_data(verts, faces, relief_verts, relief_faces)

    # Assembly lead-in at both ends of the hinge barrel.
    lead_radius = cavity_radius + scene.seanixz_pro_joint_assembly_margin_mm * mm_to_bu(scene)
    lead_len = max(scene.seanixz_pro_joint_assembly_margin_mm * 1.5, 0.3) * mm_to_bu(scene)
    if lead_len > 0:
        c1 = center - axis * (length * 0.5 - lead_len * 0.5)
        c2 = center + axis * (length * 0.5 - lead_len * 0.5)
        l1v, l1f = cone_frustum_mesh_data(c1, axis, lead_radius, cavity_radius, lead_len, segments, cap=True)
        append_mesh_data(verts, faces, l1v, l1f)
        l2v, l2f = cone_frustum_mesh_data(c2, axis, cavity_radius, lead_radius, lead_len, segments, cap=True)
        append_mesh_data(verts, faces, l2v, l2f)

    obj = create_mesh_object_from_data(context, "SeanIXz_Joint_SnapHinge_Cutter", verts, faces, display_mode='WIRE')
    obj["seanixz_pro_joint_cutter_type"] = "snap_hinge"
    select_created_cutter(context, obj)

    avg_radius_mm, avg_diameter_mm, major_mm, minor_mm = frame_dimension_summary_mm(scene, frame)
    msg = (
        f"自锁转轴活动关节切刀完成（{joint_auto_mode_text(scene)}）：圈线约 {major_mm:.2f}×{minor_mm:.2f} mm，"
        f"参考轴半径 {pin_radius_mm:.2f} mm，圆腔半径 {cavity_radius_mm:.2f} mm，锁口宽 {slot_width_mm:.2f} mm，长度 {length_mm:.2f} mm。\n"
        "已生成 C 形自锁开口、装配导入口和旋转活动间隙，适合 3D 打印按压装配式转轴关节。"
    )
    return obj, msg


# -----------------------------------------------------------------------------
# 01 单位与尺寸
# -----------------------------------------------------------------------------

class SEANIXZ_PRO_OT_set_length_unit_mm(bpy.types.Operator):
    bl_idname = "seanixz_pro.set_length_unit_mm"
    bl_label = "设置单位为毫米"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene

        try:
            scene.unit_settings.system = 'METRIC'
        except Exception:
            pass

        try:
            scene.unit_settings.length_unit = 'MILLIMETERS'
        except Exception:
            pass

        try:
            scene.unit_settings.scale_length = 1.0
        except Exception:
            pass

        changed, clip_start_bu = set_view_clip_start_mm(context, 1.0)

        msg = (
            "单位设置完成。\n"
            "长度单位：毫米\n"
            "缩放单位：1\n"
            "视图裁剪起始：1mm\n"
            "说明：第 01 步用于建模阶段保持 Blender 默认比例，并把视图裁剪起始调小，方便查看小尺寸卡榫、关节和切刀细节。"
        )

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg, title="单位设置完成", icon='SCENE_DATA')
        return {'FINISHED'}

class SEANIXZ_PRO_OT_set_scene_unit_mm(bpy.types.Operator):
    bl_idname = "seanixz_pro.set_scene_unit_mm"
    bl_label = "统一3D打印软件尺寸"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene

        try:
            scene.unit_settings.system = 'METRIC'
        except Exception:
            pass

        try:
            scene.unit_settings.length_unit = 'MILLIMETERS'
        except Exception:
            pass

        try:
            scene.unit_settings.scale_length = 0.001
        except Exception:
            pass

        changed, clip_start_bu = set_view_clip_start_mm(context, 1.0)

        msg = (
            "3D打印软件尺寸统一完成。\n"
            "长度单位：毫米\n"
            "缩放单位：0.001\n"
            "视图裁剪起始：1mm\n"
            "说明：用于让 Blender 尺寸与常见 3D 打印/切片软件的毫米尺寸保持一致，并保持小尺寸细节可见。"
        )

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg, title="3D打印尺寸统一完成", icon='SCENE_DATA')
        return {'FINISHED'}

class SEANIXZ_PRO_OT_set_height(bpy.types.Operator):
    bl_idname = "seanixz_pro.set_height"
    bl_label = "设置高度"
    bl_options = {'REGISTER', 'UNDO'}

    target_height_mm: bpy.props.FloatProperty(
        name="目标高度 mm",
        default=0.0,
        min=0.0,
        precision=3
    )

    def execute(self, context):
        scene = context.scene

        if self.target_height_mm > 0:
            target_height_mm = self.target_height_mm
            scene.seanixz_pro_target_height_mm = self.target_height_mm
        else:
            target_height_mm = scene.seanixz_pro_target_height_mm

        target_bu = target_height_mm * mm_to_bu(scene)
        objs = mesh_objects_from_selection(context)

        if not objs:
            self.report({'ERROR'}, "请选择至少一个网格模型")
            return {'CANCELLED'}

        changed = 0

        for obj in objs:
            current_h = obj.dimensions.z

            if current_h <= 0:
                continue

            factor = target_bu / current_h
            obj.scale *= factor
            changed += 1

        context.view_layer.update()

        msg = f"尺寸设置完成：{changed} 个模型，高度 {target_height_mm:.3f} mm。"
        self.report({'INFO'}, msg)
        show_popup(msg, title="尺寸设置完成", icon='OBJECT_DATA')
        return {'FINISHED'}

# -----------------------------------------------------------------------------
# 获取面数
# -----------------------------------------------------------------------------

class SEANIXZ_PRO_OT_get_face_count(bpy.types.Operator):
    bl_idname = "seanixz_pro.get_face_count"
    bl_label = "获取面数"
    bl_options = {'REGISTER', 'UNDO'}

    section: bpy.props.EnumProperty(
        items=[
            ('DECIMATE', "精简", ""),
            ('REMESH', "重建修复", ""),
        ],
        default='DECIMATE'
    )

    def execute(self, context):
        objs = mesh_objects_from_selection(context)

        if not objs:
            self.report({'ERROR'}, "请选择至少一个网格模型")
            return {'CANCELLED'}

        raw_count = selected_face_count(context, evaluated=False)
        evaluated_count = selected_face_count(context, evaluated=True)
        scene = context.scene

        if self.section == 'DECIMATE':
            scene.seanixz_pro_decimate_before_faces = raw_count
            scene.seanixz_pro_decimate_after_faces = evaluated_count
        else:
            scene.seanixz_pro_remesh_before_faces = raw_count
            scene.seanixz_pro_remesh_after_faces = evaluated_count

        msg = f"当前选中模型面数：{raw_count:,}"

        if evaluated_count != raw_count:
            msg += f"\n含修改器预估面数：{evaluated_count:,}"

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg, title="面数统计", icon='MESH_DATA')
        return {'FINISHED'}

# -----------------------------------------------------------------------------
# 02 模型精简
# -----------------------------------------------------------------------------

SMOOTH_REMESH_AFTER_DECIMATE = "SeanIXz_平滑重构预览"


def configure_smooth_remesh_modifier(mod, scene):
    """Configure legacy Remesh modifier in Smooth mode with Octree depth."""
    if not mod:
        return

    try:
        mod.mode = 'SMOOTH'
    except Exception:
        pass

    try:
        mod.octree_depth = int(scene.seanixz_pro_remesh_octree_depth)
    except Exception:
        pass

    try:
        mod.use_smooth_shade = True
    except Exception:
        pass

    try:
        mod.use_remove_disconnected = False
    except Exception:
        pass


def remove_smooth_remesh_preview(obj):
    mod = obj.modifiers.get(SMOOTH_REMESH_AFTER_DECIMATE)
    if mod:
        try:
            obj.modifiers.remove(mod)
        except Exception:
            pass

class SEANIXZ_PRO_OT_decimate_preview(bpy.types.Operator):
    bl_idname = "seanixz_pro.decimate_preview"
    bl_label = "精简预览"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        ensure_decimate_percent_compatible(scene)
        objs = mesh_objects_from_selection(context)

        if not objs:
            self.report({'ERROR'}, "请选择至少一个网格模型")
            return {'CANCELLED'}

        before = selected_face_count(context, evaluated=False)

        for obj in objs:
            mod = obj.modifiers.get("SeanIXz_Pro_精简预览") or obj.modifiers.new("SeanIXz_Pro_精简预览", 'DECIMATE')
            mod.decimate_type = 'COLLAPSE'
            mod.ratio = max(min(scene.seanixz_pro_decimate_percent / 100.0, 1.0), 0.001)

            try:
                mod.show_on_cage = True
            except Exception:
                pass

            remove_smooth_remesh_preview(obj)

        context.view_layer.update()

        after = selected_face_count(context, evaluated=True)
        scene.seanixz_pro_decimate_before_faces = before
        scene.seanixz_pro_decimate_after_faces = after
        scene.seanixz_pro_decimate_has_preview = True

        msg = f"精简预览完成：当前面数 {before:,}，预估精简后 {after:,}，比例 {scene.seanixz_pro_decimate_percent:.1f}%。"
        self.report({'INFO'}, msg)
        return {'FINISHED'}

class SEANIXZ_PRO_OT_decimate_apply(bpy.types.Operator):
    bl_idname = "seanixz_pro.decimate_apply"
    bl_label = "执行精简"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        ensure_decimate_percent_compatible(scene)
        objs = mesh_objects_from_selection(context)

        if not objs:
            self.report({'ERROR'}, "请选择至少一个网格模型")
            return {'CANCELLED'}

        before = selected_face_count(context, evaluated=False)

        for obj in objs:
            mod = obj.modifiers.get("SeanIXz_Pro_精简预览") or obj.modifiers.new("SeanIXz_Pro_精简预览", 'DECIMATE')
            mod.decimate_type = 'COLLAPSE'
            mod.ratio = max(min(scene.seanixz_pro_decimate_percent / 100.0, 1.0), 0.001)
            apply_modifier(context, obj, mod.name)

            remove_smooth_remesh_preview(obj)

        after = selected_face_count(context, evaluated=False)
        scene.seanixz_pro_decimate_before_faces = before
        scene.seanixz_pro_decimate_after_faces = after

        msg = f"精简完成：{before:,} -> {after:,} 面，比例 {scene.seanixz_pro_decimate_percent:.1f}%。"
        self.report({'INFO'}, msg)
        show_popup(msg, title="精简报告", icon='MOD_DECIM')
        return {'FINISHED'}

class SEANIXZ_PRO_OT_decimate_one_click(bpy.types.Operator):
    bl_idname = "seanixz_pro.decimate_one_click"
    bl_label = "一键执行精简"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.ops.seanixz_pro.decimate_preview()
        bpy.ops.seanixz_pro.decimate_apply()
        return {'FINISHED'}

# -----------------------------------------------------------------------------
# 03 重建修复
# -----------------------------------------------------------------------------

def configure_main_remesh_modifier(mod, scene):
    """Configure 03 Remesh Repair: Voxel mode or Smooth mode."""
    mode = getattr(scene, "seanixz_pro_remesh_mode", 'VOXEL')

    if mode == 'SMOOTH':
        try:
            mod.mode = 'SMOOTH'
        except Exception:
            pass

        try:
            mod.octree_depth = int(scene.seanixz_pro_remesh_octree_depth)
        except Exception:
            pass
    else:
        try:
            mod.mode = 'VOXEL'
        except Exception:
            pass

        try:
            mod.voxel_size = max(scene.seanixz_pro_voxel_size_mm * mm_to_bu(scene), 0.000001)
        except Exception:
            pass

    try:
        mod.use_smooth_shade = scene.seanixz_pro_remesh_smooth
    except Exception:
        pass

    try:
        mod.use_remove_disconnected = False
    except Exception:
        pass


def remesh_mode_report(scene):
    mode = getattr(scene, "seanixz_pro_remesh_mode", 'VOXEL')
    if mode == 'SMOOTH':
        return f"平滑重构，八叉树深度 {scene.seanixz_pro_remesh_octree_depth}"
    return f"体素重构，体素 {scene.seanixz_pro_voxel_size_mm:.3f} mm"


class SEANIXZ_PRO_OT_remesh_preview(bpy.types.Operator):
    bl_idname = "seanixz_pro.remesh_preview"
    bl_label = "重建修复预览"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        objs = mesh_objects_from_selection(context)

        if not objs:
            self.report({'ERROR'}, "请选择至少一个网格模型")
            return {'CANCELLED'}

        before = selected_face_count(context, evaluated=False)

        for obj in objs:
            mod = obj.modifiers.get("SeanIXz_Pro_重建修复预览") or obj.modifiers.new("SeanIXz_Pro_重建修复预览", 'REMESH')
            configure_main_remesh_modifier(mod, scene)

        context.view_layer.update()

        after = selected_face_count(context, evaluated=True)
        scene.seanixz_pro_remesh_before_faces = before
        scene.seanixz_pro_remesh_after_faces = after
        scene.seanixz_pro_remesh_has_preview = True

        self.report({'INFO'}, f"重建修复预览：{before:,} -> {after:,} 面，{remesh_mode_report(scene)}。")
        return {'FINISHED'}

class SEANIXZ_PRO_OT_remesh_apply(bpy.types.Operator):
    bl_idname = "seanixz_pro.remesh_apply"
    bl_label = "执行重建修复"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        objs = mesh_objects_from_selection(context)

        if not objs:
            self.report({'ERROR'}, "请选择至少一个网格模型")
            return {'CANCELLED'}

        before = selected_face_count(context, evaluated=False)

        for obj in objs:
            mod = obj.modifiers.get("SeanIXz_Pro_重建修复预览") or obj.modifiers.new("SeanIXz_Pro_重建修复预览", 'REMESH')
            configure_main_remesh_modifier(mod, scene)
            apply_modifier(context, obj, mod.name)

            if scene.seanixz_pro_remesh_smooth:
                for p in obj.data.polygons:
                    p.use_smooth = True

        after = selected_face_count(context, evaluated=False)
        scene.seanixz_pro_remesh_before_faces = before
        scene.seanixz_pro_remesh_after_faces = after

        msg = f"重建完成：{before:,} -> {after:,} 面，{remesh_mode_report(scene)}。"
        self.report({'INFO'}, msg)
        show_popup(msg, title="重建修复报告", icon='MOD_REMESH')
        return {'FINISHED'}

class SEANIXZ_PRO_OT_remesh_one_click(bpy.types.Operator):
    bl_idname = "seanixz_pro.remesh_one_click"
    bl_label = "一键执行重建修复"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.ops.seanixz_pro.remesh_preview()
        bpy.ops.seanixz_pro.remesh_apply()
        return {'FINISHED'}

# -----------------------------------------------------------------------------
# 04 切刀绘制
# -----------------------------------------------------------------------------

class SEANIXZ_PRO_OT_setup_surface_snap(bpy.types.Operator):
    bl_idname = "seanixz_pro.setup_surface_snap"
    bl_label = "一键面吸附+法向"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ts = context.scene.tool_settings

        try:
            ts.use_snap = True
            ts.snap_elements = {'FACE'}
            ts.snap_target = 'CLOSEST'
            ts.use_snap_align_rotation = True
        except Exception:
            pass

        try:
            context.scene.transform_orientation_slots[0].type = 'NORMAL'
        except Exception:
            pass

        msg = "已设置为：面吸附 + 法向变换。"
        self.report({'INFO'}, msg)
        show_popup(msg, title="吸附设置完成", icon='SNAP_FACE')
        return {'FINISHED'}

class SEANIXZ_PRO_OT_create_single_point_cutter(bpy.types.Operator):
    bl_idname = "seanixz_pro.create_single_point_cutter"
    bl_label = "创建点"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ensure_object_mode()

        scene = context.scene
        size = max(10.0 * mm_to_bu(scene), 0.001)

        bpy.ops.mesh.primitive_plane_add(size=size, enter_editmode=False, align='WORLD')
        obj = context.active_object

        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "创建平面失败。")
            return {'CANCELLED'}

        obj.name = "SeanIXz_Pro_Cutter_Point"
        setup_cutter_display(obj)

        ensure_edit_mode(obj)

        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.merge(type='CENTER')

        msg = "已创建单点切刀起点。"
        self.report({'INFO'}, msg)
        show_popup(msg, title="创建点完成", icon='MESH_PLANE')
        return {'FINISHED'}

class SEANIXZ_PRO_OT_setup_snap_and_create_cutter_point(bpy.types.Operator):
    bl_idname = "seanixz_pro.setup_snap_and_create_cutter_point"
    bl_label = "一键面吸附并创建起点"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ts = context.scene.tool_settings

        try:
            ts.use_snap = True
            ts.snap_elements = {'FACE'}
            ts.snap_target = 'CLOSEST'
            ts.use_snap_align_rotation = True
        except Exception:
            pass

        try:
            context.scene.transform_orientation_slots[0].type = 'NORMAL'
        except Exception:
            pass

        ensure_object_mode()

        scene = context.scene
        size = max(10.0 * mm_to_bu(scene), 0.001)

        bpy.ops.mesh.primitive_plane_add(size=size, enter_editmode=False, align='WORLD')
        obj = context.active_object

        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "创建切刀起点失败。")
            return {'CANCELLED'}

        obj.name = "SeanIXz_Pro_Cutter_Point"
        setup_cutter_display(obj)

        ensure_edit_mode(obj)

        try:
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.merge(type='CENTER')
        except Exception:
            pass

        msg = (
            "已完成：面吸附 + 法向变换 + 创建切刀起点。\n"
            "下一步：保持编辑模式，用 G 移动到模型表面，用 E 挤出继续画切刀线。"
        )
        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg, title="切刀绘制准备完成", icon='SNAP_FACE')
        return {'FINISHED'}


class SEANIXZ_PRO_OT_close_selected_points(bpy.types.Operator):
    bl_idname = "seanixz_pro.close_selected_points"
    bl_label = "一键闭合"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh_object(context)

        if not obj or obj.mode != 'EDIT':
            self.report({'ERROR'}, "请先选中切刀并进入编辑模式。")
            return {'CANCELLED'}

        bm = bmesh.from_edit_mesh(obj.data)
        selected_verts = [v for v in bm.verts if v.select]

        if len(selected_verts) != 2:
            self.report({'ERROR'}, "请只选中首尾两个点。")
            return {'CANCELLED'}

        try:
            bpy.ops.mesh.edge_face_add()
        except Exception:
            self.report({'ERROR'}, "闭合失败，请确认只选中了两个端点。")
            return {'CANCELLED'}

        self.report({'INFO'}, "闭合完成。")
        return {'FINISHED'}

class SEANIXZ_PRO_OT_fit_selected_loop(bpy.types.Operator):
    bl_idname = "seanixz_pro.fit_selected_loop"
    bl_label = "一键拟合"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh_object(context)

        if not obj or obj.mode != 'EDIT':
            self.report({'ERROR'}, "请先选中切刀并进入编辑模式。")
            return {'CANCELLED'}

        ok, msg = rebuild_selected_loop_as_smooth_curve(obj, context.scene)

        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg)
        show_popup(
            "拟合完成。\n原始点保持不动，仅在相邻点之间插入曲线过渡点，提高边线流畅度。",
            title="拟合完成",
            icon='MOD_SUBSURF'
        )
        return {'FINISHED'}

class SEANIXZ_PRO_OT_toggle_tenon_direction(bpy.types.Operator):
    bl_idname = "seanixz_pro.toggle_tenon_direction"
    bl_label = "一键反向卡榫"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        scene.seanixz_pro_tenon_reverse_direction = not bool(scene.seanixz_pro_tenon_reverse_direction)
        state = "反向" if scene.seanixz_pro_tenon_reverse_direction else "正向"
        msg = f"卡榫生成方向已切换为：{state}。再次点击可切回。"
        self.report({'INFO'}, msg)
        show_popup(msg + "\n说明：该按钮影响下一次生成卡榫1/卡榫2，不会自动翻转已经生成的旧卡榫。", title="卡榫方向切换", icon='FILE_REFRESH')
        return {'FINISHED'}


class SEANIXZ_PRO_OT_make_simple_tenon(bpy.types.Operator):
    bl_idname = "seanixz_pro.make_simple_tenon"
    bl_label = "简单卡榫1"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh_object(context)

        if not obj or obj.mode != 'EDIT':
            self.report({'ERROR'}, "请先选中切刀并进入编辑模式。")
            return {'CANCELLED'}

        ok, msg = make_simple_tenon_geometry(obj, context.scene)

        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg)
        show_popup(
            msg + "\n流程：圈线 E,S 外扩 → 内圈法向 E 拉出 → 顶部缩放 → F填顶面 → 拉平 → 可选倒角。",
            title="简单卡榫1完成",
            icon='MESH_CUBE'
        )
        return {'FINISHED'}


class SEANIXZ_PRO_OT_make_simple_tenon2(bpy.types.Operator):
    bl_idname = "seanixz_pro.make_simple_tenon2"
    bl_label = "简单卡榫2"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh_object(context)

        if not obj or obj.mode != 'EDIT':
            self.report({'ERROR'}, "请先选中切刀并进入编辑模式。")
            return {'CANCELLED'}

        ok, msg = make_simple_tenon2_geometry(obj, context.scene)

        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg)
        show_popup(
            msg + "\n流程：圈线 E,S 外扩 → 内圈 E,S 内缩 → 法向拉出 → F填顶面 → 拉平 → 可选倒角。",
            title="简单卡榫2完成",
            icon='MESH_CUBE'
        )
        return {'FINISHED'}


class SEANIXZ_PRO_OT_bevel_selected_edges(bpy.types.Operator):
    bl_idname = "seanixz_pro.bevel_selected_edges"
    bl_label = "一键倒角"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh_object(context)

        if not obj or obj.mode != 'EDIT':
            self.report({'ERROR'}, "请先选中需要倒角的边，并进入编辑模式。")
            return {'CANCELLED'}

        scene = context.scene
        bevel = scene.seanixz_pro_bevel_mm * mm_to_bu(scene)

        if bevel <= 0:
            self.report({'ERROR'}, "倒角尺寸必须大于 0。")
            return {'CANCELLED'}

        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        edges = selected_edges_or_edges_from_selected_verts(bm)

        if not edges:
            self.report({'ERROR'}, "没有找到已选中的边。请选中顶部圈线或需要倒角的边。")
            return {'CANCELLED'}

        try:
            ret = bmesh.ops.bevel(
                bm,
                geom=edges,
                offset=max(bevel, 0.000001),
                offset_type='OFFSET',
                segments=max(scene.seanixz_pro_bevel_segments, 1),
                profile=0.5,
                affect='EDGES',
                clamp_overlap=True,
            )
        except Exception as exc:
            self.report({'ERROR'}, f"倒角失败：{exc}")
            return {'CANCELLED'}

        recalc_bmesh_normals(bm)

        face_set, edge_set, vert_set = collect_valid_faces_edges_verts(extra_geom=ret.get('geom', []) + ret.get('faces', []))
        select_geometry(bm, verts=vert_set, edges=edge_set, faces=face_set)

        bmesh.update_edit_mesh(obj.data)
        obj.data.update()

        msg = f"倒角完成：{scene.seanixz_pro_bevel_mm:.3f} mm，段数 {scene.seanixz_pro_bevel_segments}。"
        self.report({'INFO'}, msg)
        show_popup(msg, title="一键倒角完成", icon='MOD_BEVEL')
        return {'FINISHED'}


class SEANIXZ_PRO_OT_apply_joint_fit_preset(bpy.types.Operator):
    bl_idname = "seanixz_pro.apply_joint_fit_preset"
    bl_label = "应用打印间隙预设"
    bl_description = "根据打印方式设置活动间隙、装配余量和磁铁孔余量；建议仍先打印小样校准"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        preset = scene.seanixz_pro_joint_fit_preset
        values = {
            'RESIN': (0.15, 0.20, 0.10, "树脂精细"),
            'FDM_TIGHT': (0.22, 0.28, 0.12, "FDM 紧配"),
            'FDM_STANDARD': (0.30, 0.40, 0.15, "FDM 标准"),
            'FDM_LOOSE': (0.42, 0.55, 0.22, "FDM 宽松"),
        }
        clearance, margin, magnet_fit, label = values[preset]
        scene.seanixz_pro_joint_clearance_mm = clearance
        scene.seanixz_pro_joint_assembly_margin_mm = margin
        scene.seanixz_pro_joint_magnet_clearance_mm = magnet_fit
        msg = (
            f"已应用{label}预设：活动间隙 {clearance:.2f} mm，"
            f"装配余量 {margin:.2f} mm，磁铁孔单边余量 {magnet_fit:.2f} mm。"
        )
        self.report({'INFO'}, msg)
        return {'FINISHED'}


def figure_joint_preset_settings(preset):
    values = {
        # 类型、圈线比例、最小可打印尺寸、深度、摆角、轴向、阻尼、活动空间、分离外扩倍率、额外外扩mm、名称
        'NECK': ('DOUBLE_BALL', 0.48, 6.0, 6.0, 35.0, 'LONG', False, 1.38, 1.10, 1.2, "头颈双球头"),
        'SHOULDER': ('BALL_LINK', 0.65, 7.0, 7.0, 58.0, 'LONG', False, 1.55, 1.12, 1.3, "肩部独立球头连接件"),
        'ELBOW': ('DOUBLE_HINGE', 0.50, 5.2, 8.0, 5.0, 'SHORT', False, 1.38, 1.12, 1.3, "肘部可压入双转轴"),
        'WRIST': ('BALL_LINK', 0.48, 5.0, 4.5, 40.0, 'LONG', False, 1.38, 1.10, 1.0, "腕部加大球头连接件"),
        'TORSO': ('DOUBLE_BALL', 0.62, 8.0, 8.0, 35.0, 'LONG', False, 1.42, 1.10, 1.5, "胸腹一体分离双球头"),
        'WAIST': ('DOUBLE_BALL', 0.55, 7.0, 7.0, 30.0, 'LONG', False, 1.35, 1.10, 1.3, "腰部紧凑双球头"),
        'HIP': ('BALL_LINK', 0.62, 8.0, 8.0, 58.0, 'LONG', False, 1.55, 1.12, 1.5, "髋部独立球头连接件"),
        'KNEE': ('DOUBLE_HINGE', 0.52, 6.0, 10.0, 5.0, 'SHORT', False, 1.42, 1.12, 1.5, "膝部可压入双转轴"),
        'ANKLE': ('DOUBLE_BALL', 0.42, 5.5, 5.5, 45.0, 'LONG', False, 1.45, 1.10, 1.0, "踝部双球头摇摆"),
    }
    return values.get(preset, values['SHOULDER'])


def apply_figure_joint_preset_values(scene):
    preset = scene.seanixz_pro_figure_joint_preset
    (
        joint_type,
        size_factor,
        min_size_mm,
        depth_mm,
        angle_deg,
        hinge_axis,
        damping,
        swing_factor,
        split_factor,
        split_expand_mm,
        label,
    ) = figure_joint_preset_settings(preset)
    scene.seanixz_pro_joint_auto_size = True
    scene.seanixz_pro_joint_type = joint_type
    scene.seanixz_pro_joint_size_factor = size_factor
    scene.seanixz_pro_joint_min_print_size_mm = min_size_mm
    scene.seanixz_pro_joint_connection_depth_mm = depth_mm
    scene.seanixz_pro_joint_angle_deg = angle_deg
    scene.seanixz_pro_joint_hinge_axis = hinge_axis
    scene.seanixz_pro_joint_hinge_damping = damping
    scene.seanixz_pro_joint_swing_room_factor = swing_factor
    scene.seanixz_pro_joint_integrated_split_cutter = True
    scene.seanixz_pro_joint_split_expand_factor = split_factor
    scene.seanixz_pro_joint_split_expand_mm = split_expand_mm
    return label


def update_figure_joint_preset(self, context):
    scene = getattr(context, "scene", None)
    if scene is not None:
        apply_figure_joint_preset_values(scene)


class SEANIXZ_PRO_OT_apply_figure_joint_preset(bpy.types.Operator):
    bl_idname = "seanixz_pro.apply_figure_joint_preset"
    bl_label = "应用可动手办部位预设"
    bl_description = "按头颈、肩肘、胸腰、髋膝和踝腕用途设置关节类型与推荐起始尺寸；仍需打印小样校准"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        label = apply_figure_joint_preset_values(scene)

        msg = (
            f"已应用{label}预设：类型 {scene.seanixz_pro_joint_type}，尺寸比例 {scene.seanixz_pro_joint_size_factor:.2f}，"
            f"最小尺寸 {scene.seanixz_pro_joint_min_print_size_mm:.2f} mm，连接深度 {scene.seanixz_pro_joint_connection_depth_mm:.2f} mm。"
        )
        self.report({'INFO'}, msg)
        show_popup(
            msg + "\n\n这是基于可动手办结构图整理的通用起点。不同材料、层纹方向和模型比例仍需先打印关节小样。",
            title="可动手办关节预设已应用",
            icon='CONSTRAINT_BONE',
        )
        return {'FINISHED'}


class SEANIXZ_PRO_OT_make_print_ready_figure_joint(bpy.types.Operator):
    bl_idname = "seanixz_pro.make_print_ready_figure_joint"
    bl_label = "一键生成可打印活动关节"
    bl_description = "自动应用所选身体部位参数，生成一体式分离切刀和独立连接件；切刀一次布尔即可完成分件、关节腔和装配入口"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        label = apply_figure_joint_preset_values(scene)
        male, female, msg = make_hi3d_joint_pair(context)
        if not male or not female:
            self.report({'ERROR'}, msg)
            show_popup(msg, title="活动关节生成失败", icon='ERROR')
            return {'CANCELLED'}
        self.report({'INFO'}, f"{label}可打印关节已生成")
        show_popup(
            msg + "\n\n安装顺序：先应用蓝色一体切刀并按松散块分离零件；再安装绿色连接件。首次使用请打印同尺寸小样。",
            title="可打印活动关节已生成",
            icon='MOD_BOOLEAN',
        )
        return {'FINISHED'}


class SEANIXZ_PRO_OT_make_joint_magnet_pocket_pair(bpy.types.Operator):
    bl_idname = "seanixz_pro.make_joint_magnet_pocket_pair"
    bl_label = "生成成对磁铁孔切刀"
    bl_description = "根据所选闭合圈线，在装配面 A、B 两侧生成同轴磁铁孔切刀"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cutter_a, cutter_b, msg = make_joint_magnet_pocket_pair(context)
        if not cutter_a or not cutter_b:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(
            msg + "\n\n建议让两颗磁铁的极性相吸，并在最终布尔前确认 A/B 切刀没有用反。",
            title="磁吸定位孔切刀完成",
            icon='MOD_BOOLEAN',
        )
        return {'FINISHED'}


class SEANIXZ_PRO_OT_make_hi3d_joint_pair(bpy.types.Operator):
    bl_idname = "seanixz_pro.make_hi3d_joint_pair"
    bl_label = "生成成对连接件"
    bl_description = "根据所选闭合圈线一次生成公连接件和带间隙的母槽切刀"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        male, female, msg = make_hi3d_joint_pair(context)

        if not male or not female:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(
            msg + "\n\n使用顺序：公件与一侧模型做并集；母槽切刀与另一侧模型做差集。建议先打印小样确认材料对应的组装间隙。",
            title="活动连接对生成完成",
            icon='CONSTRAINT_BONE',
        )
        return {'FINISHED'}


class SEANIXZ_PRO_OT_make_joint_pin_cutter(bpy.types.Operator):
    bl_idname = "seanixz_pro.make_joint_pin_cutter"
    bl_label = "圆轴孔切刀"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj, msg = make_joint_pin_cutter(context)

        if not obj:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(
            msg + "\n\n新手理解：它生成的是‘减去用的圆柱切刀’，不是最终零件。把它和目标模型做普通布尔差集，就能得到可插轴的孔。",
            title="圆轴孔切刀完成",
            icon='MESH_CYLINDER'
        )
        return {'FINISHED'}


class SEANIXZ_PRO_OT_make_joint_disc_clearance_cutter(bpy.types.Operator):
    bl_idname = "seanixz_pro.make_joint_disc_clearance_cutter"
    bl_label = "圆盘间隙切刀"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj, msg = make_joint_disc_clearance_cutter(context)

        if not obj:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(
            msg + "\n\n新手理解：它像一个薄圆饼，用来给旋转片、摆臂或圆盘关节预留转动空间，避免两个零件贴死。",
            title="圆盘间隙切刀完成",
            icon='MESH_CYLINDER'
        )
        return {'FINISHED'}


class SEANIXZ_PRO_OT_make_joint_hinge_barrel_cutter(bpy.types.Operator):
    bl_idname = "seanixz_pro.make_joint_hinge_barrel_cutter"
    bl_label = "横向合页轴槽"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj, msg = make_joint_hinge_barrel_cutter(context)

        if not obj:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(
            msg + "\n\n新手理解：它会沿所选圈线的最长方向生成横向圆柱切刀，适合做合页/铰链那种横穿的圆轴槽。",
            title="横向合页轴槽完成",
            icon='MESH_CYLINDER'
        )
        return {'FINISHED'}


class SEANIXZ_PRO_OT_make_joint_ball_socket_cutter(bpy.types.Operator):
    bl_idname = "seanixz_pro.make_joint_ball_socket_cutter"
    bl_label = "球窝关节切刀"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj, msg = make_joint_ball_socket_cutter(context)

        if not obj:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(
            msg + "\n\n新手理解：它会生成球形活动空间和开口通道。打印前建议先做小样测试，因为球窝关节对材料韧性、层纹方向和打印间隙很敏感。",
            title="球窝关节切刀完成",
            icon='MESH_UVSPHERE'
        )
        return {'FINISHED'}


class SEANIXZ_PRO_OT_make_joint_snap_ball_socket_cutter(bpy.types.Operator):
    bl_idname = "seanixz_pro.make_joint_snap_ball_socket_cutter"
    bl_label = "生成球形关节切刀"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj, msg = make_joint_snap_ball_socket_cutter(context)

        if not obj:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(
            msg + "\n\n使用方法：把蓝色线框切刀与球窝所在部件执行差集。球形内腔负责转动，较小锁口负责卡持，外扩锥口负责给球杆预留摆动空间。打印前建议先用小样校准装配间隙和材料弹性。",
            title="球形关节切刀完成",
            icon='MESH_UVSPHERE'
        )
        return {'FINISHED'}


class SEANIXZ_PRO_OT_make_joint_snap_hinge_cutter(bpy.types.Operator):
    bl_idname = "seanixz_pro.make_joint_snap_hinge_cutter"
    bl_label = "自锁转轴活动切刀"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj, msg = make_joint_snap_hinge_cutter(context)

        if not obj:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(
            msg + "\n\n新手理解：这是 C 形按压装配式转轴关节切刀。圆腔用于轴转动，窄口保留锁止边，外侧活动槽用于增加旋转范围。",
            title="自锁转轴活动切刀完成",
            icon='MESH_CYLINDER'
        )
        return {'FINISHED'}


class SEANIXZ_PRO_OT_add_tenon_lock_wedge(bpy.types.Operator):
    bl_idname = "seanixz_pro.add_tenon_lock_wedge"
    bl_label = "楔形锁止凸起"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh_object(context)
        if not obj or obj.mode != 'EDIT':
            self.report({'ERROR'}, "请先选中卡榫顶部面或顶部圈线，并进入编辑模式。")
            return {'CANCELLED'}

        ok, msg = add_tenon_lock_geometry(obj, context.scene, 'WEDGE')
        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg + "\n新手提示：楔形方向感最强，适合做防呆，减少装反。", title="楔形锁止完成", icon='MESH_CUBE')
        return {'FINISHED'}


class SEANIXZ_PRO_OT_add_tenon_lock_triangle(bpy.types.Operator):
    bl_idname = "seanixz_pro.add_tenon_lock_triangle"
    bl_label = "三角防呆凸起"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh_object(context)
        if not obj or obj.mode != 'EDIT':
            self.report({'ERROR'}, "请先选中卡榫顶部面或顶部圈线，并进入编辑模式。")
            return {'CANCELLED'}

        ok, msg = add_tenon_lock_geometry(obj, context.scene, 'TRIANGLE')
        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg + "\n新手提示：三角形适合做方向定位，让装配件只能以一个明显方向对准。", title="三角防呆完成", icon='MESH_CUBE')
        return {'FINISHED'}


class SEANIXZ_PRO_OT_add_tenon_lock_hex(bpy.types.Operator):
    bl_idname = "seanixz_pro.add_tenon_lock_hex"
    bl_label = "六边定位凸起"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh_object(context)
        if not obj or obj.mode != 'EDIT':
            self.report({'ERROR'}, "请先选中卡榫顶部面或顶部圈线，并进入编辑模式。")
            return {'CANCELLED'}

        ok, msg = add_tenon_lock_geometry(obj, context.scene, 'HEX')
        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg + "\n新手提示：六边形更像定位柱/止转点，适合让上下件更稳地对位。", title="六边定位完成", icon='MESH_CYLINDER')
        return {'FINISHED'}


class SEANIXZ_PRO_OT_add_tenon_lock_square(bpy.types.Operator):
    bl_idname = "seanixz_pro.add_tenon_lock_square"
    bl_label = "方形定位结构"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh_object(context)
        if not obj or obj.mode != 'EDIT':
            self.report({'ERROR'}, "请先选中卡榫顶部面或顶部圈线，并进入编辑模式。")
            return {'CANCELLED'}

        ok, msg = add_tenon_lock_geometry(obj, context.scene, 'SQUARE')
        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg + "\n新手提示：方形适合做基础定位和防转结构，底部接触面为空，方便作为切刀布尔。", title="方形定位完成", icon='MESH_CUBE')
        return {'FINISHED'}


class SEANIXZ_PRO_OT_add_tenon_lock_diamond(bpy.types.Operator):
    bl_idname = "seanixz_pro.add_tenon_lock_diamond"
    bl_label = "菱形防呆结构"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh_object(context)
        if not obj or obj.mode != 'EDIT':
            self.report({'ERROR'}, "请先选中卡榫顶部面或顶部圈线，并进入编辑模式。")
            return {'CANCELLED'}

        ok, msg = add_tenon_lock_geometry(obj, context.scene, 'DIAMOND')
        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg + "\n新手提示：菱形方向感明显，适合做只能按特定方向对齐的防呆结构。", title="菱形防呆完成", icon='MESH_CUBE')
        return {'FINISHED'}


class SEANIXZ_PRO_OT_cutter_wire_display(bpy.types.Operator):
    bl_idname = "seanixz_pro.cutter_wire_display"
    bl_label = "切刀线框/平面切换"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh_object(context)

        if not obj:
            self.report({'ERROR'}, "请先选中一个切刀对象。")
            return {'CANCELLED'}

        is_wire = (obj.display_type == 'WIRE' and bool(obj.show_in_front))

        if is_wire:
            set_cutter_display_mode(obj, 'PLANE')
            msg = "已切换为平面模式：常规显示，不透视，便于观察切刀面与模型相交区域。"
            icon = 'MESH_PLANE'
        else:
            set_cutter_display_mode(obj, 'WIRE')
            msg = "已切换为线框模式：线框显示并开启透视，便于继续绘制和定位切刀。"
            icon = 'SHADING_WIRE'

        self.report({'INFO'}, msg)
        show_popup(msg, title="切刀显示模式", icon=icon)
        return {'FINISHED'}

# -----------------------------------------------------------------------------
# 05 切刀预处理
# -----------------------------------------------------------------------------

class SEANIXZ_PRO_OT_merge_by_distance(bpy.types.Operator):
    bl_idname = "seanixz_pro.merge_by_distance"
    bl_label = "合并-按距离"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = mesh_objects_from_selection(context)

        if not objs:
            self.report({'ERROR'}, "请选择至少一个网格模型")
            return {'CANCELLED'}

        threshold = context.scene.seanixz_pro_merge_distance_mm * mm_to_bu(context.scene)
        total_removed = 0

        ensure_object_mode()

        for obj in objs:
            before = len(obj.data.vertices)

            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj

            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')

            try:
                bpy.ops.mesh.remove_doubles(threshold=threshold)
            except Exception:
                bpy.ops.mesh.merge_by_distance(distance=threshold)

            bpy.ops.object.mode_set(mode='OBJECT')

            after = len(obj.data.vertices)
            total_removed += before - after

        context.scene.seanixz_pro_last_preprocess_report = (
            f"合并后减少顶点：{total_removed} 个；合并间距：{context.scene.seanixz_pro_merge_distance_mm:.3f} mm。"
        )

        self.report({'INFO'}, context.scene.seanixz_pro_last_preprocess_report)
        return {'FINISHED'}

class SEANIXZ_PRO_OT_recalc_normals(bpy.types.Operator):
    bl_idname = "seanixz_pro.recalc_normals"
    bl_label = "Shift+N 法线统一"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = mesh_objects_from_selection(context)

        if not objs:
            self.report({'ERROR'}, "请选择至少一个网格模型")
            return {'CANCELLED'}

        ensure_object_mode()

        for obj in objs:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj

            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode='OBJECT')

        self.report({'INFO'}, f"已统一 {len(objs)} 个模型的法线方向")
        return {'FINISHED'}

class SEANIXZ_PRO_OT_delete_interior_loose(bpy.types.Operator):
    bl_idname = "seanixz_pro.delete_interior_loose"
    bl_label = "删除内部面/松散元素"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = mesh_objects_from_selection(context)

        if not objs:
            self.report({'ERROR'}, "请选择至少一个网格模型")
            return {'CANCELLED'}

        ensure_object_mode()

        total_v = 0
        total_f = 0

        for obj in objs:
            before_v = len(obj.data.vertices)
            before_f = len(obj.data.polygons)

            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj

            try:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='DESELECT')
                bpy.ops.mesh.select_interior_faces()
                bpy.ops.mesh.delete(type='FACE')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.delete_loose()
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                ensure_object_mode()
                remove_loose_and_interior(obj)

            total_v += max(before_v - len(obj.data.vertices), 0)
            total_f += max(before_f - len(obj.data.polygons), 0)

        context.scene.seanixz_pro_last_preprocess_report = (
            f"删除松散元素减少顶点：{total_v} 个；删除内部/垃圾面：{total_f} 个。"
        )

        self.report({'INFO'}, context.scene.seanixz_pro_last_preprocess_report)
        return {'FINISHED'}

class SEANIXZ_PRO_OT_delete_floating_faces(bpy.types.Operator):
    bl_idname = "seanixz_pro.delete_floating_faces"
    bl_label = "清理游离面"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = mesh_objects_from_selection(context)

        if not objs:
            self.report({'ERROR'}, "请选择至少一个网格模型")
            return {'CANCELLED'}

        ensure_object_mode()

        total_faces = 0
        total_verts = 0

        for obj in objs:
            deleted_faces, deleted_verts = remove_floating_face_islands(obj)
            total_faces += deleted_faces
            total_verts += deleted_verts

        context.scene.seanixz_pro_last_preprocess_report = (
            f"游离面清理完成：删除游离面 {total_faces} 个，清理游离顶点 {total_verts} 个。\n"
            "说明：该功能保留最大连续面片岛，删除较小的漂浮面片，适合清理布尔失败前的残留面。"
        )

        self.report({'INFO'}, context.scene.seanixz_pro_last_preprocess_report.replace('\n', ' '))
        show_popup(context.scene.seanixz_pro_last_preprocess_report, title="游离面清理", icon='BRUSH_DATA')
        return {'FINISHED'}


class SEANIXZ_PRO_OT_preprocess_all(bpy.types.Operator):
    bl_idname = "seanixz_pro.preprocess_all"
    bl_label = "一键切刀预处理"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = mesh_objects_from_selection(context)

        if not objs:
            self.report({'ERROR'}, "请选择至少一个网格模型")
            return {'CANCELLED'}

        before_v = sum(len(o.data.vertices) for o in objs)
        before_f = sum(len(o.data.polygons) for o in objs)

        bpy.ops.seanixz_pro.merge_by_distance()
        bpy.ops.seanixz_pro.recalc_normals()
        bpy.ops.seanixz_pro.delete_interior_loose()

        floating_faces = 0
        floating_verts = 0
        for obj in objs:
            deleted_faces, deleted_verts = remove_floating_face_islands(obj)
            floating_faces += deleted_faces
            floating_verts += deleted_verts

        after_v = sum(len(o.data.vertices) for o in objs)
        after_f = sum(len(o.data.polygons) for o in objs)

        report = (
            f"切刀预处理完成。\n"
            f"合并/清理后减少顶点：{max(before_v - after_v, 0)} 个\n"
            f"删除内部/垃圾面：{max(before_f - after_f, 0)} 个\n"
            f"清理游离面：{floating_faces} 个，游离顶点：{floating_verts} 个\n"
            f"法线方向：已按 Shift+N 统一朝外\n"
            f"合并间距：{context.scene.seanixz_pro_merge_distance_mm:.3f} mm"
        )

        context.scene.seanixz_pro_last_preprocess_report = report
        self.report({'INFO'}, report.replace('\n', ' '))
        show_popup(report, title="切刀预处理报告", icon='BRUSH_DATA')
        return {'FINISHED'}

# -----------------------------------------------------------------------------
# 06 布尔分件
# -----------------------------------------------------------------------------

def evaluated_mesh_island_summary(context, obj):
    """返回求值后网格的孤岛数量和世界尺寸，不修改源模型。"""
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = None

    try:
        mesh = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
        vertex_count = len(mesh.vertices)

        if vertex_count == 0:
            return 0, Vector((0.0, 0.0, 0.0))

        parent = list(range(vertex_count))
        rank = bytearray(vertex_count)

        def find_root(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(a, b):
            root_a = find_root(a)
            root_b = find_root(b)

            if root_a == root_b:
                return

            if rank[root_a] < rank[root_b]:
                root_a, root_b = root_b, root_a

            parent[root_b] = root_a

            if rank[root_a] == rank[root_b]:
                rank[root_a] += 1

        for edge in mesh.edges:
            union(edge.vertices[0], edge.vertices[1])

        island_count = len({find_root(index) for index in range(vertex_count)})
        return island_count, Vector(eval_obj.dimensions)
    finally:
        if mesh is not None:
            try:
                eval_obj.to_mesh_clear()
            except Exception:
                pass


def enabled_named_socket(sockets, name):
    """查找节点中当前启用的同名输入端口。"""
    named = [socket for socket in sockets if socket.name == name]

    for socket in named:
        if getattr(socket, "enabled", True) and not getattr(socket, "hide", False):
            return socket

    return named[-1] if named else None


def ensure_nondestructive_preview_node_group():
    node_group = bpy.data.node_groups.get(ND_PREVIEW_NODE_GROUP)

    if not node_group:
        node_group = bpy.data.node_groups.new(ND_PREVIEW_NODE_GROUP, 'GeometryNodeTree')

    if node_group.get("seanixz_preview_node_version") == ND_PREVIEW_NODE_VERSION:
        try:
            source_socket = next(
                item for item in node_group.interface.items_tree
                if getattr(item, "in_out", None) == 'INPUT' and item.name == "源模型"
            )
            cutter_socket = next(
                item for item in node_group.interface.items_tree
                if getattr(item, "in_out", None) == 'INPUT' and item.name == "切刀"
            )
            gap_socket = next(
                item for item in node_group.interface.items_tree
                if getattr(item, "in_out", None) == 'INPUT' and item.name == "观察间距"
            )
            count_socket = next(
                item for item in node_group.interface.items_tree
                if getattr(item, "in_out", None) == 'INPUT' and item.name == "拆件数量"
            )
            return (
                node_group,
                source_socket.identifier,
                cutter_socket.identifier,
                gap_socket.identifier,
                count_socket.identifier,
            )
        except StopIteration:
            pass

    node_group.nodes.clear()
    node_group.interface.clear()

    node_group.interface.new_socket(
        name="几何数据",
        in_out='INPUT',
        socket_type='NodeSocketGeometry',
    )
    source_socket = node_group.interface.new_socket(
        name="源模型",
        in_out='INPUT',
        socket_type='NodeSocketObject',
    )
    cutter_socket = node_group.interface.new_socket(
        name="切刀",
        in_out='INPUT',
        socket_type='NodeSocketObject',
    )
    gap_socket = node_group.interface.new_socket(
        name="观察间距",
        in_out='INPUT',
        socket_type='NodeSocketFloat',
    )
    gap_socket.default_value = 0.01
    gap_socket.min_value = 0.0
    count_socket = node_group.interface.new_socket(
        name="拆件数量",
        in_out='INPUT',
        socket_type='NodeSocketFloat',
    )
    count_socket.default_value = 2.0
    count_socket.min_value = 1.0
    node_group.interface.new_socket(
        name="几何数据",
        in_out='OUTPUT',
        socket_type='NodeSocketGeometry',
    )

    nodes = node_group.nodes
    links = node_group.links

    group_input = nodes.new("NodeGroupInput")
    group_input.name = "SeanIXz_群组输入"
    group_input.label = "源模型、切刀与观察间距"
    group_input.location = (-1160.0, -240.0)

    object_info = nodes.new("GeometryNodeObjectInfo")
    object_info.name = "SeanIXz_物体信息"
    object_info.label = "读取未应用修改器的结果"
    object_info.location = (-940.0, 140.0)
    object_info.transform_space = 'ORIGINAL'

    cutter_info = nodes.new("GeometryNodeObjectInfo")
    cutter_info.name = "SeanIXz_切刀物体信息"
    cutter_info.label = "实时读取切割面"
    cutter_info.location = (-940.0, -300.0)
    cutter_info.transform_space = 'ORIGINAL'

    normal_input = nodes.new("GeometryNodeInputNormal")
    normal_input.name = "SeanIXz_切刀表面法向"
    normal_input.location = (-720.0, -480.0)

    sample_normal = nodes.new("GeometryNodeSampleIndex")
    sample_normal.name = "SeanIXz_采样切割面法向"
    sample_normal.data_type = 'FLOAT_VECTOR'
    sample_normal.domain = 'FACE'
    sample_normal.location = (-500.0, -360.0)
    sample_normal.inputs["Index"].default_value = 0

    rotate_direction = nodes.new("ShaderNodeVectorRotate")
    rotate_direction.name = "SeanIXz_应用切刀物体旋转"
    rotate_direction.rotation_type = 'EULER_XYZ'
    rotate_direction.location = (-260.0, -420.0)

    normalize_direction = nodes.new("ShaderNodeVectorMath")
    normalize_direction.name = "SeanIXz_归一化切割法向"
    normalize_direction.operation = 'NORMALIZE'
    normalize_direction.location = (-20.0, -380.0)

    mesh_island = nodes.new("GeometryNodeInputMeshIsland")
    mesh_island.name = "SeanIXz_网格孤岛"
    mesh_island.location = (-940.0, 380.0)

    split_instances = nodes.new("GeometryNodeSplitToInstances")
    split_instances.name = "SeanIXz_按孤岛拆分实例"
    split_instances.label = "孤岛自动拆件"
    split_instances.location = (-660.0, 260.0)
    split_instances.domain = 'POINT'

    bounding_box = nodes.new("GeometryNodeBoundBox")
    bounding_box.name = "SeanIXz_源模型包围盒"
    bounding_box.location = (-660.0, -80.0)

    size_vector = nodes.new("ShaderNodeVectorMath")
    size_vector.name = "SeanIXz_包围盒尺寸"
    size_vector.operation = 'SUBTRACT'
    size_vector.location = (-420.0, -80.0)

    separate_size = nodes.new("ShaderNodeSeparateXYZ")
    separate_size.name = "SeanIXz_分离包围盒尺寸"
    separate_size.location = (-180.0, -80.0)

    x_spacing = nodes.new("ShaderNodeMath")
    x_spacing.name = "SeanIXz_X轴尺寸加间距"
    x_spacing.operation = 'ADD'
    x_spacing.location = (60.0, -40.0)

    count_minus_one = nodes.new("ShaderNodeMath")
    count_minus_one.name = "SeanIXz_拆件数量减一"
    count_minus_one.operation = 'SUBTRACT'
    count_minus_one.inputs[1].default_value = 1.0
    count_minus_one.location = (-180.0, 420.0)

    half_count = nodes.new("ShaderNodeMath")
    half_count.name = "SeanIXz_计算居中基准"
    half_count.operation = 'MULTIPLY'
    half_count.inputs[1].default_value = 0.5
    half_count.location = (40.0, 420.0)

    centered_order = nodes.new("ShaderNodeMath")
    centered_order.name = "SeanIXz_居中孤岛顺序"
    centered_order.operation = 'SUBTRACT'
    centered_order.location = (260.0, 300.0)

    x_offset = nodes.new("ShaderNodeMath")
    x_offset.name = "SeanIXz_X轴水平偏移"
    x_offset.operation = 'MULTIPLY'
    x_offset.location = (500.0, 120.0)

    x_direction = nodes.new("ShaderNodeCombineXYZ")
    x_direction.name = "SeanIXz_X轴方向"
    x_direction.inputs["X"].default_value = 1.0
    x_direction.location = (500.0, -80.0)

    scale_x_direction = nodes.new("ShaderNodeVectorMath")
    scale_x_direction.name = "SeanIXz_生成X轴水平位移"
    scale_x_direction.operation = 'SCALE'
    scale_x_direction.location = (740.0, 100.0)

    translate_x = nodes.new("GeometryNodeTranslateInstances")
    translate_x.name = "SeanIXz_第一步X轴水平排布"
    translate_x.label = "第一步：沿 X 轴水平展示"
    translate_x.location = (980.0, 300.0)

    normal_offset = nodes.new("ShaderNodeMath")
    normal_offset.name = "SeanIXz_切面法向展开距离"
    normal_offset.operation = 'MULTIPLY'
    normal_offset.location = (740.0, -200.0)

    scale_normal_direction = nodes.new("ShaderNodeVectorMath")
    scale_normal_direction.name = "SeanIXz_沿切割法向生成偏移"
    scale_normal_direction.operation = 'SCALE'
    scale_normal_direction.location = (980.0, -160.0)

    translate_normal = nodes.new("GeometryNodeTranslateInstances")
    translate_normal.name = "SeanIXz_第二步切面法向分离"
    translate_normal.label = "第二步：沿切面法向分离"
    translate_normal.location = (1220.0, 300.0)

    realize_instances = nodes.new("GeometryNodeRealizeInstances")
    realize_instances.name = "SeanIXz_实现拆件预览"
    realize_instances.location = (1460.0, 300.0)

    group_output = nodes.new("NodeGroupOutput")
    group_output.name = "SeanIXz_群组输出"
    group_output.location = (1700.0, 300.0)
    group_output.is_active_output = True

    links.new(group_input.outputs["源模型"], object_info.inputs["Object"])
    links.new(group_input.outputs["切刀"], cutter_info.inputs["Object"])
    links.new(cutter_info.outputs["Geometry"], sample_normal.inputs["Geometry"])
    links.new(normal_input.outputs["Normal"], sample_normal.inputs["Value"])
    links.new(sample_normal.outputs["Value"], rotate_direction.inputs["Vector"])
    links.new(cutter_info.outputs["Rotation"], rotate_direction.inputs["Rotation"])
    links.new(rotate_direction.outputs["Vector"], normalize_direction.inputs[0])
    links.new(object_info.outputs["Geometry"], split_instances.inputs["Geometry"])
    links.new(mesh_island.outputs["Island Index"], split_instances.inputs["Group ID"])
    links.new(object_info.outputs["Geometry"], bounding_box.inputs["Geometry"])
    links.new(bounding_box.outputs["Max"], size_vector.inputs[0])
    links.new(bounding_box.outputs["Min"], size_vector.inputs[1])
    links.new(size_vector.outputs["Vector"], separate_size.inputs["Vector"])
    links.new(separate_size.outputs["X"], x_spacing.inputs[0])
    links.new(group_input.outputs["观察间距"], x_spacing.inputs[1])
    links.new(group_input.outputs["拆件数量"], count_minus_one.inputs[0])
    links.new(count_minus_one.outputs[0], half_count.inputs[0])
    links.new(split_instances.outputs["Group ID"], centered_order.inputs[0])
    links.new(half_count.outputs[0], centered_order.inputs[1])
    links.new(centered_order.outputs[0], x_offset.inputs[0])
    links.new(x_spacing.outputs[0], x_offset.inputs[1])
    links.new(x_direction.outputs["Vector"], scale_x_direction.inputs[0])
    links.new(x_offset.outputs[0], scale_x_direction.inputs["Scale"])
    links.new(split_instances.outputs["Instances"], translate_x.inputs["Instances"])
    links.new(scale_x_direction.outputs["Vector"], translate_x.inputs["Translation"])
    links.new(centered_order.outputs[0], normal_offset.inputs[0])
    links.new(group_input.outputs["观察间距"], normal_offset.inputs[1])
    links.new(normalize_direction.outputs["Vector"], scale_normal_direction.inputs[0])
    links.new(normal_offset.outputs[0], scale_normal_direction.inputs["Scale"])
    links.new(translate_x.outputs["Instances"], translate_normal.inputs["Instances"])
    links.new(scale_normal_direction.outputs["Vector"], translate_normal.inputs["Translation"])
    links.new(translate_normal.outputs["Instances"], realize_instances.inputs["Geometry"])
    links.new(realize_instances.outputs["Geometry"], group_output.inputs["几何数据"])

    node_group["seanixz_preview_node_version"] = ND_PREVIEW_NODE_VERSION
    node_group.description = "先沿 X 轴水平排布孤岛，再沿切割面法向居中分离，便于观察切面。"
    return (
        node_group,
        source_socket.identifier,
        cutter_socket.identifier,
        gap_socket.identifier,
        count_socket.identifier,
    )


def cleanup_nondestructive_preview():
    collection = bpy.data.collections.get(ND_PREVIEW_COLLECTION)

    if not collection:
        return 0

    removed = 0

    for obj in list(collection.objects):
        data = obj.data if obj.type == 'MESH' else None
        bpy.data.objects.remove(obj, do_unlink=True)
        removed += 1

        if data and data.users == 0:
            bpy.data.meshes.remove(data)

    bpy.data.collections.remove(collection)
    return removed


def suspend_nondestructive_preview():
    """暂停实时几何求值但保留载体，避免属性切换和撤销时删除数据。"""
    collection = bpy.data.collections.get(ND_PREVIEW_COLLECTION)

    if not collection:
        return 0

    suspended = 0
    collection.hide_viewport = True

    for preview in collection.objects:
        modifier = preview.modifiers.get(ND_PREVIEW_MODIFIER)

        if modifier:
            modifier.show_viewport = False
            modifier.show_render = False

        preview.hide_viewport = True

        try:
            preview.hide_set(True)
        except Exception:
            pass

        suspended += 1

    return suspended


def nondestructive_preview_update_blocked():
    if _SEANIXZ_PRO_UNDO_IN_PROGRESS:
        return True

    try:
        return bool(bpy.context.window_manager.is_interface_locked)
    except Exception:
        return False


def update_auto_nondestructive_preview(scene, context):
    """关闭时暂停载体；显式清除或重新生成时才删除，避免污染撤销过程。"""
    if nondestructive_preview_update_blocked():
        return

    if not scene.seanixz_pro_auto_nondestructive_preview:
        suspend_nondestructive_preview()


def nondestructive_preview_source(context):
    active = context.active_object

    if active and bool(active.get(ND_PREVIEW_OBJECT_TAG, False)):
        return bpy.data.objects.get(active.get(ND_PREVIEW_SOURCE_TAG, ""))

    if active and active.type == 'MESH':
        return active

    collection = bpy.data.collections.get(ND_PREVIEW_COLLECTION)

    if collection:
        return bpy.data.objects.get(collection.get(ND_PREVIEW_SOURCE_TAG, ""))

    return None


def nondestructive_preview_cutter(source):
    for modifier in reversed(source.modifiers):
        if modifier.type == 'BOOLEAN':
            cutter = getattr(modifier, "object", None)
            if cutter and cutter.type == 'MESH':
                return cutter

    return None


def create_nondestructive_preview(context, source, island_count, dimensions, cutter=None):
    scene = context.scene
    cleanup_nondestructive_preview()

    collection = bpy.data.collections.new(ND_PREVIEW_COLLECTION)
    scene.collection.children.link(collection)
    collection[ND_PREVIEW_SOURCE_TAG] = source.name
    collection.hide_viewport = False

    (
        node_group,
        source_identifier,
        cutter_identifier,
        gap_identifier,
        count_identifier,
    ) = ensure_nondestructive_preview_node_group()
    gap = max(scene.seanixz_pro_preview_gap_mm * mm_to_bu(scene), 0.0)
    layout_cutter = cutter or nondestructive_preview_cutter(source) or source

    mesh = bpy.data.meshes.new(f"{source.name}_实时拆件预览载体")
    preview = bpy.data.objects.new(f"{source.name}_实时拆件预览", mesh)
    collection.objects.link(preview)
    preview.matrix_world = source.matrix_world.copy()
    preview[ND_PREVIEW_OBJECT_TAG] = True
    preview[ND_PREVIEW_SOURCE_TAG] = source.name

    modifier = preview.modifiers.new(ND_PREVIEW_MODIFIER, 'NODES')
    modifier.node_group = node_group
    modifier[source_identifier] = source
    modifier[cutter_identifier] = layout_cutter
    modifier[gap_identifier] = gap
    modifier[count_identifier] = max(float(island_count), 1.0)
    modifier.show_viewport = True
    modifier.show_render = False

    preview.hide_viewport = False

    try:
        preview.hide_set(False)
    except Exception:
        pass

    bpy.ops.object.select_all(action='DESELECT')
    preview.select_set(True)
    context.view_layer.objects.active = preview

    context.view_layer.update()
    return [preview]


def update_nondestructive_preview_gap(scene, context):
    if nondestructive_preview_update_blocked() or not scene.seanixz_pro_auto_nondestructive_preview:
        return

    collection = bpy.data.collections.get(ND_PREVIEW_COLLECTION)
    node_group = bpy.data.node_groups.get(ND_PREVIEW_NODE_GROUP)

    if not collection or not node_group:
        return

    try:
        gap_socket = next(
            item for item in node_group.interface.items_tree
            if getattr(item, "in_out", None) == 'INPUT' and item.name == "观察间距"
        )
    except StopIteration:
        return

    gap = max(scene.seanixz_pro_preview_gap_mm * mm_to_bu(scene), 0.0)

    for preview in collection.objects:
        modifier = preview.modifiers.get(ND_PREVIEW_MODIFIER)

        if modifier and modifier.type == 'NODES':
            modifier[gap_socket.identifier] = gap
            preview.update_tag()

    node_group.update_tag()


@persistent
def seanixz_pro_history_pre(_dummy):
    """Ctrl+Z/Ctrl+Shift+Z 前暂停高负载实时预览。"""
    global _SEANIXZ_PRO_UNDO_IN_PROGRESS
    _SEANIXZ_PRO_UNDO_IN_PROGRESS = True

    try:
        suspend_nondestructive_preview()
    except Exception:
        pass


@persistent
def seanixz_pro_history_post(_dummy):
    """撤销完成后保持预览暂停；用户再次点预览按钮时恢复。"""
    global _SEANIXZ_PRO_UNDO_IN_PROGRESS
    _SEANIXZ_PRO_UNDO_IN_PROGRESS = False

    try:
        suspend_nondestructive_preview()
        unlock_backup_eye_control()
    except Exception:
        pass


def auto_create_nondestructive_preview(context, source, max_parts, cutter=None):
    try:
        island_count, dimensions = evaluated_mesh_island_summary(context, source)
    except Exception as exc:
        return 0, False, f"拆件预览读取失败：{exc}"

    if island_count <= 0:
        return 0, False, "切割结果没有可预览的网格"

    if island_count > max_parts:
        return island_count, False, f"检测到 {island_count} 个孤岛，超过预览上限 {max_parts}"

    create_nondestructive_preview(
        context,
        source,
        island_count,
        dimensions,
        cutter=cutter,
    )
    return island_count, True, ""


class SEANIXZ_PRO_OT_nondestructive_preview_create(bpy.types.Operator):
    bl_idname = "seanixz_pro.nondestructive_preview_create"
    bl_label = "生成非破坏拆件预览"
    bl_description = "不应用布尔修改器，实时按网格孤岛生成拆件预览对象"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not context.scene.seanixz_pro_auto_nondestructive_preview:
            self.report({'ERROR'}, "请先勾选“开启非破坏实时拆件预览（较耗资源）”")
            return {'CANCELLED'}

        ensure_object_mode()
        source = nondestructive_preview_source(context)

        if not source or source.type != 'MESH':
            self.report({'ERROR'}, "请将保留布尔修改器的源模型设为活动对象")
            return {'CANCELLED'}

        if bool(source.get(ND_PREVIEW_OBJECT_TAG, False)):
            self.report({'ERROR'}, "预览载体不能作为源模型")
            return {'CANCELLED'}

        try:
            island_count, dimensions = evaluated_mesh_island_summary(context, source)
        except Exception as exc:
            self.report({'ERROR'}, f"读取源模型求值结果失败：{exc}")
            return {'CANCELLED'}

        if island_count <= 0:
            self.report({'ERROR'}, "源模型求值结果没有可预览的网格")
            return {'CANCELLED'}

        max_parts = context.scene.seanixz_pro_preview_max_parts

        if island_count > max_parts:
            self.report(
                {'ERROR'},
                f"检测到 {island_count} 个孤岛，超过安全上限 {max_parts}；请先清理游离几何或提高上限",
            )
            return {'CANCELLED'}

        create_nondestructive_preview(
            context,
            source,
            island_count,
            dimensions,
        )

        if island_count == 1:
            self.report({'WARNING'}, "仅检测到 1 个孤岛；当前布尔结果尚未形成可分离的多个零件")
        else:
            self.report({'INFO'}, f"已生成 {island_count} 个动态拆件预览；先沿 X 轴横排，再沿切面法向分离")

        return {'FINISHED'}


class SEANIXZ_PRO_OT_nondestructive_preview_clear(bpy.types.Operator):
    bl_idname = "seanixz_pro.nondestructive_preview_clear"
    bl_label = "清除非破坏预览"
    bl_description = "删除插件生成的预览载体，不修改源模型和布尔修改器"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        removed = cleanup_nondestructive_preview()

        if removed:
            self.report({'INFO'}, f"已清除 {removed} 个非破坏预览对象")
        else:
            self.report({'INFO'}, "当前没有非破坏预览对象")

        return {'FINISHED'}


class SEANIXZ_PRO_OT_preview_transforms_to_deltas(bpy.types.Operator):
    bl_idname = "seanixz_pro.preview_transforms_to_deltas"
    bl_label = "预览变换转增量"
    bl_description = "保持预览件当前位置不变，把位置、旋转和缩放转入增量变换"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ensure_object_mode()
        selected = [
            obj for obj in context.selected_objects
            if bool(obj.get(ND_PREVIEW_OBJECT_TAG, False))
        ]

        if not selected:
            self.report({'ERROR'}, "请先选择至少一个非破坏预览对象")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')

        for obj in selected:
            obj.select_set(True)

        context.view_layer.objects.active = selected[0]
        bpy.ops.object.transforms_to_deltas(mode='ALL', reset_values=True)
        self.report({'INFO'}, f"已将 {len(selected)} 个预览件的全部变换转为增量")
        return {'FINISHED'}


class SEANIXZ_PRO_OT_boolean_preview(bpy.types.Operator):
    bl_idname = "seanixz_pro.boolean_preview"
    bl_label = "预览切割"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        target = active_mesh_object(context)

        if not target:
            self.report({'ERROR'}, "请选择切刀和目标；最后选中的活动对象必须是被切目标")
            return {'CANCELLED'}

        cutters = get_selected_real_cutters(context, target)

        if not cutters:
            self.report({'ERROR'}, "没有找到切刀。请先选切刀，再选目标模型，最后选中目标模型")
            return {'CANCELLED'}

        cleanup_boolean_preview_objects(context, target)

        live_cutters = []

        for cutter in cutters:
            setup_cutter_display(cutter)
            if not ensure_cutter_preview_solidify(cutter, scene):
                continue

            live_cutters.append(cutter)

            mod = target.modifiers.new(BOOL_MOD_PREFIX + cutter.name, 'BOOLEAN')
            configure_boolean_modifier(
                mod,
                scene,
                operation=scene.seanixz_pro_boolean_operation,
                cutter=cutter
            )

        if not live_cutters:
            self.report({'ERROR'}, "实时实体化切刀预览失败，请确认切刀是网格对象")
            return {'CANCELLED'}

        target.hide_viewport = False
        target.hide_render = False

        try:
            target.hide_set(False)
        except Exception:
            pass

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target
        context.view_layer.update()

        if scene.seanixz_pro_auto_nondestructive_preview:
            island_count, preview_created, preview_note = auto_create_nondestructive_preview(
                context,
                target,
                scene.seanixz_pro_preview_max_parts,
                cutter=live_cutters[0],
            )
        else:
            cleanup_nondestructive_preview()
            island_count, preview_created, preview_note = 0, False, ""

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target

        msg = (
            f"实时预览已启用：布尔直接引用 {len(live_cutters)} 个真实切刀，"
            f"厚度 {scene.seanixz_pro_cutter_tolerance_mm:.3f} mm。"
        )

        if scene.seanixz_pro_auto_nondestructive_preview:
            msg += (
                f" 检测到 {island_count} 个拆件；移动、旋转或缩放切刀会立即更新，"
                "拆件会先沿 X 轴水平排开，再沿切割面法向保持观察间距。"
            )

            if not preview_created and preview_note:
                msg += f" {preview_note}。"
        else:
            msg += " 非破坏拆件预览已关闭。"

        self.report({'INFO'}, msg)
        return {'FINISHED'}

class SEANIXZ_PRO_OT_boolean_apply_separate(bpy.types.Operator):
    bl_idname = "seanixz_pro.boolean_apply_separate"
    bl_label = "确认切割并分离"
    bl_options = {'REGISTER', 'UNDO'}

    def separate_loose_parts(self, context, obj):
        ensure_object_mode()

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        try:
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.separate(type='LOOSE')
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            ensure_object_mode()

        return [o for o in context.selected_objects if o and o.type == 'MESH']

    def execute(self, context):
        scene = context.scene
        target = active_mesh_object(context)

        if not target:
            self.report({'ERROR'}, "请将被切模型设为活动对象")
            return {'CANCELLED'}

        mods = [
            m for m in target.modifiers
            if m.type == 'BOOLEAN' and m.name.startswith(BOOL_MOD_PREFIX)
        ]

        if not mods:
            cutters = get_selected_real_cutters(context, target)

            if not cutters:
                self.report({'ERROR'}, "没有找到切刀。请先选切刀，再选目标模型，最后选中目标模型")
                return {'CANCELLED'}

            temp_cutters = []

            for cutter in cutters:
                setup_cutter_display(cutter)
                ensure_cutter_preview_solidify(cutter, scene)

                temp_cutter = create_temp_boolean_cutter(context, cutter, scene)

                if temp_cutter:
                    temp_cutters.append(temp_cutter)

            if not temp_cutters:
                self.report({'ERROR'}, "临时实体化切刀失败，请确认切刀是网格对象")
                return {'CANCELLED'}

            for temp_cutter in temp_cutters:
                mod = target.modifiers.new(BOOL_MOD_PREFIX + temp_cutter.name, 'BOOLEAN')
                configure_boolean_modifier(
                    mod,
                    scene,
                    operation=scene.seanixz_pro_boolean_operation,
                    cutter=temp_cutter
                )
                mods.append(mod)

        if scene.seanixz_pro_make_backup:
            duplicate_backup(target, "_Boolean_Backup")

        applied_count = 0

        for mod in list(mods):
            if mod and mod.type == 'BOOLEAN':
                if apply_modifier(context, target, mod.name):
                    applied_count += 1

        if applied_count == 0:
            self.report({'ERROR'}, "布尔修改器应用失败，请尝试增大刀具实体化厚度，例如 0.3mm 或 0.5mm")
            return {'CANCELLED'}

        final_results = self.separate_loose_parts(context, target)

        if not final_results:
            final_results = [target]

        cleaned_results = []

        for obj in final_results:
            if obj and obj.type == 'MESH' and len(obj.data.polygons) > 0:
                cleaned_results.append(obj)

        final_results = cleaned_results

        if not final_results:
            cleanup_temp_boolean_cutters()
            self.report({'ERROR'}, "切割后没有生成有效模型，请检查切刀是否穿过目标模型")
            return {'CANCELLED'}

        for obj in final_results:
            move_to_collection(obj, "SeanIXz_Pro_Results")
            obj.hide_viewport = False
            obj.hide_render = False

            try:
                obj.hide_set(False)
            except Exception:
                pass

            recalc_mesh_normals(obj)

        cleanup_temp_boolean_cutters()

        bpy.ops.object.select_all(action='DESELECT')

        for obj in final_results:
            obj.select_set(True)

        context.view_layer.objects.active = final_results[0]

        msg = (
            f"分件完成：生成 {len(final_results)} 个结果对象。\n"
            f"切刀厚度：{scene.seanixz_pro_cutter_tolerance_mm:.3f} mm。"
        )

        if scene.seanixz_pro_make_backup:
            msg += "\n已保留 1 份切刀计算前的源模型备份；切割结果不再重复备份。"

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg, title="布尔切割完成", icon='MOD_BOOLEAN')
        return {'FINISHED'}


class SEANIXZ_PRO_OT_boolean_raw_preview(bpy.types.Operator):
    bl_idname = "seanixz_pro.boolean_raw_preview"
    bl_label = "普通布尔预览"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        target = active_mesh_object(context)

        if not target:
            self.report({'ERROR'}, "请选择切刀和目标；最后选中的活动对象必须是被切目标")
            return {'CANCELLED'}

        cutters = get_selected_real_cutters(context, target)

        if not cutters:
            self.report({'ERROR'}, "没有找到普通布尔切刀。请先选切刀，再选目标模型，最后选中目标模型")
            return {'CANCELLED'}

        cleanup_boolean_preview_objects(context, target)

        created = 0

        for cutter in cutters:
            # 普通布尔使用切刀原始网格，不增加 Solidify 厚度。
            set_cutter_display_mode(cutter, 'PLANE')

            mod = target.modifiers.new(BOOL_RAW_MOD_PREFIX + cutter.name, 'BOOLEAN')
            configure_boolean_modifier(
                mod,
                scene,
                operation=scene.seanixz_pro_boolean_operation,
                cutter=cutter
            )
            created += 1

        if created == 0:
            self.report({'ERROR'}, "普通布尔预览失败，请确认切刀是可参与布尔的网格对象")
            return {'CANCELLED'}

        target.hide_viewport = False
        target.hide_render = False

        try:
            target.hide_set(False)
        except Exception:
            pass

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target
        context.view_layer.update()

        if scene.seanixz_pro_auto_nondestructive_preview:
            island_count, preview_created, preview_note = auto_create_nondestructive_preview(
                context,
                target,
                scene.seanixz_pro_preview_max_parts,
                cutter=cutters[0],
            )
        else:
            cleanup_nondestructive_preview()
            island_count, preview_created, preview_note = 0, False, ""

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target

        msg = f"普通布尔实时预览完成：已直接引用 {created} 个原始切刀。"

        if scene.seanixz_pro_auto_nondestructive_preview:
            msg += (
                f"\n检测到 {island_count} 个拆件；移动、旋转或缩放切刀会立即更新，"
                "拆件会先沿 X 轴水平排开，再沿切割面法向保持观察间距。"
            )

            if not preview_created and preview_note:
                msg += f"\n{preview_note}。"
        else:
            msg += "\n非破坏拆件预览已关闭。"

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg, title="普通布尔预览", icon='MOD_BOOLEAN')
        return {'FINISHED'}

class SEANIXZ_PRO_OT_boolean_raw_apply_separate(bpy.types.Operator):
    bl_idname = "seanixz_pro.boolean_raw_apply_separate"
    bl_label = "执行普通布尔"
    bl_options = {'REGISTER', 'UNDO'}

    def separate_loose_parts(self, context, obj):
        ensure_object_mode()

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        try:
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.separate(type='LOOSE')
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            ensure_object_mode()

        return [o for o in context.selected_objects if o and o.type == 'MESH']

    def execute(self, context):
        scene = context.scene
        target = active_mesh_object(context)

        if not target:
            self.report({'ERROR'}, "请将被切模型设为活动对象")
            return {'CANCELLED'}

        mods = [
            m for m in target.modifiers
            if m.type == 'BOOLEAN' and m.name.startswith(BOOL_RAW_MOD_PREFIX)
        ]

        if not mods:
            cutters = get_selected_real_cutters(context, target)

            if not cutters:
                self.report({'ERROR'}, "没有找到普通布尔切刀。请先选切刀，再选目标模型，最后选中目标模型")
                return {'CANCELLED'}

            for cutter in cutters:
                set_cutter_display_mode(cutter, 'PLANE')
                mod = target.modifiers.new(BOOL_RAW_MOD_PREFIX + cutter.name, 'BOOLEAN')
                configure_boolean_modifier(
                    mod,
                    scene,
                    operation=scene.seanixz_pro_boolean_operation,
                    cutter=cutter
                )
                mods.append(mod)

        if scene.seanixz_pro_make_backup:
            duplicate_backup(target, "_RawBoolean_Backup")

        applied_count = 0

        for mod in list(mods):
            if mod and mod.type == 'BOOLEAN':
                if apply_modifier(context, target, mod.name):
                    applied_count += 1

        if applied_count == 0:
            self.report({'ERROR'}, "普通布尔修改器应用失败。请确认切刀本身是有效实体/面片，且与目标模型有真实相交。")
            return {'CANCELLED'}

        final_results = self.separate_loose_parts(context, target)

        if not final_results:
            final_results = [target]

        final_results = [obj for obj in final_results if obj and obj.type == 'MESH' and len(obj.data.polygons) > 0]

        if not final_results:
            self.report({'ERROR'}, "普通布尔后没有生成有效模型，请检查切刀是否穿过目标模型")
            return {'CANCELLED'}

        for obj in final_results:
            move_to_collection(obj, "SeanIXz_Pro_Results")
            obj.hide_viewport = False
            obj.hide_render = False

            try:
                obj.hide_set(False)
            except Exception:
                pass

            recalc_mesh_normals(obj)

        bpy.ops.object.select_all(action='DESELECT')

        for obj in final_results:
            obj.select_set(True)

        context.view_layer.objects.active = final_results[0]

        msg = (
            f"普通布尔完成：生成 {len(final_results)} 个结果对象。\n"
            "说明：本次没有给切刀增加实体化厚度。"
        )
        if scene.seanixz_pro_make_backup:
            msg += "\n已保留 1 份切刀计算前的源模型备份；切割结果不再重复备份。"
        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg, title="普通布尔完成", icon='MOD_BOOLEAN')
        return {'FINISHED'}

class SEANIXZ_PRO_OT_boolean_raw_one_click(bpy.types.Operator):
    bl_idname = "seanixz_pro.boolean_raw_one_click"
    bl_label = "一键普通布尔"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        result = bpy.ops.seanixz_pro.boolean_raw_preview()
        if result == {'CANCELLED'}:
            return {'CANCELLED'}

        result = bpy.ops.seanixz_pro.boolean_raw_apply_separate()
        if result == {'CANCELLED'}:
            return {'CANCELLED'}

        return {'FINISHED'}

class SEANIXZ_PRO_OT_duplicate_mirror_cutter(bpy.types.Operator):
    bl_idname = "seanixz_pro.duplicate_mirror_cutter"
    bl_label = "复制并镜像切刀"
    bl_options = {'REGISTER', 'UNDO'}

    axis: bpy.props.EnumProperty(
        name="镜像轴",
        items=[
            ('X', "X轴", ""),
            ('Y', "Y轴", ""),
            ('Z', "Z轴", ""),
        ],
        default='X'
    )

    def execute(self, context):
        ensure_object_mode()

        selected = mesh_objects_from_selection(context)
        active = active_mesh_object(context)

        if not selected:
            self.report({'ERROR'}, "请选择至少一个切刀对象")
            return {'CANCELLED'}

        cutters = selected

        if active and len(selected) > 1:
            cutters = [o for o in selected if o != active]

        cutters = [o for o in cutters if not bool(o.get("seanixz_pro_temp_boolean_cutter", False))]

        if not cutters:
            self.report({'ERROR'}, "没有可复制的切刀。请选中切刀，或先选切刀再选目标")
            return {'CANCELLED'}

        new_objects = []

        for cutter in cutters:
            new_obj = cutter.copy()
            new_obj.data = cutter.data.copy()
            new_obj.name = f"{cutter.name}_Mirror_{self.axis}"

            if "seanixz_pro_temp_boolean_cutter" in new_obj:
                try:
                    del new_obj["seanixz_pro_temp_boolean_cutter"]
                except Exception:
                    new_obj["seanixz_pro_temp_boolean_cutter"] = False

            context.scene.collection.objects.link(new_obj)
            new_obj.matrix_world = cutter.matrix_world.copy()

            if self.axis == 'X':
                new_obj.scale.x *= -1
            elif self.axis == 'Y':
                new_obj.scale.y *= -1
            elif self.axis == 'Z':
                new_obj.scale.z *= -1

            setup_cutter_display(new_obj)
            ensure_cutter_preview_solidify(new_obj, context.scene)

            new_objects.append(new_obj)

        bpy.ops.object.select_all(action='DESELECT')

        for obj in new_objects:
            obj.select_set(True)

        context.view_layer.objects.active = new_objects[0]
        context.view_layer.update()

        msg = f"已复制并沿 {self.axis} 轴镜像 {len(new_objects)} 个切刀。"
        self.report({'INFO'}, msg)
        show_popup(msg, title="切刀镜像完成", icon='MOD_MIRROR')
        return {'FINISHED'}

class SEANIXZ_PRO_OT_boolean_one_click(bpy.types.Operator):
    bl_idname = "seanixz_pro.boolean_one_click"
    bl_label = "一键布尔分件"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        result = bpy.ops.seanixz_pro.boolean_preview()
        if result == {'CANCELLED'}:
            return {'CANCELLED'}

        result = bpy.ops.seanixz_pro.boolean_apply_separate()
        if result == {'CANCELLED'}:
            return {'CANCELLED'}

        return {'FINISHED'}

# -----------------------------------------------------------------------------
# 07 收尾处理
# -----------------------------------------------------------------------------

def organize_joint_cutters_collection():
    """把当前文件中旧版本生成的活动关节切刀迁移到独立集合。"""
    collection = get_or_create_collection(JOINT_CUTTER_COLLECTION_NAME)
    cutters = []
    for obj in list(bpy.data.objects):
        if not obj or obj.type != 'MESH' or not bool(obj.get("seanixz_pro_joint_cutter", False)):
            continue
        move_to_collection(obj, JOINT_CUTTER_COLLECTION_NAME)
        obj.hide_render = True
        cutters.append(obj)
    return collection, cutters


class SEANIXZ_PRO_OT_toggle_joint_cutters_visibility(bpy.types.Operator):
    bl_idname = "seanixz_pro.toggle_joint_cutters_visibility"
    bl_label = "显示/隐藏活动关节切刀"
    bl_description = "统一显示或隐藏 SeanIXz_Pro_Joint_Cutters 独立集合中的所有活动关节切刀"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        collection, cutters = organize_joint_cutters_collection()
        if not cutters:
            self.report({'WARNING'}, "当前没有已生成的活动关节切刀")
            return {'CANCELLED'}

        should_hide = not bool(collection.hide_viewport)
        collection.hide_viewport = should_hide
        if not should_hide:
            for obj in cutters:
                obj.hide_viewport = False
                try:
                    obj.hide_set(False)
                except Exception:
                    pass

        state = "隐藏" if should_hide else "显示"
        msg = f"已{state} {len(cutters)} 个活动关节切刀。"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class SEANIXZ_PRO_OT_toggle_backup_cutters_visibility(bpy.types.Operator):
    bl_idname = "seanixz_pro.toggle_backup_cutters_visibility"
    bl_label = "隐藏/显示备份切刀"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        coll = bpy.data.collections.get(CUTTER_COLLECTION_NAME)

        if not coll:
            self.report({'ERROR'}, f"没有找到 {CUTTER_COLLECTION_NAME} 集合")
            return {'CANCELLED'}

        cutters = []

        for obj in coll.objects:
            if not obj or obj.type != 'MESH':
                continue

            if bool(obj.get("seanixz_pro_temp_boolean_cutter", False)):
                continue

            cutters.append(obj)

        if not cutters:
            self.report({'ERROR'}, f"{CUTTER_COLLECTION_NAME} 集合中没有可切换显示的切刀")
            return {'CANCELLED'}

        any_visible = False

        for obj in cutters:
            try:
                if not obj.hide_get() and not obj.hide_viewport:
                    any_visible = True
                    break
            except Exception:
                if not obj.hide_viewport:
                    any_visible = True
                    break

        should_hide = any_visible

        for obj in cutters:
            obj.hide_render = True

            try:
                obj.hide_set(should_hide)
            except Exception:
                pass

            # 隐藏时暂停切刀修改器求值；小眼睛再次打开后轮询器会自动解除。
            obj.hide_viewport = should_hide

        try:
            coll.hide_viewport = False
        except Exception:
            pass

        state = "隐藏" if should_hide else "显示"
        msg = f"已{state} {len(cutters)} 个备份/保留切刀。"

        self.report({'INFO'}, msg)
        show_popup(msg, title="切刀显示切换", icon='HIDE_ON' if should_hide else 'HIDE_OFF')
        return {'FINISHED'}


class SEANIXZ_PRO_OT_toggle_backups_visibility(bpy.types.Operator):
    bl_idname = "seanixz_pro.toggle_backups_visibility"
    bl_label = "显示/隐藏备份模型"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        coll = bpy.data.collections.get(BACKUP_COLLECTION_NAME)

        if not coll:
            self.report({'ERROR'}, f"没有找到 {BACKUP_COLLECTION_NAME} 集合")
            return {'CANCELLED'}

        backup_objects = [obj for obj in coll.objects if obj]

        if not backup_objects:
            self.report({'ERROR'}, f"{BACKUP_COLLECTION_NAME} 集合中没有备份模型")
            return {'CANCELLED'}

        any_visible = False
        for obj in backup_objects:
            try:
                if not obj.hide_get() and not obj.hide_viewport:
                    any_visible = True
                    break
            except Exception:
                if not obj.hide_viewport:
                    any_visible = True
                    break

        should_hide = any_visible

        # 集合保持可访问；对象隐藏时同步暂停后台求值。
        try:
            coll.hide_viewport = False
        except Exception:
            pass

        for obj in backup_objects:
            obj.hide_render = True

            try:
                obj.hide_set(should_hide)
            except Exception:
                pass

            obj.hide_viewport = should_hide

            try:
                obj.hide_select = False
            except Exception:
                pass

        state = "隐藏" if should_hide else "显示"
        msg = (
            f"已{state} {len(backup_objects)} 个备份模型。\n"
            "说明：备份只使用对象小眼睛控制，可在大纲视图逐个恢复显示。"
        )

        self.report({'INFO'}, msg.replace('\n', ' '))
        show_popup(msg, title="备份模型显示切换", icon='HIDE_ON' if should_hide else 'HIDE_OFF')
        return {'FINISHED'}

class SEANIXZ_PRO_OT_reset_all_objects_location(bpy.types.Operator):
    bl_idname = "seanixz_pro.reset_all_objects_location"
    bl_label = "一键模型复位"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ensure_object_mode()

        visible_objects = [obj for obj in context.view_layer.objects if obj]

        if not visible_objects:
            self.report({'ERROR'}, "当前视图层没有可操作的物体")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='SELECT')

        selected = list(context.selected_objects)

        if not selected:
            self.report({'ERROR'}, "没有可选中的物体，请检查是否都被隐藏或禁用选择")
            return {'CANCELLED'}

        context.view_layer.objects.active = selected[0]

        try:
            bpy.ops.object.location_clear(clear_delta=False)
        except Exception:
            self.report({'ERROR'}, "模型复位失败，请确认当前处于物体模式")
            return {'CANCELLED'}

        msg = f"模型复位完成：{len(selected)} 个物体已回到原点。"
        self.report({'INFO'}, msg)
        show_popup(msg, title="模型复位完成", icon='OBJECT_ORIGIN')
        return {'FINISHED'}

class SEANIXZ_PRO_OT_manifoldize(bpy.types.Operator):
    bl_idname = "seanixz_pro.manifoldize"
    bl_label = "一键流形化处理"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = mesh_objects_from_selection(context)

        if not objs:
            self.report({'ERROR'}, "请选择至少一个网格模型")
            return {'CANCELLED'}

        before_v = sum(len(o.data.vertices) for o in objs)
        before_f = sum(len(o.data.polygons) for o in objs)

        for obj in objs:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj

            try:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')

                try:
                    bpy.ops.mesh.remove_doubles(
                        threshold=context.scene.seanixz_pro_merge_distance_mm * mm_to_bu(context.scene)
                    )
                except Exception:
                    bpy.ops.mesh.merge_by_distance(
                        distance=context.scene.seanixz_pro_merge_distance_mm * mm_to_bu(context.scene)
                    )

                bpy.ops.mesh.normals_make_consistent(inside=False)
                bpy.ops.mesh.delete_loose()
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                ensure_object_mode()

            if context.scene.seanixz_pro_manifold_use_voxel:
                mod = obj.modifiers.new("SeanIXz_Pro_流形化体素重构", 'REMESH')
                mod.mode = 'VOXEL'
                mod.voxel_size = max(context.scene.seanixz_pro_manifold_voxel_size_mm * mm_to_bu(context.scene), 0.000001)

                try:
                    mod.use_smooth_shade = context.scene.seanixz_pro_remesh_smooth
                except Exception:
                    pass

                apply_modifier(context, obj, mod.name)

            if context.scene.seanixz_pro_remesh_smooth:
                for p in obj.data.polygons:
                    p.use_smooth = True

        after_v = sum(len(o.data.vertices) for o in objs)
        after_f = sum(len(o.data.polygons) for o in objs)

        voxel_note = "已启用体素重构" if context.scene.seanixz_pro_manifold_use_voxel else "未启用体素重构，仅执行基础清理"
        msg = f"3D打印流形化处理完成：顶点 {before_v:,}->{after_v:,}，面 {before_f:,}->{after_f:,}。{voxel_note}。"
        self.report({'INFO'}, msg)
        show_popup(msg, title="流形化报告", icon='MESH_ICOSPHERE')
        return {'FINISHED'}

# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------

class SEANIXZ_PRO_PT_main_panel(bpy.types.Panel):
    bl_label = "SeanIXz Pro 分件助手"
    bl_idname = "SEANIXZ_PRO_PT_3d_print_part_assistant"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'SeanIXz Pro'

    def draw_foldout(self, layout, scene, prop_name, title, icon='TRIA_RIGHT'):
        box = layout.box()
        opened = bool(getattr(scene, prop_name, False))
        row = box.row(align=True)
        row.prop(
            scene,
            prop_name,
            text=title,
            icon='TRIA_DOWN' if opened else 'TRIA_RIGHT',
            emboss=False,
        )
        return box, opened

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        ensure_decimate_percent_compatible(scene)

        header = layout.box()
        col = header.column(align=True)
        col.label(text="SeanIXz Pro 分件助手", icon='MOD_BOOLEAN')
        col.label(text=f"Commercial Workflow  {ADDON_VERSION_TEXT}")
        col.label(text="专业版：精简界面 / 完整功能 / 熟练流程")

        box, opened = self.draw_foldout(layout, scene, "seanixz_pro_ui_show_global", "Global / 备份", 'PREFERENCES')
        if opened:
            box.prop(scene, "seanixz_pro_make_backup", text="仅布尔切刀计算前备份")
            box.label(text="精简、重建、清理与切割结果不再重复备份")

        box, opened = self.draw_foldout(layout, scene, "seanixz_pro_ui_show_step01", "01 单位 / 尺寸", 'EMPTY_ARROWS')
        if opened:
            box.operator("seanixz_pro.set_length_unit_mm", text="毫米 + 缩放1 + 裁剪1mm", icon='SCENE_DATA')
            row = box.row(align=True)
            row.prop(scene, "seanixz_pro_target_height_mm", text="高度mm")
            row.operator("seanixz_pro.set_height", text="应用", icon='CHECKMARK')
            row = box.row(align=True)
            op = row.operator("seanixz_pro.set_height", text="200")
            op.target_height_mm = 200.0
            op = row.operator("seanixz_pro.set_height", text="100")
            op.target_height_mm = 100.0
            op = row.operator("seanixz_pro.set_height", text="50")
            op.target_height_mm = 50.0

        box, opened = self.draw_foldout(layout, scene, "seanixz_pro_ui_show_step02", "02 精简", 'MOD_DECIM')
        if opened:
            box.prop(scene, "seanixz_pro_decimate_percent", text="保留%", slider=True)
            row = box.row(align=True)
            op = row.operator("seanixz_pro.get_face_count", text="面数", icon='MESH_DATA')
            op.section = 'DECIMATE'
            row.operator("seanixz_pro.decimate_preview", text="预览", icon='HIDE_OFF')
            box.operator("seanixz_pro.decimate_one_click", text="执行精简", icon='PLAY')
            if scene.seanixz_pro_decimate_before_faces or scene.seanixz_pro_decimate_after_faces:
                box.label(text=f"{scene.seanixz_pro_decimate_before_faces:,} → {scene.seanixz_pro_decimate_after_faces:,}")

        box, opened = self.draw_foldout(layout, scene, "seanixz_pro_ui_show_step03", "03 重建", 'MOD_REMESH')
        if opened:
            box.prop(scene, "seanixz_pro_remesh_mode", text="模式")
            if scene.seanixz_pro_remesh_mode == 'VOXEL':
                box.prop(scene, "seanixz_pro_voxel_size_mm", text="体素mm")
            else:
                box.prop(scene, "seanixz_pro_remesh_octree_depth", text="深度")
            box.prop(scene, "seanixz_pro_remesh_smooth", text="平滑着色")
            row = box.row(align=True)
            op = row.operator("seanixz_pro.get_face_count", text="面数", icon='MESH_DATA')
            op.section = 'REMESH'
            row.operator("seanixz_pro.remesh_preview", text="预览", icon='HIDE_OFF')
            box.operator("seanixz_pro.remesh_one_click", text="执行重建", icon='PLAY')

        box, opened = self.draw_foldout(layout, scene, "seanixz_pro_ui_show_step04", "04 切刀", 'CURVE_PATH')
        if opened:
            box.operator("seanixz_pro.setup_snap_and_create_cutter_point", text="吸附 + 法向 + 起点", icon='SNAP_FACE')
            row = box.row(align=True)
            row.operator("seanixz_pro.close_selected_points", text="闭合", icon='EDGESEL')
            row.operator("seanixz_pro.fit_selected_loop", text="拟合", icon='MOD_SUBSURF')
            box.prop(scene, "seanixz_pro_fit_smooth_repeat", text="插点")
            box.operator("seanixz_pro.cutter_wire_display", text="线框/平面", icon='SHADING_WIRE')

        box, opened = self.draw_foldout(layout, scene, "seanixz_pro_ui_show_step05", "05 卡榫 / 锁止", 'MESH_CUBE')
        if opened:
            box.label(text="05-1 卡榫")
            row = box.row(align=True)
            row.prop(scene, "seanixz_pro_outer_scale", text="外扩")
            row.prop(scene, "seanixz_pro_tenon_depth_mm", text="深度")
            row = box.row(align=True)
            row.prop(scene, "seanixz_pro_inner_scale", text="卡榫1")
            row.prop(scene, "seanixz_pro_tenon2_scale", text="卡榫2")
            row.prop(scene, "seanixz_pro_tenon_reverse_direction", text="反向")
            row = box.row(align=True)
            row.operator("seanixz_pro.make_simple_tenon", text="卡榫1", icon='MESH_CUBE')
            row.operator("seanixz_pro.make_simple_tenon2", text="卡榫2", icon='MESH_CUBE')
            row = box.row(align=True)
            row.prop(scene, "seanixz_pro_use_bevel", text="倒角")
            row.prop(scene, "seanixz_pro_bevel_mm", text="mm")
            row.prop(scene, "seanixz_pro_bevel_segments", text="段")
            box.operator("seanixz_pro.bevel_selected_edges", text="当前边倒角", icon='MOD_BEVEL')

            box.separator()
            box.label(text="05-2 防呆锁止")
            row = box.row(align=True)
            row.prop(scene, "seanixz_pro_lock_height_mm", text="凸起")
            row.prop(scene, "seanixz_pro_lock_size_factor", text="比例")
            row = box.row(align=True)
            row.prop(scene, "seanixz_pro_lock_reverse_direction", text="锁止反向")
            row.prop(scene, "seanixz_pro_lock_taper_scale", text="斜角")
            box.prop(scene, "seanixz_pro_lock_size_mm", text="手动锁尺寸mm")
            row = box.row(align=True)
            row.operator("seanixz_pro.add_tenon_lock_wedge", text="楔形")
            row.operator("seanixz_pro.add_tenon_lock_triangle", text="三角")
            row.operator("seanixz_pro.add_tenon_lock_hex", text="六边")
            row = box.row(align=True)
            row.operator("seanixz_pro.add_tenon_lock_square", text="方形")
            row.operator("seanixz_pro.add_tenon_lock_diamond", text="菱形")

        box, opened = self.draw_foldout(layout, scene, "seanixz_pro_ui_show_step06", "06 活动关节", 'CONSTRAINT_BONE')
        if opened:
            figure_box = box.box()
            figure_box.label(text="可动手办部位预设（参考拼装结构）", icon='ARMATURE_DATA')
            row = figure_box.row(align=True)
            row.prop(scene, "seanixz_pro_figure_joint_preset", text="部位")
            row.operator("seanixz_pro.apply_figure_joint_preset", text="重新应用", icon='FILE_REFRESH')
            figure_box.label(text="切换部位会自动应用参数；肩髋腕生成独立球头连接件")
            figure_box.operator(
                "seanixz_pro.make_print_ready_figure_joint",
                text="一键生成一体式切刀 + 独立连接件",
                icon='MOD_BOOLEAN',
            )
            figure_box.label(text="蓝色切刀同时完成平面分离、关节腔、活动避让和装配入口")
            figure_box.label(text="打印前仍需用相同材料制作关节小样")

            joint_collection = bpy.data.collections.get(JOINT_CUTTER_COLLECTION_NAME)
            joint_cutters_hidden = bool(joint_collection and joint_collection.hide_viewport)
            cutter_count = len(joint_collection.objects) if joint_collection else 0
            row = box.row(align=True)
            row.operator(
                "seanixz_pro.toggle_joint_cutters_visibility",
                text="显示关节切刀" if joint_cutters_hidden else "隐藏关节切刀",
                icon='HIDE_OFF' if joint_cutters_hidden else 'HIDE_ON',
            )
            row.label(text=f"切刀组：{cutter_count}")

            params_box, params_opened = self.draw_foldout(
                box, scene, "seanixz_pro_ui_show_joint_params", "高级关节参数", 'PREFERENCES'
            )
            if params_opened:
                params_box.label(text="绿色件独立打印；蓝色切刀用于差集")
                row = params_box.row(align=True)
                row.prop(scene, "seanixz_pro_joint_fit_preset", text="打印间隙")
                row.operator("seanixz_pro.apply_joint_fit_preset", text="应用预设", icon='CHECKMARK')
                params_box.prop(scene, "seanixz_pro_joint_type", text="连接类型")
                params_box.prop(scene, "seanixz_pro_joint_direction", text="方向", expand=True)
                row = params_box.row(align=True)
                row.prop(scene, "seanixz_pro_joint_auto_size", text="按圈线自动尺寸")
                if scene.seanixz_pro_joint_auto_size:
                    row.prop(scene, "seanixz_pro_joint_size_factor", text="尺寸比例")
                else:
                    row.prop(scene, "seanixz_pro_joint_size_mm", text="尺寸mm")
                row = params_box.row(align=True)
                row.prop(scene, "seanixz_pro_joint_clearance_mm", text="组装间隙mm")
                row.prop(scene, "seanixz_pro_joint_connection_depth_mm", text="连接深度mm")
                if scene.seanixz_pro_joint_type in {'BALL', 'BALL_LINK', 'DOUBLE_BALL'}:
                    params_box.prop(scene, "seanixz_pro_joint_angle_deg", text="球关节摆动角度")
                elif scene.seanixz_pro_joint_type == 'LIMITED_AXLE':
                    row = params_box.row(align=True)
                    row.prop(scene, "seanixz_pro_joint_axle_limit_deg", text="限位角度")
                    row.prop(scene, "seanixz_pro_joint_axle_tab_count", text="锁片数量")
                elif scene.seanixz_pro_joint_type in {'DAMPED_HINGE', 'DOUBLE_HINGE'}:
                    params_box.prop(scene, "seanixz_pro_joint_hinge_axis", text="转轴方向", expand=True)
                    if scene.seanixz_pro_joint_type == 'DAMPED_HINGE':
                        row = params_box.row(align=True)
                        row.prop(scene, "seanixz_pro_joint_hinge_damping", text="端面阻尼齿")
                        if scene.seanixz_pro_joint_hinge_damping:
                            row.prop(scene, "seanixz_pro_joint_hinge_tooth_count", text="齿数")
                            row.prop(scene, "seanixz_pro_joint_hinge_tooth_height_mm", text="齿高mm")
                params_box.prop(scene, "seanixz_pro_joint_segments", text="圆形精度")
                params_box.prop(scene, "seanixz_pro_joint_integrated_split_cutter", text="一体式接缝分离切刀")
                if scene.seanixz_pro_joint_integrated_split_cutter:
                    params_box.prop(scene, "seanixz_pro_joint_fuse_integrated_cutter", text="融合为单一流形切刀")
                    params_box.prop(scene, "seanixz_pro_joint_fuse_print_connector", text="融合独立连接件")
                    row = params_box.row(align=True)
                    row.prop(scene, "seanixz_pro_joint_split_expand_factor", text="外扩倍率")
                    row.prop(scene, "seanixz_pro_joint_split_expand_mm", text="额外外扩mm")
                    row = params_box.row(align=True)
                    row.prop(scene, "seanixz_pro_joint_split_thickness_mm", text="分离缝mm")
                    row.prop(scene, "seanixz_pro_joint_min_print_size_mm", text="最小关节mm")
                params_box.operator(
                    "seanixz_pro.make_hi3d_joint_pair",
                    text="按当前参数生成连接对",
                    icon='CONSTRAINT_BONE',
                )

            cutter_box, cutter_opened = self.draw_foldout(
                box, scene, "seanixz_pro_ui_show_joint_ball_socket", "单独球窝切刀", 'MESH_UVSPHERE'
            )
            if cutter_opened:
                row = cutter_box.row(align=True)
                row.prop(scene, "seanixz_pro_joint_lock_throat_factor", text="锁口收紧")
                row.prop(scene, "seanixz_pro_joint_assembly_margin_mm", text="入口余量mm")
                cutter_box.operator(
                    "seanixz_pro.make_joint_snap_ball_socket_cutter",
                    text="生成球窝切刀",
                    icon='MOD_BOOLEAN',
                )

            magnet_box, magnet_opened = self.draw_foldout(
                box, scene, "seanixz_pro_ui_show_joint_magnet", "磁吸定位孔", 'MOD_BOOLEAN'
            )
            if magnet_opened:
                row = magnet_box.row(align=True)
                row.prop(scene, "seanixz_pro_joint_magnet_diameter_mm", text="直径mm")
                row.prop(scene, "seanixz_pro_joint_magnet_depth_mm", text="厚度mm")
                magnet_box.prop(scene, "seanixz_pro_joint_magnet_clearance_mm", text="单边余量mm")
                magnet_box.operator(
                    "seanixz_pro.make_joint_magnet_pocket_pair",
                    text="生成成对磁铁孔切刀",
                    icon='MOD_BOOLEAN',
                )

            axle_box, axle_opened = self.draw_foldout(
                box, scene, "seanixz_pro_ui_show_joint_axle", "单独转轴母槽", 'MESH_CYLINDER'
            )
            if axle_opened:
                row = axle_box.row(align=True)
                row.operator("seanixz_pro.make_joint_hinge_barrel_cutter", text="横向合页轴槽")
                row.operator("seanixz_pro.make_joint_snap_hinge_cutter", text="C形自锁轴槽")
                axle_box.label(text="编辑模式选择闭合圈线后生成")

        box, opened = self.draw_foldout(layout, scene, "seanixz_pro_ui_show_step07", "07 预处理", 'BRUSH_DATA')
        if opened:
            box.prop(scene, "seanixz_pro_merge_distance_mm", text="合并mm")
            row = box.row(align=True)
            row.operator("seanixz_pro.merge_by_distance", text="合并点")
            row.operator("seanixz_pro.recalc_normals", text="法线")
            row = box.row(align=True)
            row.operator("seanixz_pro.delete_interior_loose", text="内部/松散")
            row.operator("seanixz_pro.delete_floating_faces", text="游离面")
            box.operator("seanixz_pro.preprocess_all", text="一键预处理", icon='PLAY')

        box, opened = self.draw_foldout(layout, scene, "seanixz_pro_ui_show_step08", "08 布尔", 'MOD_BOOLEAN')
        if opened:
            row = box.row(align=True)
            row.prop(scene, "seanixz_pro_boolean_operation", text="类型")
            row.prop(scene, "seanixz_pro_boolean_solver", text="解算")
            row = box.row(align=True)
            row.prop(scene, "seanixz_pro_boolean_use_self", text="自交")
            row.prop(scene, "seanixz_pro_boolean_hole_tolerant", text="孔洞")
            row.prop(scene, "seanixz_pro_duplicate_cutters", text="保留")
            box.prop(scene, "seanixz_pro_cutter_tolerance_mm", text="固定厚度mm")
            box.prop(
                scene,
                "seanixz_pro_auto_nondestructive_preview",
                text="开启非破坏实时拆件预览（较耗资源）",
            )
            row = box.row(align=True)
            row.operator("seanixz_pro.boolean_preview", text="实时实体预览")
            row.operator("seanixz_pro.boolean_apply_separate", text="实体执行")
            box.operator("seanixz_pro.boolean_one_click", text="一键实体化布尔", icon='PLAY')
            row = box.row(align=True)
            row.operator("seanixz_pro.boolean_raw_preview", text="普通预览")
            row.operator("seanixz_pro.boolean_raw_apply_separate", text="普通执行")
            box.operator("seanixz_pro.boolean_raw_one_click", text="一键普通布尔", icon='PLAY')
            row = box.row(align=True)
            op = row.operator("seanixz_pro.duplicate_mirror_cutter", text="X镜像")
            op.axis = 'X'
            op = row.operator("seanixz_pro.duplicate_mirror_cutter", text="Y镜像")
            op.axis = 'Y'
            op = row.operator("seanixz_pro.duplicate_mirror_cutter", text="Z镜像")
            op.axis = 'Z'

            preview_box = box.box()
            preview_box.label(text="非破坏拆件预览默认关闭", icon='GEOMETRY_NODES')
            if scene.seanixz_pro_auto_nondestructive_preview:
                preview_box.label(text="重新点击上方“实时实体预览”即可生成两段式动态展开")
                row = preview_box.row(align=True)
                row.prop(scene, "seanixz_pro_preview_gap_mm", text="X轴/法向间距mm")
                row.prop(scene, "seanixz_pro_preview_max_parts", text="件数上限")
                preview_box.operator(
                    "seanixz_pro.nondestructive_preview_clear",
                    text="清除当前非破坏预览",
                    icon='X',
                )
                preview_box.label(text="先沿 X 轴水平排开，再沿切面法向分离；切刀变化会实时更新")
            else:
                preview_box.label(text="当前“实时实体预览”仅显示原位实体布尔结果，资源占用更低")

        box, opened = self.draw_foldout(layout, scene, "seanixz_pro_ui_show_step09", "09 收尾", 'MESH_ICOSPHERE')
        if opened:
            box.prop(scene, "seanixz_pro_manifold_use_voxel", text="体素重构")
            if scene.seanixz_pro_manifold_use_voxel:
                box.prop(scene, "seanixz_pro_manifold_voxel_size_mm", text="体素mm")
            box.operator("seanixz_pro.manifoldize", text="流形化", icon='PLAY')
            row = box.row(align=True)
            row.operator("seanixz_pro.reset_all_objects_location", text="复位")
            row.operator("seanixz_pro.toggle_backup_cutters_visibility", text="批量切刀显隐")
            row.operator("seanixz_pro.toggle_backups_visibility", text="布尔备份显隐")
            box.operator("seanixz_pro.set_scene_unit_mm", text="打印尺寸统一", icon='SCENE_DATA')

        footer = layout.box()
        footer.label(text=f"{ADDON_COPYRIGHT}  {ADDON_VERSION_TEXT}", icon='INFO')

# -----------------------------------------------------------------------------
# 注册
# -----------------------------------------------------------------------------

classes = (
    SEANIXZ_PRO_OT_set_length_unit_mm,
    SEANIXZ_PRO_OT_set_scene_unit_mm,
    SEANIXZ_PRO_OT_set_height,
    SEANIXZ_PRO_OT_get_face_count,
    SEANIXZ_PRO_OT_decimate_preview,
    SEANIXZ_PRO_OT_decimate_apply,
    SEANIXZ_PRO_OT_decimate_one_click,
    SEANIXZ_PRO_OT_remesh_preview,
    SEANIXZ_PRO_OT_remesh_apply,
    SEANIXZ_PRO_OT_remesh_one_click,

    SEANIXZ_PRO_OT_setup_surface_snap,
    SEANIXZ_PRO_OT_create_single_point_cutter,
    SEANIXZ_PRO_OT_setup_snap_and_create_cutter_point,
    SEANIXZ_PRO_OT_close_selected_points,
    SEANIXZ_PRO_OT_fit_selected_loop,
    SEANIXZ_PRO_OT_toggle_tenon_direction,
    SEANIXZ_PRO_OT_make_simple_tenon,
    SEANIXZ_PRO_OT_make_simple_tenon2,
    SEANIXZ_PRO_OT_bevel_selected_edges,
    SEANIXZ_PRO_OT_add_tenon_lock_wedge,
    SEANIXZ_PRO_OT_add_tenon_lock_triangle,
    SEANIXZ_PRO_OT_add_tenon_lock_hex,
    SEANIXZ_PRO_OT_add_tenon_lock_square,
    SEANIXZ_PRO_OT_add_tenon_lock_diamond,
    SEANIXZ_PRO_OT_apply_joint_fit_preset,
    SEANIXZ_PRO_OT_apply_figure_joint_preset,
    SEANIXZ_PRO_OT_make_print_ready_figure_joint,
    SEANIXZ_PRO_OT_make_joint_magnet_pocket_pair,
    SEANIXZ_PRO_OT_make_hi3d_joint_pair,
    SEANIXZ_PRO_OT_make_joint_pin_cutter,
    SEANIXZ_PRO_OT_make_joint_disc_clearance_cutter,
    SEANIXZ_PRO_OT_make_joint_hinge_barrel_cutter,
    SEANIXZ_PRO_OT_make_joint_ball_socket_cutter,
    SEANIXZ_PRO_OT_make_joint_snap_ball_socket_cutter,
    SEANIXZ_PRO_OT_make_joint_snap_hinge_cutter,
    SEANIXZ_PRO_OT_cutter_wire_display,

    SEANIXZ_PRO_OT_merge_by_distance,
    SEANIXZ_PRO_OT_recalc_normals,
    SEANIXZ_PRO_OT_delete_interior_loose,
    SEANIXZ_PRO_OT_delete_floating_faces,
    SEANIXZ_PRO_OT_preprocess_all,
    SEANIXZ_PRO_OT_nondestructive_preview_create,
    SEANIXZ_PRO_OT_nondestructive_preview_clear,
    SEANIXZ_PRO_OT_preview_transforms_to_deltas,
    SEANIXZ_PRO_OT_boolean_preview,
    SEANIXZ_PRO_OT_boolean_apply_separate,
    SEANIXZ_PRO_OT_boolean_raw_preview,
    SEANIXZ_PRO_OT_boolean_raw_apply_separate,
    SEANIXZ_PRO_OT_boolean_raw_one_click,
    SEANIXZ_PRO_OT_duplicate_mirror_cutter,
    SEANIXZ_PRO_OT_boolean_one_click,
    SEANIXZ_PRO_OT_toggle_joint_cutters_visibility,
    SEANIXZ_PRO_OT_toggle_backup_cutters_visibility,
    SEANIXZ_PRO_OT_toggle_backups_visibility,
    SEANIXZ_PRO_OT_reset_all_objects_location,
    SEANIXZ_PRO_OT_manifoldize,
    SEANIXZ_PRO_PT_main_panel,
)

def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass
            bpy.utils.register_class(cls)

    for handler in list(bpy.app.handlers.load_post):
        if getattr(handler, "__name__", "") == "seanixz_pro_backup_eye_load_post":
            bpy.app.handlers.load_post.remove(handler)

    bpy.app.handlers.load_post.append(seanixz_pro_backup_eye_load_post)

    history_handlers = (
        (bpy.app.handlers.undo_pre, seanixz_pro_history_pre),
        (bpy.app.handlers.undo_post, seanixz_pro_history_post),
        (bpy.app.handlers.redo_pre, seanixz_pro_history_pre),
        (bpy.app.handlers.redo_post, seanixz_pro_history_post),
    )

    for handler_list, callback in history_handlers:
        for handler in list(handler_list):
            if getattr(handler, "__name__", "") == callback.__name__:
                handler_list.remove(handler)
        handler_list.append(callback)

    try:
        if bpy.app.timers.is_registered(unlock_backup_eye_control):
            bpy.app.timers.unregister(unlock_backup_eye_control)
        if not bpy.app.timers.is_registered(backup_eye_visibility_poller):
            bpy.app.timers.register(backup_eye_visibility_poller, first_interval=0.1, persistent=True)
    except Exception:
        pass

    # 折叠式 UI 开关：默认只展开全局和第 01 步，避免面板过长。
    ui_steps = [
        ('seanixz_pro_ui_show_global', "显示全局设置", True),
        ('seanixz_pro_ui_show_step01', "展开 01 单位与尺寸", True),
        ('seanixz_pro_ui_show_step02', "展开 02 模型精简", False),
        ('seanixz_pro_ui_show_step03', "展开 03 重建修复", False),
        ('seanixz_pro_ui_show_step04', "展开 04 切刀绘制", False),
        ('seanixz_pro_ui_show_step05', "展开 05 卡榫 / 防呆锁止", False),
        ('seanixz_pro_ui_show_step06', "展开 06 活动关节切刀", False),
        ('seanixz_pro_ui_show_joint_params', "展开高级关节参数", False),
        ('seanixz_pro_ui_show_joint_ball_socket', "展开单独球窝切刀", False),
        ('seanixz_pro_ui_show_joint_magnet', "展开磁吸定位孔", False),
        ('seanixz_pro_ui_show_joint_axle', "展开单独转轴母槽", False),
        ('seanixz_pro_ui_show_step07', "展开 07 切刀预处理", False),
        ('seanixz_pro_ui_show_step08', "展开 08 布尔分件", False),
        ('seanixz_pro_ui_show_step09', "展开 09 收尾处理", False),
    ]
    for prop_name, prop_label, default_value in ui_steps:
        setattr(
            bpy.types.Scene,
            prop_name,
            bpy.props.BoolProperty(name=prop_label, default=default_value)
        )

    bpy.types.Scene.seanixz_pro_make_backup = bpy.props.BoolProperty(
        name="布尔切刀计算前备份",
        default=True,
        description="仅在正式应用布尔切刀前复制一份源模型；其他步骤和切割结果不再创建备份"
    )

    bpy.types.Scene.seanixz_pro_target_height_mm = bpy.props.FloatProperty(
        name="目标高度",
        default=200.0,
        min=0.001,
        precision=3,
        description="模型目标高度，单位 mm，默认 200mm"
    )

    bpy.types.Scene.seanixz_pro_decimate_percent = bpy.props.FloatProperty(
        name="精简比例",
        default=10.0,
        min=0.1,
        max=100.0,
        precision=1,
        subtype='PERCENTAGE',
        description="Decimate Collapse 保留百分比；10% 会传入 0.1 的实际保留比例"
    )

    # 注意：不要在 register() 中访问 bpy.data.scenes。
    # Blender 启用插件时处于 _RestrictData 限制环境，直接访问会导致导入失败。
    # 旧版本精简百分比迁移改为在面板绘制或执行精简时惰性处理。

    bpy.types.Scene.seanixz_pro_decimate_before_faces = bpy.props.IntProperty(default=0)
    bpy.types.Scene.seanixz_pro_decimate_after_faces = bpy.props.IntProperty(default=0)
    bpy.types.Scene.seanixz_pro_decimate_has_preview = bpy.props.BoolProperty(default=False)

    bpy.types.Scene.seanixz_pro_remesh_mode = bpy.props.EnumProperty(
        name="重构模式",
        items=[
            ('VOXEL', "体素重构", "适合修补破面、闭合网格，但面数可能增加"),
            ('SMOOTH', "平滑重构", "使用 Remesh Smooth 模式，适合让精简后的表面更柔和"),
        ],
        default='VOXEL',
        description="03 重建修复使用的重构方式"
    )

    bpy.types.Scene.seanixz_pro_voxel_size_mm = bpy.props.FloatProperty(
        name="体素大小",
        default=1.0,
        min=0.001,
        precision=3,
        description="Remesh Voxel 体素大小，单位 mm，默认 1mm"
    )

    bpy.types.Scene.seanixz_pro_remesh_octree_depth = bpy.props.IntProperty(
        name="平滑重构八叉树深度",
        default=8,
        min=1,
        max=12,
        description="Remesh Smooth 模式的 Octree Depth，默认 8；越高越细但越慢"
    )

    bpy.types.Scene.seanixz_pro_remesh_smooth = bpy.props.BoolProperty(
        name="平滑着色",
        default=True
    )

    bpy.types.Scene.seanixz_pro_remesh_before_faces = bpy.props.IntProperty(default=0)
    bpy.types.Scene.seanixz_pro_remesh_after_faces = bpy.props.IntProperty(default=0)
    bpy.types.Scene.seanixz_pro_remesh_has_preview = bpy.props.BoolProperty(default=False)

    bpy.types.Scene.seanixz_pro_fit_smooth_repeat = bpy.props.IntProperty(
        name="每段插点数",
        default=3,
        min=1,
        max=12,
        description="拟合时每条原始边之间插入的曲线过渡点数量；原始顶点位置不改变"
    )

    bpy.types.Scene.seanixz_pro_outer_scale = bpy.props.FloatProperty(
        name="外扩倍率",
        default=1.2,
        min=1.0,
        max=10.0,
        precision=3,
        description="卡榫圈线 E,S 外扩倍率，默认 1.2"
    )

    bpy.types.Scene.seanixz_pro_inner_scale = bpy.props.FloatProperty(
        name="卡榫1顶部缩放",
        default=0.9,
        min=0.01,
        max=10.0,
        precision=3,
        description="简单卡榫1沿法向拉出后，顶部 S 缩放倍率，默认 0.9，然后顶部 F 充填并拉平"
    )

    bpy.types.Scene.seanixz_pro_tenon2_scale = bpy.props.FloatProperty(
        name="卡榫2内缩倍率",
        default=0.8,
        min=0.01,
        max=10.0,
        precision=3,
        description="简单卡榫2选中内圈后执行 E,S 的缩放倍率，默认 0.8，然后沿法向拉出并顶部 F 充填拉平"
    )

    bpy.types.Scene.seanixz_pro_tenon_depth_mm = bpy.props.FloatProperty(
        name="法向拉出 mm",
        default=5.0,
        min=-1000.0,
        max=1000.0,
        precision=3,
        description="卡榫结构沿法线拉出距离，默认 5mm"
    )

    bpy.types.Scene.seanixz_pro_tenon_reverse_direction = bpy.props.BoolProperty(
        name="反向生成卡榫",
        default=False,
        description="开启后，卡榫1/卡榫2会沿所选圈线法线反方向生成；适合卡榫偶尔生成到错误一侧时快速切换"
    )

    bpy.types.Scene.seanixz_pro_use_bevel = bpy.props.BoolProperty(
        name="使用倒角",
        default=True,
        description="卡榫1/卡榫2是否在顶部圈线自动执行倒角；关闭后可手动点一键倒角"
    )

    bpy.types.Scene.seanixz_pro_bevel_mm = bpy.props.FloatProperty(
        name="倒角 mm",
        default=1.0,
        min=0.0,
        max=100.0,
        precision=3,
        description="简单卡榫切刀倒角尺寸"
    )

    bpy.types.Scene.seanixz_pro_bevel_segments = bpy.props.IntProperty(
        name="倒角段数",
        default=1,
        min=1,
        max=12,
        description="简单卡榫倒角段数，默认 1"
    )

    bpy.types.Scene.seanixz_pro_lock_height_mm = bpy.props.FloatProperty(
        name="锁止凸起高度",
        default=5.0,
        min=0.05,
        max=50.0,
        precision=3,
        description="卡榫表面防呆/锁止凸起的高度，单位 mm，默认 5mm"
    )

    bpy.types.Scene.seanixz_pro_lock_size_factor = bpy.props.FloatProperty(
        name="锁止自动尺寸比例",
        default=0.5,
        min=0.05,
        max=0.95,
        precision=3,
        description="锁止结构按所选表面短边自动缩放的比例，默认 0.5"
    )

    bpy.types.Scene.seanixz_pro_lock_reverse_direction = bpy.props.BoolProperty(
        name="锁止结构反向",
        default=False,
        description="切换防呆/锁止结构凸起方向。默认正向；方向不对时勾选后重新生成锁止结构"
    )

    bpy.types.Scene.seanixz_pro_lock_taper_scale = bpy.props.FloatProperty(
        name="锁止斜角缩放",
        default=0.8,
        min=0.05,
        max=1.0,
        precision=3,
        description="锁止结构顶部相对底部的缩放倍率，默认 0.8；数值越小，入口斜角越明显，装配更顺滑但锁止面积变小"
    )

    bpy.types.Scene.seanixz_pro_lock_size_mm = bpy.props.FloatProperty(
        name="锁止手动尺寸",
        default=0.0,
        min=0.0,
        max=1000.0,
        precision=3,
        description="锁止结构手动尺寸；0 表示根据所选表面自动计算"
    )

    bpy.types.Scene.seanixz_pro_lock_min_size_mm = bpy.props.FloatProperty(
        name="锁止最小尺寸",
        default=1.2,
        min=0.05,
        max=100.0,
        precision=3,
        description="自动尺寸时的最小锁止结构尺寸，避免小面生成过小而无法打印"
    )

    bpy.types.Scene.seanixz_pro_joint_fit_preset = bpy.props.EnumProperty(
        name="打印间隙预设",
        items=[
            ('RESIN', "树脂精细", "活动间隙 0.15mm，适合精细树脂打印；先打印小样确认"),
            ('FDM_TIGHT', "FDM紧配", "活动间隙 0.22mm，适合校准较好的 FDM 设备"),
            ('FDM_STANDARD', "FDM标准", "活动间隙 0.30mm，推荐作为普通 FDM 起点"),
            ('FDM_LOOSE', "FDM宽松", "活动间隙 0.42mm，适合粗层高或较难拆支撑的情况"),
        ],
        default='FDM_STANDARD',
    )

    bpy.types.Scene.seanixz_pro_figure_joint_preset = bpy.props.EnumProperty(
        name="可动手办部位",
        items=[
            ('NECK', "头颈", "双球头连杆，兼顾转头、低头和轻微侧倾"),
            ('SHOULDER', "肩部", "大摆角球关节，适合抬臂和前后摆动"),
            ('ELBOW', "肘部", "双转轴中央连接器，适合扩大屈肘范围"),
            ('WRIST', "腕部", "小球关节，适合旋转和轻微摆动"),
            ('TORSO', "胸腹", "双球头连杆，适合胸腔俯仰和侧摆"),
            ('WAIST', "腰部", "较紧凑的双球头连杆，兼顾扭腰与俯仰"),
            ('HIP', "髋部", "大摆角球关节，适合前踢、侧抬和旋转"),
            ('KNEE', "膝部", "双转轴中央连接器，适合扩大屈膝范围"),
            ('ANKLE', "踝部", "小型双球头摇摆结构，适合前后俯仰和侧向接地"),
        ],
        default='SHOULDER',
        update=update_figure_joint_preset,
    )

    bpy.types.Scene.seanixz_pro_joint_type = bpy.props.EnumProperty(
        name="连接件类型",
        items=[
            ('BALL', "球关节", "生成球头公件、球窝母槽和可调摆动开口"),
            ('BALL_LINK', "独立球头连接件", "生成可单独打印的球头插销连接件，以及包含固定插孔、球窝和分离面的组合切刀"),
            ('DOUBLE_BALL', "双球头", "生成双球头中央连杆及两端球窝组合切刀，适合头颈、胸腰和踝部"),
            ('RIVET', "铆钉", "生成带圆头锁止的铆钉公件和对应母孔"),
            ('TENON', "榫卯", "生成带轻微锥度的榫头和对应榫槽切刀"),
            ('LIMITED_AXLE', "限位车轴", "生成可对位插入、旋转锁止、带角度挡块并可拆卸的车轴公件和母槽切刀"),
            ('DAMPED_HINGE', "阻尼转轴", "生成横向止推转轴、端面阻尼齿和对应分度母槽切刀"),
            ('DOUBLE_HINGE', "肘膝双转轴", "生成独立中央连接器及两端转轴活动腔组合切刀"),
        ],
        default='BALL',
    )

    bpy.types.Scene.seanixz_pro_joint_integrated_split_cutter = bpy.props.BoolProperty(
        name="一体式接缝分离切刀",
        default=True,
        description="把按圈线尺寸外扩的平面分离体并入蓝色母槽切刀，一次布尔同时完成分件和关节腔",
    )

    bpy.types.Scene.seanixz_pro_joint_fuse_integrated_cutter = bpy.props.BoolProperty(
        name="自动融合为流形切刀",
        default=True,
        description="生成后自动用细体素融合分离片、关节腔和装配入口，避免布尔后出现额外松散块",
    )

    bpy.types.Scene.seanixz_pro_joint_fuse_print_connector = bpy.props.BoolProperty(
        name="融合独立连接件",
        default=True,
        description="把球头、连接杆、插销或转轴融合为可直接切片打印的单一流形网格",
    )

    bpy.types.Scene.seanixz_pro_joint_split_expand_factor = bpy.props.FloatProperty(
        name="圈线外扩倍率",
        default=1.08,
        min=1.0,
        max=2.0,
        precision=3,
        description="分离切刀相对所选圈线长宽的外扩倍率；只需略大于模型接缝轮廓",
    )

    bpy.types.Scene.seanixz_pro_joint_split_expand_mm = bpy.props.FloatProperty(
        name="额外外扩",
        default=1.0,
        min=0.0,
        max=50.0,
        precision=2,
        description="在圈线外扩倍率之外，向四周额外增加的覆盖距离，单位 mm",
    )

    bpy.types.Scene.seanixz_pro_joint_split_thickness_mm = bpy.props.FloatProperty(
        name="分离缝厚度",
        default=0.8,
        min=0.1,
        max=10.0,
        precision=2,
        description="用于切断整个接缝的薄片厚度；最终会自动不小于两倍活动间隙加0.25mm",
    )

    bpy.types.Scene.seanixz_pro_joint_min_print_size_mm = bpy.props.FloatProperty(
        name="最小可打印关节尺寸",
        default=5.0,
        min=1.0,
        max=50.0,
        precision=2,
        description="按圈线自动尺寸时的关节最小主体尺寸，防止腕部等小圈线生成无法打印和装配的微小球头",
    )

    bpy.types.Scene.seanixz_pro_joint_direction = bpy.props.EnumProperty(
        name="连接方向",
        items=[
            ('A_TO_B', "A → B", "A 侧生成公件，B 侧生成母槽切刀，沿圈线法向"),
            ('B_TO_A', "B → A", "B 侧生成公件，A 侧生成母槽切刀，沿圈线法向反向"),
        ],
        default='A_TO_B',
    )

    bpy.types.Scene.seanixz_pro_joint_size_factor = bpy.props.FloatProperty(
        name="连接尺寸比例",
        default=0.60,
        min=0.10,
        max=1.50,
        precision=2,
        description="自动尺寸时，连接件相对所选圈线短边的比例",
    )

    bpy.types.Scene.seanixz_pro_joint_size_mm = bpy.props.FloatProperty(
        name="连接件尺寸",
        default=6.0,
        min=0.2,
        max=500.0,
        precision=2,
        description="关闭自动尺寸后使用的连接件主体尺寸，单位 mm",
    )

    bpy.types.Scene.seanixz_pro_joint_connection_depth_mm = bpy.props.FloatProperty(
        name="连接深度",
        default=6.0,
        min=0.5,
        max=1000.0,
        precision=2,
        description="连接结构从装配面伸入另一侧的深度，单位 mm",
    )

    bpy.types.Scene.seanixz_pro_joint_angle_deg = bpy.props.FloatProperty(
        name="球关节摆动角度",
        default=35.0,
        min=5.0,
        max=80.0,
        precision=1,
        description="球杆在球窝开口处允许的近似摆动半角",
    )

    bpy.types.Scene.seanixz_pro_joint_axle_limit_deg = bpy.props.FloatProperty(
        name="车轴限位角度",
        default=90.0,
        min=10.0,
        max=170.0,
        precision=1,
        description="锁片进入周向轨道后允许旋转的角度；为保留实体挡块，会根据锁片数量自动限制最大有效角度",
    )

    bpy.types.Scene.seanixz_pro_joint_axle_tab_count = bpy.props.IntProperty(
        name="车轴锁片数量",
        default=3,
        min=2,
        max=6,
        description="可拆卸车轴的径向锁片与对应入口槽数量；数量越多越稳，但需要更准确地对位装配",
    )

    bpy.types.Scene.seanixz_pro_joint_hinge_axis = bpy.props.EnumProperty(
        name="阻尼转轴方向",
        items=[
            ('LONG', "沿圈线长轴", "转轴沿所选闭合圈线的最长方向布置"),
            ('SHORT', "沿圈线短轴", "转轴沿所选闭合圈线的短方向布置"),
        ],
        default='LONG',
    )

    bpy.types.Scene.seanixz_pro_joint_hinge_damping = bpy.props.BoolProperty(
        name="启用端面阻尼齿",
        default=True,
        description="在止推盘端面生成阻尼齿，并在母槽切刀中生成对应分度槽",
    )

    bpy.types.Scene.seanixz_pro_joint_hinge_tooth_count = bpy.props.IntProperty(
        name="阻尼齿数量",
        default=16,
        min=6,
        max=36,
        description="一圈阻尼定位齿数量；数量越多，单次分度角越小",
    )

    bpy.types.Scene.seanixz_pro_joint_hinge_tooth_height_mm = bpy.props.FloatProperty(
        name="阻尼齿高度",
        default=0.25,
        min=0.0,
        max=3.0,
        precision=3,
        description="端面阻尼齿突出高度，单位 mm；过大可能导致关节过紧",
    )

    bpy.types.Scene.seanixz_pro_joint_magnet_diameter_mm = bpy.props.FloatProperty(
        name="磁铁直径",
        default=5.0,
        min=0.2,
        max=100.0,
        precision=2,
        description="圆片磁铁标称直径，单位 mm",
    )

    bpy.types.Scene.seanixz_pro_joint_magnet_depth_mm = bpy.props.FloatProperty(
        name="磁铁厚度",
        default=2.0,
        min=0.2,
        max=100.0,
        precision=2,
        description="圆片磁铁标称厚度，单位 mm",
    )

    bpy.types.Scene.seanixz_pro_joint_magnet_clearance_mm = bpy.props.FloatProperty(
        name="磁铁孔单边余量",
        default=0.15,
        min=0.0,
        max=3.0,
        precision=3,
        description="磁铁孔半径和深度额外增加的装配余量，单位 mm",
    )

    bpy.types.Scene.seanixz_pro_joint_auto_size = bpy.props.BoolProperty(
        name="关节自动尺寸",
        default=True,
        description="根据选中闭合圈线的尺寸自动计算关节切刀大小，适合新手"
    )

    bpy.types.Scene.seanixz_pro_joint_auto_depth_factor = bpy.props.FloatProperty(
        name="自动穿透深度倍率",
        default=1.35,
        min=0.2,
        max=10.0,
        precision=3,
        description="自动尺寸时，轴孔/关节切刀长度相对圈线直径的倍率"
    )

    bpy.types.Scene.seanixz_pro_joint_assembly_margin_mm = bpy.props.FloatProperty(
        name="装配余量",
        default=0.4,
        min=0.0,
        max=10.0,
        precision=3,
        description="额外装配余量，帮助轴、圆盘或球头更容易装入，单位 mm"
    )

    bpy.types.Scene.seanixz_pro_joint_swing_room_factor = bpy.props.FloatProperty(
        name="活动空间倍率",
        default=1.35,
        min=1.0,
        max=3.0,
        precision=3,
        description="在基础活动间隙之外额外放大关节活动空间；越大越灵活，但强度越低"
    )

    bpy.types.Scene.seanixz_pro_joint_clearance_mm = bpy.props.FloatProperty(
        name="活动间隙",
        default=0.3,
        min=0.0,
        max=5.0,
        precision=3,
        description="活动关节切刀额外预留间隙，单位 mm。FDM 常可先从 0.2~0.4mm 试起"
    )

    bpy.types.Scene.seanixz_pro_joint_lock_throat_factor = bpy.props.FloatProperty(
        name="自锁口收紧比例",
        default=0.72,
        min=0.35,
        max=0.95,
        precision=3,
        description="自锁活动关节开口相对内部活动腔的收紧比例；数值越小越不易脱落，但装配更紧"
    )

    bpy.types.Scene.seanixz_pro_joint_segments = bpy.props.IntProperty(
        name="圆形段数",
        default=32,
        min=8,
        max=96,
        description="圆轴孔、圆盘、球窝等关节切刀的圆形细分段数"
    )

    bpy.types.Scene.seanixz_pro_joint_pin_radius_mm = bpy.props.FloatProperty(
        name="轴孔半径",
        default=2.0,
        min=0.1,
        max=100.0,
        precision=3,
        description="圆轴孔切刀的基础半径，不包含活动间隙"
    )

    bpy.types.Scene.seanixz_pro_joint_depth_mm = bpy.props.FloatProperty(
        name="轴孔深度",
        default=12.0,
        min=0.1,
        max=1000.0,
        precision=3,
        description="圆轴孔切刀沿所选圈线法向的长度/穿透深度"
    )

    bpy.types.Scene.seanixz_pro_joint_disc_radius_mm = bpy.props.FloatProperty(
        name="圆盘半径",
        default=8.0,
        min=0.1,
        max=1000.0,
        precision=3,
        description="圆盘活动间隙切刀半径，不包含活动间隙"
    )

    bpy.types.Scene.seanixz_pro_joint_disc_thickness_mm = bpy.props.FloatProperty(
        name="圆盘厚度",
        default=2.0,
        min=0.1,
        max=1000.0,
        precision=3,
        description="圆盘活动间隙切刀厚度，会额外加上两侧活动间隙"
    )

    bpy.types.Scene.seanixz_pro_joint_hinge_radius_mm = bpy.props.FloatProperty(
        name="合页轴槽半径",
        default=2.5,
        min=0.1,
        max=100.0,
        precision=3,
        description="横向合页轴槽切刀半径，不包含活动间隙"
    )

    bpy.types.Scene.seanixz_pro_joint_hinge_length_mm = bpy.props.FloatProperty(
        name="合页轴槽长度",
        default=20.0,
        min=0.1,
        max=1000.0,
        precision=3,
        description="横向合页轴槽切刀长度，方向由所选闭合圈线的最长方向自动判断"
    )

    bpy.types.Scene.seanixz_pro_joint_ball_radius_mm = bpy.props.FloatProperty(
        name="球窝半径",
        default=4.0,
        min=0.1,
        max=100.0,
        precision=3,
        description="球窝关节切刀球体半径，不包含活动间隙"
    )

    bpy.types.Scene.seanixz_pro_joint_ball_neck_radius_mm = bpy.props.FloatProperty(
        name="球窝开口半径",
        default=2.2,
        min=0.1,
        max=100.0,
        precision=3,
        description="球窝关节切刀开口通道半径，不包含活动间隙"
    )

    bpy.types.Scene.seanixz_pro_joint_ball_neck_length_mm = bpy.props.FloatProperty(
        name="球窝开口长度",
        default=6.0,
        min=0.1,
        max=1000.0,
        precision=3,
        description="球窝关节切刀开口通道长度"
    )

    bpy.types.Scene.seanixz_pro_merge_distance_mm = bpy.props.FloatProperty(
        name="合并间距",
        default=0.1,
        min=0.0,
        precision=3,
        description="合并重叠点距离，单位 mm，默认 0.1mm"
    )

    bpy.types.Scene.seanixz_pro_last_preprocess_report = bpy.props.StringProperty(default="")

    bpy.types.Scene.seanixz_pro_boolean_operation = bpy.props.EnumProperty(
        name="布尔类型",
        items=[
            ('DIFFERENCE', "差集 Difference", "使用临时实体化切刀从目标中切除"),
            ('UNION', "并集 Union", "合并目标和临时实体化切刀"),
            ('INTERSECT', "交集 Intersect", "保留目标与临时实体化切刀相交部分"),
        ],
        default='DIFFERENCE'
    )

    bpy.types.Scene.seanixz_pro_boolean_solver = bpy.props.EnumProperty(
        name="布尔解算器",
        items=[
            ('FAST', "快速 Fast", "速度较快，但复杂模型可能不稳定"),
            ('EXACT', "精确 Exact", "更适合复杂或高精度切割"),
        ],
        default='EXACT'
    )

    bpy.types.Scene.seanixz_pro_boolean_use_self = bpy.props.BoolProperty(
        name="自身交集",
        default=False,
        description="允许布尔对象自身相交。默认关闭"
    )

    bpy.types.Scene.seanixz_pro_boolean_hole_tolerant = bpy.props.BoolProperty(
        name="孔洞优化",
        default=False,
        description="启用孔洞容错。默认关闭"
    )

    bpy.types.Scene.seanixz_pro_duplicate_cutters = bpy.props.BoolProperty(
        name="保留原切刀",
        default=False,
        description="保留原始切刀，使用临时切刀参与布尔运算"
    )

    bpy.types.Scene.seanixz_pro_cutter_tolerance_mm = bpy.props.FloatProperty(
        name="刀具实体化厚度",
        default=0.2,
        min=-10.0,
        max=10.0,
        precision=3,
        description="切刀 Solidify 预览与临时布尔实体化厚度，单位 mm，默认 0.2mm"
    )

    bpy.types.Scene.seanixz_pro_auto_nondestructive_preview = bpy.props.BoolProperty(
        name="开启非破坏实时拆件预览",
        default=False,
        description="默认关闭以降低资源占用；勾选后点击实体/普通布尔预览才会创建实时拆件预览",
        update=update_auto_nondestructive_preview,
    )

    # 注册阶段 Blender 使用 _RestrictData，不能访问 bpy.data。
    # 默认关闭由 BoolProperty 的 default=False 保证；清理由用户取消勾选时执行。

    bpy.types.Scene.seanixz_pro_preview_gap_mm = bpy.props.FloatProperty(
        name="非破坏预览间距",
        default=10.0,
        min=0.0,
        max=10000.0,
        precision=2,
        description="先用于 X 轴水平排布间距，再作为切面法向分离距离，单位 mm",
        update=update_nondestructive_preview_gap,
    )

    bpy.types.Scene.seanixz_pro_preview_max_parts = bpy.props.IntProperty(
        name="非破坏预览件数上限",
        default=64,
        min=1,
        max=512,
        description="限制一次生成的预览载体数量，避免异常游离几何生成过多对象",
    )

    bpy.types.Scene.seanixz_pro_manifold_use_voxel = bpy.props.BoolProperty(
        name="使用体素重构",
        default=False,
        description="默认关闭。体素重构会重新生成网格，复杂模型非常消耗计算资源；只有普通清理无法修复时再开启"
    )

    bpy.types.Scene.seanixz_pro_manifold_voxel_size_mm = bpy.props.FloatProperty(
        name="收尾体素大小",
        default=1.0,
        min=0.001,
        max=100.0,
        precision=3,
        description="09 收尾处理体素重构专用体素大小，单位 mm，默认 1mm"
    )

def unregister():
    for handler in list(bpy.app.handlers.load_post):
        if getattr(handler, "__name__", "") == "seanixz_pro_backup_eye_load_post":
            bpy.app.handlers.load_post.remove(handler)

    for handler_list, callback_name in (
        (bpy.app.handlers.undo_pre, "seanixz_pro_history_pre"),
        (bpy.app.handlers.undo_post, "seanixz_pro_history_post"),
        (bpy.app.handlers.redo_pre, "seanixz_pro_history_pre"),
        (bpy.app.handlers.redo_post, "seanixz_pro_history_post"),
    ):
        for handler in list(handler_list):
            if getattr(handler, "__name__", "") == callback_name:
                handler_list.remove(handler)

    try:
        if bpy.app.timers.is_registered(unlock_backup_eye_control):
            bpy.app.timers.unregister(unlock_backup_eye_control)
        if bpy.app.timers.is_registered(backup_eye_visibility_poller):
            bpy.app.timers.unregister(backup_eye_visibility_poller)
    except Exception:
        pass

    props = [
        'seanixz_pro_ui_show_global',
        'seanixz_pro_ui_show_step01',
        'seanixz_pro_ui_show_step02',
        'seanixz_pro_ui_show_step03',
        'seanixz_pro_ui_show_step04',
        'seanixz_pro_ui_show_step05',
        'seanixz_pro_ui_show_step06',
        'seanixz_pro_ui_show_joint_params',
        'seanixz_pro_ui_show_joint_ball_socket',
        'seanixz_pro_ui_show_joint_magnet',
        'seanixz_pro_ui_show_joint_axle',
        'seanixz_pro_ui_show_step07',
        'seanixz_pro_ui_show_step08',
        'seanixz_pro_ui_show_step09',
        'seanixz_pro_make_backup',
        'seanixz_pro_target_height_mm',
        'seanixz_pro_decimate_percent',
        'seanixz_pro_decimate_use_smooth_remesh',
        'seanixz_pro_decimate_remesh_octree_depth',
        'seanixz_pro_decimate_ratio',
        'seanixz_pro_decimate_before_faces',
        'seanixz_pro_decimate_after_faces',
        'seanixz_pro_decimate_has_preview',
        'seanixz_pro_voxel_size_mm',
        'seanixz_pro_remesh_mode',
        'seanixz_pro_remesh_octree_depth',
        'seanixz_pro_remesh_smooth',
        'seanixz_pro_remesh_before_faces',
        'seanixz_pro_remesh_after_faces',
        'seanixz_pro_remesh_has_preview',

        'seanixz_pro_fit_smooth_repeat',
        'seanixz_pro_outer_scale',
        'seanixz_pro_inner_scale',
        'seanixz_pro_tenon2_scale',
        'seanixz_pro_tenon_depth_mm',
        'seanixz_pro_tenon_reverse_direction',
        'seanixz_pro_use_bevel',
        'seanixz_pro_bevel_mm',
        'seanixz_pro_bevel_segments',
        'seanixz_pro_lock_height_mm',
        'seanixz_pro_lock_size_factor',
        'seanixz_pro_lock_reverse_direction',
        'seanixz_pro_lock_taper_scale',
        'seanixz_pro_lock_size_mm',
        'seanixz_pro_lock_min_size_mm',
        'seanixz_pro_joint_fit_preset',
        'seanixz_pro_figure_joint_preset',
        'seanixz_pro_joint_type',
        'seanixz_pro_joint_integrated_split_cutter',
        'seanixz_pro_joint_fuse_integrated_cutter',
        'seanixz_pro_joint_fuse_print_connector',
        'seanixz_pro_joint_split_expand_factor',
        'seanixz_pro_joint_split_expand_mm',
        'seanixz_pro_joint_split_thickness_mm',
        'seanixz_pro_joint_min_print_size_mm',
        'seanixz_pro_joint_direction',
        'seanixz_pro_joint_size_factor',
        'seanixz_pro_joint_size_mm',
        'seanixz_pro_joint_connection_depth_mm',
        'seanixz_pro_joint_angle_deg',
        'seanixz_pro_joint_axle_limit_deg',
        'seanixz_pro_joint_axle_tab_count',
        'seanixz_pro_joint_hinge_axis',
        'seanixz_pro_joint_hinge_damping',
        'seanixz_pro_joint_hinge_tooth_count',
        'seanixz_pro_joint_hinge_tooth_height_mm',
        'seanixz_pro_joint_magnet_diameter_mm',
        'seanixz_pro_joint_magnet_depth_mm',
        'seanixz_pro_joint_magnet_clearance_mm',
        'seanixz_pro_joint_auto_size',
        'seanixz_pro_joint_auto_depth_factor',
        'seanixz_pro_joint_assembly_margin_mm',
        'seanixz_pro_joint_swing_room_factor',
        'seanixz_pro_joint_clearance_mm',
        'seanixz_pro_joint_lock_throat_factor',
        'seanixz_pro_joint_segments',
        'seanixz_pro_joint_pin_radius_mm',
        'seanixz_pro_joint_depth_mm',
        'seanixz_pro_joint_disc_radius_mm',
        'seanixz_pro_joint_disc_thickness_mm',
        'seanixz_pro_joint_hinge_radius_mm',
        'seanixz_pro_joint_hinge_length_mm',
        'seanixz_pro_joint_ball_radius_mm',
        'seanixz_pro_joint_ball_neck_radius_mm',
        'seanixz_pro_joint_ball_neck_length_mm',

        'seanixz_pro_merge_distance_mm',
        'seanixz_pro_last_preprocess_report',
        'seanixz_pro_boolean_operation',
        'seanixz_pro_boolean_solver',
        'seanixz_pro_boolean_use_self',
        'seanixz_pro_boolean_hole_tolerant',
        'seanixz_pro_duplicate_cutters',
        'seanixz_pro_cutter_tolerance_mm',
        'seanixz_pro_auto_nondestructive_preview',
        'seanixz_pro_preview_gap_mm',
        'seanixz_pro_preview_max_parts',
        'seanixz_pro_manifold_use_voxel',
        'seanixz_pro_manifold_voxel_size_mm',
    ]

    for prop in props:
        if hasattr(bpy.types.Scene, prop):
            try:
                delattr(bpy.types.Scene, prop)
            except Exception:
                pass

    cleanup_temp_boolean_cutters()
    cleanup_nondestructive_preview()

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

if __name__ == "__main__":
    register()
