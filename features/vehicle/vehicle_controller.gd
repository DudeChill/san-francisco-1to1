class_name CityCar
extends VehicleBody3D
## Drivable city car. Jolt VehicleBody3D: suspension stiffness + wheel friction
## dominate feel. Chase camera on a SpringArm3D.

const MAX_STEER := 0.55
const STEER_SPEED := 3.5
const ENGINE_FORCE := 2400.0
const REVERSE_FORCE := 1200.0
const BRAKE_FORCE := 45.0
const MAX_SPEED_KMH := 95.0

var _steer := 0.0
var _driver: PlayerController = null
var _camera: Camera3D
var _speed_label_ready := false

func _ready() -> void:
	mass = 900.0
	center_of_mass_mode = RigidBody3D.CENTER_OF_MASS_MODE_CUSTOM
	center_of_mass = Vector3(0, 0.2, 0)

	var col := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(1.85, 1.1, 4.4)
	col.shape = box
	col.position = Vector3(0, 0.75, 0)
	add_child(col)

	var body_mesh := MeshInstance3D.new()
	var chassis := BoxMesh.new()
	chassis.size = Vector3(1.85, 0.75, 4.4)
	body_mesh.mesh = chassis
	body_mesh.position = Vector3(0, 0.85, 0)
	var paint := StandardMaterial3D.new()
	paint.albedo_color = Color(0.72, 0.13, 0.11)
	paint.metallic = 0.55
	paint.roughness = 0.35
	body_mesh.material_override = paint
	add_child(body_mesh)

	var cabin_mesh := MeshInstance3D.new()
	var cabin := BoxMesh.new()
	cabin.size = Vector3(1.7, 0.6, 2.1)
	cabin_mesh.mesh = cabin
	cabin_mesh.position = Vector3(0, 1.5, -0.2)
	var glass := StandardMaterial3D.new()
	glass.albedo_color = Color(0.06, 0.09, 0.12, 0.82)
	glass.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	glass.metallic = 0.8
	glass.roughness = 0.1
	cabin_mesh.material_override = glass
	add_child(cabin_mesh)

	_add_wheel(Vector3(0.82, 0.35, 1.45), true)
	_add_wheel(Vector3(-0.82, 0.35, 1.45), true)
	_add_wheel(Vector3(0.82, 0.35, -1.45), false)
	_add_wheel(Vector3(-0.82, 0.35, -1.45), false)

	var arm := SpringArm3D.new()
	arm.name = "ChaseArm"
	arm.spring_length = 7.5
	arm.position = Vector3(0, 2.3, 0)
	arm.rotation.x = -0.32
	arm.collision_mask = 1
	add_child(arm)
	_camera = Camera3D.new()
	_camera.fov = 72.0
	_camera.near = 0.1
	_camera.far = 12000.0
	arm.add_child(_camera)

func _add_wheel(local_pos: Vector3, steered: bool) -> void:
	var wheel := VehicleWheel3D.new()
	wheel.position = local_pos
	wheel.wheel_radius = 0.35
	wheel.wheel_rest_length = 0.35
	wheel.suspension_stiffness = 55.0
	wheel.damping_compression = 4.5
	wheel.damping_relaxation = 3.5
	wheel.wheel_friction_slip = 3.5
	wheel.suspension_travel = 0.22
	wheel.use_as_traction = not steered
	wheel.use_as_steering = steered
	var wmesh := MeshInstance3D.new()
	var cyl := CylinderMesh.new()
	cyl.top_radius = 0.35
	cyl.bottom_radius = 0.35
	cyl.height = 0.25
	wmesh.mesh = cyl
	wmesh.rotation = Vector3(0, 0, PI / 2)
	var rubber := StandardMaterial3D.new()
	rubber.albedo_color = Color(0.08, 0.08, 0.08)
	rubber.roughness = 0.95
	wmesh.material_override = rubber
	wheel.add_child(wmesh)
	add_child(wheel)

func make_camera_current() -> void:
	_camera.make_current()

func set_driver(player: PlayerController) -> void:
	_driver = player
	if player != null:
		StreamManager.set_target(self)

func _physics_process(delta: float) -> void:
	if _driver == null:
		engine_force = 0.0
		brake = 2.0 # parking brake
		_steer = move_toward(_steer, 0.0, STEER_SPEED * delta)
		_apply_steering()
		return
	var accel := Input.get_axis("move_back", "move_forward")
	var forward_kmh := -linear_velocity.dot(global_transform.basis.z) * 3.6
	var drive_force := 0.0
	if accel > 0.0 and forward_kmh < MAX_SPEED_KMH:
		drive_force = ENGINE_FORCE * accel
	elif accel < 0.0:
		drive_force = -REVERSE_FORCE if forward_kmh < 5.0 else 0.0
	engine_force = drive_force
	brake = BRAKE_FORCE if Input.is_action_pressed("jump") else 0.0
	var steer_target := -Input.get_axis("move_left", "move_right") * MAX_STEER
	_steer = move_toward(_steer, steer_target, STEER_SPEED * delta)
	_apply_steering()

func _apply_steering() -> void:
	for wheel in get_children():
		if wheel is VehicleWheel3D and (wheel as VehicleWheel3D).use_as_steering:
			(wheel as VehicleWheel3D).steering = _steer
