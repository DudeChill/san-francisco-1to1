extends Node
## StreamManager: streams city tiles around a tracking target.
## Data contract: local://sf_contract.md (data/tiles/*).
## Full-detail tier near camera, LOD1 tier beyond, threaded loads, MultiMesh props.

signal index_ready
signal index_failed

const TILE_DIR := "res://data/tiles"
const PROP_DIR := "res://data/props"
const TILE_SIZE_DEFAULT := 256.0
const FULL_RADIUS := 2            # tiles radius for full detail
const LOD1_RADIUS := 8            # tiles radius for simplified tier
const UNLOAD_MARGIN := 2          # hysteresis in tiles beyond LOD1_RADIUS
const MAX_CONCURRENT_LOADS := 10
const MAX_INSTANTIATE_PER_FRAME := 3

const FACADE_SHADER := preload("res://shaders/facade.gdshader")
const WATER_SHADER := preload("res://shaders/water.gdshader")

var index: Dictionary = {}
var index_loaded := false
var tile_size := TILE_SIZE_DEFAULT
var grid_x0 := 0.0
var grid_z0 := 0.0
var loaded_count := 0

var _target: Node3D
var _tiles_root: Node3D
var _tiles: Dictionary = {}        # Vector2i -> TileEntry
var _pending: Dictionary = {}      # Vector2i -> String path
var _spawn_queue: Array[Vector2i] = []
var _prop_meshes: Dictionary = {}  # String type -> Mesh
var _prop_queue: Array[String] = []
var _facade_mats: Dictionary = {}  # String district -> ShaderMaterial
var _water_mat: ShaderMaterial
var _tile_meta: Dictionary = {}    # Vector2i -> Dictionary (elev, foggy, district)
var _last_center_tile := Vector2i(1 << 20, 1 << 20)

class TileEntry:
	var node: Node3D
	var tier: int = 0
	var props_built := false

func _ready() -> void:
	_tiles_root = Node3D.new()
	_tiles_root.name = "TilesRoot"
	add_child(_tiles_root)
	_water_mat = ShaderMaterial.new()
	_water_mat.shader = WATER_SHADER
	_load_index()
	if index_loaded:
		_queue_prop_meshes()
		index_ready.emit()
	else:
		push_warning("StreamManager: data/tiles/index.json missing — running unstreamed.")
		index_failed.emit()

func set_target(node: Node3D) -> void:
	_target = node

func get_target() -> Node3D:
	return _target

func tile_index_at(world_x: float, world_z: float) -> Vector2i:
	return Vector2i(
		floori((world_x - grid_x0) / tile_size),
		floori((world_z - grid_z0) / tile_size))

func tile_origin_world(i: int, j: int) -> Vector3:
	return Vector3(grid_x0 + i * tile_size, 0.0, grid_z0 + j * tile_size)

func tile_foggy(i: int, j: int) -> bool:
	var meta: Dictionary = _tile_meta.get(Vector2i(i, j), {})
	return meta.get("foggy", false)

func get_spawn() -> Vector3:
	var s: Dictionary = index.get("spawn", {})
	return Vector3(float(s.get("x", 0.0)), float(s.get("y", 3.0)), float(s.get("z", 0.0)))

func _tile_key(key: Vector2i) -> String:
	return "%d_%d" % [key.x, key.y]

