# *-* coding: utf-8 *-*

from threading import Lock
from collections import namedtuple, deque
from itertools import islice
from PyQt4 import QtGui, QtCore
from midiutils import *

MidiSource = namedtuple('MidiSource', 'client port')
PatternData = namedtuple('PatternData', 'time vel source')
RemoteCtrlEvent = namedtuple('RemoteCtrlEvent', 'event_type param value channel')
#accept CtrlEvent with only event_type and param too
RemoteCtrlEvent.__new__.__defaults__ = (None, -1)

EventRole = QtCore.Qt.UserRole + 1
EventIdRole = EventRole + 1
IdRole = EventIdRole
DefaultRole = EventIdRole + 1
TriggerRole = DefaultRole + 1
RecordRole = TriggerRole + 1
IgnoreRole = RecordRole + 1

NameRole = QtCore.Qt.UserRole + 10
ClientRole = NameRole + 1
PortRole = ClientRole + 1

SysExRole = QtCore.Qt.UserRole + 20

event_model = []
event_model_dict = {}
for i, (s, e) in enumerate([('Ctrl', CTRL), ('Note On', NOTEON), ('Note Off', NOTEOFF), ('SysEx', SYSEX)]):
    item = QtGui.QStandardItem(s)
    item.setData(e, EventRole)
    item.setData(i, EventIdRole)
    event_model.append(item)
    event_model_dict[e] = item


class deque2(deque):
    def __new__(cls, *args):
        return deque.__new__(cls, *args)
    def __getslice__(self, start, end):
        return list(islice(self, start, end))

