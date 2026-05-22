# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AzurLaneAutoScript (ALAS / AzurPilot) is an automation framework for the mobile game Azur Lane. It controls Android emulators via ADB/uiautomator2, takes screenshots, recognizes UI elements through image matching and OCR, and executes game tasks automatically. Supports CN/EN/JP/TW game servers with server-specific assets. Licensed under GPL-3.0.

**Design constraints**: Designed for 7×24h continuous operation. Real Android devices are not supported (black screen/freeze under long runs, screenshot compression, OCR model migration issues). Fixed 1280×720 resolution only — best balance between clarity and screenshot latency, non-standard aspect ratios have no unified standard.

## Commands

This project uses **uv** for Python dependency management. Linux/macOS entry points bootstrap a local `.venv` automatically.

### Environment Setup
```bash
uv venv                                        # Create virtual environment
uv pip sync requirements-linux.txt             # Linux
uv pip sync requirements.txt                   # Windows
```

### Running the Application
```bash
python gui.py           # Start WebUI server; bootstraps .venv with uv on Linux/macOS
python alas.py          # Run scheduler directly; bootstraps .venv with uv on Linux/macOS
```

### Linting
```bash
# Python (CI uses ruff with permissive settings - fatal syntax errors and undefined names only)
uv run ruff check . --select E9,F63,F7,F82 --ignore F821,F722

# Webapp (Electron/Vue)
cd webapp && pnpm lint
cd webapp && pnpm typecheck
```

### Building the Webapp
```bash
cd webapp && pnpm install
cd webapp && pnpm build && pnpm compile
```

### Config Generation (required after modifying config YAML files)
```bash
uv run -m module.config.config_updater
```
This regenerates `args.json`, `menu.json`, `config_generated.py`, `template.json`, and `i18n/*.json`.

### Asset Management
```bash
uv run -m dev_tools.button_extract    # Extract button definitions from screenshots
```

## Architecture

### Core Flow
1. `gui.py` starts the web server and manages config instances
2. `alas.py` (`AzurLaneAutoScript`) is the task runner — loads config, initializes device, dispatches tasks to handlers
3. Each task handler (e.g., `module/research/research.py`) inherits from base classes, uses the device for screenshots, UI detection, and input
4. `module/device/device.py` wraps ADB/uiautomator2 for screenshot capture and touch input
5. UI navigation (`module/ui/ui.py`) handles page detection and routing between game screens
6. Template matching (`module/base/template.py`) and OCR (`module/ocr/`) identify game UI elements

### Entry Points
- **`alas.py`** — Core scheduler. `AzurLaneAutoScript.loop()` runs an infinite scheduling loop: pick next task by priority, dispatch to method, handle errors, sleep until next task.
- **`gui.py`** — WebUI backend (PyWebIO + Starlette + uvicorn). Each ALAS config instance runs in its own `multiprocessing.Process`.
- **`mcp_server_sse.py`** — MCP server exposing 18 tools over SSE for external AI assistant integration.

### Module Layer Structure (`module/`)

**Base layer** (`module/base/`):
- `ModuleBase` (`base.py`) — Root class for all game logic. Composes `AzurLaneConfig` + `Device`. Provides `appear()`, `appear_then_click()`, `loop()`, image utilities.
- `Button` (`button.py`) — UI element with bounding box, color, click area, template image. Supports server-specific assets.
- `Template` (`template.py`) — Template matching against screenshots.
- `Resource` (`resource.py`) — Base class tracking all Button/Template instances, supports cache release.

**Device layer** (`module/device/`):
- `Device` (`device.py`) — Multiple inheritance: `Screenshot + Control + AppControl + Input`. Unified interface for emulator interaction.
- `module/device/method/` — Multiple screenshot/input backends: adb, minitouch, maatouch, droidcast, uiautomator2, nemu_ipc, ldopengl, hermit, wsa, ascreencap.
- `module/device/platform/` — Emulator management (LDPlayer, BlueStacks, NoxPlayer, MuMu, etc.).

**Config system** (`module/config/`):
- `config/template.json` defines the schema and defaults for all config options.
- `module/config/config_generated.py` is auto-generated from `template.json` — provides IDE autocomplete.
- `module/config/config_updater.py` regenerates `config_generated.py` when `template.json` changes.
- `module/config/config.py` (`AzurLaneConfig`) loads user config from `config/{config_name}.json` and merges with the template.
- User config files are stored in `config/{config_name}.json` (e.g., `config/alas.json`).
- 3-layer YAML pipeline for GUI: `task.yaml` (task→group mapping) → `argument.yaml` (group→argument definitions) → `override.yaml` (value/display patches).
- `config_updater.py` generates: `args.json`, `menu.json`, `config_generated.py`, `template.json`, `i18n/*.json`.
- Config path format: `<Task>.<Group>.<Argument>` (e.g., `Main.Campaign.Name`).
- Access config: `self.config.Group_Argument` (underscore-separated).

