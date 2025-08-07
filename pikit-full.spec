# pikit-full.spec
# For use with: pyinstaller pikit-full.spec

block_cipher = None

a = Analysis(
    ['pikit.py'],  # Your entry-point script
    pathex=['.'],
    binaries=[],
    datas=[
        ('storage/*', 'storage'),
        ('exported_docs/*', 'exported_docs'),
    ],
    hiddenimports=[
        'tkinter',
        'PIL.ImageTk',
        'cv2',
        'librosa',
        'torch',
        'sklearn',
        'matplotlib.pyplot',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tests',  # If any test packages are lying around
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='pikit-full',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disable UPX compression for PyTorch compatibility
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to True if you want terminal output
)

