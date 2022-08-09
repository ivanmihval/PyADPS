# -*- coding: utf-8 -*-
import os

from setuptools import find_packages, setup


def read(filename: str) -> str:
    with open(os.path.join(os.path.dirname(__file__), filename)) as file:
        return file.read()


def parse_requirements() -> tuple:
    """Parse requirements.txt for install_requires"""
    requirements = read('requirements.txt')
    return tuple(requirements.split('\n'))


setup(
    name='pyadps',
    version='0.0.1',
    description='PyADPS - Python implementation of the ADPS',
    packages=find_packages(exclude=['tests*', ]),
    url='https://adps-project.org',
    download_url='https://adps-project.org',
    author='Ivan Mikhailov',
    author_email='ivanmihval@yandex.ru',
    long_description=read('README.md'),
    python_requires='~=3.7',
    zip_safe=True,
    install_requires=parse_requirements(),
    entry_points={
        'console_scripts': [
            'adps=pyadps.cli:cli',
        ],
    }
)
