extends Node
## TimeOfDay: sun/moon at SF latitude, PhysicalSkyMaterial, environment
## (SDFGI, SSAO, volumetric fog base), day/night factor for facade shader.

signal time_changed(hour: float)

const LATITUDE_DEG := 37.77
const NOON_ALTITUDE_DEG := 90.0 - LATITUDE_DEG # equinox solar noon

var hour := 17.4          # golden hour start
var time_scale := 0.0     # game-hours per real second; N key steps 1 h
var night_factor := 0.0   # 0 = day, 1 = full night

var _sun: DirectionalLight3D
var _moon: DirectionalLight3D
var _world_env: WorldEnvironment
var _sky_mat: PhysicalSkyMaterial

func _ready() -> void:
	var hour_env := OS.get_environment("SF_HOUR")
	if hour_env != "":
		hour = clampf(float(hour_env), 0.0, 24.0)
	_sky_mat = PhysicalSkyMaterial.new()
	var sky := Sky.new()
	sky.sky_material = _sky_mat
	sky.radiance_size = Sky.RADIANCE_SIZE_256

	var env := Environment.new()
	if OS.get_environment("SF_CLEAR_FOG") == "1":
		env.volumetric_fog_enabled = false
		env.fog_enabled = false
	if OS.get_environment("SF_LOWFI") == "1":
		env.sdfgi_enabled = false
		env.ssao_enabled = false
		env.glow_enabled = false
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.tonemap_mode = Environment.TONE_MAPPER_AGX
	env.tonemap_white = 6.0
	env.tonemap_exposure = 1.6
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.reflected_light_source = Environment.REFLECTION_SOURCE_SKY
	env.ssao_enabled = true
	env.ssao_intensity = 1.6
	env.sdfgi_enabled = true
	env.sdfgi_cascades = 6
	env.sdfgi_max_distance = 450.0
	env.sdfgi_bounce_feedback = 0.6
	env.volumetric_fog_enabled = true
	env.volumetric_fog_density = 0.004
	env.volumetric_fog_albedo = Color(0.92, 0.94, 1.0)
	env.volumetric_fog_emission = Color(0.15, 0.17, 0.22)
	env.volumetric_fog_anisotropy = 0.6
	env.volumetric_fog_length = 220.0
	env.volumetric_fog_ambient_inject = 0.6
	env.volumetric_fog_sky_affect = 0.2
	env.fog_light_color = Color(0.86, 0.89, 0.94)
	env.fog_density = 0.0012
	env.glow_enabled = true
	env.glow_intensity = 0.35
	env.glow_bloom = 0.05

	_world_env = WorldEnvironment.new()
	_world_env.environment = env
	add_child(_world_env)

	_sun = DirectionalLight3D.new()
	_sun.shadow_enabled = true
	_sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_4_SPLITS
	_sun.directional_shadow_blend_splits = true
	_sun.shadow_bias = 0.04
	_sun.shadow_normal_bias = 1.5
	_sun.light_energy = 1.3
	add_child(_sun)

	_moon = DirectionalLight3D.new()
	_moon.shadow_enabled = false
	_moon.light_energy = 0.0
	_moon.light_color = Color(0.62, 0.70, 0.95)
	add_child(_moon)

	_apply(true)

func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("time_forward"):
		hour = fmod(hour + 1.0, 24.0)
		_apply(false)
		get_viewport().set_input_as_handled()

func _process(delta: float) -> void:
	if time_scale != 0.0:
		hour = fmod(hour + time_scale * delta, 24.0)
		_apply(false)

func _apply(force_emit: bool) -> void:
	# Equinox model: sunrise 06:00, sunset 18:00. t in [0, PI] across the day.
	var t := (hour - 6.0) / 12.0 * PI
	var el_deg := sin(t) * NOON_ALTITUDE_DEG
	var el := deg_to_rad(el_deg)
	var sun_dir := Vector3(cos(t) * cos(el), sin(el), sin(t) * cos(el))

	var sun_up := el_deg > -6.0
	_sun.visible = sun_up
	if sun_up:
		_sun.look_at_from_position(sun_dir * 600.0, Vector3.ZERO, Vector3.UP)
		var dayness := clampf(remap(el_deg, -6.0, 10.0, 0.0, 1.0), 0.0, 1.0)
		_sun.light_energy = lerpf(0.05, 1.35, dayness)
		_sun.light_color = Color(1.0, 0.62, 0.36).lerp(Color(1.0, 0.97, 0.92), dayness)
		_sun.rotation.z = 0.0

	_moon.visible = not sun_up
	if _moon.visible:
		_moon.look_at_from_position(-sun_dir * 600.0, Vector3.ZERO, Vector3.UP)
		_moon.light_energy = clampf(remap(el_deg, -12.0, -4.0, 0.0, 0.25), 0.0, 0.25)

	night_factor = clampf(remap(el_deg, 8.0, -6.0, 0.0, 1.0), 0.0, 1.0)

	_sky_mat.energy_multiplier = lerpf(1.0, 0.03, night_factor)
	_sky_mat.ground_color = Color(0.06, 0.06, 0.08).lerp(Color(0.12, 0.11, 0.09), 1.0 - night_factor)
	var env := _world_env.environment
	env.ambient_light_energy = lerpf(1.0, 0.35, night_factor)
	env.volumetric_fog_density = lerpf(0.004, 0.0015, night_factor)
	if is_equal_approx(time_scale, 0.0) and not force_emit:
		pass # static hour; still emit for listeners below
	time_changed.emit(hour)
