# KasaSwitchManager.spec
# PyInstaller spec file for Kasa Alpaca Switch Manager GUI

block_cipher = None

a = Analysis(
    ['device/gui_manager.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('device/config.toml', '.'),  # Copy config.toml to dist root
        ('device/*.py', 'device'),    # Copy all device source files
        ('device/*.json', 'device'),  # Copy all JSON data files
        ('device/*.txt', 'device'),   # Copy all text files
        ('device/*.pem', 'device'),   # Copy all PEM files
        ('device/*.crt', 'device'),   # Copy all CRT files
        ('device/*.cfg', 'device'),   # Copy all CFG files
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
        'dateutil.zoneinfo',
        'dateutil._common',
        'dateutil._parser',
        'dateutil._tzinfo',
        'tzdata',
        'tzlocal',
        'pytz',
        'asyncio',
        'concurrent',
        'concurrent.futures',
        'ssl',
        'socket',
        'selectors',
        'importlib',
        'importlib.resources',
        'importlib.metadata',
        'importlib._common',
        'importlib._bootstrap',
        'importlib._bootstrap_external',
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