from distutils.core import setup

from catkin_pkg.python_setup import generate_distutils_setup

# fetch values from package.xml
setup_args = generate_distutils_setup(
    packages=["mule_bridge", "hovermap_runtime"],
    package_dir={"": "src"},
    package_data={"": ["pyarmor_runtime.so"]}
)

setup(**setup_args)