**UI navigation** (`module/ui/`):
- `Page` (`page.py`) — Graph-based navigation. Each page has a `check_button` and `links` dict. Uses A* pathfinding for shortest navigation.
- `UI` (`ui.py`) — `ui_goto(page)`, `ui_page_appear()`, `ui_ensure()`, `ui_back()`.

**Game logic modules** — Each feature has its own subdirectory (combat, campaign, commission, research, dorm, guild, shop, etc.). Each module has its own `assets.py` defining Button/Template objects. Task modules contain a `run()` method.

**Campaign data** (`campaign/`) — Map definition files dynamically loaded via `importlib.import_module()`. Organized by event/date.

**Assets** (`assets/`) — PNG images organized by server (cn/en/jp/tw) then by module. Named after Button constants (e.g., `BATTLE_PREPARATION.BUTTON.png`).

### Class Hierarchy
```
ModuleBase ← AzurLaneConfig + Device
  ├── UI ← InfoHandler (page navigation)
  ├── Combat ← Level + HPBalancer + Retirement + SubmarineCall + CombatAuto + CombatManual
  ├── CampaignBase ← CampaignUI + Map + AutoSearchCombat
  └── LoginHandler ← UI (app restart/login flow)

AzurLaneAutoScript (alas.py) ← AzurLaneConfig + Device + ServerChecker
  └── dispatches to task modules via lazy imports

Device ← Screenshot + Control + AppControl + Input
```

### Task Scheduling
Priority order: `Restart > OpsiCrossMonth > Commission > Tactical > Research > Exercise > Dorm > Meowfficer > Guild > Gacha > Reward > ShopFrequent > ... > Main > Main2 > Main3 > GemsFarming`

3 consecutive failures of the same task triggers `RequestHumanTakeover`. Config hot-reloads between tasks via `ConfigWatcher`.

## Core Design Rules

### State-Loop Pattern (mandatory)
All game interaction must use continuous screenshot-and-check loops. **Never** use click-wait-sleep patterns:

```python
def some_function(self, skip_first_screenshot=True):
    while 1:
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            self.device.screenshot()

        # End — use appear() for exit conditions, no interval
        if self.appear(END_CONDITION):
            break

        # Click — use interval to prevent rapid re-clicking (2-5 seconds)
        if self.appear_then_click(BUTTON_A, interval=2):
            continue
        if self.appear_then_click(BUTTON_B, interval=3):
            continue
```

Rules:
- `skip_first_screenshot=True` reuses the screenshot from the previous state loop (avoids redundant capture).
- The `interval` parameter prevents rapid re-clicking (typically 2-5 seconds). Do not set interval on exit conditions.
- Do not add `sleep()` inside state loops.
- Do not use negative conditions for loop control.
- Do not use `appear_then_click()` as a loop exit condition — use `appear()` for exits.
- Do not nest state loops — flatten into the parent loop.
- `handle_*()` methods return `bool`: `True` means "action taken, need new screenshot."

### Dead Loop Detection
- `GameStuckError`: No actionable screenshot for 1 minute (5 min during combat/startup).
- `GameTooManyClickError`: Last 15 operations have one button clicked ≥12 times, or two buttons each ≥6 times.

### Exception Hierarchy (`module/exception.py`)
- **Normal campaign end**: `CampaignEnd`, `OilExhausted`
- **Map navigation errors**: `MapDetectionError`, `MapWalkError`, `MapEnemyMoved`
- **Game state errors** (trigger restart): `GameStuckError`, `GameBugError`, `GameTooManyClickError`
- **Connection/page errors**: `GameNotRunningError`, `GamePageUnknownError`
- **Developer error**: `ScriptError`
- **Unrecoverable**: `RequestHumanTakeover` — requires manual intervention

### Resolution
Fixed 1280×720 for all image recognition. All screenshots and assets must match this resolution.

### Debugging a Button
```python
# Run with: uv run debug_button.py
az = SomeModule('alas', task='SomeTask')
az.image_file = r'path/to/screenshot.png'
print(az.appear(SOME_BUTTON))
```

### Debugging for Other Servers
```python
import module.config.server as server
server.server = 'en'  # Set before importing any Alas modules
```

## Config System Workflow

To add/modify a GUI option:
1. Define in `module/config/argument/argument.yaml` (type, value, option, validate, display).
2. Ensure the group is linked to the correct task in `module/config/argument/task.yaml`.
3. Optionally override values/visibility in `module/config/argument/override.yaml`.
4. Run `uv run -m module.config.config_updater` to regenerate all derived files.
5. **Never** manually edit `args.json`, `menu.json`, `config_generated.py`, `template.json`, or `i18n/*.json` — they are auto-generated.

