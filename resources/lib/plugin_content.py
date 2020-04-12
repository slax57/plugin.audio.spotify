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
    base_url = "plugin://plugin.audio.spotify-headless/" # sys.argv[0]
    addon_handle = int(sys.argv[1])
    _cache_checksum = ""
    last_playlist_position = 0

    def __init__(self):
        try:
            self.addon = xbmcaddon.Addon(id=ADDON_ID)
            self.win = xbmcgui.Window(10000)
            self.__init_cache()
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
                    self.precache_library()
            else:
                xbmcplugin.endOfDirectory(handle=self.addon_handle)
        except Exception as exc:
            log_exception(__name__, exc)
            xbmcplugin.endOfDirectory(handle=self.addon_handle)
    
    def __init_cache(self):
        self.cache = SimpleCache()
        if not self.addon.getSetting("enable_memory_cache") == "true":
            self.cache.enable_mem_cache = False

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
        playlistid = self.params.get("playlistid", None)
        if playlistid:
            self.playlistid = playlistid[0].decode("utf-8")
        ownerid = self.params.get("ownerid", None)
        if ownerid:
            self.ownerid = ownerid[0].decode("utf-8")
        trackid = self.params.get("trackid", None)
        if trackid:
            self.trackid = trackid[0].decode("utf-8")
        albumid = self.params.get("albumid", None)
        if albumid:
            self.albumid = albumid[0].decode("utf-8")
        artistid = self.params.get("artistid", None)
        if artistid:
            self.artistid = artistid[0].decode("utf-8")
        artistname = self.params.get("artistname", None)
        if artistname:
            self.artistname = artistname[0].decode("utf-8")
        offset = self.params.get("offset", None)
        if offset:
            self.offset = int(offset[0])
        filter = self.params.get("applyfilter", None)
        if filter:
            self.filter = filter[0].decode("utf-8")
        # default settings
        self.append_artist_to_title = self.addon.getSetting("appendArtistToTitle") == "true"

    def cache_checksum(self, opt_value=None):
        '''simple cache checksum based on a few most important values'''
        result = self._cache_checksum
        if not result:
            saved_tracks = self.get_saved_tracks_ids()
            saved_albums = self.get_savedalbumsids()
            followed_artists = self.get_followedartists()
            generic_checksum = self.addon.getSetting("cache_checksum")
            result = "%s-%s-%s-%s" % (len(saved_tracks), len(saved_albums), len(followed_artists), generic_checksum)
            self._cache_checksum = result
        if opt_value:
            result += "-%s" % opt_value
        return result

    def build_url(self, query):
        query_encoded = {}
        for key, value in query.iteritems():
            if isinstance(key, unicode):
                key = key.encode("utf-8")
            if isinstance(value, unicode):
                value = value.encode("utf-8")
            query_encoded[key] = value
        url = self.base_url + '?' + urllib.urlencode(query_encoded)
        log_msg("build_url - Built URL: %s" % url)
        return url

    def refresh_listing(self):
        self.addon.setSetting("cache_checksum", time.strftime("%Y%m%d%H%M%S", time.gmtime()))
        xbmc.executebuiltin("Container.Refresh")

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

    def play_track_radio(self):
        player = SpotifyRadioPlayer()
        player.set_parent(self)
        seed_track = self.sp.track(self.trackid)
        player.set_seed_tracks([seed_track])
        player.play()
        monitor = xbmc.Monitor()
        monitor.waitForAbort()

    def connect_playback(self):
        '''start playback using spotty connect abilities'''
        # handle playback with spotify connect
        # Note: the offset by trackid seems to be broken in the api so we have to use the numeric offset
        if self.offset:
            offset = {"position": self.offset}
        elif self.trackid:
            offset = {"uri": "spotify:track:%s" % self.trackid}
        else:
            offset = None
        if self.playlistid:
            context_uri = "spotify:user:%s:playlist:%s" % (self.ownerid, self.playlistid)
            self.sp.start_playback(context_uri=context_uri, offset=offset)
        elif self.albumid:
            context_uri = "spotify:album:%s" % (self.albumid)
            self.sp.start_playback(context_uri=context_uri, offset=offset)
        elif self.artistid:
            context_uri = "spotify:artist:%s" % (self.artistid)
            self.sp.start_playback(context_uri=context_uri, offset=offset)
        elif self.trackid:
            uris = ["spotify:track:%s" % self.trackid]
            self.sp.start_playback(uris=uris)

    def browse_main(self):
        # main listing
        xbmcplugin.setContent(self.addon_handle, "files")
        items = []
        items.append(
            (self.addon.getLocalizedString(11013),
             "plugin://plugin.audio.spotify-headless/?action=browse_main_library",
             "DefaultMusicCompilations.png", True))
        items.append(
            (self.addon.getLocalizedString(11014),
             "plugin://plugin.audio.spotify-headless/?action=browse_main_explore",
             "DefaultMusicGenres.png", True))
        items.append(
            (xbmc.getLocalizedString(137), # search
             "plugin://plugin.audio.spotify-headless/?action=search",
             "DefaultMusicSearch.png", True))
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

    def browse_main_library(self):
        # library nodes
        xbmcplugin.setContent(self.addon_handle, "files")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', self.addon.getLocalizedString(11013))
        items = []
        items.append(
            (xbmc.getLocalizedString(136),
             "plugin://plugin.audio.spotify-headless/?action=browse_playlists&ownerid=%s" %
             (self.userid),
                "DefaultMusicPlaylists.png"))
        items.append(
            (xbmc.getLocalizedString(132),
             "plugin://plugin.audio.spotify-headless/?action=browse_savedalbums",
             "DefaultMusicAlbums.png"))
        items.append(
            (xbmc.getLocalizedString(134),
             "plugin://plugin.audio.spotify-headless/?action=browse_savedtracks",
             "DefaultMusicSongs.png"))
        items.append(
            (xbmc.getLocalizedString(133),
             "plugin://plugin.audio.spotify-headless/?action=browse_savedartists",
             "DefaultMusicArtists.png"))
        items.append(
            (self.addon.getLocalizedString(11023),
             "plugin://plugin.audio.spotify-headless/?action=browse_topartists",
             "DefaultMusicArtists.png"))
        items.append(
            (self.addon.getLocalizedString(11024),
             "plugin://plugin.audio.spotify-headless/?action=browse_toptracks",
             "DefaultMusicSongs.png"))
        for item in items:
            li = xbmcgui.ListItem(
                item[0],
                path=item[1],
                iconImage=item[2]
            )
            li.setProperty('do_not_analyze', 'true')
            li.setProperty('IsPlayable', 'false')
            li.setArt({"fanart": "special://home/addons/plugin.audio.spotify-headless/fanart.jpg"})
            li.addContextMenuItems([], True)
            xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=item[1], listitem=li, isFolder=True)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def browse_topartists(self):
        xbmcplugin.setContent(self.addon_handle, "artists")
        result = self.sp.current_user_top_artists(limit=20, offset=0)
        cachestr = "spotify.topartists.%s" % self.userid
        checksum = self.cache_checksum(result["total"])
        items = self.cache.get(cachestr, checksum=checksum)
        if not items:
            count = len(result["items"])
            while result["total"] > count:
                result["items"] += self.sp.current_user_top_artists(limit=20, offset=count)["items"]
                count += 50
            items = self.prepare_artist_listitems(result["items"])
            self.cache.set(cachestr, items, checksum=checksum)
        self.add_artist_listitems(items)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def browse_toptracks(self):
        xbmcplugin.setContent(self.addon_handle, "songs")
        results = self.sp.current_user_top_tracks(limit=20, offset=0)
        cachestr = "spotify.toptracks.%s" % self.userid
        checksum = self.cache_checksum(results["total"])
        items = self.cache.get(cachestr, checksum=checksum)
        if not items:
            items = results["items"]
            while results["next"]:
                results = self.sp.next(results)
                items.extend(results["items"])
            items = self.prepare_track_listitems(tracks=items)
            self.cache.set(cachestr, items, checksum=checksum)
        self.add_track_listitems(items, True)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def get_explore_categories(self):
        items = []
        categories = self.sp.categories(country=self.usercountry, limit=50, locale=self.usercountry)
        count = len(categories["categories"]["items"])
        while categories["categories"]["total"] > count:
            categories["categories"]["items"] += self.sp.categories(
                country=self.usercountry, limit=50, offset=count, locale=self.usercountry)["categories"]["items"]
            count += 50
        for item in categories["categories"]["items"]:
            thumb = "DefaultMusicGenre.png"
            for icon in item["icons"]:
                thumb = icon["url"]
                break
            items.append(
                (item["name"],
                 "plugin://plugin.audio.spotify-headless/?action=browse_category&applyfilter=%s" %
                 (item["id"]),
                    thumb))
        return items

    def browse_main_explore(self):
        # explore nodes
        xbmcplugin.setContent(self.addon_handle, "files")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', self.addon.getLocalizedString(11014))
        items = []
        items.append(
            (self.addon.getLocalizedString(11015),
             "plugin://plugin.audio.spotify-headless/?action=browse_playlists&applyfilter=featured",
             "DefaultMusicPlaylists.png"))
        items.append(
            (self.addon.getLocalizedString(11016),
             "plugin://plugin.audio.spotify-headless/?action=browse_newreleases",
             "DefaultMusicAlbums.png"))

        # add categories
        items += self.get_explore_categories()

        for item in items:
            li = xbmcgui.ListItem(
                item[0],
                path=item[1],
                iconImage=item[2]
            )
            li.setProperty('do_not_analyze', 'true')
            li.setProperty('IsPlayable', 'false')
            li.setArt({"fanart": "special://home/addons/plugin.audio.spotify-headless/fanart.jpg"})
            li.addContextMenuItems([], True)
            xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=item[1], listitem=li, isFolder=True)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def get_album_tracks(self, album):
        count = 0
        cachestr = "spotify.albumtracks.%s" % album["id"]
        checksum = self.cache_checksum()
        album_tracks = self.cache.get(cachestr, checksum=checksum)
        if not album_tracks:
            trackids = []
            while album["tracks"]["total"] > count:
                albumtracks = self.sp.album_tracks(
                    album["id"], market=self.usercountry, limit=50, offset=count)["items"]
                for track in albumtracks:
                    trackids.append(track["id"])
                count += 50
            album_tracks = self.prepare_track_listitems(trackids, albumdetails=album)
            self.cache.set(cachestr, album_tracks, checksum=checksum)
        return album_tracks

    def browse_album(self):
        xbmcplugin.setContent(self.addon_handle, "songs")
        album = self.sp.album(self.albumid, market=self.usercountry)
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', album["name"])
        tracks = self.get_album_tracks(album)
        if album.get("album_type") == "compilation":
            self.add_track_listitems(tracks, True)
        else:
            self.add_track_listitems(tracks)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_TRACKNUM)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_TITLE)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_SONG_RATING)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_ARTIST)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def artist_toptracks(self):
        xbmcplugin.setContent(self.addon_handle, "songs")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', self.addon.getLocalizedString(11011))
        tracks = self.sp.artist_top_tracks(self.artistid, country=self.usercountry)
        tracks = self.prepare_track_listitems(tracks=tracks["tracks"])
        self.add_track_listitems(tracks)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_TRACKNUM)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_TITLE)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_SONG_RATING)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def related_artists(self):
        xbmcplugin.setContent(self.addon_handle, "artists")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', self.addon.getLocalizedString(11012))
        cachestr = "spotify.relatedartists.%s" % self.artistid
        checksum = self.cache_checksum()
        artists = self.cache.get(cachestr, checksum=checksum)
        if not artists:
            artists = self.sp.artist_related_artists(self.artistid)
            artists = self.prepare_artist_listitems(artists['artists'])
            self.cache.set(cachestr, artists, checksum=checksum)
        self.add_artist_listitems(artists)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def get_playlist_details(self, ownerid, playlistid):
        playlist = self.sp.user_playlist(ownerid, playlistid, market=self.usercountry,
                                         fields="tracks(total),name,owner(id),id")
        # get from cache first
        cachestr = "spotify.playlistdetails.%s" % playlist["id"]
        checksum = self.cache_checksum(playlist["tracks"]["total"])
        playlistdetails = self.cache.get(cachestr, checksum=checksum)
        if not playlistdetails:
            # get listing from api
            count = 0
            playlistdetails = playlist
            playlistdetails["tracks"]["items"] = []
            while playlist["tracks"]["total"] > count:
                playlistdetails["tracks"]["items"] += self.sp.user_playlist_tracks(
                    playlist["owner"]["id"], playlist["id"], market=self.usercountry, fields="", limit=50, offset=count)["items"]
                count += 50
            playlistdetails["tracks"]["items"] = self.prepare_track_listitems(
                tracks=playlistdetails["tracks"]["items"], playlistdetails=playlist)
            self.cache.set(cachestr, playlistdetails, checksum=checksum)
        return playlistdetails

    def browse_playlist(self):
        xbmcplugin.setContent(self.addon_handle, "songs")
        playlistdetails = self.get_playlist_details(self.ownerid, self.playlistid)
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', playlistdetails["name"])
        self.add_track_listitems(playlistdetails["tracks"]["items"], True)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def play_playlist(self):
        '''play entire playlist'''
        playlistdetails = self.get_playlist_details(self.ownerid, self.playlistid)
        kodi_playlist = xbmc.PlayList(0)
        kodi_playlist.clear()
        kodi_player = xbmc.Player()
        # add first track and start playing
        url, li = parse_spotify_track(playlistdetails["tracks"]["items"][0])
        kodi_playlist.add(url, li)
        kodi_player.play(kodi_playlist)
        # add remaining tracks to the playlist while already playing
        for track in playlistdetails["tracks"]["items"][1:]:
            url, li = parse_spotify_track(track)
            kodi_playlist.add(url, li)

    def get_category(self, categoryid):
        category = self.sp.category(categoryid, country=self.usercountry, locale=self.usercountry)
        playlists = self.sp.category_playlists(categoryid, country=self.usercountry, limit=50, offset=0)
        playlists['category'] = category["name"]
        count = len(playlists['playlists']['items'])
        while playlists['playlists']['total'] > count:
            playlists['playlists']['items'] += self.sp.category_playlists(
                categoryid, country=self.usercountry, limit=50, offset=count)['playlists']['items']
            count += 50
        playlists['playlists']['items'] = self.prepare_playlist_listitems(playlists['playlists']['items'])
        return playlists

    def browse_category(self):
        xbmcplugin.setContent(self.addon_handle, "files")
        playlists = self.get_category(self.filter)
        self.add_playlist_listitems(playlists['playlists']['items'])
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', playlists['category'])
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def follow_playlist(self):
        result = self.sp.follow_playlist(self.ownerid, self.playlistid)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def add_track_to_playlist(self):
        xbmc.executebuiltin("ActivateWindow(busydialog)")

        if not self.trackid and xbmc.getInfoLabel("MusicPlayer.(1).Property(spotifytrackid)"):
            self.trackid = xbmc.getInfoLabel("MusicPlayer.(1).Property(spotifytrackid)")

        playlists = self.sp.user_playlists(self.userid, limit=50, offset=0)
        ownplaylists = []
        ownplaylistnames = []
        for playlist in playlists['items']:
            if playlist["owner"]["id"] == self.userid:
                ownplaylists.append(playlist)
                ownplaylistnames.append(playlist["name"])
        ownplaylistnames.append(xbmc.getLocalizedString(525))
        xbmc.executebuiltin("Dialog.Close(busydialog)")
        select = xbmcgui.Dialog().select(xbmc.getLocalizedString(524), ownplaylistnames)
        if select != -1 and ownplaylistnames[select] == xbmc.getLocalizedString(525):
            # create new playlist...
            kb = xbmc.Keyboard('', xbmc.getLocalizedString(21381))
            kb.setHiddenInput(False)
            kb.doModal()
            if kb.isConfirmed():
                name = kb.getText()
                playlist = self.sp.user_playlist_create(self.userid, name, False)
                self.sp.user_playlist_add_tracks(self.userid, playlist["id"], [self.trackid])
        elif select != -1:
            playlist = ownplaylists[select]
            self.sp.user_playlist_add_tracks(self.userid, playlist["id"], [self.trackid])

    def remove_track_from_playlist(self):
        self.sp.user_playlist_remove_all_occurrences_of_tracks(self.userid, self.playlistid, [self.trackid])
        self.refresh_listing()

    def unfollow_playlist(self):
        self.sp.unfollow_playlist(self.ownerid, self.playlistid)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def follow_artist(self):
        result = self.sp.follow("artist", self.artistid)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def unfollow_artist(self):
        self.sp.unfollow("artist", self.artistid)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def save_album(self):
        result = self.sp.current_user_saved_albums_add([self.albumid])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def remove_album(self):
        result = self.sp.current_user_saved_albums_delete([self.albumid])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def save_track(self):
        result = self.sp.current_user_saved_tracks_add([self.trackid])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def remove_track(self):
        result = self.sp.current_user_saved_tracks_delete([self.trackid])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def follow_user(self):
        result = self.sp.follow("user", self.userid)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def unfollow_user(self):
        self.sp.unfollow("user", self.userid)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def get_featured_playlists(self):
        playlists = self.sp.featured_playlists(country=self.usercountry, limit=50, offset=0)
        count = len(playlists['playlists']['items'])
        total = playlists['playlists']['total']
        while total > count:
            playlists['playlists'][
                'items'] += self.sp.featured_playlists(country=self.usercountry, limit=50, offset=count)['playlists']['items']
            count += 50
        playlists['playlists']['items'] = self.prepare_playlist_listitems(playlists['playlists']['items'])
        return playlists

    def get_user_playlists(self, userid):
        playlists = self.sp.user_playlists(userid, limit=1, offset=0)
        count = len(playlists['items'])
        total = playlists['total']
        cachestr = "spotify.userplaylists.%s" % userid
        checksum = self.cache_checksum(total)
        cache = self.cache.get(cachestr, checksum=checksum)
        if cache:
            playlists = cache
        else:
            while total > count:
                playlists["items"] += self.sp.user_playlists(userid, limit=50, offset=count)["items"]
                count += 50
            playlists = self.prepare_playlist_listitems(playlists['items'])
            self.cache.set(cachestr, playlists, checksum=checksum)
        return playlists

    def get_curuser_playlistids(self):
        playlistids = []
        playlists = self.sp.current_user_playlists(limit=1, offset=0)
        count = len(playlists['items'])
        total = playlists['total']
        cachestr = "spotify.userplaylistids.%s" % self.userid
        playlistids = self.cache.get(cachestr, checksum=total)
        if not playlistids:
            playlistids = []
            while total > count:
                playlists["items"] += self.sp.current_user_playlists(limit=50, offset=count)["items"]
                count += 50
            for playlist in playlists["items"]:
                playlistids.append(playlist["id"])
            self.cache.set(cachestr, playlistids, checksum=total)
        return playlistids

    def browse_playlists(self):
        xbmcplugin.setContent(self.addon_handle, "files")
        if self.filter == "featured":
            playlists = self.get_featured_playlists()
            xbmcplugin.setProperty(self.addon_handle, 'FolderName', playlists['message'])
            playlists = playlists['playlists']['items']
        else:
            xbmcplugin.setProperty(self.addon_handle, 'FolderName', xbmc.getLocalizedString(136))
            playlists = self.get_user_playlists(self.ownerid)

        self.add_playlist_listitems(playlists)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def get_newreleases(self):
        albums = self.sp.new_releases(country=self.usercountry, limit=50, offset=0)
        count = len(albums['albums']['items'])
        while albums["albums"]["total"] > count:
            albums['albums'][
                'items'] += self.sp.new_releases(country=self.usercountry, limit=50, offset=count)['albums']['items']
            count += 50
        albumids = []
        for album in albums['albums']['items']:
            albumids.append(album["id"])
        albums = self.prepare_album_listitems(albumids)
        return albums

    def browse_newreleases(self):
        xbmcplugin.setContent(self.addon_handle, "albums")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', self.addon.getLocalizedString(11005))
        albums = self.get_newreleases()
        self.add_album_listitems(albums)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def prepare_track_listitems(self, trackids=[], tracks=[], playlistdetails=None, albumdetails=None):
        newtracks = []
        # for tracks we always get the full details unless full tracks already supplied
        if trackids and not tracks:
            chunks = get_chunks(trackids, 20)
            for chunk in get_chunks(trackids, 20):
                tracks += self.sp.tracks(chunk, market=self.usercountry)['tracks']

        savedtracks = self.get_saved_tracks_ids()

        followedartists = []
        for artist in self.get_followedartists():
            followedartists.append(artist["id"])

        for track in tracks:

            if track.get('track'):
                track = track['track']
            if albumdetails:
                track["album"] = albumdetails
            if track.get("images"):
                thumb = track["images"][0]['url']
            elif track['album'].get("images"):
                thumb = track['album']["images"][0]['url']
            else:
                thumb = "DefaultMusicSongs.png"
            track['thumb'] = thumb

            # skip local tracks in playlists
            if not track['id']:
                continue

            artists = []
            for artist in track['artists']:
                artists.append(artist["name"])
            track["artist"] = " / ".join(artists)
            track["genre"] = " / ".join(track["album"].get("genres", []))
            track["year"] = int(track["album"].get("release_date", "0").split("-")[0])
            track["rating"] = str(get_track_rating(track["popularity"]))
            if playlistdetails:
                track["playlistid"] = playlistdetails["id"]
            track["artistid"] = track['artists'][0]['id']

            # use original trackid for actions when the track was relinked
            if track.get("linked_from"):
                real_trackid = track["linked_from"]["id"]
                real_trackuri = track["linked_from"]["uri"]
            else:
                real_trackid = track["id"]
                real_trackuri = track["uri"]

            contextitems = []
            if track["id"] in savedtracks:
                contextitems.append(
                    (self.addon.getLocalizedString(11008),
                     "RunPlugin(plugin://plugin.audio.spotify-headless/?action=remove_track&trackid=%s)" %
                     (real_trackid)))
            else:
                contextitems.append(
                    (self.addon.getLocalizedString(11007),
                     "RunPlugin(plugin://plugin.audio.spotify-headless/?action=save_track&trackid=%s)" %
                     (real_trackid)))

            if self.local_playback:
                contextitems.append(
                    (self.addon.getLocalizedString(11035),
                     "RunPlugin(plugin://plugin.audio.spotify-headless/?action=play_track_radio&trackid=%s)" %
                     (real_trackid)))

            if playlistdetails and playlistdetails["owner"]["id"] == self.userid:
                contextitems.append(
                    ("%s %s" %(self.addon.getLocalizedString(11017), playlistdetails["name"]),
                     "RunPlugin(plugin://plugin.audio.spotify-headless/?action=remove_track_from_playlist&trackid=%s&playlistid=%s)" %
                     (real_trackuri,
                      playlistdetails["id"])))

            contextitems.append(
                (xbmc.getLocalizedString(526),
                 "RunPlugin(plugin://plugin.audio.spotify-headless/?action=add_track_to_playlist&trackid=%s)" %
                 real_trackuri))

            contextitems.append(
                (self.addon.getLocalizedString(11011),
                 "Container.Update(plugin://plugin.audio.spotify-headless/?action=artist_toptracks&artistid=%s)" %
                 track["artistid"]))
            contextitems.append(
                (self.addon.getLocalizedString(11012),
                 "Container.Update(plugin://plugin.audio.spotify-headless/?action=related_artists&artistid=%s)" %
                 track["artistid"]))
            contextitems.append(
                (self.addon.getLocalizedString(11018),
                 "Container.Update(plugin://plugin.audio.spotify-headless/?action=browse_artistalbums&artistid=%s)" %
                 track["artistid"]))

            if track["artistid"] in followedartists:
                # unfollow artist
                contextitems.append(
                    (self.addon.getLocalizedString(11026),
                     "RunPlugin(plugin://plugin.audio.spotify-headless/?action=unfollow_artist&artistid=%s)" %
                     track["artistid"]))
            else:
                # follow artist
                contextitems.append(
                    (self.addon.getLocalizedString(11025),
                     "RunPlugin(plugin://plugin.audio.spotify-headless/?action=follow_artist&artistid=%s)" %
                     track["artistid"]))

            contextitems.append((self.addon.getLocalizedString(11027),
                                 "RunPlugin(plugin://plugin.audio.spotify-headless/?action=refresh_listing)"))
            track["contextitems"] = contextitems
            newtracks.append(track)

        return newtracks

    def add_track_listitems(self, tracks, append_artist_to_label=False):
        list_items = []
        for count, track in enumerate(tracks):

            if append_artist_to_label:
                label = "%s - %s" % (track["artist"], track['name'])
            else:
                label = track['name']
            duration = track["duration_ms"] / 1000

            if KODI_VERSION > 17:
                li = xbmcgui.ListItem(label, offscreen=True)
            else:
                li = xbmcgui.ListItem(label)
            
            # local playback by using proxy on this machine
            url = "http://localhost:%s/track/%s/%s" % (PROXY_PORT, track['id'], duration)
            li.setProperty("isPlayable", "true")

            if self.append_artist_to_title:
                title = label
            else:
                title = track['name']

            li.setInfo('music', {
                "title": title,
                "genre": track["genre"],
                "year": track["year"],
                "tracknumber": track["track_number"],
                "album": track['album']["name"],
                "artist": track["artist"],
                "rating": track["rating"],
                "duration": duration
            })
            li.setArt({"thumb": track['thumb']})
            li.setProperty("spotifytrackid", track['id'])
            li.setContentLookup(False)
            li.addContextMenuItems(track["contextitems"], True)
            li.setProperty('do_not_analyze', 'true')
            li.setMimeType("audio/wave")
            list_items.append((url, li, False))
        xbmcplugin.addDirectoryItems(self.addon_handle, list_items, totalItems=len(list_items))

    def prepare_album_listitems(self, albumids=[], albums=[]):

        if not albums and albumids:
            # get full info in chunks of 20
            chunks = get_chunks(albumids, 20)
            for chunk in get_chunks(albumids, 20):
                albums += self.sp.albums(chunk, market=self.usercountry)['albums']

        savedalbums = self.get_savedalbumsids()

        # process listing
        for item in albums:
            if item.get("images"):
                item['thumb'] = item["images"][0]['url']
            else:
                item['thumb'] = "DefaultMusicAlbums.png"

            item['url'] = self.build_url({'action': 'browse_album', 'albumid': item['id']})

            artists = []
            for artist in item['artists']:
                artists.append(artist["name"])
            item['artist'] = " / ".join(artists)
            item["genre"] = " / ".join(item["genres"])
            item["year"] = int(item["release_date"].split("-")[0])
            item["rating"] = str(get_track_rating(item["popularity"]))
            item["artistid"] = item['artists'][0]['id']

            contextitems = []
            # play
            contextitems.append(
                (xbmc.getLocalizedString(208),
                 "RunPlugin(plugin://plugin.audio.spotify-headless/?action=connect_playback&albumid=%s)" %
                 (item["id"])))
            contextitems.append((xbmc.getLocalizedString(1024), "RunPlugin(%s)" % item["url"]))
            if item["id"] in savedalbums:
                contextitems.append(
                    (self.addon.getLocalizedString(11008),
                     "RunPlugin(plugin://plugin.audio.spotify-headless/?action=remove_album&albumid=%s)" %
                     (item['id'])))
            else:
                contextitems.append(
                    (self.addon.getLocalizedString(11007),
                     "RunPlugin(plugin://plugin.audio.spotify-headless/?action=save_album&albumid=%s)" %
                     (item['id'])))
            contextitems.append(
                (self.addon.getLocalizedString(11011),
                 "Container.Update(plugin://plugin.audio.spotify-headless/?action=artist_toptracks&artistid=%s)" %
                 item["artistid"]))
            contextitems.append(
                (self.addon.getLocalizedString(11012),
                 "Container.Update(plugin://plugin.audio.spotify-headless/?action=related_artists&artistid=%s)" %
                 item["artistid"]))
            contextitems.append(
                (self.addon.getLocalizedString(11018),
                 "Container.Update(plugin://plugin.audio.spotify-headless/?action=browse_artistalbums&artistid=%s)" %
                 item["artistid"]))
            contextitems.append((self.addon.getLocalizedString(11027),
                                 "RunPlugin(plugin://plugin.audio.spotify-headless/?action=refresh_listing)"))
            item["contextitems"] = contextitems
        return albums

    def add_album_listitems(self, albums, append_artist_to_label=False):

        # process listing
        for item in albums:

            if append_artist_to_label:
                label = "%s - %s" % (item["artist"], item['name'])
            else:
                label = item['name']

            if KODI_VERSION > 17:
                li = xbmcgui.ListItem(label, path=item['url'], offscreen=True)
            else:
                li = xbmcgui.ListItem(label, path=item['url'])

            infolabels = {
                "title": item['name'],
                "genre": item["genre"],
                "year": item["year"],
                "album": item["name"],
                "artist": item["artist"],
                "rating": item["rating"]
            }
            li.setInfo(type="Music", infoLabels=infolabels)
            li.setArt({"thumb": item['thumb']})
            li.setProperty('do_not_analyze', 'true')
            li.setProperty('IsPlayable', 'false')
            li.addContextMenuItems(item["contextitems"], True)
            xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=item["url"], listitem=li, isFolder=True)

    def prepare_artist_listitems(self, artists, isFollowed=False):

        followedartists = []
        if not isFollowed:
            for artist in self.get_followedartists():
                followedartists.append(artist["id"])

        for item in artists:
            if not item:
                return []
            if item.get("artist"):
                item = item["artist"]
            if item.get("images"):
                item["thumb"] = item["images"][0]['url']
            else:
                item["thumb"] = "DefaultMusicArtists.png"

            item['url'] = self.build_url({'action': 'browse_artistalbums', 'artistid': item['id']})

            item["genre"] = " / ".join(item["genres"])
            item["rating"] = str(get_track_rating(item["popularity"]))
            item["followerslabel"] = "%s followers" % item["followers"]["total"]
            contextitems = []
            # play
            contextitems.append(
                (xbmc.getLocalizedString(208),
                 "RunPlugin(plugin://plugin.audio.spotify-headless/?action=connect_playback&artistid=%s)" %
                 (item["id"])))
            contextitems.append((xbmc.getLocalizedString(132), "Container.Update(%s)" % item["url"]))
            contextitems.append(
                (self.addon.getLocalizedString(11011),
                 "Container.Update(plugin://plugin.audio.spotify-headless/?action=artist_toptracks&artistid=%s)" %
                 (item['id'])))
            contextitems.append(
                (self.addon.getLocalizedString(11012),
                 "Container.Update(plugin://plugin.audio.spotify-headless/?action=related_artists&artistid=%s)" %
                 (item['id'])))
            if isFollowed or item["id"] in followedartists:
                # unfollow artist
                contextitems.append(
                    (self.addon.getLocalizedString(11026),
                     "RunPlugin(plugin://plugin.audio.spotify-headless/?action=unfollow_artist&artistid=%s)" %
                     item['id']))
            else:
                # follow artist
                contextitems.append(
                    (self.addon.getLocalizedString(11025),
                     "RunPlugin(plugin://plugin.audio.spotify-headless/?action=follow_artist&artistid=%s)" %
                     item['id']))
            item["contextitems"] = contextitems
        return artists

    def add_artist_listitems(self, artists):
        for item in artists:
            if KODI_VERSION > 17:
                li = xbmcgui.ListItem(item["name"], path=item['url'], offscreen=True)
            else:
                li = xbmcgui.ListItem(item["name"], path=item['url'])
            infolabels = {
                "title": item["name"],
                "genre": item["genre"],
                "artist": item["name"],
                "rating": item["rating"]
            }
            li.setInfo(type="Music", infoLabels=infolabels)
            li.setArt({"thumb": item['thumb']})
            li.setProperty('do_not_analyze', 'true')
            li.setProperty('IsPlayable', 'false')
            li.setLabel2(item["followerslabel"])
            li.addContextMenuItems(item["contextitems"], True)
            xbmcplugin.addDirectoryItem(
                handle=self.addon_handle,
                url=item["url"],
                listitem=li,
                isFolder=True,
                totalItems=len(artists))

    def prepare_playlist_listitems(self, playlists):
        playlists2 = []
        followed_playlists = self.get_curuser_playlistids()
        for item in playlists:

            if item.get("images"):
                item["thumb"] = item["images"][0]['url']
            else:
                item["thumb"] = "DefaultMusicAlbums.png"

            item['url'] = self.build_url(
                {'action': 'browse_playlist', 'playlistid': item['id'],
                 'ownerid': item['owner']['id']})

            contextitems = []
            # play
            contextitems.append(
                (xbmc.getLocalizedString(208),
                 "RunPlugin(plugin://plugin.audio.spotify-headless/?action=play_playlist&playlistid=%s&ownerid=%s)" %
                 (item["id"], item['owner']['id'])))
            if item['owner']['id'] != self.userid and item['id'] in followed_playlists:
                # unfollow playlist
                contextitems.append(
                    (self.addon.getLocalizedString(11010),
                     "RunPlugin(plugin://plugin.audio.spotify-headless/?action=unfollow_playlist&playlistid=%s&ownerid=%s)" %
                     (item['id'],
                      item['owner']['id'])))
            elif item['owner']['id'] != self.userid:
                # follow playlist
                contextitems.append(
                    (self.addon.getLocalizedString(11009),
                     "RunPlugin(plugin://plugin.audio.spotify-headless/?action=follow_playlist&playlistid=%s&ownerid=%s)" %
                     (item['id'],
                      item['owner']['id'])))

            contextitems.append((self.addon.getLocalizedString(11027),
                                 "RunPlugin(plugin://plugin.audio.spotify-headless/?action=refresh_listing)"))
            item["contextitems"] = contextitems
            playlists2.append(item)
        return playlists2

    def add_playlist_listitems(self, playlists):

        for item in playlists:

            if KODI_VERSION > 17:
                li = xbmcgui.ListItem(item["name"], path=item['url'], offscreen=True)
            else:
                li = xbmcgui.ListItem(item["name"], path=item['url'])
            li.setProperty('do_not_analyze', 'true')
            li.setProperty('IsPlayable', 'false')

            li.addContextMenuItems(item["contextitems"], True)
            li.setArt({"fanart": "special://home/addons/plugin.audio.spotify-headless/fanart.jpg", "thumb": item['thumb']})
            xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=item["url"], listitem=li, isFolder=True)

    def browse_artistalbums(self):
        xbmcplugin.setContent(self.addon_handle, "albums")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', xbmc.getLocalizedString(132))
        artist = self.sp.artist(self.artistid)
        artistalbums = self.sp.artist_albums(
            self.artistid,
            limit=50,
            offset=0,
            market=self.usercountry,
            album_type='album,single,compilation')
        count = len(artistalbums['items'])
        albumids = []
        while artistalbums['total'] > count:
            artistalbums['items'] += self.sp.artist_albums(self.artistid,
                                                           limit=50,
                                                           offset=count,
                                                           market=self.usercountry,
                                                           album_type='album,single,compilation')['items']
            count += 50
        for album in artistalbums['items']:
            albumids.append(album["id"])
        albums = self.prepare_album_listitems(albumids)
        self.add_album_listitems(albums)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_ALBUM_IGNORE_THE)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_SONG_RATING)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def get_savedalbumsids(self):
        albums = self.sp.current_user_saved_albums(limit=1, offset=0)
        cachestr = "spotify-savedalbumids.%s" % self.userid
        checksum = albums["total"]
        cache = self.cache.get(cachestr, checksum=checksum)
        if cache:
            return cache
        else:
            albumids = []
            if albums and albums.get("items"):
                count = len(albums["items"])
                albumids = []
                while albums["total"] > count:
                    albums["items"] += self.sp.current_user_saved_albums(limit=50, offset=count)["items"]
                    count += 50
                for album in albums["items"]:
                    albumids.append(album["album"]["id"])
                self.cache.set(cachestr, albumids, checksum=checksum)
            return albumids

    def get_savedalbums(self):
        albumids = self.get_savedalbumsids()
        cachestr = "spotify.savedalbums.%s" % self.userid
        checksum = self.cache_checksum(len(albumids))
        albums = self.cache.get(cachestr, checksum=checksum)
        if not albums:
            albums = self.prepare_album_listitems(albumids)
            self.cache.set(cachestr, albums, checksum=checksum)
        return albums

    def browse_savedalbums(self):
        xbmcplugin.setContent(self.addon_handle, "albums")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', xbmc.getLocalizedString(132))
        albums = self.get_savedalbums()
        self.add_album_listitems(albums, True)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_ALBUM_IGNORE_THE)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_SONG_RATING)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        xbmcplugin.setContent(self.addon_handle, "albums")

    def get_saved_tracks_ids(self):
        saved_tracks = self.sp.current_user_saved_tracks(
            limit=1, offset=self.offset, market=self.usercountry)
        total = saved_tracks["total"]
        cachestr = "spotify.savedtracksids.%s" % self.userid
        cache = self.cache.get(cachestr, checksum=total)
        if cache:
            return cache
        else:
            # get from api
            trackids = []
            count = len(saved_tracks["items"])
            while total > count:
                saved_tracks[
                    "items"] += self.sp.current_user_saved_tracks(limit=50, offset=count, market=self.usercountry)["items"]
                count += 50
            for track in saved_tracks["items"]:
                trackids.append(track["track"]["id"])
            self.cache.set(cachestr, trackids, checksum=total)
        return trackids

    def get_saved_tracks(self):
        # get from cache first
        trackids = self.get_saved_tracks_ids()
        cachestr = "spotify.savedtracks.%s" % self.userid
        tracks = self.cache.get(cachestr, checksum=len(trackids))
        if not tracks:
            # get from api
            tracks = self.prepare_track_listitems(trackids)
            self.cache.set(cachestr, tracks, checksum=len(trackids))
        return tracks

    def browse_savedtracks(self):
        xbmcplugin.setContent(self.addon_handle, "songs")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', xbmc.getLocalizedString(134))
        tracks = self.get_saved_tracks()
        self.add_track_listitems(tracks, True)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def get_savedartists(self):
        saved_albums = self.get_savedalbums()
        followed_artists = self.get_followedartists()
        cachestr = "spotify.savedartists.%s" % self.userid
        checksum = len(saved_albums) + len(followed_artists)
        artists = self.cache.get(cachestr, checksum=checksum)
        if not artists:
            allartistids = []
            artists = []
            # extract the artists from all saved albums
            for item in saved_albums:
                for artist in item["artists"]:
                    if artist["id"] not in allartistids:
                        allartistids.append(artist["id"])
            for chunk in get_chunks(allartistids, 50):
                artists += self.prepare_artist_listitems(self.sp.artists(chunk)['artists'])
            # append artists that are followed
            for artist in followed_artists:
                if not artist["id"] in allartistids:
                    artists.append(artist)
            self.cache.set(cachestr, artists, checksum=checksum)
        return artists

    def browse_savedartists(self):
        xbmcplugin.setContent(self.addon_handle, "artists")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', xbmc.getLocalizedString(133))
        artists = self.get_savedartists()
        self.add_artist_listitems(artists)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_TITLE)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def get_followedartists(self):
        artists = self.sp.current_user_followed_artists(limit=50)
        cachestr = "spotify.followedartists.%s" % self.userid
        checksum = artists["artists"]["total"]
        cache = self.cache.get(cachestr, checksum=checksum)
        if cache:
            artists = cache
        else:
            count = len(artists['artists']['items'])
            after = artists['artists']['cursors']['after']
            while artists['artists']['total'] > count:
                result = self.sp.current_user_followed_artists(limit=50, after=after)
                artists['artists']['items'] += result['artists']['items']
                after = result['artists']['cursors']['after']
                count += 50
            artists = self.prepare_artist_listitems(artists['artists']['items'], isFollowed=True)
            self.cache.set(cachestr, artists, checksum=checksum)
        return artists

    def browse_followedartists(self):
        xbmcplugin.setContent(self.addon_handle, "artists")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', xbmc.getLocalizedString(133))
        artists = self.get_followedartists()
        self.add_artist_listitems(artists)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def search_artists(self):
        xbmcplugin.setContent(self.addon_handle, "artists")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', xbmc.getLocalizedString(133))
        result = self.sp.search(
            q="artist:%s" %
            self.artistid,
            type='artist',
            limit=self.limit,
            offset=self.offset,
            market=self.usercountry)
        artists = self.prepare_artist_listitems(result['artists']['items'])
        self.add_artist_listitems(artists)
        self.add_next_button(result['artists']['total'])
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def search_tracks(self):
        xbmcplugin.setContent(self.addon_handle, "songs")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', xbmc.getLocalizedString(134))
        result = self.sp.search(
            q="track:%s" %
            self.trackid,
            type='track',
            limit=self.limit,
            offset=self.offset,
            market=self.usercountry)
        tracks = self.prepare_track_listitems(tracks=result["tracks"]["items"])
        self.add_track_listitems(tracks, True)
        self.add_next_button(result['tracks']['total'])
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def search_albums(self):
        xbmcplugin.setContent(self.addon_handle, "albums")
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', xbmc.getLocalizedString(132))
        result = self.sp.search(
            q="album:%s" %
            self.albumid,
            type='album',
            limit=self.limit,
            offset=self.offset,
            market=self.usercountry)
        albumids = []
        for album in result['albums']['items']:
            albumids.append(album["id"])
        albums = self.prepare_album_listitems(albumids)
        self.add_album_listitems(albums, True)
        self.add_next_button(result['albums']['total'])
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def search_playlists(self):
        xbmcplugin.setContent(self.addon_handle, "files")
        result = self.sp.search(
            q=self.playlistid,
            type='playlist',
            limit=self.limit,
            offset=self.offset,
            market=self.usercountry)
        log_msg(result)
        xbmcplugin.setProperty(self.addon_handle, 'FolderName', xbmc.getLocalizedString(136))
        playlists = self.prepare_playlist_listitems(result['playlists']['items'])
        self.add_playlist_listitems(playlists)
        self.add_next_button(result['playlists']['total'])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def search(self):
        xbmcplugin.setContent(self.addon_handle, "files")
        xbmcplugin.setPluginCategory(self.addon_handle, xbmc.getLocalizedString(283))
        kb = xbmc.Keyboard('', xbmc.getLocalizedString(16017))
        kb.doModal()
        if kb.isConfirmed():
            value = kb.getText()
            items = []
            result = self.sp.search(
                q="%s" %
                value,
                type='artist,album,track,playlist',
                limit=1,
                market=self.usercountry)
            items.append(
                ("%s (%s)" %
                 (xbmc.getLocalizedString(133),
                  result["artists"]["total"]),
                    "plugin://plugin.audio.spotify-headless/?action=search_artists&artistid=%s" %
                    (value)))
            items.append(
                ("%s (%s)" %
                 (xbmc.getLocalizedString(136),
                  result["playlists"]["total"]),
                    "plugin://plugin.audio.spotify-headless/?action=search_playlists&playlistid=%s" %
                    (value)))
            items.append(
                ("%s (%s)" %
                 (xbmc.getLocalizedString(132),
                  result["albums"]["total"]),
                    "plugin://plugin.audio.spotify-headless/?action=search_albums&albumid=%s" %
                    (value)))
            items.append(
                ("%s (%s)" %
                 (xbmc.getLocalizedString(134),
                  result["tracks"]["total"]),
                    "plugin://plugin.audio.spotify-headless/?action=search_tracks&trackid=%s" %
                    (value)))
            for item in items:
                li = xbmcgui.ListItem(
                    item[0],
                    path=item[1],
                    iconImage="DefaultMusicAlbums.png"
                )
                li.setProperty('do_not_analyze', 'true')
                li.setProperty('IsPlayable', 'false')
                li.addContextMenuItems([], True)
                xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=item[1], listitem=li, isFolder=True)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def add_next_button(self, listtotal):
        # adds a next button if needed
        params = self.params
        if listtotal > self.offset + self.limit:
            params["offset"] = self.offset + self.limit
            url = "plugin://plugin.audio.spotify-headless/"
            for key, value in params.iteritems():
                if key == "action":
                    url += "?%s=%s" % (key, value[0])
                elif key == "offset":
                    url += "&%s=%s" % (key, value)
                else:
                    url += "&%s=%s" % (key, value[0])
            li = xbmcgui.ListItem(
                xbmc.getLocalizedString(33078),
                path=url,
                iconImage="DefaultMusicAlbums.png"
            )
            li.setProperty('do_not_analyze', 'true')
            li.setProperty('IsPlayable', 'false')
            xbmcplugin.addDirectoryItem(handle=self.addon_handle, url=url, listitem=li, isFolder=True)

    def precache_library(self):
        if self.addon.getSetting("precache_user_library") == "true":
            if not self.win.getProperty("Spotify.PreCachedItems"):
                log_msg("Library precache started")
                monitor = xbmc.Monitor()
                self.win.setProperty("Spotify.PreCachedItems", "busy")
                userplaylists = self.get_user_playlists(self.userid)
                for playlist in userplaylists:
                    self.get_playlist_details(playlist['owner']['id'], playlist["id"])
                    if monitor.abortRequested():
                        return
                self.get_savedalbums()
                if monitor.abortRequested():
                    return
                self.get_savedartists()
                if monitor.abortRequested():
                    return
                self.get_saved_tracks()
                del monitor
                log_msg("Library precache done")
                self.win.setProperty("Spotify.PreCachedItems", "done")


