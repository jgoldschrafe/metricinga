About Metricinga
================
Metricinga is a gevent-based metrics forwarder that parses performance data
files from Nagios/Icinga and sends the results to Graphite via the Carbon
pickle port. It is designed to be lean, extensible, flexible, and easy to extend or hack on.

Support for StatsD and other metrics backends (OpenTSDB?) is planned.

Requirements
============
* Python 2.6 or greater (older versions may work also)
* argparse. if using Python <2.7
* gevent 1.0rc1+, installed from GitHub

Configuration
=============

Configuring Nagios/Icinga
-------------------------
If you're already using Graphios, you're already set up to send metrics through Metricinga, and you can skip to the next section! If not, read on.

### Modifying the daemon configuration

The default performance data output format used by Nagios and Icinga can't be easily extended to contain new attributes, so we're going to replace it with one that prints key-value pairs instead. This will allow us to add in whatever kind of bookkeeping attributes we want! We need these to do things like override the display name of a service with a metric name more meaningful to Graphite.

We'll need to edit one of the following files:

* **For Nagios:** /etc/nagios/nagios.cfg
* **For Icinga:** /etc/icinga/icinga.cfg

Make sure that the following configuration keys are set to something like the values below:

    process_performance_data=1
    host_perfdata_file=/var/spool/icinga/host-perfdata
    host_perfdata_file_mode=a
    host_perfdata_file_processing_command=process-host-perfdata-file
    host_perfdata_file_processing_interval=60
    host_perfdata_file_template=DATATYPE::HOSTPERFDATA\tTIMET::$TIMET$\tHOSTNAME::$HOSTNAME$\tHOSTPERFDATA::$HOSTPERFDATA$\tHOSTCHECKCOMMAND::$HOSTCHECKCOMMAND$\tHOSTSTATE::$HOSTSTATE$\tHOSTSTATETYPE::$HOSTSTATETYPE$\tGRAPHITEPREFIX::$_HOSTGRAPHITEPREFIX$\tGRAPHITEPOSTFIX::$_HOSTGRAPHITEPOSTFIX$
    service_perfdata_file=/var/spool/icinga/service-perfdata
    service_perfdata_file_mode=a
    service_perfdata_file_processing_command=process-service-perfdata-file
    service_perfdata_file_processing_interval=60
    service_perfdata_file_template=DATATYPE::SERVICEPERFDATA\tTIMET::$TIMET$\tHOSTNAME::$HOSTNAME$\tSERVICEDESC::$SERVICEDESC$\tSERVICEPERFDATA::$SERVICEPERFDATA$\tSERVICECHECKCOMMAND::$SERVICECHECKCOMMAND$\tHOSTSTATE::$HOSTSTATE$\tHOSTSTATETYPE::$HOSTSTATETYPE$\tSERVICESTATE::$SERVICESTATE$\tSERVICESTATETYPE::$SERVICESTATETYPE$\tGRAPHITEPREFIX::$_SERVICEGRAPHITEPREFIX$\tGRAPHITEPOSTFIX::$_SERVICEGRAPHITEPOSTFIX$

### Configuring file rotation

Next, the rotation commands need to be configured so the performance data files are periodically moved into the Metricinga spool directory. Depending on your system configuration, these commands may be located in `/etc/icinga/objects/commands.d`:

    define command {
        command_name    process-host-perfdata-file
        command_line    /bin/mv /var/spool/icinga/host-perfdata /var/spool/metricinga/host-perfdata.$TIMET$
    }

    define command {
        command_name    process-service-perfdata-file
        command_line    /bin/mv /var/spool/icinga/service-perfdata /var/spool/metricinga/service-perfdata.$TIMET$
    }

Configuring Metricinga
----------------------
Metricinga is configured entirely with command-line arguments. A basic sample invocation might look like this:

    python metricinga.py --prefix nagios --host graphite.mydomain.org --daemonize

Init scripts are coming soon!

BSD License
===========
Copyright (c) 2012-2013 Jeff Goldschrafe. All rights reserved. Some inspiration was taken from Shawn Sterling's [Graphios](https://github.com/shawn-sterling/graphios) project, though!

Redistribution and use in source and binary forms, with or without 
modification, are permitted provided that the following conditions are met:

  1. Redistributions of source code must retain the above copyright notice, this
     list of conditions and the following disclaimer.
  2. Redistributions in binary form must reproduce the above copyright notice,
     this list of conditions and the following disclaimer in the documentation
     and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND 
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED 
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE 
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE 
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL 
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR 
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER 
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, 
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE 
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
