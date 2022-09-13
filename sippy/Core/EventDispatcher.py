# Copyright (c) 2003-2005 Maxim Sobolev. All rights reserved.
# Copyright (c) 2006-2018 Sippy Software, Inc. All rights reserved.
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

from __future__ import print_function

from datetime import datetime
from heapq import heappush, heappop, heapify
from threading import Lock
from random import random
import sys
import traceback
import signal

if sys.version_info[0] < 3:
    from thread import get_ident
else:
    from _thread import get_ident
from sippy.Time.MonoTime import MonoTime
from sippy.Core.Exceptions import dump_exception, StdException
from elperiodic.ElPeriodic import ElPeriodic


class EventListener(object):
    etime = None
    cb_with_ts = False
    randomize_runs = None

    def __cmp__(self, other):
        if other == None:
            return 1
        return cmp(self.etime, other.etime)

    def __lt__(self, other):
        return self.etime < other.etime

    def cancel(self):
        if self.ed != None:
            # Do not crash if cleanup() has already been called
            self.ed.twasted += 1
        self.cleanup()

    def cleanup(self):
        self.callback_function = None
        self.callback_params = None
        self.cb_kw_args = None
        self.ed = None
        self.randomize_runs = None

    def get_randomizer(self, p):
        return lambda x: x * (1.0 + p * (1.0 - 2.0 * random()))

    def spread_runs(self, p):
        self.randomize_runs = self.get_randomizer(p)

    def go(self):
        if self.ed.my_ident != get_ident():
            print(datetime.now(), 'EventDispatcher2: Timer.go() from wrong thread, expect Bad Stuff[tm] to happen')
            print('-' * 70)
            traceback.print_stack(file=sys.stdout)
            print('-' * 70)
            sys.stdout.flush()
        if not self.abs_time:
            if self.randomize_runs != None:
                interval = self.randomize_runs(self.interval)
            else:
                interval = self.interval
            self.etime = self.itime.getOffsetCopy(interval)
        else:
            self.etime = self.interval
            self.interval = None
            self.number_of_ticks = 1
        heappush(self.ed.tlisteners, self)
        return


class Singleton(object):
    '''Use to create a singleton'''
    __state_lock = Lock()

    def __new__(cls, *args, **kwds):
        '''
        >>> s = Singleton()
        >>> p = Singleton()
        >>> id(s) == id(p)
        True
        '''
        sself = '__self__'
        cls.__state_lock.acquire()
        if not hasattr(cls, sself):
            instance = object.__new__(cls)
            instance.__sinit__(*args, **kwds)
            setattr(cls, sself, instance)
        cls.__state_lock.release()
        return getattr(cls, sself)

    def __sinit__(self, *args, **kwds):
        pass


