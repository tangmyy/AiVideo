"""Build a portable Windows GUI folder with PyInstaller."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path.cwd()
datas = [
    (str(root / 'aivideo.qss'), '.'),
    (str(root / '.env.example'), '.'),
    (str(root / 'icon_image' / 'icons.png'), 'icon_image'),
    (str(root / 'ffmpeg' / 'bin' / 'ffmpeg.exe'), 'ffmpeg/bin'),
]
if (root / '.model-cache' / 'models--Systran--faster-whisper-small').exists():
    datas.append((str(root / '.model-cache'), '.model-cache'))
playwright_datas, playwright_binaries, playwright_imports = collect_all('playwright')
datas.extend(playwright_datas)
a = Analysis(
    [str(root / 'aivideo_gui.py')],
    pathex=[str(root)],
    binaries=playwright_binaries,
    datas=datas,
    hiddenimports=playwright_imports + collect_submodules('bilibili_api.clients'),
    excludes=['PySide6', 'tkinter', 'faster_whisper', 'ctranslate2', 'onnxruntime', 'av'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AiVideo', console=False, contents_directory='.')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AiVideo')