## Common Development Tasks

### Adding a New Event
1. Create a new directory under `campaign/` (e.g., `event_YYYYMMDD_cn`)
2. Add map YAML files in the new directory
3. Update the event table in `campaign/Readme.md`
4. Run `uv run -m module.config.config_updater`
5. Add corresponding template images in `assets/cn/event/`

### Adding a New Feature
1. Create a new module directory under `module/`
2. Create a handler class with a `run()` method
3. Add a corresponding task method in `alas.py`'s `AzurLaneAutoScript` class
4. Add config entries in `config/template.json`
5. Run `uv run -m module.config.config_updater`
6. Add UI template images in `assets/`

### Running a Specific Task
Task methods are defined on `AzurLaneAutoScript` in `alas.py`. Common tasks: `research`, `commission`, `tactical`, `dorm`, `meowfficer`, `guild`, `reward`, `awaken`, `shop_frequent`. Each method instantiates the handler from `module/` and calls its `run()` method.

### Dev Tools
```bash
uv run -m deploy.installer              # Run ALAS installer
uv run dev_tools/map_extractor.py       # Extract map data from screenshots
uv run dev_tools/campaign_swipe.py      # Campaign swipe test tool
uv run dev_tools/item_statistics.py     # Item statistics extraction
```

## Key Directory Reference

| Directory | Purpose |
|---|---|
| `alas.py` | Main entry — task scheduler and runner (`AzurLaneAutoScript` class) |
| `gui.py` | Web UI launcher (uvicorn server with PyWebIO) |
| `module/` | Core logic modules — each subdirectory maps to a game feature |
| `module/base/` | Base utilities: button handling, template matching, decorators, retry logic |
| `module/device/` | Device connection, screenshot capture, input simulation (ADB-based) |
| `module/config/` | Config system — JSON/YAML-based configuration management |
| `module/handler/` | Game handlers: login, auto-search, enemy detection, fast-forward |
| `module/campaign/` | Campaign (battle) execution logic |
| `module/ui/` | UI navigation: page detection, button routing, navbar |
| `module/os/` | Operation Siren — map, camera, world map, fleet management |
| `module/os_combat/` | Operation Siren combat logic |
| `module/os_handler/` | Operation Siren event handlers |
| `module/os_ash/` | Operation Siren ash/beacon system |
| `module/os_shop/` | Operation Siren shop |
| `campaign/` | Event/map data files — each event has its own subdirectory with YAML map definitions |
| `assets/` | Template images for UI recognition, organized by server (cn/en/jp/tw) and feature |
| `config/` | Config templates (`template.json`, `deploy.template.yaml`, etc.) |
| `deploy/` | Install scripts, Docker setup, platform-specific deployment (AidLux, Windows) |
| `webapp/` | Electron + Vue 3 desktop application |
| `dev_tools/` | Dev tools: map extractor, campaign swipe tool, item statistics |
| `bin/` | Binary tools: DroidCast, scrcpy, ascreencap, MaaTouch, cnocr models |
| `submodule/` | External bridges: AlasFpyBridge, AlasMaaBridge |

## Testing
No formal Python test suite exists. The webapp has a basic Playwright test (`webapp/tests/app.spec.js`). Testing is done by running tasks against real emulator instances.

## Notes
- The `run()` method in `alas.py` raises exceptions instead of calling `exit(1)`, allowing the scheduler loop to catch and retry
- Different server regions (CN/EN/JP/TW) use different template images under `assets/`
- `bin/` contains screenshot capture tools; default method varies by platform
- Campaign map files in `campaign/` are YAML format defining grid layouts, enemy positions, and spawn points
- Operation Siren (大世界) is the most complex feature, spanning `module/os/`, `module/os_combat/`, `module/os_handler/`, `module/os_ash/`, and `module/os_shop/`

## Key Conventions

- **Comments**: Use Google docstring style. Include `Pages:` annotations for game UI state (e.g., `Pages: in: page_meowfficer, out: MEOWFFICER_BUY`). Comments should be in Simplified Chinese. Aim for comments occupying 1/3–1/2 of a function, one function per screen, one file ≤500 lines.
- **Logging**: Use `logger.hr(title, level)` for section headers (level 0=script start, 1=feature start, 2=phase start, 3=sub-phase), `logger.attr(name, value)` for attributes. Avoid overusing emphasis — if everything is emphasized, nothing is.
- **Naming**: `point` = (x,y) screen coordinate, `area` = (x1,y1,x2,y2) bounding box, `location` = (x,y) grid coordinate, `node` = "E3" string grid reference.
- **Module independence**: All modules can run standalone, not dependent on GUI or user config. Each module typically has only one method that reads user config.
- **Performance**: ~99% of runtime is waiting for emulator screenshots (~350ms). Image processing is ~2.5ms. Map detection/OCR ~100-180ms. Don't over-optimize Python code.
- **Exception handling**: Exceptions are only caught at the top level. On catch, logs and recent screenshots are saved to a separate folder. User-identifying info is scrubbed.

