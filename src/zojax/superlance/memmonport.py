#!/usr/bin/env python -u
##############################################################################
#
# Copyright (c) 2007 Agendaless Consulting and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the BSD-like license at
# http://www.repoze.org/LICENSE.txt.  A copy of the license should accompany
# this distribution.  THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL
# EXPRESS OR IMPLIED WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND
# FITNESS FOR A PARTICULAR PURPOSE
#
##############################################################################

# A event listener meant to be subscribed to TICK_60 (or TICK_5)
# events, which restarts any processes that are children of
# supervisord that consume "too much" memory.  Performs horrendous
# screenscrapes of ps output.  Works on Linux and OS X (Tiger/Leopard)
# as far as I know.

# A supervisor config snippet that tells supervisor to use this script
# as a listener is below.
#
# [eventlistener:memmonport]
# command=python memmonport.py [options]
# events=TICK_60

doc = """\
memmonport.py [-p processname=byte_size]  [-g groupname=byte_size]
          [-a byte_size] [-s sendmail] [-m email_address]

Options:

-p -- specify a process_name=byte_size pair.  Restart the supervisor
      process named 'process_name' when it uses more than byte_size
      RSS.  If this process is in a group, it can be specified using
      the 'process_name:group_name' syntax.

-g -- specify a group_name=byte_size pair.  Restart any process in this group
      when it uses more than byte_size RSS.

-a -- specify a global byte_size.  Restart any child of the supervisord
      under which this runs if it uses more than byte_size RSS.

-s -- the sendmail command to use to send email
      (e.g. "/usr/sbin/sendmail -t -i").  Must be a command which accepts
      header and message data on stdin and sends mail.
      Default is "/usr/sbin/sendmail -t -i".

-m -- specify an email address.  The script will send mail to this
      address when any process is restarted.  If no email address is
      specified, email will not be sent.

-i -- pingport is port number value to be checked for being listened by
      any application

The -p and -g options may be specified more than once, allowing for
specification of multiple groups and processes.

Any byte_size can be specified as a plain integer (10000) or a
suffix-multiplied integer (e.g. 1GB).  Valid suffixes are 'KB', 'MB'
and 'GB'.

A sample invocation:

memmonport.py -p program1=200MB -p theprog:thegroup=100MB -g thegroup=100MB -a 1GB -s "/usr/sbin/sendmail -t -i" -m chrism@plope.com
"""

import os
import sys

from supervisor import childutils
from supervisor.datatypes import byte_size

from superlance.memmon import Memmon as MemmonBase
from superlance.memmon import parse_namesize, parse_size

from portcheck import PortListenCheck

def usage():
    print doc
    sys.exit(255)

def shell(cmd):
    return os.popen(cmd).read()

def write_stdout(s):
    sys.stdout.write(s)
    sys.stdout.flush()

def write_stderr(s):
    sys.stderr.write(s)
    sys.stderr.flush()

class CustomMemmon(MemmonBase, PortListenCheck):

    def __init__(self, *args, **kwargs):
        self.pingport = args[-1:]
        MemmonBase.__init__(self, *args[0:-1], **kwargs)

    def runforever(self, test=False):
        while 1:
            # we explicitly use self.stdin, self.stdout, and self.stderr
            # instead of sys.* so we can unit test this code
            headers, payload = childutils.listener.wait(self.stdin, self.stdout)

            if not headers['eventname'].startswith('TICK'):
                # do nothing with non-TICK events
                childutils.listener.ok(self.stdout)
                if test:
                    break
                continue

            if not self.listenPort(self.pingport):
                childutils.listener.ok(self.stdout)
                continue

            status = []
            if self.programs:
                status.append(
                    'Checking programs %s' % ', '.join(
                    [ '%s=%s' % x for x in self.programs.items() ] )
                    )

            if self.groups:
                status.append(
                    'Checking groups %s' % ', '.join(
                    [ '%s=%s' % x for x in self.groups.items() ] )
                    )
            if self.any is not None:
                status.append('Checking any=%s' % self.any)

            self.stderr.write('\n'.join(status) + '\n')

            infos = self.rpc.supervisor.getAllProcessInfo()

            for info in infos:
                pid = info['pid']
                name = info['name']
                group = info['group']
                pname = '%s:%s' % (group, name)

                if not pid:
                    # ps throws an error in this case (for processes
                    # in standby mode, non-auto-started).
                    continue

                data = shell(self.pscommand % pid)
                if not data:
                    # no such pid (deal with race conditions)
                    continue

                try:
                    rss = data.lstrip().rstrip()
                    rss = int(rss) * 1024 # rss is in KB
                except ValueError:
                    # line doesn't contain any data, or rss cant be intified
                    continue

                for n in name, pname:
                    if n in self.programs:
                        self.stderr.write('RSS of %s is %s\n' % (pname, rss))
                        if  rss > self.programs[name]:
                            self.restart(pname, rss)
                            continue

                if group in self.groups:
                    self.stderr.write('RSS of %s is %s\n' % (pname, rss))
                    if rss > self.groups[group]:
                        self.restart(pname, rss)
                        continue

                if self.any is not None:
                    self.stderr.write('RSS of %s is %s\n' % (pname, rss))
                    if rss > self.any:
                        self.restart(pname, rss)
                        continue

            self.stderr.flush()
            childutils.listener.ok(self.stdout)
            if test:
                break


def main():
    import getopt
    short_args="hp:g:a:s:m:i:"
    long_args=[
        "help",
        "program=",
        "group=",
        "any=",
        "sendmail_program=",
        "email=",
        "pingport=",
        ]
    arguments = sys.argv[1:]
    if not arguments:
        usage()
    try:
        opts, args=getopt.getopt(arguments, short_args, long_args)
    except:
        print __doc__
        sys.exit(2)

    programs = {}
    groups = {}
    any = None
    sendmail = '/usr/sbin/sendmail -t -i'
    email = None
    pingport = None

    for option, value in opts:

        if option in ('-h', '--help'):
            usage()

        if option in ('-p', '--program'):
            name, size = parse_namesize(option, value)
            programs[name] = size

        if option in ('-g', '--group'):
            name, size = parse_namesize(option, value)
            groups[name] = size

        if option in ('-a', '--any'):
            size = parse_size(option, value)
            any = size

        if option in ('-s', '--sendmail_program'):
            sendmail = value

        if option in ('-m', '--email'):
            email = value

        if option in ('-i', '--pingport'):
            pingport = value

    rpc = childutils.getRPCInterface(os.environ)
    memmon = CustomMemmon(programs, groups, any, sendmail, email, rpc, pingport)
    memmon.runforever()

if __name__ == '__main__':
    main()



