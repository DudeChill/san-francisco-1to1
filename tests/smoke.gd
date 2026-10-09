extends SceneTree
## Headless smoke gate: boots the project (autoloads + world_boot), streams
## tiles for ~6 s, then asserts the pipeline↔runtime contract end to end.
## Run: godot --headless --path . --script tests/smoke.gd

var _frames := 0
var _ran_checks := false

func _initialize() -> void:
	print("SMOKE: booting")
	# --script replaces the main scene; instantiate the world manually.
	var world: Node = (load("res://features/world/world_boot.tscn") as PackedScene).instantiate()
	world.name = "World"
	root.add_child(world)

func _process(_delta: float) -> bool:
	_frames += 1
	if _frames < 360:
		return false
	if _ran_checks:
		return true
	_ran_checks = true
	var failures: Array[String] = []
	var sm := root.get_node_or_null("/root/StreamManager")
	var tod := root.get_node_or_null("/root/TimeOfDay")
	if sm == null:
		failures.append("StreamManager autoload missing")
		_finish(failures)
		return true
	if not sm.index_loaded:
		failures.append("index.json not loaded")
	elif int(sm.index.get("tiles", []).size()) < 1:
		failures.append("index lists zero tiles")
	if int(sm.loaded_count) < 1:
		failures.append("no tiles loaded after 6 s (loaded_count=%d)" % int(sm.loaded_count))
	var player := root.get_node_or_null("World").find_children("*", "CharacterBody3D", true, false)
	if player.is_empty():
		failures.append("player CharacterBody3D not spawned")
	else:
		var body := player[0] as Node3D
		var y := body.global_position.y
		if y < -50.0:
			failures.append("player fell through terrain (y=%.1f)" % y)
	if tod == null:
		failures.append("TimeOfDay autoload missing")
	print("SMOKE: tiles loaded=%d index=%s" % [int(sm.loaded_count), str(sm.index_loaded)])
	_finish(failures)
	return true

func _finish(failures: Array[String]) -> void:
	if failures.is_empty():
		print("SMOKE: PASS")
		quit(0)
	else:
		for f in failures:
			printerr("SMOKE FAIL: " + f)
		quit(1)
