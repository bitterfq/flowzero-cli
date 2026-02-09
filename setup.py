from setuptools import setup, find_packages

setup(
    name="flowzero-orders-cli",
    version="2.0.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "click>=8.0",
        "requests>=2.25",
        "boto3>=1.26",
        "geopandas>=0.12",
        "python-dotenv>=1.0",
        "rich>=13.0",
        "shapely>=2.0",
        "folium>=0.14",
        "flask>=2.0",
        "python-dateutil>=2.8",
        "aiohttp>=3.9.0",
        "tenacity>=8.2.0",
        "pyyaml>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "flowzero=flowzero.cli.app:cli",
        ],
    },
    python_requires=">=3.8",
)
