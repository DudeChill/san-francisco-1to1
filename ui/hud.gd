class_name Hud
extends CanvasLayer
## Minimal telemetry + help overlay built in code.

var _info: Label
var _toast: Label
var _help: Label
var _accum := 0.0

func _ready() -> void:
	_info = _make_label(Vector2(16, 12))
	_help = _make_label(Vector2(16, 0))
	_help.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_LEFT)
	_help.position = Vector2(16, -34)
	_help.text = "WASD move · Shift sprint · Space jump / fly-up · Ctrl fly-down · F fly · E vehicle · T tour · N +1h · Esc mouse"
	_toast = _make_label(Vector2(0, 64))
	_toast.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	_toast.text = ""
	SignalBus.tour_destination_changed.connect(func(name: String): _flash(name))
	SignalBus.player_mode_changed.connect(func(mode: String): _flash(mode.to_upper()))

func _make_label(pos: Vector2) -> Label:
	var label := Label.new()
	label.position = pos
	label.add_theme_font_size_override("font_size", 16)
	label.add_theme_color_override("font_color", Color(1, 1, 1, 0.92))
	label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
	label.add_theme_constant_override("outline_size", 5)
	add_child(label)
	return label

func _flash(text: String) -> void:
	_toast.text = text
	var tween := create_tween()
	tween.tween_interval(2.2)
	tween.tween_property(_toast, "modulate:a", 0.0, 0.6)
	tween.tween_callback(func(): _toast.modulate.a = 1.0; _toast.text = "")

func _process(delta: float) -> void:
	_accum += delta
	if _accum < 0.25:
		return
	_accum = 0.0
	var p := StreamManager.get_target()
	var pos_text := "—"
	if p != null:
		var gp := p.global_position
		pos_text = "%.0f, %.0f, %.0f" % [gp.x, gp.y, gp.z]
	var hour := int(floor(TimeOfDay.hour))
	var minute := int(round(fmod(TimeOfDay.hour, 1.0) * 60.0)) % 60
	_info.text = "SF 1:1  ·  pos %s  ·  tiles %d  ·  %d fps  ·  %02d:%02d  ·  %s" % [
		pos_text, StreamManager.loaded_count, Engine.get_frames_per_second(),
		hour, minute, "NIGHT" if TimeOfDay.night_factor > 0.5 else "DAY"]
