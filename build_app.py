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
    """ALWAYS rebuild Vue frontend before packaging.

    Previously this skipped `npm run build` when frontend/dist already
    existed. That's a release-time footgun: if you edit a Vue file and
    run `make app` without first rebuilding, the bundled .app will ship
    with stale JS/CSS and none of your UI changes will actually reach
    users (Evidence Collector caught this shipping v0.7.0 with v0.6.x
    bundle contents). Rebuild every time — it's only ~150ms with Vite.
    """
    print("Building frontend (always, to ensure fresh bundle)...")
    subprocess.run(
        ["npm", "run", "build"],
        cwd=PROJECT_DIR / "frontend",
        check=True,
    )
    dist = PROJECT_DIR / "frontend" / "dist"
    # Verify the produced bundle so accidentally-missing outputs fail loud.
    for p in ("index.html", "assets"):
        if not (dist / p).exists():
            raise RuntimeError(
                f"frontend/dist/{p} missing after npm run build — "
                "packaging would ship a broken frontend"
            )
    # Print the JS bundle hash so release audits can verify what's inside.
    assets = dist / "assets"
    js_files = sorted(assets.glob("index-*.js"))
    if js_files:
        print(f"Bundle JS: {js_files[-1].name} ({js_files[-1].stat().st_size // 1024} KB)")


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

    # Bundle CJK font for PDF reports (Noto Sans TC)
    font_path = PROJECT_DIR / "assets" / "NotoSansTC-Regular.ttf"
    if font_path.exists():
        added_data.append(f"{font_path}:assets")
    else:
        print(f"WARNING: {font_path} not found — PDF exports will fail at runtime.")

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
        "--hidden-import=modules.pricing",
        "--hidden-import=modules.pdf_report",
        "--hidden-import=modules.phash",
        "--hidden-import=reportlab.pdfbase.cidfonts",
        # Exclude heavyweight packages that PyInstaller sometimes grabs
        # transitively. None of these are used by Happy Vision and together
        # they add ~800 MB to the .app bundle.
        "--exclude-module=torch",
        "--exclude-module=torchvision",
        "--exclude-module=tensorflow",
        "--exclude-module=polars",
        "--exclude-module=pyarrow",
        "--exclude-module=pandas",
        "--exclude-module=scipy",
        "--exclude-module=sklearn",
        "--exclude-module=cv2",
        "--exclude-module=av",
        "--exclude-module=llvmlite",
        "--exclude-module=numba",
        "--exclude-module=onnxruntime",
        "--exclude-module=tokenizers",
        "--exclude-module=transformers",
        "--exclude-module=lxml",
        "--exclude-module=matplotlib",
        "--exclude-module=IPython",
        "--exclude-module=notebook",
        "--exclude-module=imagehash",
        "--exclude-module=pywt",
        "--hidden-import=api",
        "--hidden-import=api.settings",
        "--hidden-import=api.analysis",
        "--hidden-import=api.results",
        "--hidden-import=api.export",
        "--hidden-import=api.update",
        "--hidden-import=api.watch",
        "--hidden-import=api.system",
        "--hidden-import=api.batch",
        "--hidden-import=modules.updater",
        "--hidden-import=modules.gemini_batch",
        "--hidden-import=modules.batch_monitor",
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

    _codesign_if_identity_available(DIST_DIR / f"{APP_NAME}.app")

    print(f"\n{'='*50}")
    print("BUILD COMPLETE!")
    print(f"{'='*50}")
    print(f"App: {DIST_DIR / APP_NAME}")
    print(f"Launcher: {launcher}")
    print(f"\nTo test: double-click {launcher.name}")
    print(f"Or run: ./{launcher.relative_to(PROJECT_DIR)}")


# v0.7.2: self-signed code-signing identity to fix the "Keychain keeps
# asking for password every build" problem. Ad-hoc signed apps have no
# stable designated requirement, so macOS can't persist the Keychain ACL
# entry across rebuilds — every new binary triggers a fresh password
# prompt. Signing with ANY stable identity (self-signed is fine here,
# this is a dev tool not an App Store release) makes the ACL stick to
# the identity rather than the binary hash.
CODESIGN_IDENTITY = "Happy Vision Developer (Local)"
CODESIGN_IDENTITY_DIR = Path.home() / ".happy-vision-codesign"


