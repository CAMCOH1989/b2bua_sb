# Copyright (c) 2003-2005 Maxim Sobolev. All rights reserved.
# Copyright (c) 2006-2014 Sippy Software, Inc. All rights reserved.
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation and/or
# other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from signal import signal, SIG_IGN, SIG_DFL

from sippy.Core.Exceptions import dump_exception
from sippy.Core.EventDispatcher import ED2


class Signal(object):
    callback = None
    parameters = None
    previous_handler = None

    def __init__(self, signum, callback, *parameters):
        self.signum = signum
        self.callback = callback
        self.parameters = parameters
        self.previous_handler = signal(signum, self.signal_handler)

    def signal_handler(self, signum, *frame):
        ED2.callFromThread(self.dispatch)
        if self.previous_handler not in (SIG_IGN, SIG_DFL):
            try:
                self.previous_handler(signum, *frame)
            except:
                dump_exception('Signal: unhandled exception in signal chain')

    def dispatch(self):
        try:
            self.callback(*self.parameters)
        except:
            dump_exception('Signal: unhandled exception in signal callback')

    def cancel(self):
        signal(self.signum, self.previous_handler)
        self.callback = None
        self.parameters = None
        self.previous_handler = None


def log_signal(signum, sip_logger, signal_cb, callback_params):
    sip_logger.write('Dispatching signal %d to handler %s' % (signum, str(signal_cb)))
    return signal_cb(*callback_params)


def LogSignal(sip_logger, signum, signal_cb, *callback_params):
    sip_logger.write('Registering signal %d to handler %s' % (signum, str(signal_cb)))
    return Signal(signum, log_signal, signum, sip_logger, signal_cb, callback_params)


if __name__ == '__main__':
    from signal import SIGHUP, SIGURG, SIGTERM
    from os import kill, getpid


    def test(arguments):
        arguments['test'] = not arguments['test']
        ED2.breakLoop()


    arguments = {'test': False}
    s = Signal(SIGURG, test, arguments)
    kill(getpid(), SIGURG)
    ED2.loop()
    assert (arguments['test'])
    s.cancel()
    Signal(SIGHUP, test, arguments)
    kill(getpid(), SIGURG)
    kill(getpid(), SIGHUP)
    ED2.loop()
    assert (not arguments['test'])
    from sippy.SipLogger import SipLogger

    sip_logger = SipLogger('Signal::selftest')
    LogSignal(sip_logger, SIGTERM, test, arguments)
    kill(getpid(), SIGTERM)
    ED2.loop()
    assert (arguments['test'])
