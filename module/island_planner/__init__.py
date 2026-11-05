"""AzurPilot additions on top of the generated ALAS island data."""

from module.island_planner import data as _data
from module.island_planner.winter_extension import apply_winter_extension as _apply_winter_extension


_apply_winter_extension(_data)
