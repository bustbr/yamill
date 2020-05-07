import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="yamill",
    version="0.0.1",
    author="Nona Suomy",
    author_email="liam@nona.party",
    description="A formatter and linter for YAML files.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/bustbr/yamill",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    entry_points={"console_scripts": ["yamill=yamill:main"]},
    python_requires=">=3.6",
)
