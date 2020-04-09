# -*- coding: utf-8 -*-
import threading
import thread
import time
import re
import struct
import cherrypy
from cherrypy._cpnative_server import CPHTTPServer
from datetime import datetime
import random
import sys
import platform
import logging
import os
from utils import log_msg, log_exception, create_wave_header, PROXY_PORT, StringIO
import xbmc
import math

class Root:
    spotty = None
    connect_player = None
    
    spotty_bin = None
    spotty_trackid = None
    spotty_range_l = None
    
    def __init__(self, spotty, connect_player):
        self.__spotty = spotty
        self.__connect_player = connect_player

    def _check_request(self):
        method = cherrypy.request.method.upper()
        headers = cherrypy.request.headers
        # Fail for other methods than get or head
        if method not in ("GET", "HEAD"):
            raise cherrypy.HTTPError(405)
        # Error if the requester is not allowed
        # for now this is a simple check just checking if the useragent matches Kodi
        user_agent = headers['User-Agent'].lower()
        if not ("kodi" in user_agent or "osmc" in user_agent):
            raise cherrypy.HTTPError(403)
        return method


    @cherrypy.expose
    @cherrypy.tools.json_out()
    @cherrypy.tools.json_in()
    def lms(self, filename, **kwargs):
        ''' fake lms hook to retrieve events form spotty daemon'''
        method = cherrypy.request.method.upper()
        if method != "POST" or filename != "jsonrpc.js":
            raise cherrypy.HTTPError(405)
        input_json = cherrypy.request.json
        if input_json and input_json.get("params"):
            event = input_json["params"][1]
            log_msg("lms event hook called. Event: %s" % event)
            # check username, it might have changed
            spotty_user = self.__spotty.get_username()
            cur_user = xbmc.getInfoLabel("Window(Home).Property(spotify-username)").decode("utf-8")
            if spotty_user != cur_user:
                log_msg("user change detected")
                xbmc.executebuiltin("SetProperty(spotify-cmd,__LOGOUT__,Home)")
            if "start" in event:
                log_msg("playback start requested by connect")
                self.__connect_player.handle_lms_event_change()
            elif "change" in event:
                log_msg("playback change requested by connect")
                self.__connect_player.handle_lms_event_change()
            elif "stop" in event:
                log_msg("playback stop requested by connect")
                self.__connect_player.handle_lms_event_stop()
            elif "volume" in event:
                vol_level = event[2]
                log_msg("volume change detected on connect player: %s" % vol_level)
                # ignore for now as it needs more work
                #xbmc.executebuiltin("SetVolume(%s,true)" % vol_level)
        return {"operation": "request", "result": "success"}

    @cherrypy.expose
    def track(self, track_id, duration, **kwargs):
        # Check sanity of the request
        self._check_request()

        # Calculate file size, and obtain the header
        duration = int(duration)
        wave_header, filesize = create_wave_header(duration)
        request_range = cherrypy.request.headers.get('Range', '')
        # response timeout must be at least the duration of the track: read/write loop
        # checks for timeout and stops pushing audio to player if it occurs
        cherrypy.response.timeout =  int(math.ceil(duration * 1.5))
    
        range_l = 0
        range_r = filesize

        # headers
        if request_range and request_range != "bytes=0-":
            # partial request
            cherrypy.response.status = '206 Partial Content'
            cherrypy.response.headers['Content-Type'] = 'audio/x-wav'
            range = cherrypy.request.headers["Range"].split("bytes=")[1].split("-")
            log_msg("request header range: %s" % (cherrypy.request.headers['Range']), xbmc.LOGDEBUG)
            range_l = int(range[0])
            try:
                range_r = int(range[1])
            except:
                range_r = filesize

            cherrypy.response.headers['Accept-Ranges'] = 'bytes'
            cherrypy.response.headers['Content-Length'] = filesize
            cherrypy.response.headers['Content-Range'] = "bytes %s-%s/%s" % (range_l, range_r, filesize)
            log_msg("partial request range: %s, length: %s" % (cherrypy.response.headers['Content-Range'], cherrypy.response.headers['Content-Length']), xbmc.LOGDEBUG)
        else:
            # full file
            cherrypy.response.headers['Content-Type'] = 'audio/x-wav'
            cherrypy.response.headers['Accept-Ranges'] = 'bytes'
            cherrypy.response.headers['Content-Length'] = filesize

        # If method was GET, write the file content
        if cherrypy.request.method.upper() == 'GET':
            return self.send_audio_stream(track_id, filesize, wave_header, range_l)
    track._cp_config = {'response.stream': True}

    def kill_spotty(self):
        self.spotty_bin.terminate()
        self.spotty_bin = None
        self.spotty_trackid = None
        self.spotty_range_l = None

    def send_audio_stream(self, track_id, filesize, wave_header, range_l):
        '''chunked transfer of audio data from spotty binary'''
        if self.spotty_bin != None and \
           self.spotty_trackid == track_id and \
           self.spotty_range_l == range_l:
            # leave the existing spotty running and don't start a new one.
            log_msg("WHOOPS!!! Running spotty still handling same request - leave it alone.", \
                    xbmc.LOGERROR)
            return
        elif self.spotty_bin != None:
            # If spotty binary still attached for a different request, try to terminate it.
            log_msg("WHOOPS!!! Running spotty detected - killing it to continue.", \
                    xbmc.LOGERROR)
            self.kill_spotty()

        log_msg("start transfer for track %s - range: %s" % (track_id, range_l), \
                xbmc.LOGDEBUG)
        try:
            self.spotty_trackid = track_id
            self.spotty_range_l = range_l

            # Initialize some loop vars
            max_buffer_size = 524288
            bytes_written = 0

            # Write wave header
            # only count bytes actually from the spotify stream
            # bytes_written = len(wave_header)
            if not range_l:
                yield wave_header

            # get pcm data from spotty stdout and append to our buffer
            args = ["-n", "temp", "--single-track", track_id]
            self.spotty_bin = self.__spotty.run_spotty(args, use_creds=True)
            
            # ignore the first x bytes to match the range request
            if range_l:
                self.spotty_bin.stdout.read(range_l)

            # Loop as long as there's something to output
            frame = self.spotty_bin.stdout.read(max_buffer_size)
            while frame:
                if cherrypy.response.timed_out:
                    # A timeout occured on the cherrypy session and has been flagged - so exit
                    # The session timer was set to be longer than the track being played so this
                    # would probably require network problems or something bad elsewhere.
                    log_msg("SPOTTY cherrypy response timeout: %r - %s" % \
                            (repr(cherrypy.response.timed_out), cherrypy.response.status), xbmc.LOGERROR)
                    break
                bytes_written += len(frame)
                yield frame
                frame = self.spotty_bin.stdout.read(max_buffer_size)
        except Exception as exc:
            log_exception(__name__, exc)
        finally:
            # make sure spotty always gets terminated
            if self.spotty_bin != None:
                self.kill_spotty()
            log_msg("FINISH transfer for track %s - range %s" % (track_id, range_l), \
                    xbmc.LOGDEBUG)

    @cherrypy.expose
    def silence(self, duration, **kwargs):
        '''stream silence audio for the given duration, used by spotify connect player'''
        duration = int(duration)
        wave_header, filesize = create_wave_header(duration)
        output_buffer = StringIO()
        output_buffer.write(wave_header)
        output_buffer.write('\0' * (filesize - output_buffer.tell()))
        return cherrypy.lib.static.serve_fileobj(output_buffer, content_type="audio/wav",
                                                 name="%s.wav" % duration, filesize=output_buffer.tell())

    @cherrypy.expose
    def nexttrack(self, **kwargs):
        '''play silence while spotify connect player is waiting for the next track'''
        return self.silence(20)

    @cherrypy.expose
    def callback(self, **kwargs):
        cherrypy.response.headers['Content-Type'] = 'text/html'
        code = kwargs.get("code")
        url = "http://localhost:%s/callback?code=%s" % (PROXY_PORT, code)
        if cherrypy.request.method.upper() in ['GET', 'POST']:
            html = "<html><body><h1>Authentication succesfull</h1>"
            html += "<p>You can now close this browser window.</p>"
            html += "</body></html>"
            xbmc.executebuiltin("SetProperty(spotify-token-info,%s,Home)" % url)
            log_msg("authkey sent")
            return html

class ProxyRunner(threading.Thread):
    __server = None
    __root = None

    def __init__(self, spotty, connect_player):
        self.__root = Root(spotty, connect_player)
        log = cherrypy.log
        log.access_file = ''
        log.error_file = ''
        log.screen = False
        cherrypy.config.update({
            'server.socket_host': '0.0.0.0',
            'server.socket_port': PROXY_PORT,
            'engine.timeout_monitor.frequency': 5,
            'server.shutdown_timeout': 1
        })
        self.__server = cherrypy.server.httpserver = CPHTTPServer(cherrypy.server)
        threading.Thread.__init__(self)

    def run(self):
        conf = { '/': {}}
        cherrypy.quickstart(self.__root, '/', conf)

    def get_port(self):
        return self.__server.bind_addr[1]

    def get_host(self):
        return self.__server.bind_addr[0]

    def stop(self):
        cherrypy.engine.exit()
        self.join(0)
        del self.__root
        del self.__server
