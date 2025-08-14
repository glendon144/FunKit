# Regenerate pikit_lean.spec with lean settings and common excludes.
from pathlib import Path

spec = r'''# -*- mode: python ; coding: utf-8 -*-
# Lean PyInstaller spec for PiKit (v1.2.1+)
# - one-dir build at dist/pikit
# - strips debug symbols
# - excludes heavy unused stacks (torch/tensorflow/etc.)
# - includes Flask stack via hiddenimports (lazy import safe)
# Usage:  pyinstaller -y --clean pikit_lean.spec

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Export server & templating
        'flask', 'jinja2', 'werkzeug', 'markupsafe', 'itsdangerous',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Big ML stacks not used by PiKit core
        'torch', 'torchvision', 'torchaudio', 'triton',
        'tensorflow', 'tensorboard',
        'onnx', 'onnxruntime',
        # JIT/CUDA/science runtimes
        'numba', 'llvmlite', 'scipy', 'sympy',
        # Data/viz libs
        'matplotlib', 'pandas', 'pyarrow', 'moviepy', 'imageio',
        # Computer vision (exclude if unused)
        'opencv-python', 'cv2',
        # Optional NumPy plugin that can trigger TBB warnings
        'numpy.np.ufunc.tbbpool',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='pikit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,   # remove debug symbols to reduce size
    upx=False,    # set to True if UPX is installed and desired
    console=True, # keep terminal for logs; set False for windowed
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='pikit',
)
'''

out = Path('/mnt/data/pikit_lean.spec')
out.write_text(spec, encoding='utf-8')
print(out.as_posix())