class ParamCombo(QtGui.QComboBox):
    def __init__(self, parent=None):
        QtGui.QComboBox.__init__(self, parent)
        self.setEditable(True)
        self.setInsertPolicy(QtGui.QComboBox.NoInsert)
        self.setMaximumWidth(100)
        self.p_model = QtGui.QStandardItemModel()
        self.name_model = QtGui.QStandardItemModel()
        self.setModel(self.p_model)

        metrics = QtGui.QFontMetrics(self.view().font())
        ctrl_width = []
        note_width = []
        for i in range(128):
            ctrl = Controllers[i]
            ctrl_str = '{} - {}'.format(i, ctrl)
            ctrl_item = QtGui.QStandardItem(ctrl_str)
            ctrl_item.setData(i, IdRole)
            ctrl_item.setData(ctrl, NameRole)
            ctrl_width.append(metrics.width(ctrl_str))
            ctrl_name_item = QtGui.QStandardItem(ctrl)
            ctrl_name_item.setData(i, IdRole)
            note = NoteNames[i].title()
            note_str = '{} - {}'.format(i, note)
            note_item = QtGui.QStandardItem(note_str)
            note_item.setData(i, IdRole)
            note_item.setData(note, NameRole)
            note_width.append(metrics.width(note_str))
            note_name_item = QtGui.QStandardItem(note)
            note_name_item.setData(i, IdRole)
            self.p_model.appendRow([ctrl_item, note_item])
            self.name_model.appendRow([ctrl_name_item, note_name_item])

        self.ctrl_width = max(ctrl_width)
        self.note_width = max(note_width)
        self.ref_size = self.width()

        self.activated.connect(lambda i: self.lineEdit().setCursorPosition(0))
        self.currentIndexChanged.connect(lambda i: self.lineEdit().setCursorPosition(0))

    def showEvent(self, event):
        QtGui.QComboBox.showEvent(self, event)
        completer_model = self.lineEdit().completer().model()
        new_model = QtGui.QStandardItemModel(self)
        for r in range(self.p_model.rowCount()):
            new_model.appendRow([completer_model.item(r, 0).clone(), completer_model.item(r, 1).clone()])
            new_model.appendRow([self.name_model.item(r, 0).clone(), self.name_model.item(r, 1).clone()])
        self.lineEdit().completer().setModel(new_model)
        self.lineEdit().completer().setCompletionMode(QtGui.QCompleter.PopupCompletion)
        self.lineEdit().completer().activated['QModelIndex'].connect(self.completer_activated)
        self.lineEdit().completer().highlighted['QModelIndex'].connect(self.completer_activated)
        self.setModelColumn(self.modelColumn())

    def completer_activated(self, index):
        self.setCurrentIndex(index.data(IdRole).toPyObject())

    def focusOutEvent(self, event):
        QtGui.QComboBox.focusOutEvent(self, event)
        text = str(self.lineEdit().text())
        found = self.p_model.findItems(text, QtCore.Qt.MatchFixedString, self.modelColumn())
        if found: return
        text = text.strip()
        if not text.isdigit():
            found = self.name_model.findItems(text, QtCore.Qt.MatchFixedString, self.modelColumn())
            if found:
                self.setCurrentIndex(found[0].data(IdRole).toPyObject())
            else:
                self.lineEdit().setText(self.p_model.item(self.currentIndex(), self.modelColumn()).text())
        elif not 0 <= int(text) <= 127:
            self.lineEdit().setText(self.p_model.item(self.currentIndex(), self.modelColumn()).text())
        else:
            self.setCurrentIndex(int(text))
        self.lineEdit().setCursorPosition(0)

    def setModelColumn(self, col):
        QtGui.QComboBox.setModelColumn(self, col if col <= 1 else 1)
        if not self.isVisible(): return
        if col == 0:
            self.ref_size = self.ctrl_width if self.ctrl_width >= self.width() else self.width()
        else:
            self.ref_size = self.note_width if self.note_width >= self.width() else self.width()
        self.view().setMinimumWidth(self.ref_size)
        self.view().setMaximumWidth(self.ref_size)
        self.lineEdit().completer().popup().setMinimumWidth(self.ref_size)

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
    def __init__(self, max_size=64, trigger_types=(NOTEON, ), time_threshold=100, ignore_doublenote=False):
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
        self.trigger_types = trigger_types
        self.time_threshold = time_threshold
        self.ignore_doublenote = ignore_doublenote
        self.lock = Lock()
        self.watch_id = None
        self.pattern = []
        self.noteoff = {}
        self.last_note = None
        self.pattern_data = []
        self.pattern_set = False
        self.repeats = 1
        self.max_repeats = 3

    def append(self, event, time, source=None):
        if self.pattern_set: return
        if event.type == NOTEON and event.velocity == 0:
            event_type = NOTEOFF
        else:
            event_type = event.type
        if event_type in self.trigger_types:
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
#        print 'note_data: {}'.format([get_note_name(n) for n in self.note_data])
        if note not in self.note_data:
            return
        if len(self.note_data) > 1 and self.ignore_doublenote and self.note_data[-2] == note:
            return
        pattern_range = None
        for i in xrange(1, len(self.note_data)/2):
            prev_note_data = self.rev_note_data[:i]
#            print 'searching pattern: {}'.format(list(reversed(prev_note_data)))
            for j in xrange(1, 3):
                pattern_range = (i*j, i*(j+1))
                new_note_data = self.rev_note_data[pattern_range[0]:pattern_range[1]]
#                print 'searching with indexes [{}:{}]: {}'.format(i*j, i*(j+1), new_note_data)
                if prev_note_data == new_note_data:
#                    print 'coincide, controllo i tempi'
                    if j > 1:
#                        print [int(h) for h in self.rev_time_data]
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
#                                print 'timing non coincide'
                                break
                            orig_next_time = self.rev_time_data[t+(i*2)]
                            delta3 = orig_prev_time-orig_next_time
                            if abs(delta3-delta2) < self.time_threshold:
                                pattern_prev_time = pattern_next_time
                                orig_prev_time = orig_next_time
                            else:
#                                print 'timing non coincide'
                                break
                        else:
                            prev_note_data = new_note_data
                            continue
                        break
                    prev_note_data = new_note_data
                else:
