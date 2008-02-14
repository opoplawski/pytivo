import transcode, os, socket, re, urllib, zlib
from Cheetah.Template import Template
from plugin import Plugin, quote, unquote
from urlparse import urlparse
from xml.sax.saxutils import escape
from lrucache import LRUCache
from UserDict import DictMixin
from datetime import datetime, timedelta
import config
import time

SCRIPTDIR = os.path.dirname(__file__)

CLASS_NAME = 'Video'

extfile = os.path.join(SCRIPTDIR, 'video.ext')
try:
    extensions = file(extfile).read().split()
except:
    extensions = None

debug = config.getDebug()
hack83 = config.getHack83()

def debug_write(data):
    if debug:
        debug_out = []
        debug_out.append('Video.py - ')
        for x in data:
            debug_out.append(str(x))
        fdebug = open('debug.txt', 'a')
        fdebug.write(' '.join(debug_out))
        fdebug.close()

if hack83:
    debug_write(['Hack83 is enabled.\n'])

class Video(Plugin):

    CONTENT_TYPE = 'x-container/tivo-videos'

    # Used for 8.3's broken requests
    count = 0
    request_history = {}

    def video_file_filter(self, full_path, type=None):
        if os.path.isdir(full_path):
            return True
        if extensions:
            return os.path.splitext(full_path)[1].lower() in extensions
        else:
            return transcode.supported_format(full_path)

    def hack(self, handler, query, subcname):
        debug_write(['Hack new request ------------------------\n'])
        debug_write(['Hack TiVo request is: \n', query, '\n'])
        queryAnchor = ''
        rightAnchor = ''
        leftAnchor = ''
        tsn = handler.headers.getheader('tsn', '')

        # not a tivo
        if not tsn:
            debug_write(['Hack this was not a TiVo request.\n'])
            return query, None

        # this breaks up the anchor item request into seperate parts
        if 'AnchorItem' in query and query['AnchorItem'] != ['Hack8.3']:
            queryAnchor = urllib.unquote_plus(''.join(query['AnchorItem']))
            if queryAnchor.find('Container=') >= 0:
                # This is a folder
                queryAnchor = queryAnchor.split('Container=')[-1]
            else:
                # This is a file
                queryAnchor = queryAnchor.split('/', 1)[-1]
            leftAnchor, rightAnchor = queryAnchor.rsplit('/', 1)
            debug_write(['Hack queryAnchor: ', queryAnchor,
                         ' leftAnchor: ', leftAnchor,
                         ' rightAnchor: ', rightAnchor, '\n'])
        try:
            path, state = self.request_history[tsn]
        except KeyError:
            # Never seen this tsn, starting new history
            debug_write(['New TSN.\n'])
            path = []
            state = {}
            self.request_history[tsn] = (path, state)
            state['query'] = query
            state['page'] = ''
            state['time'] = int(time.time()) + 1000

        debug_write(['Hack our saved request is: \n', state['query'], '\n'])

        current_folder = subcname.split('/')[-1]

        # Begin figuring out what the request TiVo sent us means
        # There are 7 options that can occur

        # 1. at the root - This request is always accurate
        if len(subcname.split('/')) == 1:
            debug_write(['Hack we are at the root.',
                         'Saving query, Clearing state[page].\n'])
            path[:] = [current_folder]
            state['query'] = query
            state['page'] = ''
            return query, path

        # 2. entering a new folder
        # If there is no AnchorItem in the request then we must be 
        # entering a new folder.
        if 'AnchorItem' not in query:
            debug_write(['Hack we are entering a new folder.',
                         'Saving query, setting time, setting state[page].\n'])
            path[:] = subcname.split('/')
            state['query'] = query
            state['time'] = int(time.time())
            files, total, start = self.get_files(handler, query,
                                                 self.video_file_filter)
            if files:
                state['page'] = files[0]
            else:
                state['page'] = ''
            return query, path

        # 3. Request a page after pyTivo sent a 302 code
        # we know this is the proper page
        if ''.join(query['AnchorItem']) == 'Hack8.3':
            debug_write(['Hack requested page from 302 code.',
                         'Returning saved query,\n'])
            return state['query'], path

        # 4. this is a request for a file
        if 'ItemCount' in query and int(''.join(query['ItemCount'])) == 1:
            debug_write(['Hack requested a file', '\n'])
            # Everything in this request is right except the container
            query['Container'] = ['/'.join(path)]
            state['page'] = ''
            return query, path

        # All remaining requests could be a second erroneous request for 
        # each of the following we will pause to see if a correct 
        # request is coming right behind it.

        # Sleep just in case the erroneous request came first this 
        # allows a proper request to be processed first
        debug_write(['Hack maybe erroneous request, sleeping.\n'])
        time.sleep(.25)

        # 5. scrolling in a folder
        # This could be a request to exit a folder or scroll up or down 
        # within the folder
        # First we have to figure out if we are scrolling
        if 'AnchorOffset' in query:
            debug_write(['Hack Anchor offset was in query.',
                         'leftAnchor needs to match ', '/'.join(path), '\n'])
            if leftAnchor == str('/'.join(path)):
                debug_write(['Hack leftAnchor matched.', '\n'])
                query['Container'] = ['/'.join(path)]
                files, total, start = self.get_files(handler, query, 
                                                     self.video_file_filter)
                debug_write(['Hack saved page is= ', state['page'],
                             ' top returned file is= ', files[0], '\n'])
                # If the first file returned equals the top of the page
                # then we haven't scrolled pages
                if files[0] != str(state['page']):
                    debug_write(['Hack this is scrolling within a folder.\n'])
                    state['page'] = files[0]
                    return query, path               

        # The only remaining options are exiting a folder or this is a 
        # erroneous second request.

        # 6. this an extraneous request
        # this came within a second of a valid request; just use that 
        # request.
        if (int(time.time()) - state['time']) <= 1:
            debug_write(['Hack erroneous request, send a 302 error', '\n'])
            return None, path

        # 7. this is a request to exit a folder
        # this request came by itself; it must be to exit a folder
        else:
            debug_write(['Hack over 1 second,',
                         'must be request to exit folder\n'])
            path.pop()
            state['query'] = {'Command': query['Command'],
                              'SortOrder': query['SortOrder'],
                              'ItemCount': query['ItemCount'],
                              'Filter': query['Filter'],
                              'Container': ['/'.join(path)]}
            return None, path

        # just in case we missed something.
        debug_write(['Hack ERROR, should not have made it here. ',
                     'Trying to recover.\n'])
        return state['query'], path

    def send_file(self, handler, container, name):
        if handler.headers.getheader('Range') and \
           handler.headers.getheader('Range') != 'bytes=0-':
            handler.send_response(206)
            handler.send_header('Connection', 'close')
            handler.send_header('Content-Type', 'video/x-tivo-mpeg')
            handler.send_header('Transfer-Encoding', 'chunked')
            handler.end_headers()
            handler.wfile.write("\x30\x0D\x0A")
            return

        tsn = handler.headers.getheader('tsn', '')

        o = urlparse("http://fake.host" + handler.path)
        path = unquote(o[2])
        handler.send_response(200)
        handler.end_headers()
        transcode.output_video(container['path'] + path[len(name) + 1:],
                               handler.wfile, tsn)

    def __isdir(self, full_path):
        return os.path.isdir(full_path)

    def __duration(self, full_path):
        return transcode.video_info(full_path)[4]

    def __est_size(self, full_path, tsn = ''):
        # Size is estimated by taking audio and video bit rate adding 2%

        if transcode.tivo_compatable(full_path, tsn):
            # Is TiVo-compatible mpeg2
            return int(os.stat(full_path).st_size)
        else:
            # Must be re-encoded
            audioBPS = config.strtod(config.getAudioBR(tsn))
            videoBPS = config.strtod(config.getVideoBR(tsn))
            bitrate =  audioBPS + videoBPS
            return int((self.__duration(full_path) / 1000) *
                       (bitrate * 1.02 / 8))

    def __getMetadataFromTxt(self, full_path):
        metadata = {}

        default_file = os.path.join(os.path.split(full_path)[0], 'default.txt')
        description_file = full_path + '.txt'

        metadata.update(self.__getMetadataFromFile(default_file))
        metadata.update(self.__getMetadataFromFile(description_file))

        return metadata

    def __getMetadataFromFile(self, file):
        metadata = {}

        if os.path.exists(file):
            for line in open(file):
                if line.strip().startswith('#'):
                    continue
                if not ':' in line:
                    continue

                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()

                if key.startswith('v'):
                    if key in metadata:
                        metadata[key].append(value)
                    else:
                        metadata[key] = [value]
                else:
                    metadata[key] = value

        return metadata

    def __metadata_basic(self, full_path):
        metadata = {}

        base_path, title = os.path.split(full_path)
        originalAirDate = datetime.fromtimestamp(os.stat(full_path).st_ctime)

        metadata['title'] = '.'.join(title.split('.')[:-1])
        metadata['seriesTitle'] = metadata['title'] # default to the filename
        metadata['originalAirDate'] = originalAirDate.isoformat()

        metadata.update(self.__getMetadataFromTxt(full_path))

        return metadata

    def __metadata_full(self, full_path, tsn=''):
        metadata = {}
        metadata.update(self.__metadata_basic(full_path))

        now = datetime.now()

        duration = self.__duration(full_path)
        duration_delta = timedelta(milliseconds = duration)

        metadata['time'] = now.isoformat()
        metadata['startTime'] = now.isoformat()
        metadata['stopTime'] = (now + duration_delta).isoformat()

        metadata.update( self.__getMetadataFromTxt(full_path) )

        metadata['size'] = self.__est_size(full_path, tsn)
        metadata['duration'] = duration

        min = duration_delta.seconds / 60
        sec = duration_delta.seconds % 60
        hours = min / 60
        min = min % 60
        metadata['iso_duration'] = 'P' + str(duration_delta.days) + \
                                   'DT' + str(hours) + 'H' + str(min) + \
                                   'M' + str(sec) + 'S'
        return metadata

    def QueryContainer(self, handler, query):
        tsn = handler.headers.getheader('tsn', '')
        subcname = query['Container'][0]

        # If you are running 8.3 software you want to enable hack83
        # in the config file

        if hack83:
            print '=' * 73
            query, hackPath = self.hack(handler, query, subcname)
            hackPath = '/'.join(hackPath)
            print 'Tivo said:', subcname, '|| Hack said:', hackPath
            debug_write(['Hack Tivo said: ', subcname, ' || Hack said: ',
                         hackPath, '\n'])
            subcname = hackPath

            if not query:
                debug_write(['Hack sending 302 redirect page', '\n'])
                handler.send_response(302)
                handler.send_header('Location ', 'http://' +
                                    handler.headers.getheader('host') +
                                    '/TiVoConnect?Command=QueryContainer&' +
                                    'AnchorItem=Hack8.3&Container=' + hackPath)
                handler.end_headers()
                return

        # End hack mess

        cname = subcname.split('/')[0]

        if not handler.server.containers.has_key(cname) or \
           not self.get_local_path(handler, query):
            handler.send_response(404)
            handler.end_headers()
            return

        files, total, start = self.get_files(handler, query,
                                             self.video_file_filter)

        videos = []
        local_base_path = self.get_local_base_path(handler, query)
        for file in files:
            video = VideoDetails()
            video['name'] = os.path.split(file)[1]
            video['path'] = file
            video['part_path'] = file.replace(local_base_path, '', 1)
            video['title'] = os.path.split(file)[1]
            video['is_dir'] = self.__isdir(file)
            if video['is_dir']:
                video['small_path'] = subcname + '/' + video['name']
            else:
                if len(files) > 1:
                    video['valid'] = True
                    video.update(self.__metadata_basic(file))
                else:
                    video['valid'] = transcode.supported_format(file)
                    if video['valid']:
                        video.update(self.__metadata_full(file, tsn))

            videos.append(video)

        handler.send_response(200)
        handler.end_headers()
        t = Template(file=os.path.join(SCRIPTDIR,'templates', 'container.tmpl'))
        t.container = cname
        t.name = subcname
        t.total = total
        t.start = start
        t.videos = videos
        t.quote = quote
        t.escape = escape
        t.crc = zlib.crc32
        t.guid = config.getGUID()
        handler.wfile.write(t)

    def TVBusQuery(self, handler, query):
        tsn = handler.headers.getheader('tsn', '')       
        file = query['File'][0]
        path = self.get_local_path(handler, query)
        file_path = path + file

        file_info = VideoDetails()
        file_info['valid'] = transcode.supported_format(file_path)
        if file_info['valid']:
            file_info.update(self.__metadata_full(file_path, tsn))

        handler.send_response(200)
        handler.end_headers()
        t = Template(file=os.path.join(SCRIPTDIR,'templates', 'TvBus.tmpl'))
        t.video = file_info
        t.escape = escape
        handler.wfile.write(t)

class VideoDetails(DictMixin):

    def __init__(self, d=None):
        if d:
            self.d = d
        else:
            self.d = {}

    def __getitem__(self, key):
        if key not in self.d:
            self.d[key] = self.default(key)
        return self.d[key]

    def __contains__(self, key):
        return True

    def __setitem__(self, key, value):
        self.d[key] = value

    def __delitem__(self):
        del self.d[key]

    def keys(self):
        return self.d.keys()

    def __iter__(self):
        return self.d.__iter__()

    def iteritems(self):
        return self.d.iteritems()

    def default(self, key):
        defaults = {
            'showingBits' : '0',
            'episodeNumber' : '0',
            'displayMajorNumber' : '0',
            'displayMinorNumber' : '0',
            'isEpisode' : 'true',
            'colorCode' : ('COLOR', '4'),
            'showType' : ('SERIES', '5'),
            'tvRating' : ('NR', '7')
        }
        if key in defaults:
            return defaults[key]
        elif key.startswith('v'):
            return []
        else:
            return ''
