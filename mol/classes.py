# *-* coding: utf-8 *-*

from threading import Lock
from collections import namedtuple, deque
from itertools import islice
from PyQt4 import QtCore
from midiutils import *

MidiSource = namedtuple('MidiSource', 'client port')
PatternData = namedtuple('PatternData', 'time vel source')


class deque2(deque):
    def __new__(cls, *args):
        return deque.__new__(cls, *args)
    def __getslice__(self, start, end):
        return list(islice(self, start, end))

class MidiData(QtCore.QObject):
    __slots__ = 'event', 'time', 'vel', 'source'
    play = QtCore.pyqtSignal(object)
    def __init__(self, event, time=0, source=None):
        QtCore.QObject.__init__(self)
        self.event = event
        self.vel = event.data2
        self.time = time
        self.time_ms = time/(10.**6)
        self.source = source
        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.event_play)

    def event_play(self):
#        print 'playing note {}'.format(self.event.data1)
        self.play.emit(self.event)

    def set_timer(self, start):
        self.timer.setInterval(self.time-start)

    def timer_start(self):
        self.timer.start()

    def __iter__(self):
        for field in self.__slots__:
            yield getattr(self, field)

    def __repr__(self):
        return str(self.event.data1)


class MidiBuffer(QtCore.QObject):
    pattern_created = QtCore.pyqtSignal(object)
    def __init__(self, max_size=64, trigger_types=(NOTEON, ), time_threshold=100):
        QtCore.QObject.__init__(self)
        self.max_size = max_size
        self.main_data = deque2([], max_size)
        self.note_data = deque2([], max_size)
        self.rev_note_data = deque2([], max_size)
        self.time_data = deque2([], max_size)
        self.rev_time_data = deque2([], max_size)
        self.vel_data = deque2([], max_size)
        self.rev_vel_data = deque2([], max_size)
        self.source_data = []
        self.other_data = []
        self.main_types = trigger_types
        self.time_threshold = time_threshold
#        self.ignored_types = ignored_types
        self.lock = Lock()
        self.watch_id = None
        self.pattern = []
        self.pattern_data = []
        self.pattern_repeat = []
        self.pattern_repeat_data = []
        self.pattern_set = False
        self.repeats = 1
        self.max_repeats = 3

    def append(self, event, time, source=None):
        if self.pattern_set: return
        if event.type == NOTEON and event.velocity == 0:
            event_type = NOTEOFF
        else:
            event_type = event.type
        if event_type in self.main_types:
            self.lock.acquire()
            self.loop_check(event, time, source)
            self.lock.release()
        else:
            self.other_data.append(MidiData(event, time, source))

    def loop_check(self, event, time, source):
        note = event.data1
        vel = event.data2
        event_data = MidiData(event, time, source)
        self.main_data.append(event_data)
        self.note_data.append(note)
        self.rev_note_data.appendleft(note)
        self.time_data.append(time)
        self.rev_time_data.appendleft(time)
        self.vel_data.append(vel)
        self.rev_vel_data.appendleft(vel)
        self.source_data.append(source)
        print 'note_data: {}'.format([get_note_name(n) for n in self.note_data])
        if note not in self.note_data:
            return
        pattern_range = None
        for i in xrange(1, len(self.note_data)/2):
            prev_note_data = self.rev_note_data[:i]
            print 'searching pattern: {}'.format(list(reversed(prev_note_data)))
            for j in xrange(1, 3):
                pattern_range = (i*j, i*(j+1))
                new_note_data = self.rev_note_data[pattern_range[0]:pattern_range[1]]
                print 'searching with indexes [{}:{}]: {}'.format(i*j, i*(j+1), new_note_data)
                if prev_note_data == new_note_data:
                    print 'coincide, controllo i tempi'
                    if j > 1:
                        print [int(h) for h in self.rev_time_data]
                        last_prev_time = self.rev_time_data[0]
                        pattern_prev_time = self.rev_time_data[i]
                        orig_prev_time = self.rev_time_data[i*2]
                        for t in xrange(1, i):
                            last_next_time = self.rev_time_data[t]
                            delta1 = last_prev_time-last_next_time
                            pattern_next_time = self.rev_time_data[t+i]
                            delta2 = pattern_prev_time-pattern_next_time
                            if abs(delta2-delta1) < self.time_threshold:
                                last_prev_time = last_next_time
                            else:
                                print 'timing non coincide'
                                break
                            orig_next_time = self.rev_time_data[t+(i*2)]
                            delta3 = orig_prev_time-orig_next_time
                            if abs(delta3-delta2) < self.time_threshold:
                                pattern_prev_time = pattern_next_time
                                orig_prev_time = orig_next_time
                            else:
                                print 'timing non coincide'
                                break
                        else:
                            prev_note_data = new_note_data
                            continue
                        print 'non ok?'
                        break
                    prev_note_data = new_note_data
                else:
                    print 'non coincide'
                    break
            else:
                #pattern trovato!
                break
        else:
            print 'pattern non trovato'
            return
        print 'pattern trovato!!!'
        self.pattern_finalize(pattern_range[1]-pattern_range[0])


    def pattern_finalize(self, length):
        self.pattern_set = True
        self.pattern_data = self.main_data[-length:]
        time_base = self.main_data[-length-1].time
        self.length = self.pattern_data[-1].time-time_base
        time_start = self.pattern_data[0].time
        time_last = self.pattern_data[-1].time

        for data in self.pattern_data:
            data.set_timer(time_base)
        for data in self.other_data:
            if data.time >= time_base:
                data.set_timer(time_base)
                self.pattern_data.append(data)
        self.timer = QtCore.QTimer()
        self.timer.setInterval(max([e.timer.interval() for e in self.pattern_data])+1)
        self.timer.timeout.connect(self.start_event_timers)
        self.start()
        self.pattern_created.emit(self.pattern_data)


    def start_event_timers(self):
#        print 'setto data timers'
        for data in self.pattern_data:
            data.timer.start()

    def start(self):
        self.start_event_timers()
        self.timer.start()

    def stop(self):
        for data in self.pattern_data:
            data.timer.stop()







