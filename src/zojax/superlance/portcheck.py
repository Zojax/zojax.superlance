##############################################################################
#
# Copyright (c) 2008 Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""

$Id$
"""

import os, sys


def shell(cmd):
    return os.popen(cmd).read()

def write_stdout(s):
    sys.stdout.write(s)
    sys.stdout.flush()

def write_stderr(s):
    sys.stderr.write(s)
    sys.stderr.flush()

class PortListenCheck(object):

    def listenPort(self, pingport=None):
        netstat = """netstat -an | awk '{print $4"\t"$6}' | grep ':%s' | awk '{print $2}'"""

        state = True

        if not pingport:
            return state

        proc_state = shell(netstat % pingport)

        if 'LISTEN' not in proc_state:
            write_stderr( "Process is not running yet\n" )
            state = False

        return state


