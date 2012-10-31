#!/usr/bin/env python
#
# Metricinga - A coroutine-based performance data forwarder for Nagios/Icinga
#
# Author: Jeff Goldschrafe <jeff@holyhandgrenade.org>

import atexit
import os
import cPickle as pickle
from pprint import pformat, pprint
import re
import signal
import socket
import struct
import sys
import time

import gevent
from gevent import Timeout
from gevent.queue import PriorityQueue
import logging
import logging.handlers
from optparse import OptionGroup, OptionParser

try:
    import gevent_inotifyx as inotify
    use_inotify = True
except ImportError, ex:
    use_inotify = False


#
# Basic data structures
#

class Metric:
    def __init__(self, name, timestamp, value):
        self.name = name
        self.timestamp = timestamp
        self.value = value


#
# Daemon implementation
#

class Daemon:
    """
    A generic daemon class.
    
    Usage: subclass the Daemon class and override the run() method
    """
    def __init__(self, pidfile, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.pidfile = pidfile

    
    def daemonize(self):
        """
        do the UNIX double-fork magic, see Stevens' "Advanced 
        Programming in the UNIX Environment" for details (ISBN 0201563177)
        http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
        """
        try: 
            pid = os.fork() 
            if pid > 0:
                # exit first parent
                sys.exit(0) 
        except OSError, e: 
            sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
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
            sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1) 
    
        # redirect standard file descriptors
        sys.stdout.flush()
        sys.stderr.flush()
        si = file(self.stdin, 'r')
        so = file(self.stdout, 'a+')
        se = file(self.stderr, 'a+', 0)
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())
    
        # write pidfile
        atexit.register(self.delpid)
        pid = str(os.getpid())
        file(self.pidfile,'w+').write("%s\n" % pid)

    
    def delpid(self):
        os.remove(self.pidfile)


    def start(self):
        """
        Start the daemon
        """
        # Check for a pidfile to see if the daemon already runs
        try:
            pf = file(self.pidfile, 'r')
            pid = int(pf.read().strip())
            pf.close()
        except IOError:
            pid = None
    
        if pid:
            message = "pidfile %s already exists. Check that the daemon is not already running.\n"
            sys.stderr.write(message % self.pidfile)
            sys.exit(1)
        
        # Start the daemon
        self.daemonize()
        self.run()


    def stop(self):
        """
        Stop the daemon
        """
        # Get the pid from the pidfile
        try:
            pf = file(self.pidfile,'r')
            pid = int(pf.read().strip())
            pf.close()
        except IOError:
            pid = None
    
        if not pid:
            message = "pidfile %s does not exist. Daemon not running?\n"
            sys.stderr.write(message % self.pidfile)
            return # not an error in a restart

        # Try killing the daemon process    
        try:
            while 1:
                os.kill(pid, SIGTERM)
                time.sleep(0.1)
        except OSError, err:
            err = str(err)
            if err.find("No such process") > 0:
                if os.path.exists(self.pidfile):
                    os.remove(self.pidfile)
            else:
                print str(err)
                sys.exit(1)


    def restart(self):
        """
        Restart the daemon
        """
        self.stop()
        self.start()


    def run(self):
        """
        """
        def handler(signum, frame):
            cleanup(signum, tasks, queues)
    
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
    
        file_q = PriorityQueue()
        metrics_q = PriorityQueue()
        queues = [file_q, metrics_q]
        
        carbon_writer = CarbonPickleWriter(host, port)
        writers = [carbon_writer]
        
        # If we use inotify, we kick off a single-run spool runner greenlet and
        # an inotify greenlet. If we do not use inotify, the spool runner will
        # run indefinitely, processing the entire spool at some interval.
        if use_inotify:
            gevent.spawn(inotify_task, perfdata_spool_dir, file_q)
            gevent.spawn(spool_runner_task, perfdata_spool_dir, file_q)
        else:
            gevent.spawn(spool_runner_task, perfdata_spool_dir, file_q, 60)
        
        tasks = []
        tasks.append(gevent.spawn(file_task, file_q, metrics_q))
        tasks.append(gevent.spawn(write_dispatcher_task, writers, metrics_q))
        
        try:
            gevent.joinall(tasks)
        except KeyboardInterrupt, ex:
            cleanup(signal.SIGINT, tasks, queues)
        finally:
            log.info("Shut down successfully.")


#
# Event classes
#

class ApplicationEvent:
    pass


class CallableEvent(ApplicationEvent):
    def __init__(self, callback, *args):
        self.callback = callback
        self.args = args


    def __call__(self):
        self.callback(*self.args)


class CleanupEvent(ApplicationEvent):
    pass


class FileEvent(ApplicationEvent):
    def __init__(self, filename):
        self.filename = filename


