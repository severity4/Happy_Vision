"""spike_pyinstaller.py — Verify PyInstaller can bundle Flask + pyexiftool"""

import subprocess
import sys
from pathlib import Path


def main():
    print("=== PyInstaller Packaging Spike ===")

    # 1. Check exiftool is available
    try:
        result = subprocess.run(["exiftool", "-ver"], capture_output=True, text=True)
        exiftool_path = subprocess.run(["which", "exiftool"], capture_output=True, text=True).stdout.strip()
        print(f"exiftool {result.stdout.strip()} at {exiftool_path}")
    except FileNotFoundError:
        print("ERROR: exiftool not found")
        sys.exit(1)

    # 2. Try PyInstaller build
    try:
        import PyInstaller.__main__
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    # 3. Build minimal app
    print("Building minimal .app with PyInstaller...")
    subprocess.run([
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--name", "HappyVision",
        f"--add-binary={exiftool_path}:.",
        "--noconfirm",
        "web_ui.py",
    ], check=True)

    # 4. Verify the built app can start
    app_path = Path("dist/HappyVision/HappyVision")
    if app_path.exists():
        print(f"SUCCESS: Built app at {app_path}")
        print("Try running: ./dist/HappyVision/HappyVision")
    else:
        print("WARNING: App binary not found at expected path, check dist/ directory")


if __name__ == "__main__":
    main()
