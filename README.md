# MEA-Editor

GUI and library to create and modify MEA (Multi-Electrode Arrays).

Arrays are saved in a native JSON format (`specification: "mea_editor"`, version `1.11`). Optional exports produce:

- a [probeinterface](https://probeinterface.readthedocs.io/) JSON for [SpikeInterface](https://spikeinterface.readthedocs.io/)
- a full array XLSX (electrodes, pads, orientation markers, attribute schema)

**Multi-platform:** Windows, macOS, Linux.

The package is on PyPI as `mea-editor`.

## Installation (PyPI)

1. Install [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows)
2. Create a virtual environment: `uv venv si_env --python 3.12`
3. Activate it: `source si_env/bin/activate` (macOS/Linux) or `si_env\Scripts\activate` (Windows)
4. Install the library: `uv pip install mea-editor`

## Installation from source

```bash
uv venv si_env --python 3.12
source si_env/bin/activate          # Windows: si_env\Scripts\activate
uv pip install -e ".[dev]"
```

Run tests with `pytest` (set `QT_QPA_PLATFORM=offscreen` on headless Linux).

## Run application

1. Activate the virtual environment
2. Run `mea-editor`

From a source checkout you can also run `python run.py` from the project root.

## New array

**File > New array...** builds a regular electrode grid and a rectangular pad frame:

- **Pitch** (electrodes): center-to-center distance between adjacent electrodes
- **Spacing** (pads): center-to-center distance between adjacent pads, along each ring and between rings — the same meaning as electrode pitch
- Pad **Rows**: number of concentric rectangular rings around the electrode cluster

Pitch and spacing are used only at creation. After that, only the computed `(x, y)` coordinates are kept.

## Mapping views

The scene is shared. Two cameras sit side by side:

- **Electrodes** (left): fitted to the electrode cluster
- **Pads** (right): fitted to the pad frame

Each view keeps its own zoom and pan. Contacts are not dragged with the mouse. Move a contact with **X/Y** (one item) or **dX/dY** (the selection); the linked counterpart stays put. **Fit View** (`Ctrl+0`) fits both cameras.

## Identifiers

Each electrode stores built-in identifiers:

- **Potentiostat ID** (integer; uniqueness is per shank)
- **INTAN ID** (e.g. `A-003`)
- **Manufacturer ID** (optional unique contact label)
- **Shank ID**

INTAN uniqueness follows the SpikeInterface channel ID: `A-003`, `A003` and `3` are the same channel. Port-channel numbers must be 0–31 (`A-032` is invalid; use `B-000`). Empty Manufacturer IDs are allowed only when every electrode leaves that field empty (SpikeInterface all-or-nothing).

A red highlight marks identifier collisions, invalid INTAN IDs, and electrode/pad pairing problems.

Extra electrode attributes can be added with **Add attribute**. They belong to the array file (`electrode_attributes` in the JSON). Opening a file rebuilds the side panel from that list, so arrays can have more or fewer fields. An extra can be unique globally or per shank.

## Map labels

**View > Map labels** (and the side-panel checkboxes) choose which IDs are drawn on both maps.

Defaults: Potentiostat ID and Shank ID in the contact, INTAN ID beside it. Manufacturer ID and extra attributes can be shown with that outside text. Each electrode, pad, and orientation marker has a **Label position** (`above`, `below`, `left`, `right`) and a **Label orientation** (`0°`, `90°`, `180°`, `270°` clockwise) for that outside text. Defaults: below, 0°.

Outside map text stays readable when it overlaps a white orientation marker: the part on the marker is dark, the part on the dark canvas stays light. A glyph that straddles the edge can be both. Center-of-contact IDs keep a single color chosen for the fill.

The choice of visible IDs is stored in native JSON (`map_labels`). The per-item side and rotation are stored on each electrode and pad (`label_position`, `label_orientation`). They are restored on open. Both are editor display only: they are not written to SpikeInterface or XLSX exports.

## Shapes

Electrodes and pads use the three SpikeInterface contact geometries: `circle`, `square`, `rect`. For `square`, Width and Height are both filled with the side length. For `rect`, Width and Height are independent.

## Pads

Pads are connector interfaces toward other electronic systems. They appear in the pad view, each linked to one electrode. The pad map uses the **same labels as the electrode map**. Pad ID is shown in the side panel and the electrode table, not on the contact.

Pad fields:

- **Pad ID** (editor-assigned integer, like electrode `eid`; not user-editable)
- **Electrode** (required association, identified by Potentiostat / shank / INTAN)
- **Label position** (above / below / left / right; native JSON only)
- **Label orientation** (0° / 90° / 180° / 270° clockwise; native JSON only)

Each electrode should have exactly one pad. The editor highlights unpaired or shared links and asks before save or export.

The side panel has three parameterization tabs: **Electrodes**, **Pads**, and **Orientation marker**. The electrode table includes a **Pad ID** column for the linked pad.

On each tab, **Actions** sets the defaults for new items (independent of the current selection):

- **Add Electrode**: shape, size, label position, and label orientation. No pad is created; add pads separately from the Pads tab.
- **Add Pad**: electrode to link, plus shape, size, and label defaults.
- **Add Orientation Marker**: shape and size (no map label).

Click the add button, then click the scene. **Geometry** / **Properties** still edit the current selection.

## Orientation marker

An orientation marker is a white fiducial used to read the orientation of the maps. It is not an electrode or a pad: it has no electrical link, does not take part in pairing, and is not a SpikeInterface contact. Shape and size follow the same rules as electrodes and pads (`circle`, `square`, `rect`).

Fields:

- **Marker ID** (editor-assigned integer; not user-editable)
- **Shape** (`circle`, `square`, `rect`)
- **Size** (radius, side length, or width / height, depending on the shape)
- **X / Y**

Place one from the **Orientation marker** tab (**Add Orientation Marker**, then click the scene). Shape and size come from **Actions** on that tab. Several markers are allowed. They appear on both mapping views, without a map label. Nearby electrode and pad outside labels invert over the white fill so the text stays readable.

They are stored in native JSON (`orientation_markers`) and written to the Excel workbook (sheet `orientation_markers`, geometry only). SpikeInterface export omits them.

## Electrode table

**View > Electrode table...** (`Ctrl+T`) opens a sortable table of every electrode (geometry, identifiers, extras, linked pad) with search and per-column filters. Selecting a row selects that electrode and its pad on the maps.

## Native save (File > Save)

`File > Save` / `Save As` writes mea_editor JSON (`specification: "mea_editor"`, version `1.11`):

- `si_units`
- `electrode_attributes` (built-in + extra fields, including uniqueness)
- `map_labels` (visible map IDs)
- `electrodes` (geometry, shape, height, identifiers, extras, `label_position`, `label_orientation`)
- `pads` (geometry, shape, height, electrode link, `pad_id`, `label_position`, `label_orientation`)
- `orientation_markers` (geometry: `marker_id`, `x`, `y`, `shape`, `radius`, `height`, plus `label_position`, `label_orientation`)

`label_position` is `above`, `below`, `left`, or `right`. `label_orientation` is `0`, `90`, `180`, or `270` (clockwise degrees). Neither is written to SpikeInterface or XLSX exports.

This is the format to keep as the source of truth. Probeinterface JSON can still be opened (migrated into native fields). Saving then writes native JSON.

Older native files without `map_labels` open with the default labels. Missing `label_position` defaults to `below`. Missing `label_orientation` defaults to `0`.

## SpikeInterface export

`File > Export for SpikeInterface...` writes a probeinterface JSON for **recording contacts only** (pads are not SpikeInterface contacts):

- **channel ID** (`device_channel_indices`) is derived from INTAN ID (`A-003` → 3, `D-018` → 114, `NC` → -1)
- **Contact ID** (`contact_ids`) is Manufacturer ID, or INTAN ID if Manufacturer ID is unused
- `contact_shapes` / `contact_shape_params` follow SpikeInterface (`circle` / `square` / `rect`)
- `contact_annotations` stores native IDs (including `shank_id`), extra attributes, and the first linked pad (`pad_id`, `pad_x`, `pad_y`, `pad_shape`, `pad_radius`, `pad_height`)
- probe `annotations` store the electrode attribute schema and the visible map labels so a file exported from this editor can be reopened with less data loss

Opening a probeinterface JSON exported by this editor restores pads from those annotations. Plain probeinterface files (no pad geometry) still open without pads. Label position and orientation are not part of this export (they stay in native JSON only).

## XLSX export

**Export array as XLSX...** writes sheet `array` (full electrode table including extras), sheet `pads` (linked electrode identifiers, `si_channel`, extras, and pad geometry), sheet `orientation_markers` (`marker_id`, `x`, `y`, `shape`, `radius`, `width`, `height`), sheet `electrode_attributes` (schema with uniqueness). Geometry columns are `radius`, `width`, `height` (`circle` fills radius; `square` fills width and height with the side length; `rect` fills width and height independently).

`row` is electrode Y, `col` is electrode X. Label position and orientation are not written to the workbook.

## Keyboard shortcuts

Listed under **Help > Keyboard shortcuts...**:

- Click / Ctrl+Click / box-drag: selection
- Middle-drag: pan; wheel: zoom
- X/Y or dX/dY: move
- Add Electrode / Pad / Orientation Marker: set shape, size, and (for electrodes and pads) label defaults in Actions, then click the scene
- Delete / Backspace: delete selected
- Ctrl+Z / Ctrl+Y: undo / redo
- Ctrl+0: fit both maps
- Ctrl+T: electrode table

## Library API

I/O does not import Qt:

```python
from mea_editor import (
    load_array_document,
    save_array_to_file,
    export_spikeinterface_json,
    export_array_xlsx,
)

doc = load_array_document("array.json")
save_array_to_file("array.json", doc.electrodes, doc.si_units, pads=doc.pads,
                   electrode_attributes=doc.electrode_attributes, map_labels=doc.map_labels,
                   orientation_markers=doc.orientation_markers)
```

## Build a standalone executable (Windows: `.exe`, macOS/Linux: binary)

1. Activate the virtual environment
2. Using the command-line terminal, navigate to the folder where you want the executable to be located.
3. Install the build extra if needed: `uv pip install "mea-editor[build]"`
4. Build in current folder `dist/`: `mea-editor-build`

The executable will be in `dist/` (in the current directory), named `ElectrodeArrayEditor.exe` on Windows and `ElectrodeArrayEditor` elsewhere.

From a source checkout: `pip install -e ".[build]"` then `mea-editor-build`. Close the editor if an older executable is still running, or the file cannot be replaced.