## Common API Patterns

### UI Components
```python
# Switch — toggle between states
MODE_SWITCH = Switch('Mode_switch_1')
MODE_SWITCH.add_status('normal', SWITCH_1_NORMAL, sleep=STAGE_SHOWN_WAIT)
MODE_SWITCH.add_status('hard', SWITCH_1_HARD, sleep=STAGE_SHOWN_WAIT)

# Scroll — game scrollbar
COMMISSION_SCROLL = Scroll(COMMISSION_SCROLL_AREA, color=(247, 211, 66), name='COMMISSION_SCROLL')

# NavBar — tab navigation
navbar_grids = ButtonGrid(origin=(21, 126), delta=(0, 98), button_shape=(60, 80), grid_shape=(1, 5))
GACHA = Navbar(grids=navbar_grids, active_color=(247, 255, 173), inactive_color=(140, 162, 181))

# Page — game screen with navigation links
page_reward = Page(REWARD_CHECK)
page_reward.link(button=REWARD_GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_REWARD, destination=page_reward)
```

### UI Navigation Methods
- `ui_click()` — click a button and wait for next screen
- `ui_get_current_page()` — detect which page we're on
- `ui_goto(page)` — navigate along shortest path to target page
- `ui_ensure(page)` — `ui_get_current_page()` + `ui_goto()`
- `ui_ensure_index()` — paginate through map chapters
- `ui_goto_main()` — navigate to main screen
- `ui_back()` — click back arrow
- `ui_additional()` — handle popups/dialogs

### Button & Template Classes
- `Button` — UI element recognition via average color (`appear_on()`) or template matching (`match()`). `button` property generates a random click point within the area.
- `ButtonGrid(origin, delta, button_shape, grid_shape)` — generate a 2D array of Buttons.
- `Template` — template matching. Must be prefixed with `TEMPLATE_`. Methods: `match()`, `match_result()`, `match_multi()`.
- To add a new Button: screenshot at 1280×720, copy to `assets/`, crop in Photoshop, run `uv run -m dev_tools.button_extract`.

### OCR Classes (`module/ocr/`)
- `Ocr` — general text recognition
- `Digit` — recognize numbers, returns `int`
- `DigitCounter` — recognize counters like `14/15`
- `Duration` — recognize durations like `08:00:00`
- Pre-trained models: `cnocr` (default, CN+EN), `azur_lane` (game digits/letters), `jp` (Japanese)

### Decorators (`module/base/decorator.py`)
- `@Config.when(SERVER='en')` — conditionally dispatch method based on config (e.g., server-specific behavior). Define a `@Config.when(SERVER=None)` fallback for other servers.
- `@cached_property` — compute once, cache result.
- `@timer` — print function execution time.
- `@function_drop(rate=0.5, default=None)` — randomly skip function execution.

### Utility Functions (`module/base/utils.py`)
- `random_normal_distribution_int(a, b, n=3)` — random int in [a, b) with normal distribution
- `random_rectangle_point(area)` — random point within area (2D normal distribution)
- `crop(image, area)` — crop image
- `get_color(image, area)` — average color of region
- `color_similarity(color1, color2)` / `color_similar(color1, color2, threshold)` — color comparison
- `color_bar_percentage(image, area, prev_color, reverse, starter, threshold)` — progress bar percentage

### Map Symbols
- `++` land (impassable), `--` ocean, `SP` fleet spawn, `ME` enemy possible, `MB` boss possible, `MM` mystery enemy, `MA` ammo pickup, `MS` Siren/elite spawn

## Python Dependencies
All dependency management uses **uv**. Direct dependencies are declared in `requirements-in.txt`, compiled via `uv pip compile` into platform-specific lockfiles (`requirements.txt`, `requirements-linux.txt`, `requirements-macos.txt`). Sync with `uv pip sync requirements-<platform>.txt`, or run the Linux/macOS entry points directly and let them bootstrap `.venv`.

## Webapp (Electron)
Separate frontend in `webapp/` — Vue 3 + Ant Design Vue + Electron. Uses pnpm, Vite, electron-builder. Lint with `pnpm lint`, typecheck with `pnpm typecheck`, test with `pnpm test`.

## CI
GitHub Actions uses `uv` for dependency management: `uv venv` + `uv pip sync`. Runs: ruff lint, `button_extract.py`, `config_updater.py` (checks for uncommitted diffs), Docker publish, upstream sync.
