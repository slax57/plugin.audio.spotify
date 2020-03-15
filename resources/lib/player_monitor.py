#!/usr/bin/python
# -*- coding: utf-8 -*-


from utils import log_msg, log_exception, parse_spotify_track, PROXY_PORT
import xbmc
import xbmcgui
from urllib import quote_plus
import threading
import thread


class ConnectPlayer(xbmc.Player):
    '''Simulate a Spotify Connect player with the Kodi player'''

    __instance = None

    connect_playing = False  # spotify connect is playing
    username = None
    __playlist = None
    __exit = False
    __ignore_seek = False
    __sp = None
    __skip_events = False

    def __init__(self, **kwargs):
        if ConnectPlayer.__instance != None:
            raise Exception("This class is a singleton!")
        else:
            self.__sp = kwargs.get("sp")
            self.__playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
            xbmc.Player.__init__(self, **kwargs)
            ConnectPlayer.__instance = self

    @staticmethod 
    def getInstance(**kwargs):
        """ Static access method. """
        if ConnectPlayer.__instance == None:
            ConnectPlayer(**kwargs)
        return ConnectPlayer.__instance

    def close(self):
        '''cleanup on exit'''
        del self.__playlist

    def onPlayBackPaused(self):
        '''Kodi event fired when playback is paused'''
        if self.connect_playing and not self.__skip_events and not self.connect_is_paused():
            self.__sp.pause_playback()
            log_msg("Playback paused")
        self.__skip_events = False

    def onPlayBackResumed(self):
        '''Kodi event fired when playback is resumed after pause'''
        if self.connect_playing and not self.__skip_events and self.connect_is_paused():
            self.__sp.start_playback()
            log_msg("Playback unpaused")
        self.__skip_events = False

    def onPlayBackEnded(self):
        self.connect_playing = False
        pass

    def onPlayBackStarted(self):
        '''Kodi event fired when playback is started (including next tracks)'''
        if not self.__skip_events:
            filename = ""
            if self.isPlaying():
                filename = self.getPlayingFile()

            if "localhost:%s" % PROXY_PORT in filename:
                if not self.connect_playing and "connect=true" in filename:
                    # we started playback with (remote) connect player
                    log_msg("Playback started of Spotify Connect stream")
                    self.connect_playing = True
                if "nexttrack" in filename:
                    # next track requested for kodi player
                    self.__skip_events = True
                    self.__sp.next_track()
        else:
            self.__skip_events = False

    def onPlayBackSpeedChanged(self, speed):
        '''Kodi event fired when player is fast forwarding/rewinding'''
        pass

    def onPlayBackSeek(self, seekTime, seekOffset):
        '''Kodi event fired when the user is seeking'''
        if self.__ignore_seek:
            self.__ignore_seek = False
        elif self.connect_playing:
            log_msg("Kodiplayer seekto: %s" % seekTime)
            self.__ignore_seek = True
            self.__sp.seek_track(seekTime)

    def onPlayBackStopped(self):
        '''Kodi event fired when playback is stopped'''
        # event is called after every track 
        # check playlist postition to detect if playback is realy stopped
        if self.connect_playing and self.__playlist.getposition() < 0:
            self.connect_playing = False
            if not self.connect_is_paused():
                self.__sp.pause_playback()
            log_msg("Playback stopped")

    def add_nexttrack_to_playlist(self):
        '''Update the playlist: add fake item at the end which allows us to skip'''
        url = "http://localhost:%s/nexttrack" % PROXY_PORT
        li = xbmcgui.ListItem('...', path=url)
        self.__playlist.add(url, li)
##        self.__playlist.add(url, li)

    def start_playback(self, track_id):
        self.__skip_events = True
        self.connect_playing = True
        self.__playlist.clear()
        trackdetails = self.__sp.track(track_id)
        url, li = parse_spotify_track(trackdetails, silenced=False, is_connect=True)
        self.__playlist.add(url, li)
        self.add_nexttrack_to_playlist()
        self.__ignore_seek = True
        self.__sp.seek_track(0)  # for now we always start a track at the beginning
        self.play(self.__playlist)

    def update_info(self, force):
        cur_playback = None
        count = 0
        while not cur_playback and count < 10:
            try:
                cur_playback = self.__sp.current_playback()
            except:
                count += 1
                xbmc.sleep(500)
        if not cur_playback:
            log_msg("Could not retrieve trackdetails from api, stopping playback")
            self.__skip_events = True
            self.stop()
        else:
            if cur_playback["is_playing"] and (not xbmc.getCondVisibility("Player.Paused") or force):
                player_title = None
                if self.isPlaying():
                    player_title = self.getMusicInfoTag().getTitle().decode("utf-8")
                trackdetails = cur_playback["item"]
                if trackdetails is not None and (not player_title or player_title == "nexttrack" or player_title != trackdetails["name"]):
                    log_msg("Next track requested by Spotify Connect player")
                    self.start_playback(trackdetails["id"])
            elif cur_playback["is_playing"] and xbmc.getCondVisibility("Player.Paused"):
                log_msg("Playback resumed from pause requested by Spotify Connect")
                self.__skip_events = True
                self.play()
            elif not xbmc.getCondVisibility("Player.Paused"):
                log_msg("Pause requested by Spotify Connect")
                self.__skip_events = True
                self.pause()

                
    def connect_is_paused(self):
        '''check if connect player currently is paused'''
        cur_playback = self.__sp.current_playback()
        if cur_playback:
            if cur_playback["is_playing"]:
                return False
        return True
