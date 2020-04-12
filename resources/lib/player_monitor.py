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

    connect_playing = False  # spotify connect is playing
    username = None
    __playlist = None
    __sp = None
    __lms_event_stack = [] # stack of LMS events being handled

    def __init__(self, **kwargs):
        self.__sp = kwargs.get("sp")
        self.__playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        xbmc.Player.__init__(self, **kwargs)

    def close(self):
        '''cleanup on exit'''
        del self.__playlist

    def onPlayBackPaused(self):
        '''Kodi event fired when playback is paused'''
        log_msg("Kodi event fired: onPlayBackPaused")
        if "PAUSE" in self.__lms_event_stack:
            self.__lms_event_stack.remove("PAUSE")
        elif self.connect_playing:
            log_msg("Run Spotipy command: pause_playback")
            self.__sp.pause_playback()

    def onPlayBackResumed(self):
        '''Kodi event fired when playback is resumed after pause'''
        log_msg("Kodi event fired: onPlayBackResumed")
        if "RESUME" in self.__lms_event_stack:
            self.__lms_event_stack.remove("RESUME")
        elif self.connect_playing:
            log_msg("Run Spotipy command: start_playback")
            self.__sp.start_playback()

    def onPlayBackEnded(self):
        '''Kodi event fired when playback is ended, eg. at the end of current track'''
        log_msg("Kodi event fired: onPlayBackEnded")

    def onPlayBackStarted(self):
        '''Kodi event fired when playback is started (including next tracks)'''
        log_msg("Kodi event fired: onPlayBackStarted")
        filename = ""
        if self.isPlaying():
            filename = self.getPlayingFile()

        if "localhost:%s" % PROXY_PORT in filename:
            if not self.connect_playing and "connect=true" in filename:
                # we started playback with (remote) connect player
                log_msg("Playback started of Spotify Connect stream")
                self.connect_playing = True
            elif "nexttrack" in filename:
                if not "NEXTTRACK" in self.__lms_event_stack:
                    log_msg("Run Spotipy command: next_track")
                    self.__sp.next_track()
                    self.__lms_event_stack.append("NEXTTRACK")

    def onPlayBackSpeedChanged(self, speed):
        '''Kodi event fired when player is fast forwarding/rewinding'''
        log_msg("Kodi event fired: onPlayBackSpeedChanged")

    def onPlayBackSeek(self, seekTime, seekOffset):
        '''Kodi event fired when the user is seeking'''
        log_msg("Kodi event fired: onPlayBackSeek")
        if self.connect_playing:
            log_msg("Run Spotipy command: seek_track")
            self.__sp.seek_track(seekTime)

    def onPlayBackStopped(self):
        '''Kodi event fired when playback is stopped'''
        log_msg("Kodi event fired: onPlayBackStopped")
        if self.connect_playing:
            self.connect_playing = False
            log_msg("Run Spotipy command: pause_playback")
            self.__sp.pause_playback()

    def __add_nexttrack_to_playlist(self):
        '''Update the playlist: add fake item at the end which allows us to skip'''
        url = "http://localhost:%s/nexttrack" % PROXY_PORT
        li = xbmcgui.ListItem('...', path=url)
        self.__playlist.add(url, li)

    def start_new_playback(self, track_id):
        '''Create the playlist to start playback of a new track'''
        log_msg("Creating playlist to start playback of a new track")
        self.connect_playing = True
        self.__playlist.clear()
        trackdetails = self.__sp.track(track_id)
        url, li = parse_spotify_track(trackdetails, silenced=False, is_connect=True)
        self.__playlist.add(url, li)
        self.__add_nexttrack_to_playlist()
        log_msg("Run Spotipy command: seek_track")
##        self.__sp.seek_track(0)  # this is done to sync remote devices with current playback position
        self.play(self.__playlist)
        if "NEXTTRACK" in self.__lms_event_stack:
            self.__lms_event_stack.remove("NEXTTRACK") # is done loading next track

    def update_info(self):
        log_msg("Called update_info()!")
    
    def handle_lms_event_change(self):
        '''Handle LMS event in case of playback start or change'''
        log_msg("Handling LMS event start or change")
        log_msg("Run Spotipy command: current_playback")
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
                    self.start_new_playback(trackdetails["id"])

                elif xbmc.getCondVisibility("Player.Paused"):
                    log_msg("Playback resumed from pause requested by Spotify Connect")
                    self.__lms_event_stack.append("RESUME")
                    self.pause() # pause() is also used to resume playback

    def handle_lms_event_stop(self):
        '''Handle LMS event in case of playback stop'''
        log_msg("Handling LMS event stop")
        if not xbmc.getCondVisibility("Player.Paused"):
            log_msg("Stop requested by Spotify Connect")
            self.__lms_event_stack.append("PAUSE")
            self.pause()
