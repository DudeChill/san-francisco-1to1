shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_back, diffuse_burley, specular_schlick_ggx;

uniform vec4 shallow_color : source_color = vec4(0.19, 0.44, 0.47, 0.85);
uniform vec4 deep_color : source_color = vec4(0.02, 0.10, 0.17, 1.0);
uniform float wave_height = 0.18;
uniform float wave_scale = 0.09;
uniform float normal_strength : hint_range(0.0, 1.0) = 0.6;

varying vec3 world_pos;
varying float wave_h;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	float w = sin(world_pos.x * wave_scale + TIME * 1.05) * 0.62
			+ sin(world_pos.z * wave_scale * 1.31 + TIME * 0.85) * 0.38;
	wave_h = w;
	VERTEX.y += w * wave_height;
}

void fragment() {
	// Screen-space derivative normals from the displaced surface.
	vec3 wn = normalize(cross(dFdx(world_pos), dFdy(world_pos)));
	if (dot(wn, NORMAL) < 0.0) {
		wn = -wn;
	}
	NORMAL = normalize(mix(NORMAL, (VIEW_MATRIX * vec4(wn, 0.0)).xyz, normal_strength));
	vec3 view_dir = normalize(-VERTEX);
	float fres = pow(1.0 - clamp(dot(view_dir, NORMAL), 0.0, 1.0), 3.0);
	ALBEDO = mix(deep_color.rgb, shallow_color.rgb, 0.30 + 0.35 * fres);
	ALPHA = mix(0.80, 0.97, fres);
	ROUGHNESS = mix(0.03, 0.14, fres);
	SPECULAR = 0.9;
	METALLIC = 0.0;
}
