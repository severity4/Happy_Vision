"""tests/hardening/test_i1_hidden_imports.py

Hardening I1: 新增 blueprint / module 後 `make app` 不漏 hidden-import。

背景：PyInstaller 的靜態 import 偵測只跟 `import modules.X`，但 Flask 的
blueprint 是透過 `app.register_blueprint(X_bp)` 加載，register 時只傳
物件，沒有文字 import name — PyInstaller 看不到。結果：本機 python 跑
web_ui.py 沒事，打包後的 .app 啟動時缺 blueprint 模組 ImportError 炸掉。

這題踩過兩次（專案有前例，CLAUDE.md memory 記過）。把 web_ui.py 實際
import 的 `api/X_bp`、`modules/*` 對照 `build_app.py` 的 `--hidden-import`
清單，任何缺的都是未來會炸掉的未爆彈。
"""

from __future__ import annotations

import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_WEB_UI = _ROOT / "web_ui.py"
_BUILD_SPEC = _ROOT / "build_app.py"


def _imports_from_file(path: Path) -> set[str]:
    """Collect `from X import ...` and `import X` top-level modules."""
    text = path.read_text(encoding="utf-8")
    mods: set[str] = set()
    for m in re.finditer(r"^\s*from\s+([\w.]+)\s+import", text, re.MULTILINE):
        mods.add(m.group(1))
    for m in re.finditer(r"^\s*import\s+([\w.]+)", text, re.MULTILINE):
        mods.add(m.group(1))
    return mods


def _hidden_imports_from_spec(path: Path) -> set[str]:
    """Extract `--hidden-import=X` values from build_app.py."""
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"--hidden-import=([\w.]+)", text))


def test_every_api_blueprint_in_web_ui_is_hidden_import():
    """If web_ui.py imports api.FOO, build_app.py must have
    --hidden-import=api.FOO. Catch missing ones BEFORE build time."""
    web_ui_imports = _imports_from_file(_WEB_UI)
    api_modules = {m for m in web_ui_imports if m.startswith("api.")}

    hidden = _hidden_imports_from_spec(_BUILD_SPEC)

    missing = api_modules - hidden
    assert not missing, (
        f"web_ui.py imports these api.* modules but build_app.py has no "
        f"--hidden-import for them: {sorted(missing)}. "
        f"PyInstaller won't bundle them and the .app will fail with "
        f"ImportError on first launch."
    )


def test_every_module_in_api_dir_is_hidden_import():
    """Every api/<X>.py file must be listed as --hidden-import=api.X.
    Guards against a new blueprint being added with a file but never
    wired into the build spec."""
    api_dir = _ROOT / "api"
    on_disk = {
        f"api.{f.stem}"
        for f in api_dir.glob("*.py")
        if f.stem != "__init__"
    }

    hidden = _hidden_imports_from_spec(_BUILD_SPEC)

    missing = on_disk - hidden
    assert not missing, (
        f"api/ contains modules not listed in build_app.py hidden-imports: "
        f"{sorted(missing)}. If these are unused, delete the file. If used, "
        f"add --hidden-import."
    )


def test_every_module_in_modules_dir_is_hidden_import():
    """Same for modules/. Missing a module here means the .app ships
    broken on first launch."""
    mod_dir = _ROOT / "modules"
    on_disk = {
        f"modules.{f.stem}"
        for f in mod_dir.glob("*.py")
        if f.stem != "__init__"
    }

    hidden = _hidden_imports_from_spec(_BUILD_SPEC)

    # We allow tooling / dev-only modules to be absent. Flag only the
    # ones that OTHER modules import.
    all_imports_across_project: set[str] = set()
    for py in _ROOT.rglob("*.py"):
        if any(p in py.parts for p in ("tests", ".venv", "build", "dist")):
            continue
        all_imports_across_project |= _imports_from_file(py)

    referenced = {m for m in on_disk if m in all_imports_across_project}

    missing = referenced - hidden
    assert not missing, (
        f"modules/*.py referenced by the app but missing from hidden-imports: "
        f"{sorted(missing)}. Add --hidden-import for each."
    )


def test_google_genai_explicitly_imported():
    """google-genai uses dynamic sub-module loading that PyInstaller
    misses. Regression guard — hv has had this exact break before."""
    hidden = _hidden_imports_from_spec(_BUILD_SPEC)
    assert "google.genai" in hidden, (
        "--hidden-import=google.genai missing; bundled app will fail with "
        "ImportError on first photo analysis"
    )
    assert "google.genai.types" in hidden, (
        "--hidden-import=google.genai.types missing; GenerateContentConfig "
        "construction will fail at runtime"
    )


def test_pywebview_cocoa_backend_in_hidden_imports():
    """macOS PyInstaller build needs webview.platforms.cocoa explicitly."""
    hidden = _hidden_imports_from_spec(_BUILD_SPEC)
    assert "webview.platforms.cocoa" in hidden, (
        "webview.platforms.cocoa missing — bundled app won't find a GUI "
        "backend and shows white screen forever"
    )
