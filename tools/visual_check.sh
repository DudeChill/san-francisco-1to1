#!/usr/bin/env bash
# Visual verification on the shared desktop (:98, 1600x900, software Vulkan).
# Deterministic: each shot is its own run with env-var tour stop + hour.
# Usage: bash tools/visual_check.sh <out_dir>
set -u
OUT=${1:-/tmp/sf_shots}
mkdir -p "$OUT"
DESKTOP="python3 /home/alexg/projects/agent-desktop/desktop.py"

shoot() { # name stop hour pitch
  local name="$1" stop="$2" hour="$3" pitch="${4:-}"
  SF_CLEAR_FOG=1 SF_LOWFI=1 SF_TOUR_STOP="$stop" SF_HOUR="$hour" SF_TOUR_PITCH="$pitch" \
    $DESKTOP launch godot --path /home/alexg/projects/sf --resolution 1600x900
  sleep 150  # tile streaming + software-Vulkan warmup
  $DESKTOP click 800 450
  sleep 2
  $DESKTOP screenshot "$OUT/$name.png"
  pkill -f "godot --path /home/alexg/projects/sf" || true
  sleep 2
}

shoot 01_spawn_ferry_building 0 12.0 ""
shoot 02_downtown_salesforce 1 12.0 -0.85
shoot 03_golden_gate_bridge 14 12.0 -0.6
shoot 04_painted_ladies 6 12.0 -0.85
shoot 05_night_downtown 1 21.5 -0.85
echo "shots in $OUT"
