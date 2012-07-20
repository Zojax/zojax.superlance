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
# events, which restarts processes that are children of
# supervisord based on the response from an HTTP port.

# A supervisor config snippet that tells supervisor to use this script
# as a listener is below.
#
# [eventlistener:httpokport]
# command=python -u /bin/httpokport http://localhost:8080/tasty/service
# events=TICK_60

doc = """\
httpokport.py [-p processname] [-a] [-g] [-t timeout] [-c status_code] [-b inbody]
          [-m mail_address] [-s sendmail] [-i pingport] URL

Options:

-p -- specify a supervisor process_name.  Restart the supervisor
      process named 'process_name' if it's in the RUNNING state when
      the URL returns an unexpected result or times out.  If this
      process is part of a group, it can be specified using the
      'group_name:process_name' syntax.

-a -- Restart any child of the supervisord under in the RUNNING state
      if the URL returns an unexpected result or times out.  Overrides
      any -p parameters passed in the same httpok process
      invocation.

-g -- The ``gcore`` program.  By default, this is ``/usr/bin/gcore
      -o``.  The program should accept two arguments on the command
      line: a filename and a pid.

-d -- Core directory.  If a core directory is specified, httpok will
      try to use the ``gcore`` program (see ``-g``) to write a core
      file into this directory against each hung process before we
      restart it.  Append gcore stdout output to email.

-t -- The number of seconds that httpok should wait for a response
      before timing out.  If this timeout is exceeded, httpok will
      attempt to restart processes in the RUNNING state specified by
      -p or -a.  This defaults to 10 seconds.

-c -- specify an expected HTTP status code from a GET request to the
      URL.  If this status code is not the status code provided by the
      response, httpok will attempt to restart processes in the
      RUNNING state specified by -p or -a.  This defaults to the
      string, "200".

-b -- specify a string which should be present in the body resulting
      from the GET request.  If this string is not present in the
      response, the processes in the RUNNING state specified by -p
      or -a will be restarted.  The default is to ignore the
      body.

-s -- the sendmail command to use to send email
      (e.g. "/usr/sbin/sendmail -t -i").  Must be a command which accepts
      header and message data on stdin and sends mail.
      Default is "/usr/sbin/sendmail -t -i".

-m -- specify an email address.  The script will send mail to this
      address when httpok attempts to restart processes.  If no email
      address is specified, email will not be sent.

-e -- "eager":  check URL / emit mail even if no process we are monitoring
      is in the RUNNING state.  Enabled by default.

-E -- not "eager":  do not check URL / emit mail if no process we are
      monitoring is in the RUNNING state.

-i -- pingport is port number value to be checked for being listened by
      any application

URL -- The URL to which to issue a GET request.

The -p option may be specified more than once, allowing for
specification of multiple processes.  Specifying -a overrides any
selection of -p.

A sample invocation:

httpokport.py -p program1 -p group1:program2 http://localhost:8080/tasty

"""

import os, sys, urlparse

from supervisor import childutils
from supervisor.states import ProcessStates

import superlance.timeoutconn as timeoutconn
from superlance.httpok import HTTPOk as HTTPOkBase

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


class CustomHTTPOk(HTTPOkBase, PortListenCheck):

    def __init__(self, *args, **kwargs):
        self.pingport = args[-1:]
        HTTPOkBase.__init__(self, *args[0:-1], **kwargs)

    def runforever(self, test=False):
        parsed = urlparse.urlsplit(self.url)
        scheme = parsed[0].lower()
        hostport = parsed[1]
        path = parsed[2]
        query = parsed[3]

        if query:
            path += '?' + query

        if self.connclass:
            ConnClass = self.connclass
        elif scheme == 'http':
            ConnClass = timeoutconn.TimeoutHTTPConnection
        elif scheme == 'https':
            ConnClass = timeoutconn.TimeoutHTTPSConnection
        else:
            raise ValueError('Bad scheme %s' % scheme)

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

            conn = ConnClass(hostport)
            conn.timeout = self.timeout

            act = False

            specs = self.listProcesses(ProcessStates.RUNNING)
            if self.eager or len(specs) > 0:

                try:
                    conn.request('GET', path)
                    res = conn.getresponse()
                    body = res.read()
                    status = res.status
                    msg = 'status contacting %s: %s %s' % (self.url,
                                                           res.status,
                                                           res.reason)
                except Exception, why:
                    body = ''
                    status = None
                    msg = 'error contacting %s:\n\n %s' % (self.url, why)

                if str(status) != str(self.status):
                    subject = 'httpok for %s: bad status returned' % self.url
                    self.act(subject, msg)
                elif self.inbody and self.inbody not in body:
                    act = True
                    subject = 'httpok for %s: bad body returned' % self.url
                    self.act(subject, msg)

            childutils.listener.ok(self.stdout)
            if test:
                break


def main(argv=sys.argv):
    import getopt
    short_args="hp:at:c:b:s:m:g:d:eE:i:"
    long_args=[
        "help",
        "program=",
        "any",
        "timeout=",
        "code=",
        "body=",
        "sendmail_program=",
        "email=",
        "gcore=",
        "coredir=",
        "eager",
        "not-eager",
        "pingport=",
        ]
    arguments = argv[1:]
    try:
        opts, args = getopt.getopt(arguments, short_args, long_args)
    except:
        usage()

    if not args:
        usage()
    if len(args) > 1:
        usage()

    programs = []
    any = False
    sendmail = '/usr/sbin/sendmail -t -i'
    gcore = '/usr/bin/gcore -o'
    coredir = None
    eager = True
    email = None
    timeout = 10
    status = '200'
    inbody = None
    pingport = None

    for option, value in opts:

        if option in ('-h', '--help'):
            usage()

        if option in ('-p', '--program'):
            programs.append(value)

        if option in ('-a', '--any'):
            any = True

        if option in ('-s', '--sendmail_program'):
            sendmail = value

        if option in ('-m', '--email'):
            email = value

        if option in ('-t', '--timeout'):
            timeout = int(value)

        if option in ('-c', '--code'):
            status = value

        if option in ('-b', '--body'):
            inbody = value

        if option in ('-g', '--gcore'):
            gcore = value

        if option in ('-d', '--coredir'):
            coredir = value

        if option in ('-e', '--eager'):
            eager = True

        if option in ('-E', '--not-eager'):
            eager = False

        if option in ('-i', '--pingport'):
            pingport = value

    url = arguments[-1]

    try:
        rpc = childutils.getRPCInterface(os.environ)
    except KeyError, why:
        if why[0] != 'SUPERVISOR_SERVER_URL':
            raise
        sys.stderr.write('httpok must be run as a supervisor event '
                         'listener\n')
        sys.stderr.flush()
        return

    prog = CustomHTTPOk(rpc, programs, any, url, timeout, status, inbody, email,
                  sendmail, coredir, gcore, eager, pingport)
    prog.runforever()

if __name__ == '__main__':
    main()



