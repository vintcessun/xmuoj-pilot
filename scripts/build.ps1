$ErrorActionPreference = "Stop"

uv sync

uv run python -m nuitka `
  --standalone `
  --onefile `
  --output-dir=dist `
  --output-filename=xmuoj-pilot.exe `
  src/xmuoj_pilot/main.py

# If your local UPX setup is stable, you may add:
#   --enable-plugin=upx `

