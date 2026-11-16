"""Setuptools metadata for packaging ``neurorehab_plugin`` as a standalone SDK wheel.

Used by plugin authors who install the SDK in a virtual environment.  The desktop
application bundles the same sources via PyInstaller ``datas`` instead of this
package entry point.
"""

from setuptools import setup

setup(
    name="neurorehab-plugin-sdk",
    version="1.0.0",
    description="Read-only SDK for NeuroRehab database plugins",
    python_requires=">=3.11",
    packages=["neurorehab_plugin"],
    package_dir={"neurorehab_plugin": "."},
)
