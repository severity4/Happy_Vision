"""build_app.py — Build macOS .app bundle for Happy Vision"""

import subprocess
import sys
import shutil
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
DIST_DIR = PROJECT_DIR / "dist"
BUILD_DIR = PROJECT_DIR / "build"
APP_NAME = "HappyVision"


def find_exiftool() -> str:
    """Find exiftool binary path."""
    result = subprocess.run(["which", "exiftool"], capture_output=True, text=True)
    if result.returncode != 0:
        print("ERROR: exiftool not found. Install with: brew install exiftool")
        sys.exit(1)
    path = result.stdout.strip()
    print(f"Found exiftool at: {path}")
    return path


def build_frontend():
    """Build Vue frontend if not already built."""
    dist = PROJECT_DIR / "frontend" / "dist"
    if not dist.exists():
        print("Building frontend...")
        subprocess.run(
            ["npm", "run", "build"],
            cwd=PROJECT_DIR / "frontend",
            check=True,
        )
    else:
        print("Frontend dist/ already exists, skipping build.")


def build_app():
    """Build macOS .app with PyInstaller."""
    exiftool_path = find_exiftool()
    build_frontend()

    # Resolve exiftool — it might be a symlink
    exiftool_real = str(Path(exiftool_path).resolve())
    print(f"Exiftool real path: {exiftool_real}")

    # Check if exiftool is a Perl script or standalone binary
    # Homebrew exiftool is a Perl script, we need the whole lib
    exiftool_dir = Path(exiftool_real).parent
    exiftool_lib = exiftool_dir.parent / "lib"

    # Collect all data files
    added_data = [
        f"{PROJECT_DIR / 'frontend' / 'dist'}:frontend/dist",
        f"{PROJECT_DIR / 'VERSION'}:.",
    ]

    # Add exiftool lib directory if it exists (Homebrew layout)
    if exiftool_lib.exists():
        added_data.append(f"{exiftool_lib}:lib")

    print(f"\nBuilding {APP_NAME}.app...")
    print(f"Data files: {added_data}")

    # App icon
    icon_path = PROJECT_DIR / "assets" / "HappyVision.icns"
    if not icon_path.exists():
        print("WARNING: Icon not found, using default. Run generate_icon.py first.")

    icon_args = [f"--icon={icon_path}"] if icon_path.exists() else []

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",
        "--windowed",
        "--noconfirm",
        *icon_args,
        # Add exiftool binary
        f"--add-binary={exiftool_real}:.",
        # Hidden imports that PyInstaller might miss
        "--hidden-import=modules",
        "--hidden-import=modules.config",
        "--hidden-import=modules.logger",
        "--hidden-import=modules.gemini_vision",
        "--hidden-import=modules.result_store",
        "--hidden-import=modules.metadata_writer",
        "--hidden-import=modules.report_generator",
        "--hidden-import=modules.pipeline",
        "--hidden-import=api",
        "--hidden-import=api.settings",
        "--hidden-import=api.analysis",
        "--hidden-import=api.results",
        "--hidden-import=api.export",
        "--hidden-import=api.update",
        "--hidden-import=modules.updater",
        "--hidden-import=google.genai",
        "--hidden-import=google.genai.types",
        "--hidden-import=webview",
        "--hidden-import=webview.platforms.cocoa",
    ]

    # Add data files
    for data in added_data:
        cmd.extend(["--add-data", data])

    # Entry point
    cmd.append("web_ui.py")

    print(f"\nRunning: {' '.join(cmd)}\n")
    subprocess.run(cmd, check=True, cwd=PROJECT_DIR)

    # Create a launcher script that opens the browser
    app_dir = DIST_DIR / APP_NAME
    if not app_dir.exists():
        # Try .app bundle
        app_dir = DIST_DIR / f"{APP_NAME}.app" / "Contents" / "MacOS"

    launcher = PROJECT_DIR / "dist" / "launch_happy_vision.command"
    launcher.write_text(f"""#!/bin/bash
# Happy Vision Launcher
cd "$(dirname "$0")"

# Find the app
if [ -d "{APP_NAME}.app" ]; then
    APP="./{APP_NAME}.app/Contents/MacOS/{APP_NAME}"
elif [ -f "{APP_NAME}/{APP_NAME}" ]; then
    APP="./{APP_NAME}/{APP_NAME}"
else
    echo "ERROR: Cannot find {APP_NAME} app"
    exit 1
fi

echo "Starting Happy Vision on http://localhost:8081 ..."
echo "Opening browser in 3 seconds..."

# Start server in background
$APP &
SERVER_PID=$!

# Wait then open browser
sleep 3
open "http://localhost:8081"

echo ""
echo "Happy Vision is running. Close this window to stop."
echo "Press Ctrl+C to stop."

# Wait for server to exit
wait $SERVER_PID
""")
    launcher.chmod(0o755)

    print(f"\n{'='*50}")
    print("BUILD COMPLETE!")
    print(f"{'='*50}")
    print(f"App: {DIST_DIR / APP_NAME}")
    print(f"Launcher: {launcher}")
    print(f"\nTo test: double-click {launcher.name}")
    print(f"Or run: ./{launcher.relative_to(PROJECT_DIR)}")


if __name__ == "__main__":
    build_app()
