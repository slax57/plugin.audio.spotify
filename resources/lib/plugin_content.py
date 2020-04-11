# -*- coding: utf8 -*-
from __future__ import print_function, unicode_literals
from utils import log_msg, log_exception, ADDON_ID, PROXY_PORT, get_chunks, get_track_rating, parse_spotify_track, get_playername, KODI_VERSION, request_token_web
import urlparse
import urllib
import threading
import thread
import time
import spotipy
import xbmc
import sys
import xbmcaddon
import xbmcplugin
import xbmcgui
import xbmcvfs
from simplecache import SimpleCache
from player_monitor import ConnectPlayer


class PluginContent():

    action = ""
    sp = None
    userid = ""
    usercountry = ""
    offset = 0
    playlistid = ""
    albumid = ""
    trackid = ""
    artistid = ""
    artistname = ""
    ownerid = ""
    filter = ""
    token = ""
    limit = 50
    params = {}
    base_url = sys.argv[0]
    addon_handle = int(sys.argv[1])
    _cache_checksum = ""
    last_playlist_position = 0

    def __init__(self):
        try:
            self.addon = xbmcaddon.Addon(id=ADDON_ID)
            self.win = xbmcgui.Window(10000)
            self.cache = SimpleCache()
            auth_token = self.get_authkey()
            if auth_token:
                self.parse_params()
                self.sp = spotipy.Spotify(auth=auth_token)
                self.userid = self.win.getProperty("spotify-username").decode("utf-8")
                self.usercountry = self.win.getProperty("spotify-country").decode("utf-8")
                self.local_playback, self.playername, self.connect_id = self.active_playback_device()
                if self.action:
                    action = "self." + self.action
                    eval(action)()
                else:
                    self.browse_main()
            else:
                xbmcplugin.endOfDirectory(handle=self.addon_handle)
        except Exception as exc:
            log_exception(__name__, exc)
            xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def get_authkey(self):
        '''get authentication key'''
        auth_token = None
        count = 10
        while not auth_token and count: # wait max 5 seconds for the token
            auth_token = self.win.getProperty("spotify-token").decode("utf-8")
            count -= 1
            if not auth_token:
                xbmc.sleep(500)
        if not auth_token:
            if self.win.getProperty("spotify.supportsplayback"):
                if self.win.getProperty("spotify-discovery") == "disabled":
                    msg = self.addon.getLocalizedString(11050)
                else:
                    msg = self.addon.getLocalizedString(11065)
                dialog = xbmcgui.Dialog()
                header = self.addon.getAddonInfo("name")
                dialog.ok(header, msg)
                del dialog
            else:
                # login with browser
                request_token_web(force=True)
                self.win.setProperty("spotify-cmd", "__LOGOUT__")
        return auth_token

    def parse_params(self):
        '''parse parameters from the plugin entry path'''
        self.params = urlparse.parse_qs(sys.argv[2][1:])
        action = self.params.get("action", None)
        if action:
            self.action = action[0].lower().decode("utf-8")
        # default settings
        self.append_artist_to_title = self.addon.getSetting("appendArtistToTitle") == "true"

    def switch_user(self):
        '''switch or logout user'''
        return self.logoff_user()

    def logoff_user(self):
        ''' logoff user '''
        dialog = xbmcgui.Dialog()
        if dialog.yesno(self.addon.getLocalizedString(11066), self.addon.getLocalizedString(11067)):
            xbmcvfs.delete("special://profile/addon_data/%s/credentials.json" % ADDON_ID)
            xbmcvfs.delete("special://profile/addon_data/%s/spotipy.cache" % ADDON_ID)
            self.win.clearProperty("spotify-token")
            self.win.clearProperty("spotify-username")
            self.win.clearProperty("spotify-country")
            self.addon.setSetting("username", "")
            self.addon.setSetting("password", "")
            self.win.setProperty("spotify-cmd", "__LOGOUT__")
            xbmc.executebuiltin("Container.Refresh")
        del dialog

    def browse_main(self):
        # main listing
        xbmcplugin.setContent(self.addon_handle, "files")
        items = []
        cur_user_label = self.sp.me()["display_name"]
        if not cur_user_label:
            cur_user_label = self.sp.me()["id"]
        label = "%s: %s" % (self.addon.getLocalizedString(11047), cur_user_label)
        items.append(
            (label,
             "plugin://plugin.audio.spotify-headless/?action=switch_user",
             "DefaultActor.png", False))
        for item in items:
            li = xbmcgui.ListItem(
                item[0],
                path=item[1],
                iconImage=item[2]
            )
            li.setProperty('IsPlayable', 'false')
            li.setArt({"fanart": "special://home/addons/plugin.audio.spotify-headless/fanart.jpg"})
            li.addContextMenuItems([], True)
            xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=item[1], listitem=li, isFolder=item[3])
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def active_playback_device(self):
        '''always return local playback if supported'''
        playback = self.addon.getSetting("playback_device")
        
        if not playback:
            # check if local playback if supported
            if not self.win.getProperty("spotify.supportsplayback"):
                msg = self.addon.getLocalizedString(11068)
                dialog = xbmcgui.Dialog()
                header = self.addon.getAddonInfo("name")
                dialog.ok(header, msg)
                del dialog

            self.addon.setSetting("playback_device", "local")

        connect_id = ""
        is_local = True
        devicename = self.addon.getLocalizedString(11037)
        
        return is_local, devicename, connect_id


