# KasaSwitchManager.spec
# PyInstaller spec file for Kasa Alpaca Switch Manager GUI

block_cipher = None

a = Analysis(
    ['device/gui_manager.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('device/config.toml', 'device'),  # Copy config.toml into device/ in the bundle
        ('device/*.py', 'device'),         # Copy all device source files
    ],
    hiddenimports=[
        'keyring',
        'keyring.backends',
        'keyring.backends.Windows',
        'keyring.backends.fail',
        'keyring.util',
        'pystray',
        'PIL',
        'PIL._imagingtk',
        'PIL.ImageTk',
        'PIL.Image',
        'PIL.ImageDraw',
        'falcon',
        'kasa',
        'dateutil',
        'dateutil.tz',
        'dateutil.parser',
        'asyncio',
        'threading',
        'logging',
        'toml',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='KasaSwitchManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='KasaSwitchManager'
)