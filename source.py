import os
import simplejson
import datetime
import time
import urllib2
from elementtree import ElementTree
from strings import *
import ysapi

class Channel(object):
    def __init__(self, id, title, logo = None):
        self.id = id
        self.title = title
        self.logo = logo

    def __str__(self):
        return 'Channel(id=%s, title=%s, logo=%s)' \
               % (self.id, self.title, self.logo)

class Program(object):
    def __init__(self, channel, title, startDate, endDate, description):
        self.channel = channel
        self.title = title
        self.startDate = startDate
        self.endDate = endDate
        self.description = description

    def __str__(self):
        return 'Program(channel=%s, title=%s, startDate=%s, endDate=%s, description=%s)' % \
            (self.channel, self.title, self.startDate, self.endDate, self.description)


class Source(object):
    CACHE_MINUTES = 10

    def __init__(self, settings, hasChannelIcons):
        self.channelIcons = hasChannelIcons
        self.cachePath = settings['cache.path']

        self.cachedChannelList = None
        self.cachedProgramList = dict()

    def hasChannelIcons(self):
        return self.channelIcons

    def getCurrentProgram(self, channel):
        programs = self.cachedProgramList.get(channel)
        now = datetime.datetime.today()
        for program in programs:
            if program.startDate < now and program.endDate > now:
                return program

        return None

    def getChannelList(self):
        if self.cachedChannelList is None:
            self.cachedChannelList = self._getChannelList()

        return self.cachedChannelList

    def _getChannelList(self):
        return None

    def getProgramList(self, channel):
        if not self.cachedProgramList.has_key(channel):
            programList = self._getProgramList(channel)
            self.cachedProgramList[channel] = programList

        return self.cachedProgramList[channel]
    
    def _getProgramList(self, channel):
        return None

    def _downloadAndCacheUrl(self, url, cacheName):
        cacheFile = os.path.join(self.cachePath, cacheName)
        try:
            cachedOn = os.path.getmtime(cacheFile)
        except OSError:
            cachedOn = 0

        if time.time() - self.CACHE_MINUTES * 60 >= cachedOn:
            # Cache expired or miss
            u = urllib2.urlopen(url)
            content = u.read()
            u.close()
            
            if not os.path.exists(self.cachePath):
                os.mkdir(self.cachePath)

            f = open(cacheFile, 'w')
            f.write(content)
            f.close()

        else:
            f = open(cacheFile)
            content = f.read()
            f.close()

        return content

    def _cacheLogo(self, url, cacheName):
        cacheFile = os.path.join(self.cachePath, cacheName)
        if not os.path.exists(cacheFile):
            try:
                u = urllib2.urlopen(url)
                content = u.read()
                u.close()
            except urllib2.HTTPError:
                return None

            if not os.path.exists(self.cachePath):
                os.mkdir(self.cachePath)

            f = open(cacheFile, 'w')
            f.write(content)
            f.close()

        return cacheFile


class DrDkSource(Source):
    KEY = 'drdk'

    CHANNELS_URL = 'http://www.dr.dk/tjenester/programoversigt/dbservice.ashx/getChannels?type=tv'
    PROGRAMS_URL = 'http://www.dr.dk/tjenester/programoversigt/dbservice.ashx/getSchedule?channel_source_url=%s&broadcastDate=%s'

    def __init__(self, setings):
        Source.__init__(self, settings, False)
        self.date = datetime.datetime.today()

    def _getChannelList(self):
        jsonChannels = simplejson.loads(self._downloadAndCacheUrl(self.CHANNELS_URL, self.KEY + '-channels.json'))
        channelList = list()

        for channel in jsonChannels['result']:
            c = Channel(id = channel['source_url'], title = channel['name'])
            channelList.append(c)

        return channelList


    def _getProgramList(self, channel):
        url = self.PROGRAMS_URL % (channel.id.replace('+', '%2b'), self.date.strftime('%Y-%m-%dT%H:%M:%S'))
        jsonPrograms = simplejson.loads(self._downloadAndCacheUrl(url, self.KEY + '-' + channel.id.replace('/', '')))
        programs = list()

        for program in jsonPrograms['result']:
            if program.has_key('ppu_description'):
                description = program['ppu_description']
            else:
                description = strings(NO_DESCRIPTION)

            programs.append(Program(channel, program['pro_title'], self._parseDate(program['pg_start']), self._parseDate(program['pg_stop']), description))

        return programs
    
    def _parseDate(self, dateString):
        t = time.strptime(dateString[:19], '%Y-%m-%dT%H:%M:%S')
        return datetime.datetime(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)