class MetricEvent(ApplicationEvent):
    def __init__(self, metric):
        self.metric = metric


#
# Writer classes
#

class CarbonWriter:
    def __init__(self, host, port):
        """
        """
        self.host = host
        self.port = port
        self.backoff_secs = 0

        self.connect()


    def connect(self):
        """
        """
        gevent.sleep(self.backoff_secs)

        log.info("Connecting to Carbon instance at %s:%s" %
                 (self.host, self.port))

        self.sock = socket.socket()

        try:
            self.sock.connect((self.host, self.port))
            log.info("Connected to Carbon successfully")
            self.reset_backoff()
        except socket.error, ex:
            log.warn("Failed to connect to %s:%s" %
                     (self.host, self.port))

            self.increase_backoff()

            log.warn("Reconnecting in %s seconds" % self.backoff_secs)


    def increase_backoff(self):
        if self.backoff_secs == 0:
            self.backoff_secs = 1
        elif self.backoff_secs < 32:
            self.backoff_secs *= 2


    def reset_backoff(self):
        self.backoff_secs = 0


    def send_metric(self, metric):
        """
        Try to send a metric to the Graphite server. If the send fails
        because the socket is in an inoperable state, block the writer
        and continue trying to reconnect until the connection is
        successful.
        """
        (name, timestamp, value) = (metric.name, metric.timestamp,
                metric.value)

        while True:
            try:
                log.debug("Sending metric to Carbon: %s %s %s" %
                          (name, timestamp, value))

                pickle_list = [(name, (timestamp, value))]
                payload = pickle.dumps(pickle_list)
                header = struct.pack("!L", len(payload))
                message = header + payload

                self.sock.sendall(message)
                break
            except socket.error, ex:
                log.warn("Couldn't send to %s:%s: %s" %
                         (self.host, self.port, ex))
                self.connect()


class CarbonPickleWriter(CarbonWriter):
    pass


def cleanup(signal, tasks, queues):
    log.info("Caught shutdown; flushing queues and terminating")
       
    for q in queues:
        q.put((50, CleanupEvent()))

    gevent.joinall(tasks)


def delete_file(f):
    """
    Unlink a file and log success or failure.
    """

    try:
        os.remove(f)
        log.info("Deleted file %s" % (f,))
    except OSError, ex:
        log.warn("Failed to delete file %s: %s" % (f, ex))


def inotify_task(dir, q):
    """
    Receive InotifyEvents and dispatch corresponding FileEvents.
    """
    fd = inotify.init()
    wd = inotify.add_watch(fd, dir, inotify.IN_CLOSE_WRITE)

    while True:
        events = inotify.get_events(fd)
        for event in events:
            q.put((49, FileEvent(event.name)))


def extract_fields(line):
    """
    Parse KEY::VALUE pairs from a line of performance data and return it
    as a dictionary of properties.
    """
    dict = {}
    field_tokens = line.split("\t")
    for field_token in field_tokens:
        kv_tokens = field_token.split('::')
        if len(kv_tokens) == 2:
            (key, value) = kv_tokens
            dict[key] = value

    return dict


def fields_valid(d):
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


def file_task(file_q, metrics_q):
    while True:
        (pri, event) = file_q.get()

        if event.__class__ == CallableEvent:
            event()
        elif event.__class__ == CleanupEvent:
            log.info("File processor task shutting down")
            break
        else:
            filename = os.path.join(perfdata_spool_dir, event.filename)
            process_file(filename, metrics_q)


def parse_options():
    parser = OptionParser()

    parser.add_option('-d', '--debug',
            help='Do not daemonize; enable debug-level logging',
            dest='debug', action='store_true')
    parser.add_option('-D', '--spool-dir',
            help='Path to performance data spool dir',
            dest='spool_dir')
    parser.add_option('-H', '--host',
            help='Host to submit metrics to',
            dest='host')
    parser.add_option('-p', '--port',
            help='Port to submit metrics to',
            dest='port')
    parser.add_option('-P', '--prefix',
            help='Prefix to prepend to all metric names',
            dest='prefix')
    parser.add_option('-r', '--replacement-char',
            help='Replacement character for illegal metric characters (e.g. ".")',
            dest='replacement_char')

    (opts, args) = parser.parse_args()
    return (opts, args)


def parse_perfdata(s):
    """
    """

    metrics = []

    tokenizer_re = \
            r"([^\s]+|'[^']+')=([-.\d]+)(c|s|us|ms|B|KB|MB|GB|TB|%)?(?:;([-.\d]+))?(?:;([-.\d]+))?(?:;([-.\d]+))?(?:;([-.\d]+))?"
    counters = re.findall(tokenizer_re, s)
    
    if counters is None:
        log.warning("Failed to parse performance data: %s" % (s,))
        return metrics

    for (key, value, uom, warn, crit, min, max) in counters:
        try:
            metrics.append((key, float(value)))
        except ValueError, ex:
            log.warning("Couldn't convert value '%s' to float" % (value,))

    return metrics