class EventDispatcher2(Singleton):
    tlisteners = None
    slisteners = None
    endloop = False
    signals_pending = None
    twasted = 0
    tcbs_lock = None
    last_ts = None
    my_ident = None
    state_lock = Lock()
    ed_inum = 0
    elp = None
    bands = None

    def __init__(self, freq=100.0):
        EventDispatcher2.state_lock.acquire()
        if EventDispatcher2.ed_inum != 0:
            EventDispatcher2.state_lock.release()
            raise StdException('BZZZT, EventDispatcher2 has to be singleton!')
        EventDispatcher2.ed_inum = 1
        EventDispatcher2.state_lock.release()
        self.tcbs_lock = Lock()
        self.tlisteners = []
        self.slisteners = []
        self.signals_pending = []
        self.last_ts = MonoTime()
        self.my_ident = get_ident()
        self.elp = ElPeriodic(freq)
        self.elp.CFT_enable(signal.SIGURG)
        self.bands = [(freq, 0), ]

    def signal(self, signum, frame):
        self.signals_pending.append(signum)

    def regTimer(self, timeout_cb, interval, number_of_ticks=1, abs_time=False, *callback_params):
        self.last_ts = MonoTime()
        if number_of_ticks == 0:
            return
        if abs_time and not isinstance(interval, MonoTime):
            raise TypeError('interval is not MonoTime')
        el = EventListener()
        el.itime = self.last_ts.getCopy()
        el.callback_function = timeout_cb
        el.interval = interval
        el.number_of_ticks = number_of_ticks
        el.abs_time = abs_time
        el.callback_params = callback_params
        el.ed = self
        return el

    def dispatchTimers(self):
        while len(self.tlisteners) != 0:
            el = self.tlisteners[0]
            if el.callback_function != None and el.etime > self.last_ts:
                # We've finished
                return
            el = heappop(self.tlisteners)
            if el.callback_function == None:
                # Skip any already removed timers
                self.twasted -= 1
                continue
            if el.number_of_ticks == -1 or el.number_of_ticks > 1:
                # Re-schedule periodic timer
                if el.number_of_ticks > 1:
                    el.number_of_ticks -= 1
                if el.randomize_runs != None:
                    interval = el.randomize_runs(el.interval)
                else:
                    interval = el.interval
                el.etime.offset(interval)
                heappush(self.tlisteners, el)
                cleanup = False
            else:
                cleanup = True
            try:
                if not el.cb_with_ts:
                    el.callback_function(*el.callback_params)
                else:
                    el.callback_function(self.last_ts, *el.callback_params)
            except Exception as ex:
                if isinstance(ex, SystemExit):
                    raise
                dump_exception('EventDispatcher2: unhandled exception when processing timeout event')
            if self.endloop:
                return
            if cleanup:
                el.cleanup()

    def regSignal(self, signum, signal_cb, *callback_params, **cb_kw_args):
        sl = EventListener()
        if len([x for x in self.slisteners if x.signum == signum]) == 0:
            signal.signal(signum, self.signal)
        sl.signum = signum
        sl.callback_function = signal_cb
        sl.callback_params = callback_params
        sl.cb_kw_args = cb_kw_args
        self.slisteners.append(sl)
        return sl

    def unregSignal(self, sl):
        self.slisteners.remove(sl)
        if len([x for x in self.slisteners if x.signum == sl.signum]) == 0:
            signal.signal(sl.signum, signal.SIG_DFL)
        sl.cleanup()

    def dispatchSignals(self):
        while len(self.signals_pending) > 0:
            signum = self.signals_pending.pop(0)
            for sl in [x for x in self.slisteners if x.signum == signum]:
                if sl not in self.slisteners:
                    continue
                try:
                    sl.callback_function(*sl.callback_params, **sl.cb_kw_args)
                except Exception as ex:
                    if isinstance(ex, SystemExit):
                        raise
                    dump_exception('EventDispatcher2: unhandled exception when processing signal event')
                if self.endloop:
                    return

    def dispatchThreadCallback(self, thread_cb, callback_params):
        try:
            thread_cb(*callback_params)
        except Exception as ex:
            if isinstance(ex, SystemExit):
                raise
            dump_exception('EventDispatcher2: unhandled exception when processing from-thread-call')
        # print('dispatchThreadCallback dispatched', thread_cb, callback_params)

    def callFromThread(self, thread_cb, *callback_params):
        self.elp.call_from_thread(self.dispatchThreadCallback, thread_cb, callback_params)
        # print('EventDispatcher2.callFromThread completed', str(self), thread_cb, callback_params)

    def loop(self, timeout=None, freq=None):
        if freq != None and self.bands[0][0] != freq:
            for fb in self.bands:
                if fb[0] == freq:
                    self.bands.remove(fb)
                    break
            else:
                fb = (freq, self.elp.addband(freq))
            self.elp.useband(fb[1])
            self.bands.insert(0, fb)
        self.endloop = False
        self.last_ts = MonoTime()
        if timeout != None:
            etime = self.last_ts.getOffsetCopy(timeout)
        while True:
            # print("LOOOPING", self.__dict__, MonoTime())
            if len(self.signals_pending) > 0:
                self.dispatchSignals()
                if self.endloop:
                    return
            if self.endloop:
                return
            self.dispatchTimers()
            if self.endloop:
                return
            if self.twasted * 2 > len(self.tlisteners):
                # Clean-up removed timers when their share becomes more than 50%
                self.tlisteners = [x for x in self.tlisteners if x.callback_function != None]
                heapify(self.tlisteners)
                self.twasted = 0
            if (timeout != None and self.last_ts > etime) or self.endloop:
                self.endloop = False
                break
            self.elp.procrastinate()
            self.last_ts = MonoTime()

    def breakLoop(self):
        self.endloop = True

def do_smth():
    print("LOLOLOLOLOLOLO")


ED2 = EventDispatcher2()

if __name__ == "__main__":
    ED2.regTimer(do_smth, 3)
    ED2.loop()
