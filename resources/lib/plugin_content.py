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

    def refresh_connected_device(self):
        '''set reconnect flag for main_loop'''
        if self.addon.getSetting("playback_device") == "connect":
            self.win.setProperty("spotify-cmd", "__RECONNECT__")

    def switch_user(self):
        '''switch or logout user'''
        if self.addon.getSetting("multi_account") == "true":
            return self.switch_user_multi()
        else:
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

    def next_track(self):
        '''special entry which tells the remote connect player to move to the next track'''
        
        cur_playlist_position = xbmc.PlayList(xbmc.PLAYLIST_MUSIC).getposition()
        # prevent unintentional skipping when Kodi track ends before connect player
        # playlist position will increse only when play next button is pressed
        if cur_playlist_position > self.last_playlist_position:
            # move to next track
            self.sp.next_track()
            # give time for connect player to update info
            xbmc.sleep(300)
            
        self.last_playlist_position = cur_playlist_position
        cur_playback = self.sp.current_playback()
        trackdetails = cur_playback["item"]
        url, li = parse_spotify_track(trackdetails, silenced=True)
        xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, li)

    def play_connect(self):
        '''start local connect playback - called from webservice when local connect player starts playback'''
        playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        trackdetails = None
        count = 0
        while not trackdetails and count < 10:
            try:
                cur_playback = self.sp.current_playback()
                trackdetails = cur_playback["item"]
            except:
                count += 1
                xbmc.sleep(500)
        if not trackdetails:
            log_msg("Could not retrieve trackdetails from api, connect playback aborted", xbmc.LOGERROR)
        else:
            url, li = parse_spotify_track(trackdetails, silenced=False, is_connect=True)
            playlist.clear()
            playlist.add(url, li)
            playlist.add("http://localhost:%s/nexttrack" % PROXY_PORT)
            player = xbmc.Player()
            player.play(playlist)
            del playlist
            del player

    def browse_main(self):
        # main listing
        xbmcplugin.setContent(self.addon_handle, "files")
        items = []
        items.append(
            ("%s: %s" % (self.addon.getLocalizedString(11039), self.playername),
             "plugin://plugin.audio.spotify-headless/?action=browse_playback_devices",
             "DefaultMusicPlugins.png", True))
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
        self.refresh_connected_device()

    def set_playback_device(self):
        '''set the active playback device'''
        deviceid = self.params["deviceid"][0]
        if deviceid == "local":
            self.addon.setSetting("playback_device", "local")
        elif deviceid == "remote":
            headertxt = self.addon.getLocalizedString(11039)
            bodytxt = self.addon.getLocalizedString(11061)
            dialog = xbmcgui.Dialog()
            dialog.textviewer(headertxt, bodytxt)
            result = dialog.input(self.addon.getLocalizedString(11062))
            if result:
                self.addon.setSetting("playback_device", "remote")
                self.addon.setSetting("connect_id", result)
            del dialog
        elif deviceid == "squeezebox":
            self.addon.setSetting("playback_device", "squeezebox")
        else:
            cur_playback = self.sp.current_playback()
            self.sp.transfer_playback(deviceid, False)
            # resume play if connect player was playing berfore transfer_playback
            if cur_playback and cur_playback["is_playing"]:
                self.sp.start_playback()
            self.addon.setSetting("playback_device", "connect")
            self.addon.setSetting("connect_id", deviceid)

        self.refresh_connected_device()
        xbmc.executebuiltin("Container.Refresh")

    def browse_playback_devices(self):
        '''set the active playback device'''
        xbmcplugin.setContent(self.addon_handle, "files")
        items = []
        if self.win.getProperty("spotify.supportsplayback"):
            # local playback
            label = self.addon.getLocalizedString(11037)
            if self.local_playback:
                label += " [%s]" % self.addon.getLocalizedString(11040)
            url = "plugin://plugin.audio.spotify-headless/?action=set_playback_device&deviceid=local"
            li = xbmcgui.ListItem(label, iconImage="DefaultMusicCompilations.png")
            li.setProperty("isPlayable", "false")
            li.setArt({"fanart": "special://home/addons/plugin.audio.spotify-headless/fanart.jpg"})
            li.addContextMenuItems([], True)
            xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=url, listitem=li, isFolder=False)
        else:
            # local playback using a remote service
            label = self.addon.getLocalizedString(11060)
            if self.addon.getSetting("playback_device") == "remote":
                label += " [%s]" % self.addon.getLocalizedString(11040)
            url = "plugin://plugin.audio.spotify-headless/?action=set_playback_device&deviceid=remote"
            li = xbmcgui.ListItem(label, iconImage="DefaultMusicCompilations.png")
            li.setProperty("isPlayable", "false")
            li.setArt({"fanart": "special://home/addons/plugin.audio.spotify-headless/fanart.jpg"})
            li.addContextMenuItems([], True)
            xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=url, listitem=li, isFolder=False)
        # connect devices
        for device in self.sp.devices()["devices"]:
            label = "Spotify Connect: %s" % device["name"]
            if device["is_active"] and self.addon.getSetting("playback_device") == "connect":
                label += " [%s]" % self.addon.getLocalizedString(11040)
                self.refresh_connected_device()
            url = "plugin://plugin.audio.spotify-headless/?action=set_playback_device&deviceid=%s" % device["id"]
            li = xbmcgui.ListItem(label, iconImage="DefaultMusicCompilations.png")
            li.setProperty("isPlayable", "false")
            li.setArt({"fanart": "special://home/addons/plugin.audio.spotify-headless/fanart.jpg"})
            li.addContextMenuItems([], True)
            xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=url, listitem=li, isFolder=False)
        if xbmc.getCondVisibility("System.HasAddon(plugin.audio.squeezebox)"):
            # LMS playback
            label = xbmc.getInfoLabel("System.AddonTitle(plugin.audio.squeezebox)")
            if self.addon.getSetting("playback_device") == "squeezebox":
                label += " [%s]" % self.addon.getLocalizedString(11040)
            url = "plugin://plugin.audio.spotify-headless/?action=set_playback_device&deviceid=squeezebox"
            li = xbmcgui.ListItem(label, iconImage="DefaultMusicCompilations.png")
            li.setProperty("isPlayable", "false")
            li.setArt({"fanart": "special://home/addons/plugin.audio.spotify-headless/fanart.jpg"})
            li.addContextMenuItems([], True)
            xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=url, listitem=li, isFolder=False)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def active_playback_device(self):
        '''determine if we should use local playback or connect playback'''
        playback = self.addon.getSetting("playback_device")
        connect_id = ""
        if not playback:
            # set default to local playback if supported
            if self.win.getProperty("spotify.supportsplayback"):
                playback = "local"
            else:
                playback = "connect"
            self.addon.setSetting("playback_device", playback)
        # set device name
        if playback == "local":
            is_local = True
            devicename = self.addon.getLocalizedString(11037)
        elif playback == "remote":
            is_local = True
            connect_id = self.addon.getSetting("connect_id")
            devicename = self.addon.getLocalizedString(11063) % connect_id
        elif playback == "squeezebox":
            is_local = False
            devicename = xbmc.getInfoLabel("System.AddonTitle(plugin.audio.squeezebox)")
        else:
            is_local = False
            devicename = "Spotify Connect"  # placeholder value
            for device in self.sp.devices()["devices"]:
                if device["is_active"]:
                    devicename = device["name"]
        return is_local, devicename, connect_id


