from setuptools import setup, find_packages

setup(
    name="kasa-alpaca-switch",
    version="0.1.0",
    description="ASCOM Alpaca Switch driver for Kasa smart plugs",
    author="Paul Fox-Reeks",
    packages=find_packages(),                # finds the `device` package
    install_requires=[
        "falcon",
        "toml",
        "python-kasa",
        "keyring",
        "pystray",
        "Pillow",
    ],
    package_data={
        # include your config TOML so it ends up in the wheel
        "device": ["config.toml"],
    },
    include_package_data=True,
    entry_points={
        "console_scripts": [
            # installs a `kasa-switch` CLI that launches your app
            "kasa-switch = device.app:main",
            # Add a GUI manager entry point
            "kasa-switch-gui = device.gui_manager:main",
        ],
    },
    python_requires=">=3.7",
)