#                    print 'non coincide'
                    break
            else:
                #pattern trovato!
                break
        else:
#            print 'pattern non trovato'
            return
#        print 'pattern trovato!!!'
        pattern_length = pattern_range[1]-pattern_range[0]
        delta2 = self.rev_time_data[pattern_length-1]-self.rev_time_data[pattern_length]
        delta1 = self.rev_time_data[pattern_length*2-1]-self.rev_time_data[pattern_length*2]
        if abs(delta1-delta2) > self.time_threshold:
#            print 'pattern non ripetuti con lo stesso intervallo!'
            return
        self.pattern_finalize(pattern_length)


    def pattern_finalize(self, length):
        self.pattern_set = True
        self.pattern_data = self.main_data[-length:]
        time_base = self.main_data[-length-1].time
        self.length = self.pattern_data[-1].time-time_base
#        time_start = self.pattern_data[0].time
#        time_last = self.pattern_data[-1].time

        for data in self.pattern_data:
            data.set_timer(time_base)
        for data in self.other_data:
            if data.time >= time_base:
                data.set_timer(time_base)
                self.pattern_data.append(data)
        self.timer = QtCore.QTimer()
        self.timer.setInterval(max([e.timer.interval() for e in self.pattern_data])+1)
        self.timer.timeout.connect(self.start_event_timers)
        for data in self.pattern_data:
            if data.event.type == NOTEON:
                if data.event.velocity != 0:
                    data.play.connect(self.last_noteon_update)
                else:
                    data.play.connect(self.last_noteoff_update)
            elif data.event.type == NOTEOFF:
                data.play.connect(self.last_noteoff_update)
        #TODO verifica l'ordine
        self.pattern_created.emit(self.pattern_data)
        self.start()
        self.create_stop_notes()


    def start_event_timers(self):
        for data in self.pattern_data:
            data.timer.start()

    def start(self):
        self.start_event_timers()
        self.timer.start()

    def stop(self):
        for data in self.pattern_data:
            data.timer.stop()
            data.play.disconnect()
        return self.stop_notes()

    def create_stop_notes(self):
        first_note = self.pattern_data[0].time
        self.pattern_data_ordered = sorted(self.pattern_data, key=lambda m: m.time if m.time >= first_note else m.time+first_note)
        pattern_rev = reversed(self.pattern_data_ordered)
        for i, data in enumerate(self.pattern_data_ordered):
            event = data.event
            if event.type == NOTEON and not event.velocity == 0:
                for d in self.pattern_data_ordered[i+1:]:
                    if d.event.type != NOTEOFF and not (d.event.type == NOTEON and d.event.velocity == 0) and not d.event.data1 == event.data1 and not d.event.source == event.source:
                        continue
                    self.noteoff[(tuple(data.event.source), data.event.channel, data.event.data1)] = False
                continue
                for d in pattern_rev[i+1:]:
                    if d.event.type != NOTEOFF and not (d.event.type == NOTEON and d.event.velocity == 0) and not d.event.data1 == event.data1 and not d.event.source == event.source:
                        continue
                    self.noteoff[(tuple(data.event.source), data.event.channel, data.event.data1)] = False

    def last_noteon_update(self, event):
        if (tuple(event.source), event.channel, event.data1) in self.noteoff:
            self.noteoff[(tuple(event.source), event.channel, event.data1)] = True
            self.last_note = event.data1

    def last_noteoff_update(self, event):
        if (tuple(event.source), event.channel, event.data1) in self.noteoff:
            self.noteoff[(tuple(event.source), event.channel, event.data1)] = False

    def stop_notes(self):
        note_list = []
        sources = set()
        for (source, channel, data1), active in self.noteoff.items():
            sources.add(source)
            if active:
                note_list.append(MidiEvent(NOTEOFF, source=source, channel=channel, data1=data1))
        if note_list:
            return note_list, sources
        else:
            return [], sources

    def __len__(self):
        return len(self.main_data)






