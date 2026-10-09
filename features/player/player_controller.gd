class_name PlayerController
extends CharacterBody3D
## First-person walk + free-fly. E enters/exits nearest vehicle; F toggles fly.

const WALK_SPEED := 5.0
const SPRINT_SPEED := 12.0
const FLY_SPEED := 45.0
const FLY_SPRINT := 160.0
const JUMP_SPEED := 4.8
const GRAVITY := 9.8
const MOUSE_SENS := 0.0022
const VEHICLE_ENTER_RANGE := 5.0

var fly := false
var in_vehicle: VehicleBody3D = null
var nearby_vehicles: Array[CityCar] = []

var _head: Node3D
var _camera: Camera3D
var _pitch := 0.0

func _ready() -> void:
	var pitch_env := OS.get_environment("SF_TOUR_PITCH")
	if pitch_env != "":
		_pitch = clampf(float(pitch_env), -1.55, 1.55)
	var shape := CollisionShape3D.new()
	var capsule := CapsuleShape3D.new()
	capsule.radius = 0.35
	capsule.height = 1.8
	shape.shape = capsule
	shape.position = Vector3(0, 0.9, 0)
	add_child(shape)

	_head = Node3D.new()
	_head.name = "Head"
	_head.position = Vector3(0, 1.62, 0)
	_head.rotation.x = _pitch
	add_child(_head)

	_camera = Camera3D.new()
	_camera.name = "Camera"
	_camera.fov = 75.0
	_camera.near = 0.08
	_camera.far = 12000.0
	_head.add_child(_camera)
	_camera.make_current()
	StreamManager.set_target(self)

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		var motion := event as InputEventMouseMotion
		rotate_y(-motion.relative.x * MOUSE_SENS)
		_pitch = clampf(_pitch - motion.relative.y * MOUSE_SENS, -1.55, 1.55)
		_head.rotation.x = _pitch
	elif event.is_action_pressed("toggle_fly"):
		fly = not fly
		velocity = Vector3.ZERO
		SignalBus.player_mode_changed.emit("fly" if fly else "walk")
		get_viewport().set_input_as_handled()
	elif event.is_action_pressed("enter_vehicle"):
		_handle_vehicle_toggle()
		get_viewport().set_input_as_handled()
	elif event.is_action_pressed("ui_cancel"):
		if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
			Input.mouse_mode = Input.MOUSE_MODE_VISIBLE

func _handle_vehicle_toggle() -> void:
	if in_vehicle != null:
		# Exit: place beside the car, restore player.
		var car := in_vehicle
		var side: Vector3 = car.global_transform.basis.x.normalized()
		car.set_driver(null)
		in_vehicle = null
		process_mode = Node.PROCESS_MODE_INHERIT
		visible = true
		global_position = car.global_position + side * 2.2 + Vector3.UP * 1.0
		velocity = Vector3.ZERO
		StreamManager.set_target(self)
		_camera.make_current()
		SignalBus.player_mode_changed.emit("walk")
		return
	var best: CityCar = null
	var best_d := VEHICLE_ENTER_RANGE
	for v in nearby_vehicles:
		if not is_instance_valid(v):
			continue
		var d := global_position.distance_to(v.global_position)
		if d < best_d:
			best_d = d
			best = v
	if best != null:
		in_vehicle = best
		best.set_driver(self)
		best.make_camera_current()
		process_mode = Node.PROCESS_MODE_DISABLED
		visible = false
		SignalBus.player_mode_changed.emit("drive")

func teleport(pos: Vector3) -> void:
	global_position = pos
	velocity = Vector3.ZERO

func _physics_process(delta: float) -> void:
	# Fall recovery: if streaming gaps drop us far below the last known
	# ground level, snap back to spawn instead of falling forever.
	if not fly and global_position.y < StreamManager.get_spawn().y - 300.0:
		teleport(StreamManager.get_spawn() + Vector3(0, 3.0, 0))
	if fly:
		var dir := _camera_basis_direction()
		var speed := FLY_SPRINT if Input.is_action_pressed("sprint") else FLY_SPEED
		# Idle hover: fly only moves on input; never auto-drift.
		velocity = dir * speed if dir.length() > 0.01 else Vector3.ZERO
		move_and_slide()
		return
	if not is_on_floor():
		velocity.y -= GRAVITY * delta
	else:
		velocity.y = 0.0
	if is_on_floor() and Input.is_action_just_pressed("jump"):
		velocity.y = JUMP_SPEED
	var input_dir := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var dir := (transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()
	var speed := SPRINT_SPEED if Input.is_action_pressed("sprint") else WALK_SPEED
	if dir != Vector3.ZERO:
		velocity.x = dir.x * speed
		velocity.z = dir.z * speed
	else:
		velocity.x = move_toward(velocity.x, 0, speed)
		velocity.z = move_toward(velocity.z, 0, speed)
	move_and_slide()

func _camera_basis_direction() -> Vector3:
	var forward := -_camera.global_transform.basis.z
	var right := _camera.global_transform.basis.x
	var v := Vector3.ZERO
	if Input.is_action_pressed("move_forward"):
		v += forward
	if Input.is_action_pressed("move_back"):
		v -= forward
	if Input.is_action_pressed("move_right"):
		v += right
	if Input.is_action_pressed("move_left"):
		v -= right
	if Input.is_action_pressed("jump"):
		v.y += 1.0
	if Input.is_action_pressed("fly_down"):
		v.y -= 1.0
	return v.normalized() if v.length() > 0.01 else -_camera.global_transform.basis.z
