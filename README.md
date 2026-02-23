# MEA-Editor

GUI to create and modify MEA (Multi-Electrode Arrays) compatible with [probeinterface](https://probeinterface.readthedocs.io/).

**Multi-platform:** Windows, macOS, Linux.

## Installation (PyPI)

```bash
pip install mea-editor
mea-editor
```

## Build standalone executable

To create a standalone executable (Windows: `.exe`, macOS/Linux: binary):

```bash
pip install -e . pyinstaller PySide6
python run_mea_editor/build_exe.py
```

The executable will be in `dist/` (ElectrodeArrayEditor.exe on Windows).

## Installation from source (uv)

1. Install [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows)
2. `uv venv si_env --python 3.12`
3. Activate: `source si_env/bin/activate` (macOS/Linux) or `si_env\Scripts\activate` (Windows)
4. `uv pip install -r requirements.txt`

## Publishing (maintainers)

### 1. PyPI Trusted Publisher

1. Go to [pypi.org](https://pypi.org) → Manage → Publishing → Add a new trusted publisher
2. Owner: `Wireless-Neural-Interface-Team`, Repository: `MEA-Editor`
3. Workflow name: `publish-pypi.yml`
4. Environment: `release` (optional)

### 2. Release

1. Update `version` in `pyproject.toml` and `mea_editor/__init__.py`
2. Create a [GitHub Release](https://github.com/Wireless-Neural-Interface-Team/MEA-Editor/releases/new) (e.g. tag `v0.1.0`)
3. Publish the release → workflow runs and publishes to PyPI

Or run manually: Actions → Publish to PyPI → Run workflow