class SpotifyRadioTrackBuffer(object):
    FETCH_SIZE = 100
    MIN_BUFFER_SIZE = FETCH_SIZE / 2
    CHECK_BUFFER_PERIOD = 0.5

    # Public interface
    def __init__(self, seed_tracks):
        self._buffer = seed_tracks[:]
        self._buffer_lock = threading.Lock()
        self._running = False

    def start(self):
        self._running = True
        log_msg("Starting Spotify radio track buffer worker thread")
        t = threading.Thread(target=self._fill_buffer)
        t.start()

    def stop(self):
        log_msg("Stopping Spotify radio track buffer worker thread")
        self._running = False

    def __next__(self):
        # For the most part, the buffer-filling thread should prevent the need for waiting here,
        # but wait exponentially (up to about 32 seconds) for it to fill before giving up.
        log_msg("Spotify radio track buffer asked for next item", xbmc.LOGDEBUG)
        attempts = 0
        while attempts <= 5:
            self._buffer_lock.acquire()
            if len(self._buffer) <= self.MIN_BUFFER_SIZE:
                self._buffer_lock.release()
                sleep_time = pow(2, attempts)
                log_msg("Spotify radio track buffer empty, sleeping for %d seconds" % sleep_time, xbmc.LOGDEBUG)
                time.sleep(sleep_time)
                attempts += 1
            else:
                track = self._buffer.pop(0)
                self._buffer_lock.release()
                log_msg("Got track '%s' from Spotify radio track buffer" % track["id"], xbmc.LOGDEBUG)
                return track
        raise StopIteration

    # Support both Python 2.7 & Python 3.0
    next = __next__

    # Implementation
    def _fill_buffer(self):
        while self._running:
            self._buffer_lock.acquire()
            if len(self._buffer) <= self.MIN_BUFFER_SIZE:
                log_msg("Spotify radio track buffer was %d, below minimum size of %d - filling" %
                        (len(self._buffer), self.MIN_BUFFER_SIZE), xbmc.LOGDEBUG)
                self._buffer += self._fetch()
                self._buffer_lock.release()
            else:
                self._buffer_lock.release()
                time.sleep(self.CHECK_BUFFER_PERIOD)

    def _fetch(self):
        log_msg("Spotify radio track buffer invoking recommendations() via spotipy", xbmc.LOGDEBUG)
        try:
            auth_token = xbmc.getInfoLabel("Window(Home).Property(spotify-token)").decode("utf-8")
            client = spotipy.Spotify(auth_token)
            tracks = client.recommendations(
                seed_tracks=[t["id"] for t in self._buffer[0: 5]],
                limit=self.FETCH_SIZE)["tracks"]
            log_msg("Spotify radio track buffer got %d results back" % len(tracks))
            return tracks
        except Exception:
            log_exception("SpotifyRadioTrackBuffer", "Failed to fetch recommendations, returning empty result")
            return []


class SpotifyRadioPlayer(xbmc.Player):

    def set_parent(self, parent):
        self._parent = parent

    def set_seed_tracks(self, seed_tracks):
        self._seed_tracks = seed_tracks

    def play(self, *args, **kwds):
        self._pl = xbmc.PlayList(0)
        self._pl.clear()
        self._source = SpotifyRadioTrackBuffer(self._seed_tracks)
        self._source.start()

        xbmc.executebuiltin('XBMC.RandomOff')
        xbmc.executebuiltin('XBMC.RepeatOff')

        for _i in range(2):
            self._add_to_playlist()

        xbmc.Player.play(self, self._pl)

    def onPlayBackStarted(self):
        self._add_to_playlist()
        xbmc.Player.onPlayBackStarted(self)

    def onPlayBackEnded(self):
        xbmc.Player.onPlayBackEnded(self)

    def onPlayBackStopped(self):
        self._source.stop()
        self._pl.clear()
        xbmc.Player.onPlayBackStopped(self)

    def _add_to_playlist(self):
        track = self._source.next()
        url, li = parse_spotify_track(track)
        self._pl.add(url, li)
