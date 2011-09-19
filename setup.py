#!/usr/bin/env python

from setuptools import setup
from gun import __version__

setup(
      name = 'gun',
      version = __version__,
      description = 'Gentoo Updates Notifier',
      author = 'Andriy Yurchuk',
      author_email = 'ayurchuk@minuteware.net',
      url = 'http://minuteware.net/gun',
      license = 'LICENSE.txt',
      long_description = open('README.rst').read(),
      entry_points = {
                      'console_scripts': [
                                          'gun = gun.sync:main'
                                          ]
                      },
      packages = ['gun'],
      data_files = [('/etc/', ['data/gun.conf'])],
      install_requires = ['xmpppy >= 0.5.0-rc1']
      )