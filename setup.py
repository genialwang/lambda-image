################################
# Author   : septicmk
# Date     : 2015/07/24 09:37:15
# FileName : setup.py
################################
NAME="lambdaimage"
DESCRIPTION = "Image processing pipeline for lambdaimage"
LONG_DESCRIPTION = ''
MAINTAINER = 'septicmk'
MAINTAINER_EMAIL = 'mengke@ncic.ac.cn'
URL = 'https://github.com/septicmk/lambdaimage'
LICENSE = 'BSD'
DOWNLOAR_URL = 'https://github.com/septicmk/lambdaimage'

with open('lambdaimage/__init__.py') as f:
    for line in f:
        if line.startswith('__version__'):
            VERSION = line.strip().split()[-1][1:-1]
            break
with open('requirements.txt') as f:
    REQUIRE = [l.strip() for l in f.readlines() if l]


if __name__ == '__main__':
    from setuptools import find_packages, setup
    from setuptools.extension import Extension
    from setuptools.command.build_ext import build_ext
    import numpy
    extensions =[
        Extension("lambdaimage.udf._subtract_bg",
            sources=["lambdaimage/udf/_subtract_bg.pyx","lambdaimage/udf/_subtract_bg_c.cpp"],
            inlcude_dirs=[numpy.get_include()],
            language="c++"),
        Extension("lambdaimage.udf._trans",
            sources=["lambdaimage/udf/_trans.pyx","lambdaimage/udf/_trans_c.c"],
            include_dirs=[numpy.get_include()]),
        Extension("lambdaimage.udf._update",
            sources=["lambdaimage/udf/_update.pyx", "lambdaimage/udf/_update_c.c"],
            include_dirs=[numpy.get_include()]),
        Extension("lambdaimage.udf._moment",
            sources=["lambdaimage/udf/_moment.pyx"],
            inlcude_dirs=[numpy.get_include()]),
        Extension("lambdaimage.udf._intensity",
            sources=["lambdaimage/udf/_intensity.pyx"],
            include_dirs=[numpy.get_include()]),
        Extension("lambdaimage.udf._phansalkar",
            sources=["lambdaimage/udf/_phansalkar.pyx", "lambdaimage/udf/_phansalkar_c.c"],
            include_dirs=[numpy.get_include()]),
    ]
    from Cython.Build import cythonize
    extensions = cythonize(extensions)

    setup(
        name = NAME,
        description = DESCRIPTION,
        long_description = LONG_DESCRIPTION,
        maintainer = MAINTAINER,
        maintainer_email = MAINTAINER_EMAIL,
        url=URL,
        license = LICENSE,
        download_url = DOWNLOAR_URL,
        version = VERSION,
        classifiers = [
            'Development Status :: 4 - Beta',
            'Environment :: Console',
            'Intended Audience :: Developers',
            'Intended Audience :: Science/Research',
            'License :: OSI Approved :: BSD License',
            'Programming Language :: C',
            'Programming Language :: C++',
            'Programming Language :: Python',
            'Topic :: Software Development :: Libraries',
            'Topic :: Scientific/Engineering',
            'Topic :: Scientific/Engineering :: Bio-Informatics',
            'Operating System :: Microsoft :: Windows',
            'Operating System :: POSIX',
            'Operating System :: Unix',
            'Operating System :: MacOS',
        ],
        install_requires = REQUIRE,
        packages = find_packages(),
        cmdclass = {'build_ext': build_ext},
        ext_modules = extensions
    )
