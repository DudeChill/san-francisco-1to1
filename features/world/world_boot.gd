extends Node3D
## World boot: spawns player/vehicle/fog/HUD/cable cars once the tile index
## loads (or after a 6 s timeout in unstreamed fallback mode).

const PLAYER_SCRIPT := preload("res://features/player/player_controller.gd")
const CAR_SCRIPT := preload("res://features/vehicle/vehicle_controller.gd")
const CABLE_SCRIPT := preload("res://features/vehicle/cable_car.gd")
const FOG_SCRIPT := preload("res://features/world/fog_manager.gd")
const HUD_SCRIPT := preload("res://ui/hud.gd")

var player: PlayerController
var fog: FogManager
var hud: Hud
var _tour_index := -1

func _ready() -> void:
	_spawn_when_index_ready()

func _spawn_when_index_ready() -> void:
	if not StreamManager.index_loaded:
		var flag := [false]
		StreamManager.index_ready.connect(func(): flag[0] = true, CONNECT_ONE_SHOT)
		var timer := get_tree().create_timer(6.0)
		while not flag[0] and timer.time_left > 0.0:
			await get_tree().process_frame
	_build_world()

func _build_world() -> void:
	var spawn := StreamManager.get_spawn() if StreamManager.index_loaded else Vector3(0, 60, 0)
	player = PLAYER_SCRIPT.new()
	add_child(player)
	player.global_position = spawn + Vector3(0, 2.5, 0)
	# Spawn in fly mode; _physics_process lands the player once the ground
	# under them has streamed in (prevents falling through unloaded tiles).
	player.fly = true

	var car: CityCar = CAR_SCRIPT.new()
	add_child(car)
	car.global_position = spawn + Vector3(7, 1.2, 5)
	player.nearby_vehicles.append(car)

	fog = FOG_SCRIPT.new()
	add_child(fog)
	fog.set_camera(player)

	hud = HUD_SCRIPT.new()
	add_child(hud)

	_spawn_cable_cars()
	_spawn_ambience()
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	var tour_env := OS.get_environment("SF_TOUR_STOP")
	if tour_env != "" and int(tour_env) > 0:
		# _next_tour_stop() advances first, so stop N maps to landmark N-1.
		_tour_index = int(tour_env) - 2
		_next_tour_stop()

func _spawn_cable_cars() -> void:
	for line: Dictionary in StreamManager.index.get("cable_car_lines", []):
		var pts := PackedVector3Array()
		for p in line.get("points", []):
			pts.append(Vector3(float(p[0]), float(p[1]) + 2.4, float(p[2])))
		if pts.size() < 2:
			continue
		var car: CableCar = CABLE_SCRIPT.new()
		add_child(car)
		car.setup(pts)

func _spawn_ambience() -> void:
	if ResourceLoader.exists("res://audio/wind_loop.wav"):
		var ap := AudioStreamPlayer.new()
		ap.stream = load("res://audio/wind_loop.wav")
		ap.volume_db = -14.0
		add_child(ap)
		ap.play()
	# Positional ambience keyed off landmarks from the tile index.
	for lm: Dictionary in StreamManager.index.get("landmarks", []):
		var lname := str(lm.get("name", ""))
		var pos := Vector3(float(lm.x), float(lm.y) + 25.0, float(lm.z))
		if lname.contains("Golden Gate"):
			_spawn_positional("res://audio/foghorn.wav", pos, 2400.0, 26.0)
		elif lname.contains("Ferry") or lname.contains("Wharf"):
			_spawn_positional("res://audio/gull_cry.wav", pos, 400.0, 9.0)

func _spawn_positional(path: String, pos: Vector3, max_m: float, interval: float) -> void:
	var p := AudioStreamPlayer3D.new()
	p.stream = load(path)
	p.position = pos
	p.max_distance = max_m
	p.unit_size = 40.0
	add_child(p)
	var timer := Timer.new()
	timer.wait_time = interval
	timer.autostart = true
	timer.timeout.connect(func():
		if not p.playing and randf() < 0.8:
			p.play())
	add_child(timer)

func _physics_process(_delta: float) -> void:
	if player == null or not player.fly or player.in_vehicle != null:
		return
	# Only auto-land near ground level; tour teleports stay aerial.
	if player.global_position.y > 25.0:
		return
	# Auto-land: walk mode only when ground exists right below the player.
	var space := player.get_world_3d().direct_space_state
	var from := player.global_position + Vector3(0, 2.0, 0)
	var q := PhysicsRayQueryParameters3D.create(from, from + Vector3(0, -6.0, 0))
	q.exclude = [player.get_rid()]
	if not space.intersect_ray(q).is_empty():
		player.fly = false
		SignalBus.player_mode_changed.emit("walk")

func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("toggle_tour"):
		_next_tour_stop()
		get_viewport().set_input_as_handled()

const TOUR_ALTITUDE := {
	"Salesforce Tower": 360.0,
	"Transamerica Pyramid": 300.0,
	"Sutro Tower": 340.0,
	"Golden Gate Bridge": 140.0,
	"Bay Bridge": 140.0,
	"Coit Tower": 100.0,
}

func _next_tour_stop() -> void:
	if player == null:
		return
	var lms: Array = StreamManager.index.get("landmarks", [])
	if lms.is_empty():
		return
	_tour_index = (_tour_index + 1) % lms.size()
	var lm: Dictionary = lms[_tour_index]
	var alt: float = TOUR_ALTITUDE.get(str(lm.get("name", "")), 90.0)
	player.fly = true
	player.teleport(Vector3(float(lm.x), float(lm.y) + alt, float(lm.z)))
	SignalBus.tour_destination_changed.emit(str(lm.get("name", "?")))