func _load_index() -> void:
	var f := FileAccess.open(TILE_DIR + "/index.json", FileAccess.READ)
	if f == null:
		return
	var parsed: Variant = JSON.parse_string(f.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error("StreamManager: index.json is not a JSON object.")
		return
	index = parsed
	tile_size = float(index.get("tile_size", TILE_SIZE_DEFAULT))
	grid_x0 = float(index.get("grid_x0", 0.0))
	grid_z0 = float(index.get("grid_z0", 0.0))
	for t: Dictionary in index.get("tiles", []):
		_tile_meta[Vector2i(int(t.get("i", 0)), int(t.get("j", 0)))] = t
	index_loaded = true
	print("StreamManager: index loaded — %d tiles, grid origin (%.1f, %.1f)" % [
		index.get("tiles", []).size(), grid_x0, grid_z0])

func _queue_prop_meshes() -> void:
	if not DirAccess.dir_exists_absolute(PROP_DIR):
		return
	for fname in DirAccess.get_files_at(PROP_DIR):
		if fname.ends_with(".glb") or fname.ends_with(".gltf"):
			var path := PROP_DIR + "/" + fname
			ResourceLoader.load_threaded_request(path, "PackedScene", true)
			_prop_queue.append(path)

func _process(_delta: float) -> void:
	_poll_prop_meshes()
	_update_facade_night()
	if _target == null or not index_loaded:
		return
	_update_stream()
	_poll_pending()

func _update_facade_night() -> void:
	var nf := TimeOfDay.night_factor
	for mat: ShaderMaterial in _facade_mats.values():
		mat.set_shader_parameter("night_factor", nf)

func _poll_prop_meshes() -> void:
	if _prop_queue.is_empty():
		return
	for path: String in _prop_queue.duplicate():
		var status := ResourceLoader.load_threaded_get_status(path)
		if status == ResourceLoader.THREAD_LOAD_LOADED:
			var res: Resource = ResourceLoader.load_threaded_get(path)
			var scene := res as PackedScene
			if scene != null:
				var inst := scene.instantiate()
				var mi := inst.find_children("*", "MeshInstance3D", true, false)
				if not mi.is_empty():
					_prop_meshes[String(StringName(path.get_file().get_basename()))] = (mi[0] as MeshInstance3D).mesh
				inst.queue_free()
			_prop_queue.erase(path)
		elif status == ResourceLoader.THREAD_LOAD_FAILED:
			push_warning("StreamManager: prop mesh failed to load: " + path)
			_prop_queue.erase(path)

func _update_stream() -> void:
	var center := _target.global_position
	var ci := tile_index_at(center.x, center.z)
	if ci == _last_center_tile:
		return
	_last_center_tile = ci

	var wanted := {}   # Vector2i -> tier (0 full, 1 lod1)
	var full_r2 := float(FULL_RADIUS * FULL_RADIUS)
	for j in range(ci.y - LOD1_RADIUS, ci.y + LOD1_RADIUS + 1):
		for i in range(ci.x - LOD1_RADIUS, ci.x + LOD1_RADIUS + 1):
			var dx := float(i - ci.x)
			var dz := float(j - ci.y)
			var d2 := dx * dx + dz * dz
			if d2 <= full_r2:
				wanted[Vector2i(i, j)] = 0
			else:
				wanted[Vector2i(i, j)] = 1

	# Unload stale entries (hysteresis margin).
	var drop_r2 := float((LOD1_RADIUS + UNLOAD_MARGIN) * (LOD1_RADIUS + UNLOAD_MARGIN))
	for key: Vector2i in _tiles.keys():
		var dx := float(key.x - ci.x)
		var dz := float(key.y - ci.y)
		if dx * dx + dz * dz > drop_r2:
			_tiles[key].node.queue_free()
			_tiles.erase(key)
	loaded_count = _tiles.size()

	# Retier entries whose tier changed.
	for key: Vector2i in _tiles.keys():
		if not wanted.has(key):
			continue # kept alive only by hysteresis; will drop later
		var entry: TileEntry = _tiles[key]
		var want_tier: int = wanted[key]
		if entry.tier != want_tier:
			entry.node.queue_free()
			_tiles.erase(key)

	# Queue missing tiles, nearest first.
	var queue_list: Array = []
	for key: Vector2i in wanted.keys():
		if _tiles.has(key) or _pending.has(key):
			continue
		var dx := float(key.x - ci.x)
		var dz := float(key.y - ci.y)
		queue_list.append([dx * dx + dz * dz, key])
	queue_list.sort_custom(func(a, b): return a[0] < b[0])
	for item in queue_list:
		if _pending.size() >= MAX_CONCURRENT_LOADS:
			break
		var key: Vector2i = item[1]
		var tier: int = wanted[key]
		var suffix := "" if tier == 0 else "_lod1"
		var path := "%s/tile_%s%s.gltf" % [TILE_DIR, _tile_key(key), suffix]
		if not ResourceLoader.exists(path):
			continue
		ResourceLoader.load_threaded_request(path, "PackedScene", true)
		_pending[key] = path

func _poll_pending() -> void:
	if _pending.is_empty():
		return
	var ready_keys: Array[Vector2i] = []
	for key: Vector2i in _pending.keys():
		var status := ResourceLoader.load_threaded_get_status(_pending[key])
		if status == ResourceLoader.THREAD_LOAD_LOADED:
			ready_keys.append(key)
		elif status == ResourceLoader.THREAD_LOAD_FAILED:
			push_warning("StreamManager: tile failed: " + _pending[key])
			_pending.erase(key)
	var instantiated := 0
	for key in ready_keys:
		if instantiated >= MAX_INSTANTIATE_PER_FRAME:
			break
		var path: String = _pending[key]
		var res: Resource = ResourceLoader.load_threaded_get(path)
		_pending.erase(key)
		var scene := res as PackedScene
		if scene == null:
			continue
		_instantiate_tile(key, scene, 1 if path.ends_with("_lod1.gltf") else 0)
		instantiated += 1

func _instantiate_tile(key: Vector2i, scene: PackedScene, tier: int) -> void:
	var node := scene.instantiate() as Node3D
	if node == null:
		return
	var origin := tile_origin_world(key.x, key.y)
	node.position = origin
	_prepare_materials(node)
	var entry := TileEntry.new()
	entry.node = node
	entry.tier = tier
	_tiles[key] = entry
	_tiles_root.add_child(node)
	_build_props(key, entry, origin)
	loaded_count = _tiles.size()
	SignalBus.tile_count_changed.emit(loaded_count)

func _prepare_materials(node: Node3D) -> void:
	var nodes := node.find_children("*", "MeshInstance3D", true, false)
	for n in nodes:
		var mi := n as MeshInstance3D
		var mesh := mi.mesh
		if mesh == null:
			continue
		for s in mesh.get_surface_count():
			var mat := mi.get_active_material(s)
			if mat == null:
				continue
			var mname := mat.resource_name
			if mname.begins_with("Mat_Facade_"):
				mi.set_surface_override_material(s, _facade_material(mname, mat))
			elif mname == "Mat_Water":
				mi.set_surface_override_material(s, _water_mat)

func _facade_material(material_name: String, source: Material) -> ShaderMaterial:
	var district := material_name.trim_prefix("Mat_Facade_")
	if _facade_mats.has(district):
		return _facade_mats[district]
	var sm := ShaderMaterial.new()
	sm.shader = FACADE_SHADER
	var std := source as StandardMaterial3D
	var albedo: Texture2D = std.albedo_texture if std != null else null
	var emissive: Texture2D = std.emission_texture if std != null else null
	if albedo != null:
		sm.set_shader_parameter("albedo_tex", albedo)
	if emissive != null:
		sm.set_shader_parameter("emissive_tex", emissive)
	elif albedo != null:
		sm.set_shader_parameter("emissive_tex", albedo)
	_facade_mats[district] = sm
	return sm

func _build_props(key: Vector2i, entry: TileEntry, origin: Vector3) -> void:
	if entry.tier != 0 or entry.props_built:
		return
	entry.props_built = true
	var path := "%s/props_%s.json" % [TILE_DIR, _tile_key(key)]
	if not FileAccess.file_exists(path):
		return
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return
	var parsed: Variant = JSON.parse_string(f.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		return
	for type: String in parsed.keys():
		if not _prop_meshes.has(type):
			continue
		var transforms: Array = parsed[type]
		if transforms.is_empty():
			continue
		var mm := MultiMesh.new()
		mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.mesh = _prop_meshes[type]
		mm.instance_count = transforms.size()
		for idx in transforms.size():
			var t: Array = transforms[idx]
			var basis := Basis(Vector3.UP, float(t[3]))
			mm.set_instance_transform(idx, Transform3D(
				basis, Vector3(float(t[0]) - origin.x, float(t[1]), float(t[2]) - origin.z)))
		var mmi := MultiMeshInstance3D.new()
		mmi.multimesh = mm
		mmi.position = Vector3.ZERO
		entry.node.add_child(mmi)