def _codesign_if_identity_available(app_path: Path) -> None:
    """Sign the .app with the local self-signed identity if installed.
    Falls back to ad-hoc (PyInstaller default) with a warning if not."""
    if not app_path.exists():
        print(f"Skipping codesign: {app_path} not found")
        return

    # Check if the identity is installed + valid for code signing
    try:
        result = subprocess.run(
            ["security", "find-identity", "-v", "-p", "codesigning"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:
        print(f"Skipping codesign: cannot query identities ({e})")
        return

    if CODESIGN_IDENTITY not in result.stdout:
        print(f"\n⚠️  Self-signed identity '{CODESIGN_IDENTITY}' not installed.")
        print("   App will use PyInstaller's ad-hoc signature — macOS Keychain")
        print("   will keep prompting for password on every rebuild.")
        print(f"   To install once, run: python3 {__file__} --setup-codesign")
        return

    print(f"\nCodesigning .app with '{CODESIGN_IDENTITY}'...")
    try:
        subprocess.run(
            ["codesign", "--force", "--deep",
             "--sign", CODESIGN_IDENTITY,
             "--identifier", "com.inout.HappyVision",
             str(app_path)],
            check=True, timeout=120,
        )
    except subprocess.CalledProcessError as e:
        print(f"Codesign FAILED: {e}")
        return
    # Verify
    subprocess.run(["codesign", "--verify", "--verbose", str(app_path)],
                   timeout=30)
    print("Codesign verified.")


def setup_codesign_identity() -> None:
    """One-time: generate + install a self-signed code-signing identity.
    Safe to re-run — idempotent."""
    CODESIGN_IDENTITY_DIR.mkdir(mode=0o700, exist_ok=True)
    crt = CODESIGN_IDENTITY_DIR / "hv-codesign.crt"
    key = CODESIGN_IDENTITY_DIR / "hv-codesign.key"
    p12 = CODESIGN_IDENTITY_DIR / "hv-codesign.p12"

    # Already installed?
    check = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True, text=True,
    )
    if CODESIGN_IDENTITY in check.stdout:
        print(f"'{CODESIGN_IDENTITY}' is already installed. Nothing to do.")
        return

    if not crt.exists() or not key.exists():
        print(f"Generating self-signed cert at {CODESIGN_IDENTITY_DIR}")
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-days", "3650",
            "-keyout", str(key), "-out", str(crt),
            "-subj", f"/CN={CODESIGN_IDENTITY}/O=INOUT Creative/C=TW",
            "-addext", "basicConstraints=critical,CA:false",
            "-addext", "keyUsage=critical,digitalSignature",
            "-addext", "extendedKeyUsage=critical,codeSigning",
        ], check=True)

    if not p12.exists():
        print(f"Bundling PKCS12 at {p12}")
        subprocess.run([
            "openssl", "pkcs12", "-export",
            "-in", str(crt), "-inkey", str(key),
            "-out", str(p12),
            "-password", "pass:happyvision",
            "-name", CODESIGN_IDENTITY,
            # Legacy PBE so macOS security CLI can parse it
            "-keypbe", "PBE-SHA1-3DES",
            "-certpbe", "PBE-SHA1-3DES",
            "-macalg", "sha1",
        ], check=True)

    login_kc = str(Path.home() / "Library/Keychains/login.keychain-db")
    subprocess.run([
        "security", "import", str(p12),
        "-k", login_kc,
        "-P", "happyvision",
        "-T", "/usr/bin/codesign",
        "-T", "/usr/bin/security",
    ], check=True)
    subprocess.run([
        "security", "add-trusted-cert", "-r", "trustRoot",
        "-p", "codeSign", "-k", login_kc, str(crt),
    ], check=True)
    print(f"\n✅ '{CODESIGN_IDENTITY}' installed and trusted for code signing.")
    print("   Future .app builds will be signed with it. Keychain ACL will")
    print("   persist across rebuilds after one 'Always Allow' click.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--setup-codesign":
        setup_codesign_identity()
    else:
        build_app()
