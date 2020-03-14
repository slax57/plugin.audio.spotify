#!/usr/bin/python
# -*- coding: utf-8 -*-

'''
    plugin.audio.spotify-headless
    Unofficial Spotify client for Kodi - Headless player only
'''

import os, sys
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "resources", "lib"))
from plugin_content import PluginContent
#main entrypoint
if __name__ == "__main__":
    PluginContent()
