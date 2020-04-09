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
    __sp = None

    __handling_lms_event = False

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
        if self.connect_playing and not self.__handling_lms_event:
            self.__sp.pause_playback()
            log_msg("Playback paused")
        elif self.__handling_lms_event:
            self.__handling_lms_event = False

    def onPlayBackResumed(self):
        '''Kodi event fired when playback is resumed after pause'''
        if self.connect_playing and not self.__handling_lms_event:
            self.__sp.start_playback()
            log_msg("Playback resumed")
        elif self.__handling_lms_event:
            self.__handling_lms_event = False

    def onPlayBackEnded(self):
        pass

    def onPlayBackStarted(self):
        '''Kodi event fired when playback is started (including next tracks)'''
        filename = ""
        if self.isPlaying():
            filename = self.getPlayingFile()

        if "localhost:%s" % PROXY_PORT in filename:
            if not self.connect_playing and "connect=true" in filename:
                # we started playback with (remote) connect player
                log_msg("Playback started of Spotify Connect stream")
                self.connect_playing = True
            if "nexttrack" in filename and not self.__handling_lms_event:
                # next track requested for kodi player
                self.__sp.next_track()
            elif self.__handling_lms_event:
                self.__handling_lms_event = False

    def onPlayBackSpeedChanged(self, speed):
        '''Kodi event fired when player is fast forwarding/rewinding'''
        pass

    def onPlayBackSeek(self, seekTime, seekOffset):
        '''Kodi event fired when the user is seeking'''
        if self.connect_playing:
            log_msg("Kodiplayer seekto: %s" % seekTime)
            self.__sp.seek_track(seekTime)

    def onPlayBackStopped(self):
        '''Kodi event fired when playback is stopped'''
        # event is called after every track 
        # check playlist postition to detect if playback is realy stopped
        if self.connect_playing:
            self.connect_playing = False
            self.__sp.pause_playback()
            log_msg("Playback stopped")

    def add_nexttrack_to_playlist(self):
        '''Update the playlist: add fake item at the end which allows us to skip'''
        url = "http://localhost:%s/nexttrack" % PROXY_PORT
        li = xbmcgui.ListItem('...', path=url)
        self.__playlist.add(url, li)

    def start_new_playback(self, track_id):
        self.connect_playing = True
        self.__playlist.clear()
        trackdetails = self.__sp.track(track_id)
        url, li = parse_spotify_track(trackdetails, silenced=False, is_connect=True)
        self.__playlist.add(url, li)
        self.add_nexttrack_to_playlist()
        self.__sp.seek_track(0)  # for now we always start a track at the beginning
        self.play(self.__playlist)

    def update_info(self):
        log_msg("Called update_info()!")
    
    def handle_lms_event_change(self):

        cur_playback = self.__sp.current_playback()

        if not cur_playback:
            log_msg("Could not retrieve trackdetails from api, stopping playback")
            self.connect_playing = False
            self.stop()
        else:

            trackdetails = cur_playback["item"]

            if cur_playback["is_playing"] and trackdetails is not None:

                kodi_player_title = None
                if self.isPlaying():
                    kodi_player_title = self.getMusicInfoTag().getTitle().decode("utf-8")

                if not kodi_player_title or kodi_player_title != trackdetails["name"]:
                    log_msg("New track requested by Spotify Connect player")
                    self.__handling_lms_event = True
                    self.start_new_playback(trackdetails["id"])

                elif xbmc.getCondVisibility("Player.Paused"):
                    log_msg("Playback resumed from pause requested by Spotify Connect")
                    self.__handling_lms_event = True
                    self.pause() # pause() is also used to resume playback

    def handle_lms_event_stop(self):
        if not xbmc.getCondVisibility("Player.Paused"):
            log_msg("Pause requested by Spotify Connect")
            self.__handling_lms_event = True
            self.pause()