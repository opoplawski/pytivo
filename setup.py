#!/usr/bin/python
from setuptools import setup

setup(
    name = "pyTivo",
    version = "0.14",
    description = ("pyTivo is both an HMO and GoBack server. Similar to TiVo"
                   "Desktop pyTivo loads many standard video compression"
                   "codecs and outputs mpeg2 video to the TiVo. However, "
                   "pyTivo is able to load MANY more file types than TiVo"
                   "Desktop."),
    license = "GPLv2",
    url = "http://pytivo.sourceforge.net",
    packages = ['pytivo'],
    package_data = {'pytivo':['content/*','plugins/*/templates/*.tmpl','templates/*.tmpl']},
    data_files = [('/etc', ['pyTivo.conf'])],
    requires = ['Cheetah','mutagen','xmpp'],
    scripts = ['pyTivo'],
)
