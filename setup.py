#!/usr/bin/env python
"""Setup aiosenseme library."""
from __future__ import print_function

import sys

from setuptools import find_packages, setup

__version__ = "Unknown"
exec(open("aiosenseme/version.py").read())

if sys.version_info < (3, 6):
    error = """
    aiosenseme supports Python 3.6 and above.

    Python {py} detected.

    Please install using pip3 on Python 3.6 or above.
    """.format(
        py=".".join([str(v) for v in sys.version_info[:3]])
    )

    print(error, file=sys.stderr)
    sys.exit(1)

setup(
    name="aiosenseme",
    version=__version__,
    description="SenseME by Big Ass Fans asynchronous Python library",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="mikelawrence",
    author_email="mikealawr@gmail.com",
    url="https://github.com/mikelawrence/aiosenseme",
    packages=find_packages(),
    include_package_data=True,
    license="GPL3",
    install_requires=["ifaddr>=0.1.7"],
    entry_points={
        "console_scripts": ["aiosenseme = aiosenseme.scripts.commandline:cli"],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Framework :: AsyncIO",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Home Automation",
    ],
    keywords="Haiku HaikuHome SenseME fan home automation BigAssFans",
    python_requires=">=3.6",
)
