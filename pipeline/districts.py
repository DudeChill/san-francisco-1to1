"""Approximate real SF district polygons (lon/lat, WGS84) + fog belt polygons.
Boundaries are hand-approximated from real geography; used for facade material
classification, fog tiles, and diagnostics. Fallback for any land not covered:
'residential'."""

# Ordered: earlier entries win when polygons overlap.
DISTRICT_POLYS = [
    ("chinatown",      [(-122.4090, 37.7925), (-122.4030, 37.7935), (-122.4030, 37.7985), (-122.4095, 37.7975)]),
    ("financial",      [(-122.4055, 37.7910), (-122.3955, 37.7935), (-122.3960, 37.7995), (-122.4055, 37.7975)]),
    ("north_beach",    [(-122.4140, 37.7955), (-122.4040, 37.7960), (-122.4030, 37.8065), (-122.4130, 37.8060)]),
    ("nob_hill",       [(-122.4210, 37.7880), (-122.4090, 37.7885), (-122.4090, 37.7965), (-122.4210, 37.7960)]),
    ("pacific_heights",[(-122.4470, 37.8000), (-122.4210, 37.8000), (-122.4210, 37.7890), (-122.4470, 37.7890)]),
    ("presidio",       [(-122.5060, 37.8215), (-122.4470, 37.8215), (-122.4470, 37.7925), (-122.5060, 37.7925)]),
    ("marina",         [(-122.4470, 37.8100), (-122.4330, 37.8100), (-122.4330, 37.8000), (-122.4470, 37.8000)]),
    ("richmond",       [(-122.5060, 37.8060), (-122.4560, 37.8060), (-122.4560, 37.7800), (-122.5060, 37.7800)]),
    ("sunset",         [(-122.5140, 37.7800), (-122.4560, 37.7800), (-122.4560, 37.7420), (-122.5140, 37.7420)]),
    ("twin_peaks",     [(-122.4580, 37.7660), (-122.4400, 37.7660), (-122.4400, 37.7460), (-122.4580, 37.7460)]),
    ("soma",           [(-122.4160, 37.7900), (-122.3930, 37.7905), (-122.3870, 37.7830), (-122.3860, 37.7600), (-122.4010, 37.7545), (-122.4130, 37.7560), (-122.4160, 37.7760)]),
    ("potrero_hill",   [(-122.4100, 37.7700), (-122.3960, 37.7700), (-122.3940, 37.7570), (-122.4090, 37.7560)]),
    ("mission",        [(-122.4240, 37.7700), (-122.4060, 37.7695), (-122.4050, 37.7560), (-122.4010, 37.7500), (-122.4240, 37.7480)]),
    ("castro",         [(-122.4370, 37.7685), (-122.4240, 37.7690), (-122.4240, 37.7540), (-122.4370, 37.7530)]),
    ("haight",         [(-122.4480, 37.7730), (-122.4330, 37.7730), (-122.4330, 37.7640), (-122.4480, 37.7640)]),
    ("western_addition",[(-122.4400, 37.7890), (-122.4240, 37.7890), (-122.4240, 37.7730), (-122.4400, 37.7730)]),
    ("bayview",        [(-122.4200, 37.7500), (-122.3860, 37.7520), (-122.3860, 37.7090), (-122.4230, 37.7090)]),
]
DEFAULT_DISTRICT = "residential"

# Fog belt: west side + Presidio + Twin Peaks saddle + Ocean Beach edge.
FOG_POLYS = [
    [(-122.5140, 37.8320), (-122.4470, 37.8320), (-122.4470, 37.7420), (-122.5140, 37.7420)],  # west strip: Richmond+Sunset+Presidio+OB
    [(-122.4580, 37.7660), (-122.4400, 37.7660), (-122.4400, 37.7440), (-122.4580, 37.7440)],  # Twin Peaks saddle
]

FACADE_STYLE = {
    "financial": "glass",
    "soma": "glass_loft",
    "chinatown": "brick_red",
    "north_beach": "brick",
    "nob_hill": "stucco_classic",
    "pacific_heights": "victorian",
    "presidio": "plain",
    "marina": "deco_pastel",
    "richmond": "stucco",
    "sunset": "stucco_mid",
    "twin_peaks": "stucco",
    "mission": "stucco_warm",
    "castro": "victorian_color",
    "haight": "victorian_color",
    "western_addition": "victorian",
    "bayview": "stucco_warm",
    "residential": "stucco",
}

DISTRICT_ROOF_TINT = {
    "financial": [0.42, 0.43, 0.46],
    "soma": [0.45, 0.44, 0.43],
    "chinatown": [0.55, 0.28, 0.24],
    "north_beach": [0.52, 0.30, 0.26],
    "nob_hill": [0.40, 0.35, 0.33],
    "pacific_heights": [0.45, 0.40, 0.37],
    "presidio": [0.60, 0.60, 0.58],
    "marina": [0.50, 0.47, 0.44],
    "richmond": [0.42, 0.40, 0.38],
    "sunset": [0.40, 0.38, 0.36],
    "twin_peaks": [0.44, 0.42, 0.40],
    "mission": [0.55, 0.42, 0.34],
    "castro": [0.48, 0.38, 0.33],
    "haight": [0.50, 0.40, 0.34],
    "western_addition": [0.46, 0.38, 0.33],
    "potrero_hill": [0.48, 0.42, 0.36],
    "bayview": [0.52, 0.44, 0.36],
    "residential": [0.44, 0.41, 0.38],
}

_all = [n for n, _ in DISTRICT_POLYS] + [DEFAULT_DISTRICT]
assert len(set(_all)) == len(_all)
