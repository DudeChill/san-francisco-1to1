class_name CableCar
extends Node3D
## Cable car riding a Path3D at ~15 km/h (4.2 m/s), looping end to end.

const SPEED := 4.2

var follow: PathFollow3D
var _path: Path3D
var _bell: AudioStreamPlayer3D = null

func setup(points: PackedVector3Array) -> void:
	_path = Path3D.new()
	var curve := Curve3D.new()
	for p in points:
		curve.add_point(p)
	_path.curve = curve
	add_child(_path)

	follow = PathFollow3D.new()
	follow.loop = true
	follow.rotation_mode = PathFollow3D.ROTATION_ORIENTED
	follow.cubic_interp = false
	_path.add_child(follow)

	var cabin := MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = Vector3(2.4, 3.0, 6.4)
	cabin.mesh = box
	cabin.position = Vector3(0, 1.9, 0)
	var paint := StandardMaterial3D.new()
	paint.albedo_color = Color(0.45, 0.08, 0.10)
	paint.roughness = 0.6
	cabin.material_override = paint
	follow.add_child(cabin)

	var roof := MeshInstance3D.new()
	var rbox := BoxMesh.new()
	rbox.size = Vector3(2.6, 0.25, 6.7)
	roof.mesh = rbox
	roof.position = Vector3(0, 3.5, 0)
	var cream := StandardMaterial3D.new()
	cream.albedo_color = Color(0.93, 0.88, 0.72)
	roof.material_override = cream
	follow.add_child(roof)

	for grip_x in [-1.0, 1.0]:
		var pole := MeshInstance3D.new()
		var pm := BoxMesh.new()
		pm.size = Vector3(0.12, 0.9, 0.12)
		pole.mesh = pm
		pole.position = Vector3(grip_x, 3.9, 0)
		pole.material_override = cream
		follow.add_child(pole)

	if ResourceLoader.exists("res://audio/bell.wav"):
		_bell = AudioStreamPlayer3D.new()
		_bell.stream = load("res://audio/bell.wav")
		_bell.unit_size = 30.0
		follow.add_child(_bell)

func _process(delta: float) -> void:
	if follow == null:
		return
	var length := _path.curve.get_baked_length()
	if length <= 0.0:
		return
	follow.progress = fmod(follow.progress + SPEED * delta, length)
	if _bell != null and not _bell.playing and randf() < delta * 0.05:
		_bell.play()
