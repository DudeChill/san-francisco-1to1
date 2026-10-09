extends Node
## Global signal bus. Lifecycle/cross-feature events only (< 15 events).
## Signals travel up; features connect, bus never calls into features.

signal tile_count_changed(loaded_tiles: int)
signal index_loaded(tiles: int)
signal tour_destination_changed(name: String)
signal player_mode_changed(mode: String)