def process_check_result(check_result, metrics_q):
    if not fields_valid(check_result):
        log.debug("Couldn't validate fields: " + pformat(check_result))
        return

    metric_path_root = []

    if metric_prefix != '':
        metric_path_root.append(metric_prefix)

    perfdata_prefix = check_result.get('GRAPHITEPREFIX')
    if perfdata_prefix is not None:
        metric_path_root.append(perfdata_prefix)

    hostname = sanitize_metric_name(check_result['HOSTNAME'].lower())
    metric_path_root.append(hostname)

    datatype = check_result['DATATYPE']

    if datatype == 'HOSTPERFDATA':
        metric_path_root.append('host')
    if datatype == 'SERVICEPERFDATA':
        graphite_postfix = check_result.get('GRAPHITEPOSTFIX')
        service_desc = check_result.get('SERVICEDESC')

        if graphite_postfix is not None:
            metric_path_root.append(graphite_postfix)
        else:
            metric_path_root.append(service_desc)

    perfdata = check_result[datatype]
    timestamp = check_result['TIMET']
    counters = parse_perfdata(perfdata)

    for (counter, value) in counters:
        metric_path = metric_path_root + [counter]
        metric_name = ".".join([sanitize_metric_name(x) for x in metric_path])

        metric = Metric(metric_name, timestamp, value)
        event = MetricEvent(metric)

        log.debug("Submitting perfdata: %s = %s (%s)" %
                  (metric.name, metric.value, metric.timestamp))

        metrics_q.put((50, event))


def process_file(file_name, metrics_q):
    log.debug("Processing file %s" % (file_name,))

    try:
        with open(file_name, "r") as file:
            for line in file:
                line = line.rstrip(os.linesep)
                check_result = extract_fields(line)
                process_check_result(check_result, metrics_q)
                gevent.sleep(0)
                
            callable = CallableEvent(delete_file, file_name)
            metrics_q.put((50, callable))
    except IOError, ex:
        log.critical("Can't open file %s: %s" % (file_name, ex))


# Known bug: this can queue the same file several times if the file
# still exists between sweeps. Some sort of check for this needs to
# be added.
def spool_runner_task(dir, file_q, poll_interval=None):
    log.debug("Initializing spool runner task")

    while True:
        log.info("Processing spool in %s" % (dir,))

        for file in os.listdir(dir):
            file_q.put((50, FileEvent(file)))

        if poll_interval is not None:
            gevent.sleep(poll_interval)
        else:
            break



def sanitize_metric_name(s):
    return re.sub("[^\w-]", metric_replacement_char, s)


def write_dispatcher_task(writers, metrics_q):
    log.debug("Initializing writer task")
    while True:
        (pri, event) = metrics_q.get()

        if event.__class__ == CallableEvent:
            event()
        elif event.__class__ == CleanupEvent:
            log.info("Writer task shutting down")
            break
        else:
            for writer in writers:
                writer.send_metric(event.metric)
                gevent.sleep(0)


#
# Parse options
#

host = None
port = 2004
metric_prefix = ''
metric_replacement_char = '_'
perfdata_spool_dir = '/var/spool/metricinga'
pidfile = '/var/run/metricinga.pid'
daemonize = True
log_level = logging.INFO

(opts, args) = parse_options()

if opts.host is not None:
    host = opts.host
if opts.port is not None:
    port = opts.port
if opts.prefix is not None:
    metric_prefix = opts.prefix
if opts.replacement_char is not None:
    metric_replacement_char = opts.replacement_char
if opts.spool_dir is not None:
    perfdata_spool_dir = opts.spool_dir
if opts.debug is True:
    log_level = logging.DEBUG
    daemonize = False


if host is None:
    print("Fatal: No Graphite host specified!")
    sys.exit(1)


#
# Initialize logger
#

if daemonize is True:
    log_handler = logging.handlers.SysLogHandler('/dev/log')
    formatter = logging.Formatter(
            "%(filename)s: %(levelname)s %(message)s")
else:
    log_handler = logging.StreamHandler()
    formatter = logging.Formatter(
            "%(asctime)s %(filename)s: %(levelname)s %(message)s",
            "%Y/%m/%d %H:%M:%S")

log_handler.setFormatter(formatter)

log = logging.getLogger('log')
log.addHandler(log_handler)
log.setLevel(log_level)

log.info("Starting up...")


#
# Do the magic
#

app = Daemon(pidfile)

if daemonize is True:
    app.start()
else:
    app.run()

