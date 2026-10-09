class_name FogManager
extends Node3D
## Karl the Fog: advected FogVolume3D slabs drifting in from the Pacific
## (west = -X) through the Gate, density keyed to fog-belt tiles + hour.

const VOLUME_SIZE := Vector3(768.0, 110.0, 768.0)
const DRIFT := Vector3(3.0, 0.0, 0.6) # m/s eastward + slight south
const VOLUME_COUNT := 4
const FOG_DENSITY := 0.045

var _volumes: Array[FogVolume] = []
var _mats: Array[FogMaterial] = []
var _camera: Node3D
var _accum := 0.0

func _ready() -> void:
	for i in VOLUME_COUNT:
		var vol := FogVolume.new()
		vol.size = VOLUME_SIZE
		var mat := FogMaterial.new()
		mat.density = 0.0
		mat.emission = Color(0.75, 0.79, 0.86)
		mat.height_falloff = 0.12
		vol.material = mat
		add_child(vol)
		_volumes.append(vol)
		_mats.append(mat)

func set_camera(node: Node3D) -> void:
	_camera = node

func _process(delta: float) -> void:
	if _camera == null:
		return
	var cam := _camera.global_position
	_drift_phase = fposmod(_drift_phase + delta, 768.0)
	# 2x2 slot grid around the camera; slots slide with drift phase and wrap.
	for i in VOLUME_COUNT:
		var slot_x := fposmod(_drift_phase * DRIFT.x / DRIFT.length() + float(i % 2) * 384.0, 768.0) - 384.0
		var slot_z := fposmod(_drift_phase * DRIFT.z / DRIFT.length() + float(i / 2) * 384.0, 768.0) - 384.0
		_volumes[i].global_position = Vector3(cam.x + slot_x, cam.y, cam.z + slot_z)
	_accum += delta
	if _accum >= 0.5:
		_accum = 0.0
		_update_density(cam)

var _drift_phase := 0.0

func _update_density(cam: Vector3) -> void:
	if OS.get_environment("SF_CLEAR_FOG") == "1":
		for mat in _mats:
			mat.density = 0.0
		return
	var ti := StreamManager.tile_index_at(cam.x, cam.z)
	var in_belt := StreamManager.tile_foggy(ti.x, ti.y)
	# Fog thickest in early morning and evening overcast, thin at midday/night.
	var hour := TimeOfDay.hour
	var diurnal := 1.0 if (hour < 11.0 or hour > 17.0) else 0.45
	var base := FOG_DENSITY * (1.0 if in_belt else 0.12) * diurnal
	for mat in _mats:
		mat.density = base
