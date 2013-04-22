#!/usr/bin/env python
#
# Metricinga - A gevent-based performance data forwarder for Nagios/Icinga
#
# Author: Jeff Goldschrafe <jeff@holyhandgrenade.org>

from argparse import ArgumentParser
import atexit
import cPickle as pickle
import os
import logging
import logging.handlers
from pprint import pformat, pprint
import re
import signal
import socket
import struct
import sys
import time

import gevent
from gevent import Greenlet, Timeout
import gevent.monkey
from gevent.queue import PriorityQueue

try:
    import gevent_inotifyx as inotify
    use_inotify = True
except ImportError, ex:
    use_inotify = False

gevent.monkey.patch_all()
log = logging.getLogger('log')

#
# Custom daemonizer (python-daemon has unexplained issues with gevent)
#

class Daemon:
    """Daemon class for Metricinga
    """
    def __init__(self, opts, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
        self.opts = opts
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr

    
    def daemonize(self):
        """Daemonize the application

        Do the UNIX double-fork magic, see Stevens' "Advanced 
        Programming in the UNIX Environment" for details (ISBN 0201563177)
        http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
        """
        try: 
            pid = os.fork() 
            if pid > 0:
                # exit first parent
                sys.exit(0) 
        except OSError, e: 
            log.error("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1)
    
        # decouple from parent environment
        os.chdir("/") 
        os.setsid() 
        os.umask(0) 
    
        # do second fork
        try: 
            pid = os.fork() 
            if pid > 0:
                # exit from second parent
                sys.exit(0) 
        except OSError, e: 
            log.error("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1) 
    
        # redirect standard file descriptors
        sys.stdout.flush()
        sys.stderr.flush()
        si = open(self.stdin, 'r')
        so = open(self.stdout, 'a+')
        se = open(self.stderr, 'a+', 0)
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())
    
        # write pidfile
        atexit.register(self.delpid)
        pid = str(os.getpid())
        open(self.opts.pidfile,'w+').write("%s\n" % pid)

    
    def delpid(self):
        """Delete configured pid file
        """
        os.remove(self.opts.pidfile)


    def start(self):
        """Start the daemon
        """
        # Check for a pidfile to see if the daemon already runs
        try:
            with open(self.opts.pidfile, 'r') as pf:
                pid = int(pf.read().strip())
        except IOError:
            pid = None
    
        if pid:
            message = "pidfile %s already exists. Check that the daemon is not already running.\n"
            log.error(message % self.opts.pidfile)
            sys.exit(1)
        
        # Start the daemon
        self.daemonize()
        self.run()


    def stop(self):
        """Stop the daemon
        """
        # Get the pid from the pidfile
        try:
            with open(self.opts.pidfile,'r') as pf:
                pid = int(pf.read().strip())
        except IOError:
            pid = None
    
        if not pid:
            message = "pidfile %s does not exist. Daemon not running?\n"
            log.error(message % self.opts.pidfile)
            return # not an error in a restart

        # Try killing the daemon process    
        try:
            while True:
                os.kill(pid, SIGTERM)
                time.sleep(0.1)
        except OSError, err:
            err = str(err)
            if err.find("No such process") > 0:
                if os.path.exists(self.opts.pidfile):
                    os.remove(self.opts.pidfile)
            else:
                log.error(err)
                sys.exit(1)


    def restart(self):
        """Restart the daemon
        """
        self.stop()
        self.start()


    def run(self):
        """Assemble Voltron and form blazing sword
        """
        cw = CarbonPickleWriter(self.opts)

        lp = LineProcessor(self.opts)
        lp.on_metric_found.subscribe(
                lambda metric: cw.send(PublishMetricRequest(metric)))

        fp = FileProcessor(self.opts)
        fp.on_line_found.subscribe(
                lambda line: lp.send(ParseLineRequest(line)))

        iw = InotifyWatcher(self.opts)
        iw.on_find.subscribe(
                lambda path: fp.send(ParseFileRequest(path)))

        sp = SpoolRunner(self.opts)
        sp.on_find.subscribe(
                lambda path: fp.send(ParseFileRequest(path)))

        actors = [cw, lp, fp]
        tasklets = [iw, sp]
        workers = actors + tasklets

        def shutdown(actors, tasklets):
            log.info("Received shutdown signal")
            for actor in actors:
                actor.send(ShutdownRequest(), priority=0)

            for tasklet in tasklets:
                tasklet.kill()

        gevent.signal(signal.SIGINT, shutdown, actors, tasklets)
        gevent.signal(signal.SIGTERM, shutdown, actors, tasklets)

        log.info("Starting up...")
        for worker in workers:
            worker.start()

        log.info("All workers started.")
        gevent.joinall(workers)
        log.info("Shut down successfully.")


#
# Utility classes
#

class Metric(object):
    """Represents a single datapoint of a system metric
    """
    def __init__(self, path=[], timestamp=0, value=0, source=None):
        self.path = path
        self.timestamp = timestamp
        self.value = value
        self.source = source


class PurgedFileFactory(object):
    """Manage state of PurgedFileToken instances

    Singleton-like factory to ensure file paths are not shared between
    PurgedFileToken instances.
    """
    instances = {}

    @staticmethod
    def create(path):
        """Create a unique PurgedFileToken for a path

        If this is the first request to create a PurgedFileToken for a
        path, create a new instance and return it. If an instance
        already exists, return None.
        """
        if PurgedFileFactory.instances.get(path):
            return None
        else:
            PurgedFileFactory.instances[path] = True
            return PurgedFileToken(path)

    @staticmethod
    def destroy(path):
        """Remove the PurgedFileToken associated with a path
        """
        if path in PurgedFileFactory.instances:
            del PurgedFileFactory.instances[path]            


class PurgedFileToken(object):
    """Deletes a file when the last reference to the token leaves scope
    """
    def __init__(self, path):
        self.path = path

    def __del__(self):
        log.debug("Unlinking file `{0}'".format(self.path))
        try:
            os.remove(self.path)
        except OSError, ex:
            err = "Tried to delete `{path}', but it doesn't exist"
            log.warn(err.format(path=self.path))
        PurgedFileFactory.destroy(self.path)


class SourcedString(object):
    """Pairs a string with the PurgedFileToken it originated from

    Allows the original source to be purged when all references to its
    data have been removed from scope.
    """
    def __init__(self, string_, source):
        self.string_ = string_
        self.source = source


#
# Message encapsulation classes
#

class ShutdownRequest(object):
    """Request that an Actor clean up and terminate execution
    """
    pass


class ParseFileRequest(object):
    """Request that an Actor parse a file
    """
    def __init__(self, path):
        self.path = path


class ParseLineRequest(object):
    """Request that an Actor parse a line
    """
    def __init__(self, line):
        self.line = line


class PublishMetricRequest(object):
    """Request that an Actor publish a Metric
    """
    def __init__(self, metric):
        self.metric = metric


#
# Event binding classes
#

class BoundEvent(object):
    """Helper for defining subscribable events on classes
    """
    def __init__(self):
        self._fns = []

    def __call__(self, *args, **kwargs):
        for f in self._fns:
            f(*args, **kwargs)

    def subscribe(self, fn):
        self._fns.append(fn)

    def unsubscribe(self, fn):
        self._fns.remove(fn)


class event(object):
    """Decorator for defining subscribable events on classes
    """
    def __init__(self, func):
        self.__doc__ = func.__doc__
        self._key = ' ' + func.__name__

    def __get__(self, obj, cls):
        try:
            return obj.__dict__[self._key]
        except KeyError, exc:
            be = obj.__dict__[self._key] = BoundEvent()
            return be


#
# Greenlet classes
#

class Actor(Greenlet):
    """Simple implementation of the Actor pattern
    """

    def __init__(self):
        self.inbox = PriorityQueue()
        self._handlers = {ShutdownRequest: self.receive_shutdown}
        Greenlet.__init__(self)

    def receive(self, msg):
        """Dispatch a received message to the appropriate type handler
        """
        #log.debug("Received a message: " + repr(msg))
        cls = msg.__class__
        if cls in self._handlers.keys():
            self._handlers[cls](msg)
        else:
            raise NotImplemented()

    def receive_shutdown(self, msg):
        self.running = False

    def send(self, msg, priority=50):
        """Place a message into the actor's inbox
        """
        self.inbox.put((priority, msg))

    def _run(self):
        """Run the Actor in a blocking event loop
        """
        self.running = True

        while self.running:
            prio, msg = self.inbox.get()
            self.receive(msg)
            del msg


class CarbonWriter(Actor):
    """Dispatch PublishMetricRequest messages to Carbon
    """

    def __init__(self, opts):
        self.opts = opts
        self.backoff_secs = 0
        self.max_backoff_secs = 32
        self.sleep_secs = 0

        Actor.__init__(self)
        self._handlers[PublishMetricRequest] = self.receive_publish
        self._connect()


    def receive_publish(self, msg):
        """Handle received PublishMetricRequest messages

        Extract the Metric from the request, massage it into Carbon
        pickle format, and send it to Graphite. If the send fails
        because the socket is in an invalid state, requeue the metric
        at the front of the queue and then attempt to reconnect.
        """
        metric = msg.metric
        (path, timestamp, value) = (metric.path, metric.timestamp,
                                    metric.value)
        name = '.'.join([self._sanitize_metric_name(x) for x in path])

        try:
            log.debug("Sending metric to Carbon: %s %s %s" %
                      (name, timestamp, value))

            message = self._serialize(metric)
            self._sock.sendall(message)
            log.debug("Sent metric successfully.")
            gevent.sleep(self.sleep_secs)
        except socket.error, ex:
            # Attempt to reconnect, then re-queue the unsent metric
            log.warn("Couldn't send to %s:%s: %s" %
                     (self.opts.host, self.opts.port, ex))
            self.send(PublishMetricRequest(metric), priority=49)
            self._connect()


    def _connect(self):
        """Connect to the Carbon server

        Attempt to connect to the Carbon server. If the connection
        attempt fails, increase the backoff time and sleep the writer
        greenlet until the backoff time has elapsed.
        """
        gevent.sleep(self.backoff_secs)
        self._sock = socket.socket()

        try:
            log.info("Connecting to Carbon instance at %s:%s" %
                     (self.opts.host, self.opts.port))
            self._sock.connect((self.opts.host, self.opts.port))
            log.info("Connected to Carbon successfully")
            self._reset_backoff()
        except socket.error, ex:
            log.warn("Failed to connect to {host}:{port}; retry in {secs} seconds".format(
                     host=self.opts.host, port=self.opts.port,
                     secs=self.backoff_secs))
            self._increase_backoff()


    def _increase_backoff(self):
        """Increase the backoff timer until configured max is reached
        """
        if self.backoff_secs == 0:
            self.backoff_secs = 1
        elif self.backoff_secs < self.max_backoff_secs:
            self.backoff_secs *= 2


    def _reset_backoff(self):
        """Reset the backoff timer to 0
        """
        self.backoff_secs = 0


    def _sanitize_metric_name(self, s):
        """Replace unwanted characters in metric with escape sequence
        """
        return re.sub("[^\w-]", self.opts.replacement_char, s)


class CarbonLineWriter(CarbonWriter):
    def _serialize(self, metric):
        path_s = '.'.join([self._sanitize_metric_name(x)
                           for x in metric.path])
        return "{path} {value} {timestamp}\n".format(path=path_s,
                value=metric.value, timestamp=metric.timestamp)


class CarbonPickleWriter(CarbonWriter):
    def _serialize(self, metric):
        path_s = '.'.join([self._sanitize_metric_name(x)
                           for x in metric.path])
        pickle_list = [(path_s, (metric.timestamp, metric.value))]
        payload = pickle.dumps(pickle_list)
        header = struct.pack("!L", len(payload))
        return header + payload


class FileProcessor(Actor):
    """Parse files and dispatch events when lines found.
    """

    def __init__(self, opts):
        self.opts = opts
        Actor.__init__(self)
        self._handlers[ParseFileRequest] = self.receive_parse

    @event
    def on_line_found(self, line):
        """Called when a line is parsed from the file
        """

    def receive_parse(self, message):
        """Handle received ParseFileRequest messages

        Validate whether the requested file has already been seen. If it
        is a new file, read it line-by-line and dispatch the read lines
        to any event listener. If the file has already been seen (i.e.
        it is currently being processed), ignore the request.
        """
        path = message.path
        log.debug("Received file parse request: " + path)

        source = PurgedFileFactory.create(path)
        if source:
            log.debug("Accepted file parse request: " + path)
            try:
                with open(path, "r") as fp:
                    for line in fp:
                        sstr = SourcedString(line.rstrip(os.linesep),
                                             source)
                        self.on_line_found(sstr)
                        gevent.sleep(0)
            except IOError, ex:
                log.warn("Couldn't open file `{path}': {error}".format(
                        path=path, error=ex.strerror))
        else:
            log.debug("Received request to parse {0}, but file is already known".format(path))


class InotifyWatcher(Greenlet):
    """Monitor spool directory for inotify activity and emit events
    """
    def __init__(self, opts):
        self.opts = opts
        Greenlet.__init__(self)

    @event
    def on_find(self):
        """Called when a file is finished being written into spool
        """

    def _run(self):
        if not use_inotify:
            log.warn("gevent_inotifyx not loaded; not using inotify")
            return

        fd = inotify.init()
        wd = inotify.add_watch(fd, self.opts.spool_dir,
                inotify.IN_CLOSE_WRITE | inotify.IN_MOVED_TO)
        while True:
            events = inotify.get_events(fd)
            for event in events:
                path = os.path.sep.join([self.opts.spool_dir,
                                         event.name])

                # Filter out inotify events generated for files that
                # have been already unlinked from the filesystem
                # (IN_EXCL_UNLINK emulation)
                if os.path.exists(path):
                    self.on_find(path)


class LineProcessor(Actor):
    """Process lines of check results
    """

    def __init__(self, opts):
        self.opts = opts
        Actor.__init__(self)
        self._handlers[ParseLineRequest] = self.receive_line
        
        self.tokenizer_re = \
                r"([^\s]+|'[^']+')=([-.\d]+)(c|s|us|ms|B|KB|MB|GB|TB|%)?(?:;([-.\d]+))?(?:;([-.\d]+))?(?:;([-.\d]+))?(?:;([-.\d]+))?"

    @event
    def on_metric_found(self, metric):
        """Called when a metric is extracted by the line processor.
        """

    @event
    def on_parse_failed(self, line):
        """Called when the line processor fails to parse a line.
        """

    def receive_line(self, message):
        """Handle received ParseLineRequest messages

        Parse a line of performance data and validate that it is
        well-formed. If it is well-formed, emit one or more Metrics
        containing the performance data. If it is not well-formed,
        ignore it.
        """
        line = message.line.string_
        source = message.line.source
        fields = self._extract_fields(line)
        
        if not self._fields_valid(fields):
            return self.on_parse_failed(line)
        
        for metric in self._make_metrics(fields, source):
            self.on_metric_found(metric)
            gevent.sleep(0)


    def _extract_fields(self, line):
        """Parse KEY::VALUE pairs from a line of performance data
        """
        acc = {}
        field_tokens = line.split("\t")
        for field_token in field_tokens:
            kv_tokens = field_token.split('::')
            if len(kv_tokens) == 2:
                (key, value) = kv_tokens
                acc[key] = value

        return acc

    def _fields_valid(self, d):
        """Verify that all necessary fields are present
        """
        generic_fields = ['DATATYPE', 'HOSTNAME', 'TIMET']
        host_fields = ['HOSTPERFDATA']
        service_fields = ['SERVICEDESC', 'SERVICEPERFDATA']

        if 'DATATYPE' not in d:
            return False

        datatype = d['DATATYPE']
        if datatype == 'HOSTPERFDATA':
            fields = generic_fields + host_fields
        elif datatype == 'SERVICEPERFDATA':
            fields = generic_fields + service_fields
        else:
            return False

        for field in fields:
            if field not in d:
                return False

        return True

    def _make_metrics(self, fields, source):
        """Parse a field set for performance data and return Metrics
        """
        metric_path_base = []
        graphite_prefix = fields.get('GRAPHITEPREFIX')
        graphite_postfix = fields.get('GRAPHITEPOSTFIX')

        if self.opts.prefix:
            metric_path_base.append(self.opts.prefix)

        hostname = fields['HOSTNAME'].lower()
        metric_path_base.append(hostname)

        datatype = fields['DATATYPE']
        if datatype == 'HOSTPERFDATA':
            metric_path_base.append('host')
        elif datatype == 'SERVICEPERFDATA':
            service_desc = fields.get('SERVICEDESC')
            graphite_postfix = fields.get('GRAPHITEPOSTFIX')
            if graphite_postfix is not None:
                metric_path_base.append(graphite_postfix)
            else:
                metric_path_base.append(service_desc)

        timestamp = int(fields['TIMET'])
        perfdata = fields[datatype]
        counters = self._parse_perfdata(perfdata)

        for (counter, value) in counters:
            metric_path = metric_path_base + [counter]
            yield Metric(path=metric_path, timestamp=timestamp,
                         value=value, source=source)


    def _parse_perfdata(self, s):
        """Parse performance data from a *PERFDATA string
        """
        metrics = []
        counters = re.findall(self.tokenizer_re, s)
        if counters is None:
            log.warning("Failed to parse performance data: %s" % (s,))
            return metrics

        for (key, value, uom, warn, crit, min, max) in counters:
            try:
                metrics.append((key, float(value)))
            except ValueError, ex:
                log.warning("Couldn't convert value '%s' to float" % (value,))

        return metrics


class SpoolRunner(Greenlet):
    def __init__(self, opts):
        self.opts = opts
        Greenlet.__init__(self)

    @event
    def on_find(self):
        """Called when a file is found by the spool runner
        """

    def _run(self):
        while True:
            for filename in os.listdir(self.opts.spool_dir):
                self.on_find('/'.join([self.opts.spool_dir,
                                       filename]))

            if self.opts.poll_interval is not None:
                gevent.sleep(self.opts.poll_interval)
            else:
                break


def parse_arguments(args):
    parser = ArgumentParser()

    parser.set_defaults(daemonize=False,
                        host=None,
                        prefix=None,
                        replacement_char='_',
                        pidfile='/var/run/metricinga.pid',
                        poll_interval=60,
                        port=2004,
                        spool_dir='/var/spool/metricinga')
    parser.add_argument('-d', '--daemonize', action='store_true',
            help='Run as a daemon')
    parser.add_argument('--pidfile',
            help='Path to daemon pidfile')
    parser.add_argument('-v', '--verbose', action='store_true',
            help='Enable verbose output')

    parser.add_argument('-P', '--prefix',
            help='Prefix to prepend to all metric names')
    parser.add_argument('-r', '--replacement-char',
            help='Replacement char for illegal metric characters')
    parser.add_argument('-D', '--spool-dir',
            help='Spool directory to watch for perfdata files')
    parser.add_argument('--poll-interval', type=int,
            help='Spool polling interval (if not using inotify)')

    parser.add_argument('-H', '--host',
            help='Graphite host to submit metrics to')
    parser.add_argument('-p', '--port', type=int,
            help='Port to connect to')

    return parser.parse_args(args)


def main():
    opts = parse_arguments(sys.argv)

    if opts.host is None:
        print("Fatal: No Graphite host specified!")
        sys.exit(1)

    log_level = logging.INFO
    if opts.verbose:
        log_level = logging.DEBUG

    if use_inotify:
        opts.poll_interval = None

    if opts.daemonize:
        log_handler = logging.handlers.SysLogHandler('/dev/log')
        formatter = logging.Formatter(
                "%(filename)s: %(levelname)s %(message)s")
    else:
        log_handler = logging.StreamHandler()
        formatter = logging.Formatter(
                "%(asctime)s %(filename)s: %(levelname)s %(message)s",
                "%Y/%m/%d %H:%M:%S")

    log_handler.setFormatter(formatter)
    log.addHandler(log_handler)
    log.setLevel(log_level)

    app = Daemon(opts)
    if opts.daemonize:
        app.start()
    else:
        app.run()

if __name__ == '__main__':
    main()