class YouSeeTvSource(Source):
    KEY = 'youseetv'

    CHANNELS_URL = 'http://yousee.tv'
    PROGRAMS_URL = 'http://yousee.tv/feeds/tvguide/getprogrammes/?channel=%s'

    def __init__(self, settings):
        Source.__init__(self, settings, False)
        self.date = datetime.datetime.today()
        self.channelCategory = settings['youseetv.category']
        self.ysApi = ysapi.YouSeeTVGuideApi()

    def _getChannelList(self):
        channelList = list()
        for channel in self.ysApi.channelsInCategory(self.channelCategory):
            c = Channel(id = channel['id'], title = channel['name'], logo = channel['logo'])
            channelList.append(c)

        return channelList

    def _getProgramList(self, channel):
        programs = list()
        for program in self.ysApi.programs(channel.id):
            description = program['description']
            if description is None:
                description = strings(NO_DESCRIPTION)

            p = Program(channel, program['title'], self._parseDate(program['begin']), self._parseDate(program['end']), description)
            programs.append(p)

        return programs

    def _parseDate(self, dateString):
        return datetime.datetime.fromtimestamp(dateString)


class TvTidSource(Source):
    # http://tvtid.tv2.dk/js/fetch.js.php/from-1291057200.js
    KEY = 'tvtiddk'

    BASE_URL = 'http://tvtid.tv2.dk%s'
    FETCH_URL = BASE_URL % '/js/fetch.js.php/from-%d.js'

    def __init__(self, settings):
        Source.__init__(self, settings, True)
        self.time = time.time()

        # calculate nearest hour
        self.time -= self.time % 3600

    def _getChannelList(self):
        response = self._downloadAndCacheUrl(self.FETCH_URL % self.time, self.KEY + '-data.json')
        json = simplejson.loads(response)

        channelList = list()
        for channel in json['channels']:
            logoFile = self._cacheLogo(self.BASE_URL % channel['logo'], self.KEY + '-' + str(channel['id']) + '.jpg')

            c = Channel(id = channel['id'], title = channel['name'], logo = logoFile)
            channelList.append(c)

        return channelList

    def _getProgramList(self, channel):
        response = self._downloadAndCacheUrl(self.FETCH_URL % self.time, self.KEY + '-data.json')
        json = simplejson.loads(response)

        c = None
        for c in json['channels']:
            if c['id'] == channel.id:
                break

        # assume we always find a channel
        programs = list()

        for program in c['program']:
            description = program['short_description']
            if description is None:
                description = strings(NO_DESCRIPTION)

            programs.append(Program(channel, program['title'], datetime.datetime.fromtimestamp(program['start_timestamp']), datetime.datetime.fromtimestamp(program['end_timestamp']), description))

        return programs

class XMLTVSource(Source):
    KEY = 'xmltv'

    def __init__(self, settings):
        Source.__init__(self, settings, True)
        self.xmlTvFile = settings['xmltv.file']
        self.time = time.time()

        # calculate nearest hour
        self.time -= self.time % 3600

    def _getChannelList(self):
        doc = self._loadXml()
        channelList = list()
        for channel in doc.findall('channel'):
            c = Channel(id = channel.get('id'), title = channel.findtext('display-name'), logo = channel.find('icon').get('src'))
            channelList.append(c)

        return channelList

    def _getProgramList(self, channel):
        doc = self._loadXml()
        programs = list()
        for program in doc.findall('programme'):
            if program.get('channel') != channel.id:
                continue

            description = program.findtext('desc')
            if description is None:
                description = strings(NO_DESCRIPTION)

            programs.append(Program(channel, program.findtext('title'), self._parseDate(program.get('start')), self._parseDate(program.get('stop')), description))

        return programs

    def _loadXml(self):
        f = open(self.xmlTvFile)
        xml = f.read()
        f.close()

        return ElementTree.fromstring(xml)


    def _parseDate(self, dateString):
        dateStringWithoutTimeZone = dateString[:-6]
        t = time.strptime(dateStringWithoutTimeZone, '%Y%m%d%H%M%S')
        return datetime.datetime(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)

