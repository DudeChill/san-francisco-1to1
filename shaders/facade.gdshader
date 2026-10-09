shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_back, diffuse_burley, specular_schlick_ggx;

// Shared across all tiles; StreamManager caches one instance per district and
// drives night_factor from TimeOfDay. UVs are worldspace (wrapped) from the
// pipeline, so windows keep their scale on any wall.
uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D emissive_tex : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float night_factor = 0.0;
uniform float emissive_boost = 2.4;
uniform float roughness_base : hint_range(0.0, 1.0) = 0.82;
uniform float spec_base : hint_range(0.0, 1.0) = 0.25;

void fragment() {
	vec4 alb = texture(albedo_tex, UV);
	ALBEDO = alb.rgb;
	ROUGHNESS = roughness_base;
	SPECULAR = spec_base;
	vec3 em = texture(emissive_tex, UV).rgb;
	EMISSION = em * night_factor * emissive_boost;
}
