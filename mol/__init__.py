#!/usr/bin/env python2.7
# *-* coding: utf-8 *-*

import sys, re
from os import path
from pyalsa import alsaseq
from PyQt4 import QtCore, QtGui, uic
import icons
from classes import *
from midiutils import *

version = '0.5'
clientname = 'MOL'

CONNECT_SW, CONNECT_HW, CONNECT_ALL = range(1, 4)

defaults = {
            'startup_enable': False, 
            'last_event_limit': 5, 
            'ignore_doublenote': True, 
            'stop_events': [('CTRL', 123, 0), ('CTRL', 64, 0)], 
            'stop_notes': True, 
            'toggle_mode': False, 
            'ctrl_enable_event': (0, 32, 0), 
            'ctrl_disable_event': (0, 32, 1), 
            'ctrl_stop_event': (0, 32, 127), 
            'max_size': 16, 
            'time_threshold': 100, 
            'auto_connect': CONNECT_HW, 
            }

trigger_defaults = (NOTEON, )
record_defaults = (
                   NOTEOFF, CTRL, PITCHBEND, AFTERTOUCH, POLY_AFTERTOUCH, PROGRAM, SYSEX, 
                   )
ignore_defaults = (
                   SYSCM_QFRAME, SYSCM_SONGPOS, SYSCM_SONGSEL, SYSCM_TUNEREQ, 
                   SYSRT_CLOCK, SYSRT_START, SYSRT_CONTINUE, SYSRT_STOP, SYSRT_SENSING,
                   SYSRT_RESET, 
                   )

trigger_allowed = (
                   NOTEON, NOTEOFF, CTRL, 
                   )

record_allowed = trigger_allowed + (
                  PITCHBEND, AFTERTOUCH, POLY_AFTERTOUCH, PROGRAM, SYSEX
                  )

_id_to_event = {
               0: CTRL, 
               1: NOTEON, 
               2: NOTEOFF, 
               }

_event_to_id = {
                CTRL: 0, 
                NOTEON: 1, 
                NOTEOFF: 2, 
                }

DISABLED, ENABLED, ACTIVE, PLAY = range(4)
IGNORE, RECORD, TRIGGER = range(-1, 2)


def _load_ui(widget, ui_path):
    return uic.loadUi(path.join(path.dirname(path.abspath(__file__)), ui_path), widget)

def setBold(item, bold=True):
    font = item.font()
    font.setBold(bold)
    item.setFont(font)

def setItalic(item, bold=True):
    font = item.font()
    font.setItalic(bold)
    item.setFont(font)


class AlsaMidi(QtCore.QObject):
    client_start = QtCore.pyqtSignal(object)
    client_exit = QtCore.pyqtSignal(object)
    port_start = QtCore.pyqtSignal(object)
    port_exit = QtCore.pyqtSignal(object)
    conn_register = QtCore.pyqtSignal(object, bool)
    graph_changed = QtCore.pyqtSignal()
    stopped = QtCore.pyqtSignal()
    midi_signal = QtCore.pyqtSignal(object)

    def __init__(self, main, single_input=False, output=False):
        QtCore.QObject.__init__(self)
        self.main = main
        self.active = False
#        self.single_input = single_input
        self.seq = alsaseq.Sequencer(clientname=clientname)
        self.keep_going = True

        if single_input:
            input_id = self.seq.create_simple_port(name = 'MOL input', 
                                                     type = alsaseq.SEQ_PORT_TYPE_MIDI_GENERIC|alsaseq.SEQ_PORT_TYPE_APPLICATION, 
                                                     caps = alsaseq.SEQ_PORT_CAP_WRITE|alsaseq.SEQ_PORT_CAP_SUBS_WRITE|
                                                     alsaseq.SEQ_PORT_CAP_SYNC_WRITE)
        else:
            input_id = self.seq.create_simple_port(name = 'MOL monitor', 
                                                     type = alsaseq.SEQ_PORT_TYPE_MIDI_GENERIC|alsaseq.SEQ_PORT_TYPE_APPLICATION, 
                                                     caps = alsaseq.SEQ_PORT_CAP_WRITE|alsaseq.SEQ_PORT_CAP_SUBS_WRITE|
                                                     alsaseq.SEQ_PORT_CAP_NO_EXPORT)
            control_id = self.seq.create_simple_port(name = 'MOL control', 
                                                     type = alsaseq.SEQ_PORT_TYPE_MIDI_GENERIC|alsaseq.SEQ_PORT_TYPE_APPLICATION, 
                                                     caps = alsaseq.SEQ_PORT_CAP_WRITE|alsaseq.SEQ_PORT_CAP_SUBS_WRITE|
                                                     alsaseq.SEQ_PORT_CAP_SYNC_WRITE)
#        output_id = self.seq.create_simple_port(name = 'MOL player', 
#                                                     type = alsaseq.SEQ_PORT_TYPE_MIDI_GENERIC|alsaseq.SEQ_PORT_TYPE_APPLICATION, 
#                                                     caps = alsaseq.SEQ_PORT_CAP_READ|alsaseq.SEQ_PORT_CAP_SUBS_READ|
#                                                     alsaseq.SEQ_PORT_CAP_SYNC_READ)
        feedback_id = self.seq.create_simple_port(name = 'MOL feedback', 
                                                     type = alsaseq.SEQ_PORT_TYPE_MIDI_GENERIC|alsaseq.SEQ_PORT_TYPE_APPLICATION, 
                                                     caps = alsaseq.SEQ_PORT_CAP_READ|alsaseq.SEQ_PORT_CAP_SUBS_READ|
                                                     alsaseq.SEQ_PORT_CAP_SYNC_READ)

        self.seq.connect_ports((alsaseq.SEQ_CLIENT_SYSTEM, alsaseq.SEQ_PORT_SYSTEM_ANNOUNCE), (self.seq.client_id, input_id))

#        self.graph = Graph(self.seq)
        self.graph = self.main.graph = Graph(self.seq)
        self.graph.client_start.connect(self.client_start)
        self.graph.client_exit.connect(self.client_exit)
        self.graph.port_start.connect(self.port_start)
        self.graph.port_exit.connect(self.port_exit)
        self.graph.conn_register.connect(self.conn_register)
        self.id = self.seq.get_client_info()['id']
        self.input = self.graph.port_id_dict[self.id][input_id]
        self.control = self.graph.port_id_dict[self.id][control_id] if not single_input else None
        self.feedback = self.graph.port_id_dict[self.id][feedback_id]
#        self.output = self.graph.port_id_dict[self.id][output_id]

    def run(self):
        self.active = True
        while self.keep_going:
            try:
                event_list = self.seq.receive_events(timeout=1024, maxevents=1)
                for event in event_list:
                    data = event.get_data()
                    if event.type == alsaseq.SEQ_EVENT_CLIENT_START:
                        self.graph.client_created(data)
                    elif event.type == alsaseq.SEQ_EVENT_CLIENT_EXIT:
                        self.graph.client_destroyed(data)
                    elif event.type == alsaseq.SEQ_EVENT_PORT_START:
                        self.graph.port_created(data)
                    elif event.type == alsaseq.SEQ_EVENT_PORT_EXIT:
                        self.graph.port_destroyed(data)
                    elif event.type == alsaseq.SEQ_EVENT_PORT_SUBSCRIBED:
                        self.graph.conn_created(data)
                    elif event.type == alsaseq.SEQ_EVENT_PORT_UNSUBSCRIBED:
                        self.graph.conn_destroyed(data)
                    elif event.type in [alsaseq.SEQ_EVENT_NOTEON, alsaseq.SEQ_EVENT_NOTEOFF, 
                                        alsaseq.SEQ_EVENT_CONTROLLER, alsaseq.SEQ_EVENT_PITCHBEND, 
                                        alsaseq.SEQ_EVENT_CHANPRESS, alsaseq.SEQ_EVENT_KEYPRESS, 
                                        alsaseq.SEQ_EVENT_PGMCHANGE, alsaseq.SEQ_EVENT_SYSEX, 
                                        ]:
                        try:
                            newev = MidiEvent.from_alsa(event)
                            self.midi_signal.emit(newev)
#                            print newev
                        except Exception as e:
                            print 'event {} unrecognized'.format(event)
                            print e
                    elif event.type in [alsaseq.SEQ_EVENT_CLOCK, alsaseq.SEQ_EVENT_SENSING]:
                        pass
            except:
                pass
        print 'stopped'
        self.stopped.emit()

class AboutDialog(QtGui.QDialog):
    def __init__(self, main):
        QtGui.QDialog.__init__(self, parent=None)
        _load_ui(self, 'about.ui')
        self.setFixedSize(self.width(), self.height())
        self.version_lbl.setText('Version: {}'.format(version))

class PortFilterDialog(QtGui.QDialog):
    def __init__(self, main):
        QtGui.QDialog.__init__(self, parent=None)
        _load_ui(self, 'auto_connect_add.ui')
        self.main = main
        self.graph = main.main.graph
        self.graph_model = QtGui.QStandardItemModel()
        self.graph_model.setHorizontalHeaderLabels(['Name', 'Address'])
        self.input_table.setModel(self.graph_model)
        self.input_table.doubleClicked.connect(self.activate)
        self.input_table.setRowHidden(True, 2)
        self.buttonBox.button(QtGui.QDialogButtonBox.Ok).setEnabled(False)
        self.input_edit.textChanged.connect(self.text_update)
        self.build_graph()

    def activate(self, index):
        item = self.graph_model.itemFromIndex(index)
        self.input_edit.setText(item.data(NameRole).toPyObject())

    def text_update(self, text):
        self.buttonBox.button(QtGui.QDialogButtonBox.Ok).setEnabled(True if text else False)
        text = str(text).replace('(', '\(').replace(')', '\)').replace('[', '\[').replace(']', '\]')
        items = self.graph_model.findItems(text, QtCore.Qt.MatchRegExp, 1)+self.graph_model.findItems(text, QtCore.Qt.MatchRegExp, 2)
        rows = [self.graph_model.indexFromItem(item).row() for item in items]
        for row in range(self.graph_model.rowCount()):
            item = self.graph_model.item(row)
            setItalic(item, True if row in rows and item.data(PortRole).toBool() else False)

    def build_graph(self):
        for c, ports in self.graph.port_id_dict.items():
            rows = []
            for p, port in ports.items():
                if port.is_output and not port.hidden:
                    port_item = QtGui.QStandardItem(port.name)
                    port_name = '{}:{}'.format(port.client.name, port.name)
                    port_item.setData(port_name, NameRole)
                    port_item.setData(True, PortRole)
                    full_port_item = QtGui.QStandardItem(port_name)
                    setBold(port_item)
                    port_id = QtGui.QStandardItem('{}:{}'.format(port.client.id, port.id))
                    port_id.setData('{}:{}'.format(port.client.id, port.id), NameRole)
                    setBold(port_id)
                    rows.append([port_item, port_id, full_port_item])
            if rows:
               client_item = QtGui.QStandardItem(' {}'.format(port.client.name))
               client_item.setData('{}:.*'.format(port.client.name), NameRole)
               client_item.setData(QtGui.QBrush(QtCore.Qt.gray), QtCore.Qt.ForegroundRole)
               client_id = QtGui.QStandardItem(str(port.client.id))
               client_id.setData('{}:.*'.format(port.client.id), NameRole)
               client_id.setData(QtGui.QBrush(QtCore.Qt.gray), QtCore.Qt.ForegroundRole)
               self.graph_model.appendRow([client_item, client_id])
               for r in rows:
                   self.graph_model.appendRow(r)
        self.input_table.resizeColumnsToContents()
        self.input_table.resizeRowsToContents()

    def exec_(self):
        res = QtGui.QDialog.exec_(self)
        if not res or not self.input_edit.text():
            return None
        return self.input_edit.text()

class SysExEditor(QtGui.QLineEdit):
    def __init__(self, parent, sysex=None):
        QtGui.QLineEdit.__init__(self, parent)
#        self.valid_fg = self.palette()
#        self.invalid_fg = self.palette().setColor(QtGui.QPalette.Foreground, QtCore.Qt.red)
        self.valid = False
        self.textChanged.connect(self.check)
        self.valid = sysex
        if isinstance(sysex, str):
            try:
                self.sysex = map(int, sysex)
            except:
                self.sysex = []
        else:
            self.sysex = sysex
        self.setText(' '.join(['{:02X}'.format(v) for v in self.sysex]))

    def set_fg(self, valid=True):
        if valid:
            self.setStyleSheet('')
        else:
            self.setStyleSheet('color: red;')

    def check(self, text):
        text = str(text)
        text.replace(',', ' ')
        text = re.sub(' +', ' ', text)
        if set('abcdef')&set(text.lower()):
            try:
                sysex = map(lambda v: int(v, 16), text.split())
            except:
                self.set_fg(False)
                return
        else:
            try:
                sysex = map(int, text.split())
            except:
                self.set_fg(False)
                return
        if not sysex or sysex[0] != 240 or sysex[-1] != 247 or any([v for v in sysex[1:-1] if v>127]):
            self.set_fg(False)
            return
        self.valid = ' '.join(['{:02X}'.format(v) for v in sysex])
        self.sysex = sysex
        self.set_fg()


class SettingsDialog(QtGui.QDialog):
    class EventTypeDelegate(QtGui.QStyledItemDelegate):
        def __init__(self, parent=None):
            QtGui.QStyledItemDelegate.__init__(self, parent)
            self.closeEditor.connect(self.set_data)

        def createEditor(self, parent, option, index):
            self.table = parent.parent()
            self.index = index
            combo = QtGui.QComboBox(parent)
            model = QtGui.QStandardItemModel()
            [model.appendRow(item.clone()) for item in event_model]
            combo.setModel(model)
            combo.setCurrentIndex(index.data(EventIdRole).toPyObject())
            combo.activated.connect(lambda i: parent.setFocus())
            return combo

        def set_data(self, widget, hint):
            model = self.index.model()
            ev_type = widget.model().item(widget.currentIndex()).data(EventRole)
            if self.index.data(EventRole) == ev_type:
                return
            item = model.itemFromIndex(self.index)
            item.setData(ev_type, EventRole)
            item.setData(widget.model().item(widget.currentIndex()).data(EventIdRole), EventIdRole)
            ev_type = ev_type.toPyObject()
            id = model.index(self.index.row(), 2).data(IdRole).toPyObject()
            param_item = model.itemFromIndex(model.index(self.index.row(), 2))
            if ev_type == SYSEX:
                sysex = param_item.data(SysExRole).toPyObject()
                if sysex:
                    param_item.setText(' '.join(['{:02X}'.format(v) for v in sysex]))
                else:
                    param_item.setText('F0 00 00 00 00 F7')
                    param_item.setData([240, 0, 0, 0, 0, 247], SysExRole)
                chan_item = model.itemFromIndex(model.index(self.index.row(), 1))
                chan_item.setText('')
                chan_item.setEnabled(False)
                value_item = model.itemFromIndex(model.index(self.index.row(), 3))
                value_item.setText('')
                value_item.setEnabled(False)
                return
            if ev_type == CTRL:
                param_item.setText('{} - {}'.format(id, Controllers[id]))
            else:
                param_item.setText('{} - {}'.format(id, NoteNames[id].title()))
            chan_item = model.itemFromIndex(model.index(self.index.row(), 1))
            chan_item.setEnabled(True)
            if not chan_item.text():
                channel = chan_item.data(IdRole).toPyObject()
                chan_item.setText(str(channel+1) if channel >= 0 else 'All')
            value_item = model.itemFromIndex(model.index(self.index.row(), 3))
            value_item.setEnabled(True)
            if not value_item.text():
                value_item.setText(str(value_item.data(IdRole).toPyObject()))


    class ValueDelegate(QtGui.QStyledItemDelegate):
        def __init__(self, parent=None, all_channels=False):
            QtGui.QStyledItemDelegate.__init__(self, parent)
            self.all_channels = all_channels
            self.closeEditor.connect(self.set_data)

        def createEditor(self, parent, option, index):
            self.index = index
            if index.column() == 2:
                model = index.model()
                ev_type = model.itemFromIndex(model.index(self.index.row(), 0)).data(EventRole).toPyObject()
                if ev_type == SYSEX:
                    lineedit = SysExEditor(parent, index.data(SysExRole).toPyObject())
#                    lineedit.setText(index.data(SysExRole).toPyObject())
                    return lineedit
                combo = QtGui.QComboBox(parent)
                if ev_type == CTRL:
                    combo.addItems(['{} - {}'.format(id, Controllers[id]) for id in sorted(Controllers.keys())])
                elif ev_type in [NOTEON, NOTEOFF]:
                    combo.addItems(['{} - {}'.format(id, NoteNames[id].title()) for id in sorted(NoteNames.keys())])
                combo.setCurrentIndex(index.data(EventIdRole).toPyObject())
                combo.activated.connect(lambda i: parent.setFocus())
                return combo
            spin = QtGui.QSpinBox(parent)
            spin.wheelEvent = lambda event: spin.stepBy(-spin.singleStep() if event.delta() > 0 else spin.singleStep())
            if index.column() == 1:
                if not self.all_channels:
                    spin.setMinimum(1)
                else:
                    spin.setMinimum(0)
                    spin.setSpecialValueText('All')
                spin.setMaximum(16)
                spin.setValue(index.data(IdRole).toPyObject()+1)
            else:
                spin.setMinimum(0)
                spin.setMaximum(127)
            return spin

        def set_data(self, widget, hint):
            if isinstance(widget, QtGui.QComboBox):
                self.index.model().itemFromIndex(self.index).setData(widget.currentIndex(), IdRole)
            elif isinstance(widget, QtGui.QSpinBox):
                if self.index.column() == 1:
                    self.index.model().itemFromIndex(self.index).setData(widget.value()-1, IdRole)
                    if widget.value() == 0:
                        self.index.model().itemFromIndex(self.index).setText('All')
                else:
                    self.index.model().itemFromIndex(self.index).setData(widget.value(), IdRole)
            else:
                item = self.index.model().itemFromIndex(self.index)
                item.setText(widget.valid)
                item.setData(widget.sysex, SysExRole)


    def __init__(self, main):
        QtGui.QDialog.__init__(self, parent=None)
        _load_ui(self, 'settings.ui')
        self.main = main
        self.settings = main.settings
        self.startup_chk.setChecked(self.settings.value('startup_enable', defaults['startup_enable']).toBool())
        self.last_event_limit_spin.setValue(self.main.last_event_limit)
        self.max_size_spin.setValue(self.main.max_size)
        self.ignore_doublenote_chk.setChecked(self.main.ignore_doublenote)

        self.auto_connect = self.main.auto_connect
        auto_connect_btns = [self.auto_connect_custom_radio, self.auto_connect_sw_radio, self.auto_connect_hw_radio, self.auto_connect_all_radio]
        for i, radio in enumerate(auto_connect_btns):
            self.auto_connect_group.setId(radio, i)
            radio.toggled.connect(self.auto_connect_enable)
        self.auto_connect_model = QtGui.QStandardItemModel()
        self.auto_connect_list.setModel(self.auto_connect_model)
        if isinstance(self.auto_connect, int):
            self.auto_connect_group.button(self.auto_connect).setChecked(True)
        else:
            self.auto_connect_group.button(0).setChecked(True)
            for input in self.auto_connect:
                item = QtGui.QStandardItem(input)
                self.auto_connect_model.appendRow(item)
        self.auto_connect_add_btn.clicked.connect(self.auto_connect_add)
        self.auto_connect_del_btn.clicked.connect(self.auto_connect_del)

        self.blacklist = self.main.blacklist
        self.blacklist_model = QtGui.QStandardItemModel()
        self.blacklist_list.setModel(self.blacklist_model)
        for input in self.blacklist:
            item = QtGui.QStandardItem(input)
            self.blacklist_model.appendRow(item)
        self.blacklist_add_btn.clicked.connect(self.blacklist_add)
        self.blacklist_del_btn.clicked.connect(self.blacklist_del)

        self.time_threshold_spin.setValue(self.main.time_threshold)
        self.event_filter = self.main.event_filter
        self.create_event_types()
        self.trigger_add_btn.clicked.connect(self.add_trigger)
        self.trigger_del_btn.clicked.connect(self.del_trigger)
        self.record_add_btn.clicked.connect(self.add_record)
        self.record_del_btn.clicked.connect(self.del_record)

        self.stop_notes_chk.setChecked(self.main.stop_notes)

        self.ctrl_auto_connect_chk.toggled.connect(
                           lambda state: self.ctrl_auto_connect_edit.setEnabled(state if self.ctrl_auto_connect_chk.isEnabled() else False)
                           )
        if self.main.ctrl_auto_connect is not None:
            self.ctrl_auto_connect_edit.setText(self.main.ctrl_auto_connect)
            self.ctrl_auto_connect_chk.setChecked(True)
        self.toggle_mode_chk.setChecked(self.main.toggle_mode)
        self.enable_combo.setCurrentIndex(self.main.ctrl_enable_event.event_type)
        self.enable_param_spin.setValue(self.main.ctrl_enable_event.param)
        self.enable_value_spin.setValue(self.main.ctrl_enable_event.value)
        self.enable_chan_spin.setValue(self.main.ctrl_enable_event.channel+1)
        self.disable_combo.setCurrentIndex(self.main.ctrl_enable_event.event_type)
        self.disable_param_spin.setValue(self.main.ctrl_disable_event.param)
        self.disable_value_spin.setValue(self.main.ctrl_disable_event.value)
        self.disable_chan_spin.setValue(self.main.ctrl_disable_event.channel+1)
        self.stop_combo.setCurrentIndex(self.main.ctrl_stop_event.event_type)
        self.stop_param_spin.setValue(self.main.ctrl_stop_event.param)
        self.stop_value_spin.setValue(self.main.ctrl_stop_event.value)
        self.stop_chan_spin.setValue(self.main.ctrl_stop_event.channel+1)
        self.toggle_mode_chk.toggled.connect(lambda state: [
                                                       self.disable_combo.setEnabled(not state), 
                                                       self.disable_param_spin.setEnabled(not state), 
                                                       self.disable_value_spin.setEnabled(not state), 
                                                       self.disable_chan_spin.setEnabled(not state), 
                                                       self.toggle_pairing(force=state), 
                                                       ])
        self.enable_combo.currentIndexChanged.connect(self.toggle_pairing)
        self.enable_param_spin.valueChanged.connect(self.toggle_pairing)
        self.enable_value_spin.valueChanged.connect(self.toggle_pairing)
        self.enable_chan_spin.valueChanged.connect(self.toggle_pairing)
        self.toggle_mode_chk.toggled.emit(self.toggle_mode_chk.isChecked())

        self.stop_events_model = QtGui.QStandardItemModel(self)
        self.stop_events_model.setHorizontalHeaderLabels(['Event type', 'Channel', 'Parameter', 'Value'])
        self.stop_events_table.setModel(self.stop_events_model)
        self.stop_events_table.resizeColumnsToContents()
        self.stop_events_table.horizontalHeader().setResizeMode(0, QtGui.QHeaderView.Stretch)
        self.stop_events_table.resizeColumnToContents(1)
        self.stop_events_table.horizontalHeader().setResizeMode(2, QtGui.QHeaderView.Stretch)
        self.stop_events_table.verticalHeader().setResizeMode(QtGui.QHeaderView.ResizeToContents)
        self.stop_events_table.setItemDelegateForColumn(0, self.EventTypeDelegate(self))
        self.stop_events_table.setItemDelegateForColumn(1, self.ValueDelegate(self, True))
        self.stop_events_table.setItemDelegateForColumn(2, self.ValueDelegate(self))
        self.stop_events_table.setItemDelegateForColumn(3, self.ValueDelegate(self))

        self.stop_events_up_btn.clicked.connect(lambda state, table=self.stop_events_table: self.fb_up(table))
        self.stop_events_down_btn.clicked.connect(lambda state, table=self.stop_events_table: self.fb_down(table))
        self.stop_events_add_btn.clicked.connect(lambda state, table=self.stop_events_table: self.fb_add(table))
        self.stop_events_del_btn.clicked.connect(lambda state, table=self.stop_events_table: self.fb_del(table))
        self.create_stop_events(self.main.stop_events_raw)


        self.fb_auto_connect_chk.toggled.connect(lambda state: self.fb_auto_connect_edit.setEnabled(state))
        if self.main.fb_auto_connect is not None:
            self.fb_auto_connect_edit.setText(self.main.fb_auto_connect)
            self.fb_auto_connect_chk.setChecked(True)
        for action in ['enable', 'disable', 'stop', 'play']:
            for widget in ['up_btn', 'down_btn', 'table', 'add_btn', 'del_btn']:
                globals()[widget] = getattr(self, 'fb_{}_{}'.format(action, widget))
            model = QtGui.QStandardItemModel(self)
            model.setHorizontalHeaderLabels(['Event type', 'Channel', 'Parameter', 'Value'])
            action_list = getattr(self.main, 'fb_{}_events'.format(action))
            for ev_type, chan, data1, data2 in action_list:
                ev_type = eval(ev_type)
                ev_item = event_model_dict[ev_type].clone()
                if ev_type == SYSEX:
                    chan_item = QtGui.QStandardItem()
                    chan_item.setData(0, IdRole)
                    chan_item.setEnabled(False)
                    data1_item = QtGui.QStandardItem(' '.join(['{:02X}'.format(v) for v in data1]))
                    data1_item.setData(0, IdRole)
                    data1_item.setData(data1, SysExRole)
                    data2_item = QtGui.QStandardItem()
                    data2_item.setData(0, IdRole)
                    data2_item.setEnabled(False)
                else:
                    chan_item = QtGui.QStandardItem('{}'.format(chan+1))
                    chan_item.setData(chan, IdRole)
                    data1_item = QtGui.QStandardItem('{} - {}'.format(data1, Controllers[data1] if ev_type==CTRL else NoteNames[data1].title()))
                    data1_item.setData(data1, IdRole)
                    data2_item = QtGui.QStandardItem(str(data2))
                    data2_item.setData(data2, IdRole)
                model.appendRow([ev_item, chan_item, data1_item, data2_item])
            setattr(self, 'fb_{}_model'.format(action), model)
            table.setModel(model)
            table.resizeColumnsToContents()
            table.horizontalHeader().setResizeMode(0, QtGui.QHeaderView.Stretch)
            table.resizeColumnToContents(1)
            table.horizontalHeader().setResizeMode(2, QtGui.QHeaderView.Stretch)
            table.verticalHeader().setResizeMode(QtGui.QHeaderView.ResizeToContents)
            table.setItemDelegateForColumn(0, self.EventTypeDelegate(self))
            table.setItemDelegateForColumn(1, self.ValueDelegate(self))
            table.setItemDelegateForColumn(2, self.ValueDelegate(self))
            table.setItemDelegateForColumn(3, self.ValueDelegate(self))

            up_btn.clicked.connect(lambda state, table=table: self.fb_up(table))
            down_btn.clicked.connect(lambda state, table=table: self.fb_down(table))
            add_btn.clicked.connect(lambda state, table=table: self.fb_add(table))
            del_btn.clicked.connect(lambda state, table=table: self.fb_del(table))

        self.buttonBox.button(QtGui.QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore)
        self.buttonBox.button(QtGui.QDialogButtonBox.Ok).clicked.disconnect()
        self.buttonBox.button(QtGui.QDialogButtonBox.Ok).clicked.connect(self.value_check)

    def value_check(self):
        def append_tuple(event):
            if event.channel != 0:
                ctrl_list.append(tuple(event))
            else:
                for c in range(16):
                    ctrl_list.append((event.event_type, event.param, event.value, c))
        ctrl_list = []
        ctrl_enable_event = RemoteCtrlEvent(self.enable_combo.currentIndex(), self.enable_param_spin.value(), self.enable_value_spin.value(), self.enable_chan_spin.value())
        ctrl_disable_event = RemoteCtrlEvent(self.disable_combo.currentIndex(), self.disable_param_spin.value(), self.disable_value_spin.value(), self.disable_chan_spin.value())
        ctrl_stop_event = RemoteCtrlEvent(self.stop_combo.currentIndex(), self.stop_param_spin.value(), self.stop_value_spin.value(), self.stop_chan_spin.value())
        append_tuple(ctrl_enable_event)
        append_tuple(ctrl_stop_event)
        if not self.toggle_mode_chk.isChecked(): append_tuple(ctrl_disable_event)

        if len(ctrl_list) != len(set(ctrl_list)):
            QtGui.QMessageBox.critical(self, 'Control events conflict', 
                                       'Remote control events are conflicting, check for similar events or "Any" channel values', 
                                       )
            return
        self.accept()

    def restore(self):
        res = QtGui.QMessageBox.question(self, 'Restore to defaults', 
                                         'Do you want to restore original settings?', 
                                         QtGui.QMessageBox.Yes|QtGui.QMessageBox.Cancel
                                         )
        if not res == QtGui.QMessageBox.Yes: return
        self.startup_chk.setChecked(defaults['startup_enable'])
        self.last_event_limit_spin.setValue(defaults['last_event_limit'])
        self.max_size_spin.setValue(defaults['max_size'])
        self.ignore_doublenote_chk.setChecked(defaults['ignore_doublenote'])
        self.auto_connect_group.button(defaults['auto_connect']).setChecked(True)
        self.clear_model(self.auto_connect_model)
        self.clear_model(self.blacklist_model)
#        for i in range(self.auto_connect_model.rowCount()):
#            self.auto_connect_model.takeRow(0)
#        for i in range(self.blacklist_model.rowCount()):
#            self.blacklist_model.takeRow(0)

        self.time_threshold_spin.setValue(defaults['time_threshold'])
        event_dict = {}
        for model in [self.trigger_model, self.record_model, self.ignore_model]:
            for row in range(model.rowCount()):
                item = model.takeRow(0)[0]
                event_dict[item.data(EventRole).toPyObject()] = item
        targets = [(trigger_defaults, self.trigger_model), (record_defaults, self.record_model)]
        for ev_types, model in targets:
            for ev_type in ev_types:
                model.appendRow(event_dict[ev_type])

        self.stop_notes_chk.setChecked(defaults['stop_notes'])
        stop_events = []
        self.clear_model(self.stop_events_model)
        for event in defaults['stop_events']:
            if len(event) == 2:
                stop_events.append(event+(None, None))
            elif len(event) == 3:
                stop_events.append(event+(-1, ))
            else:
                stop_events.append(event)
        self.create_stop_events(stop_events)

        self.ctrl_auto_connect_edit.setText('')
        self.ctrl_auto_connect_chk.setChecked(False)
        self.toggle_mode_chk.setChecked(defaults['toggle_mode'])
        conv_dict = {
                     'ctrl_enable_event': (self.enable_combo, self.enable_param_spin, self.enable_value_spin), 
                     'ctrl_disable_event': (self.disable_combo, self.disable_param_spin, self.disable_value_spin), 
                     'ctrl_stop_event': (self.stop_combo, self.stop_param_spin, self.stop_value_spin), 
                     }
        for d, (combo, param, value) in conv_dict.items():
            t, p, v = defaults[d]
            combo.setCurrentIndex(t)
            param.setValue(p)
            value.setValue(v)

        self.fb_auto_connect_chk.setChecked(False)
        self.fb_auto_connect_edit.setText('')
        for action in ['enable', 'disable', 'stop', 'play']:
            self.clear_model(getattr(self, 'fb_{}_model'.format(action)))


    def clear_model(self, model):
        for i in range(model.rowCount()):
            model.takeRow(0)


    def create_event_types(self):
        self.trigger_model = QtGui.QStandardItemModel()
        self.record_model = QtGui.QStandardItemModel()
        self.ignore_model = QtGui.QStandardItemModel()
        self.trigger_list.setModel(self.trigger_model)
        self.record_list.setModel(self.record_model)
        self.ignore_list.setModel(self.ignore_model)
        all_types = list(trigger_defaults)+list(record_defaults)
        view_dict = {TRIGGER: self.trigger_model, RECORD: self.record_model, IGNORE: self.ignore_model}
#        defaults = {ev_type:dest for dest, t in dict({trigger_defaults: self.trigger_model, record_defaults: self.record_model, ignore_defaults: self.ignore_model}.items()) for ev_type in t}
        for ev_type in all_types:
            item = QtGui.QStandardItem(str(ev_type))
            item.setData(ev_type, EventRole)
#            item.setData(defaults[ev_type], DefaultRole)
            item.setData(True if ev_type in trigger_allowed else False, TriggerRole)
            item.setData(True if ev_type in record_allowed else False, RecordRole)
            view_dict[self.event_filter[ev_type]].appendRow(item)

    def create_stop_events(self, raw_list):
        for ev_type, data1, data2, chan in raw_list:
            ev_type = eval(ev_type)
            ev_item = event_model_dict[ev_type].clone()
            if ev_type == SYSEX:
                chan_item = QtGui.QStandardItem()
                chan_item.setData(0, IdRole)
                chan_item.setEnabled(False)
                data1_item = QtGui.QStandardItem(' '.join(['{:02X}'.format(v) for v in data1]))
                data1_item.setData(0, IdRole)
                data1_item.setData(data1, SysExRole)
                data2_item = QtGui.QStandardItem()
                data2_item.setData(0, IdRole)
                data2_item.setEnabled(False)
            else:
                chan_item = QtGui.QStandardItem('{}'.format(chan+1 if chan >= 0 else 'All'))
                chan_item.setData(chan, IdRole)
                data1_item = QtGui.QStandardItem('{} - {}'.format(data1, Controllers[data1] if ev_type==CTRL else NoteNames[data1].title()))
                data1_item.setData(data1, IdRole)
                data2_item = QtGui.QStandardItem(str(data2))
                data2_item.setData(data2, IdRole)
            self.stop_events_model.appendRow([ev_item, chan_item, data1_item, data2_item])


    def toggle_pairing(self, value=None, force=False):
        if not force and not self.toggle_mode_chk.isChecked(): return
        self.disable_combo.setCurrentIndex(self.enable_combo.currentIndex())
        self.disable_param_spin.setValue(self.enable_param_spin.value())
        self.disable_value_spin.setValue(self.enable_value_spin.value())
        self.disable_chan_spin.setValue(self.enable_chan_spin.value())

    def blacklist_add(self):
        dialog = PortFilterDialog(self)
        res = dialog.exec_()
        if res:
            item = QtGui.QStandardItem(res)
            self.blacklist_model.appendRow(item)

    def blacklist_del(self):
        current = self.blacklist_list.currentIndex()
        if current.row() < 0: return
        self.blacklist_model.takeRow(current.row())

    def auto_connect_enable(self, state):
        if not state: return
        if self.auto_connect_group.checkedId() != 0:
            enable = False
        else:
            enable = True
        self.ctrl_auto_connect_chk.setEnabled(not enable)
        self.ctrl_auto_connect_edit.setEnabled(not enable)
        self.auto_connect_add_btn.setEnabled(enable)
        self.auto_connect_del_btn.setEnabled(enable)
        self.auto_connect_list.setEnabled(enable)

    def auto_connect_add(self):
        dialog = PortFilterDialog(self)
        res = dialog.exec_()
        if res:
            item = QtGui.QStandardItem(res)
            self.auto_connect_model.appendRow(item)

    def auto_connect_del(self):
        current = self.auto_connect_list.currentIndex()
        if current.row() < 0: return
        self.auto_connect_model.takeRow(current.row())

    def add_trigger(self):
        current = self.record_list.currentIndex()
        if current.row() < 0: return
        if self.record_model.itemFromIndex(current).data(TriggerRole).toBool():
            item = self.record_model.takeRow(current.row())
            self.trigger_model.appendRow(item)
        else:
            QtGui.QMessageBox.critical(
                   self, 'Not allowed', 'Type {} cannot be used as a trigger event'.format(
                                                   self.record_model.itemFromIndex(current).text()
                                                   )
                                  )

    def del_trigger(self):
        current = self.trigger_list.currentIndex()
        if current.row() < 0 or self.trigger_model.rowCount() == 1: return
        if self.trigger_model.itemFromIndex(current).text() == 'NOTEON':
            res = QtGui.QMessageBox.question(self, 'Question', 
                                       'You are about to remove NOTEON event types from the trigger'\
                                       'list. This might result in unexpected behaviour.\n'\
                                       'Are you sure?', 
                                       QtGui.QMessageBox.Yes|QtGui.QMessageBox.No)
            if not res == QtGui.QMessageBox.Yes: return
        item = self.trigger_model.takeRow(current.row())
        self.record_model.appendRow(item)

    def add_record(self):
        current = self.ignore_list.currentIndex()
        if current.row() < 0: return
        item = self.ignore_model.takeRow(current.row())
        self.record_model.appendRow(item)

    def del_record(self):
        current = self.record_list.currentIndex()
        if current.row() < 0: return
        item = self.record_model.takeRow(current.row())
        self.ignore_model.appendRow(item)


    def fb_up(self, table):
        current = table.currentIndex()
        if current.row() < 1: return
        model = table.model()
        row = model.takeRow(current.row())
        model.insertRow(current.row()-1, row)
        table.setCurrentIndex(model.index(current.row()-1, current.column()))

    def fb_down(self, table):
        current = table.currentIndex()
        if current.row() >= current.model().rowCount()-1: return
        model = table.model()
        row = model.takeRow(current.row())
        model.insertRow(current.row()+1, row)
        table.setCurrentIndex(model.index(current.row()+1, current.column()))

    def fb_add(self, table):
        if table.model().rowCount() > 8:
            QtGui.QMessageBox.question(self, 'Too many events', 'Too many events to send, are you crazy???')
            return
        ev_type = event_model[0].clone()
        chan = QtGui.QStandardItem('1')
        chan.setData(0, IdRole)
        param = QtGui.QStandardItem('{} - {}'.format(0, Controllers[0]))
        param.setData(0, IdRole)
        value = QtGui.QStandardItem('0')
        value.setData(0, IdRole)
        table.model().appendRow([ev_type, chan, param, value])

    def fb_del(self, table):
        current = table.currentIndex()
        if current.row() < 0: return
        table.model().takeRow(current.row())


class Looper(QtCore.QObject):
    icon_states = {
                   DISABLED: QtGui.QIcon(':/systray/loop-disabled.svg'), 
                   ENABLED: QtGui.QIcon(':/systray/loop-enabled.svg'), 
                   ACTIVE: QtGui.QIcon(':/systray/loop-active.svg'), 
                   PLAY: QtGui.QIcon(':/systray/loop-play.svg'), 
                   }
    def __init__(self, parent=None):
        QtCore.QObject.__init__(self, parent)

        self.settings = QtCore.QSettings()
        self.enabled = self.settings.value('startup_enable', defaults['startup_enable']).toBool()
        self.last_event_limit = int(self.settings.value('last_event_limit', defaults['last_event_limit']).toPyObject())
        self.max_size = int(self.settings.value('max_size', defaults['max_size']).toPyObject())
        self.ignore_doublenote = self.settings.value('ignore_doublenote', defaults['ignore_doublenote']).toBool()
#        self.minimum_time = self.settings.value('minimum_time', defaults['minimum_time']).toPyObject()

        self.blacklist = self.settings.value('blacklist', []).toPyObject()
        self.auto_connect = self.settings.value('auto_connect', defaults['auto_connect']).toPyObject()
        if isinstance(self.auto_connect, QtCore.QString):
            self.auto_connect = str(self.auto_connect)
            self.single_input = True
        if isinstance(self.auto_connect, str) and self.auto_connect.isdigit():
            self.auto_connect = int(self.auto_connect)
        if isinstance(self.auto_connect, int):
            self.single_input = False if self.auto_connect&3 else True
        elif isinstance(self.auto_connect, tuple):
            self.single_input = True

        self.time_threshold = int(self.settings.value('time_threshold', defaults['time_threshold']).toPyObject())
        self.event_filter_mode = {
                             TRIGGER: self.settings.value('trigger_events', trigger_defaults).toPyObject(), 
                             RECORD: self.settings.value('record_events', record_defaults).toPyObject(), 
                             IGNORE: self.settings.value('ignore_events', ()).toPyObject(), 
                             }
        self.event_filter = {ev:dest for dest, ev_tuple in self.event_filter_mode.items() for ev in ev_tuple}
        self.ignore_list = self.event_filter_mode[IGNORE]

        self.stop_notes = self.settings.value('stop_notes', defaults['stop_notes']).toBool()
        self.create_stop_events(self.settings.value('stop_events', defaults['stop_events']).toPyObject())

        self.ctrl_auto_connect = str(self.settings.value('ctrl_auto_connect').toPyObject())
        self.toggle_mode = self.settings.value('toggle_mode', defaults['toggle_mode']).toBool()
        self.ctrl_enable_event = RemoteCtrlEvent(*self.settings.value('ctrl_enable_event', defaults['ctrl_enable_event']).toPyObject())
        self.ctrl_disable_event = RemoteCtrlEvent(*self.settings.value('ctrl_disable_event', defaults['ctrl_disable_event']).toPyObject())
        self.ctrl_stop_event = RemoteCtrlEvent(*self.settings.value('ctrl_stop_event', defaults['ctrl_stop_event']).toPyObject())
        self.create_ctrl_events()

        self.fb_auto_connect = str(self.settings.value('fb_auto_connect').toPyObject())
        self.fb_enable_events = self.settings.value('fb_enable_events', []).toPyObject()
        self.fb_disable_events = self.settings.value('fb_disable_events', []).toPyObject()
        self.fb_stop_events = self.settings.value('fb_stop_events', []).toPyObject()
        self.fb_play_events = self.settings.value('fb_play_events', []).toPyObject()

        self.pattern = None

        self.alsa_thread = QtCore.QThread()
        self.alsa = AlsaMidi(self, single_input=self.single_input)
        self.alsa.moveToThread(self.alsa_thread)
        self.alsa.stopped.connect(self.alsa_thread.quit)
        self.alsa_thread.started.connect(self.alsa.run)
        self.alsa.midi_signal.connect(self.alsa_midi_event)
        self.alsa.port_start.connect(self.new_alsa_port)
        self.alsa.conn_register.connect(self.alsa_conn_event)
        self.alsa_thread.start()
        self.seq = self.alsa.seq
        self.input = self.alsa.input
        self.control = self.alsa.control
        self.feedback = self.alsa.feedback

        self.port_discovery()
        if not self.single_input:
            self.ctrl_connect()
        if self.fb_auto_connect:
            self.fb_connect()

        self.trayicon = QtGui.QSystemTrayIcon(self.icon_states[ENABLED if self.enabled else DISABLED], parent)
        self.trayicon.show()
        self.trayicon.activated.connect(self.show_menu)

        self.timer = QtCore.QElapsedTimer()
        self.last_event_timer = QtCore.QTimer()
        self.last_event_timer.setInterval(self.last_event_limit*1000)
        self.last_event_timer.setSingleShot(True)
        self.last_event_timer.timeout.connect(self.clear_buffer)

        self.icon_timer = QtCore.QTimer()
        self.icon_timer.setInterval(200)
        self.icon_timer.setSingleShot(True)
#        self.icon_timer.timeout.connect(self.icon_set)

        self.event_buffer = MidiBuffer(self.max_size*3, self.event_filter_mode[TRIGGER], self.time_threshold, self.ignore_doublenote)
        self.event_buffer.pattern_created.connect(self.play)

#        self.show_settings()

    def ctrl_connect(self):
        ports = self.ctrl_auto_connect.replace(',', '|')
        if not ports: return
        ports_re = re.compile(ports)
        graph_dict = {}
        for c, ports in self.graph.port_id_dict.items():
            for p, port in ports.items():
                if not port.is_output: continue
                graph_dict['{}:{}'.format(self.graph.client_id_dict[c].name, port.name)] = (c, p)
                graph_dict['{}:{}'.format(c, p)] = (c, p)

        for port, addr in graph_dict.items():
            check = ports_re.match(port)
            if check is not None:
                try:
                    port_map = map(int, addr)
                    self.seq.connect_ports(port_map, self.control.addr)
                except Exception as err:
                    print err
                    print 'error trying to connect to address {}:{}'.format(*port_map)

    def fb_connect(self):
        ports = self.fb_auto_connect.replace(',', '|')
        if not ports: return
        ports_re = re.compile(ports)
        graph_dict = {}
        for c, ports in self.graph.port_id_dict.items():
            for p, port in ports.items():
                if not port.is_input: continue
                graph_dict['{}:{}'.format(self.graph.client_id_dict[c].name, port.name)] = (c, p)
                graph_dict['{}:{}'.format(c, p)] = (c, p)

        for port, addr in graph_dict.items():
            check = ports_re.match(port)
            if check is not None:
                try:
                    port_map = map(int, addr)
                    self.seq.connect_ports(self.feedback.addr, port_map)
                except Exception as err:
                    print err
                    print 'error trying to connect to address {}:{}'.format(*port_map)

    def create_stop_events(self, stop_events):
        self.stop_events = []
        self.stop_events_raw = []
        if stop_events is None: return
        for event in stop_events:
            event_type = eval(event[0])
            if event_type == SYSEX:
                self.stop_events.append(SysExEvent(0, sysex=event[1]))
                self.stop_events_raw.append(event)
                continue
            if len(event) == 4 and event[3] >= 0:
                self.stop_events_raw.append(event)
                self.stop_events.append(MidiEvent(event_type, channel=event[3], data1=event[1], data2=event[2]))
            else:
                if len(event) == 3:
                    self.stop_events_raw.append(event+(-1, ))
                else:
                    self.stop_events_raw.append(event)
                for c in range(16):
                    self.stop_events.append(MidiEvent(event_type, channel=c, data1=event[1], data2=event[2]))

    def create_ctrl_events(self):
        def fill_dict(event, func):
            if event.channel >= 0:
                self.ctrl_events[(event.channel, _id_to_event[event.event_type], event.param, event.value)] = func
            else:
                for channel in range(16):
                    self.ctrl_events[(channel, _id_to_event[event.event_type], event.param, event.value)] = func
        self.ctrl_events = {}
        if self.toggle_mode:
            fill_dict(self.ctrl_enable_event, self.enable_toggle)
        else:
            fill_dict(self.ctrl_enable_event, lambda: self.enable_set(True))
            fill_dict(self.ctrl_disable_event, lambda: self.enable_set(False))
        fill_dict(self.ctrl_stop_event, self.stop)
#        if self.toggle_mode:
#            self.ctrl_events = {
#                        (_id_to_event[self.ctrl_enable_event[0]], self.ctrl_enable_event[1], self.ctrl_enable_event[2]): self.enable_toggle, 
#                        (_id_to_event[self.ctrl_stop_event[0]], self.ctrl_stop_event[1], self.ctrl_stop_event[2]): self.stop, 
#                        }
#        else:
#            self.ctrl_events = {
#                        (_id_to_event[self.ctrl_enable_event[0]], self.ctrl_enable_event[1], self.ctrl_enable_event[2]): lambda: self.enable_set(True), 
#                        (_id_to_event[self.ctrl_disable_event[0]], self.ctrl_disable_event[1], self.ctrl_disable_event[2]): lambda: self.enable_set(False), 
#                        (_id_to_event[self.ctrl_stop_event[0]], self.ctrl_stop_event[1], self.ctrl_stop_event[2]): self.stop, 
#                        }

    def icon_set(self, state=None):
        if state is None:
            if self.enabled:
                state = ENABLED
            elif self.pattern:
                state = PLAY
            else:
                state = DISABLED
        self.trayicon.setIcon(self.icon_states[state])

    def enable_set(self, state):
        self.enabled = state
        if not state and self.pattern:
            stop_notes, sources = self.event_buffer.stop()
            for noteoff in stop_notes:
                self.output_event(noteoff)
                if self.stop_notes:
                    self.output_event(noteoff)
            self.stop_events_send(sources)
        self.clear_buffer()
        self.icon_set()
        self.fb_send(self.fb_stop_events + self.fb_enable_events if state else self.fb_disable_events)

    def enable_toggle(self):
        self.enable_set(not self.enabled)

    def port_discovery(self):
        for client_id, port_dict in self.graph.port_id_dict.items():
            if client_id == 0: continue
            for port_id, port in port_dict.items():
                if port == self.feedback: continue
                if self.blacklist:
                    ports_re = re.compile('|'.join(self.blacklist))
                    match = ports_re.match('{}:{}'.format(port.client.name, port.name))
                    if match is not None: continue
                    match = ports_re.match('{}:{}'.format(*port.addr))
                    if match is not None: continue
                if port.is_output and not alsaseq.SEQ_PORT_CAP_NO_EXPORT in port.caps:
                    if isinstance(self.auto_connect, int):
                        if self.auto_connect&3:
                            if not port.client.type&self.auto_connect:
                                continue
                        else:
                            continue
                    elif isinstance(self.auto_connect, tuple):
                        ports_re = re.compile('|'.join(self.auto_connect))
                        match = ports_re.match('{}:{}'.format(port.client.name, port.name))
                        if match is None:
                            match = ports_re.match('{}:{}'.format(*port.addr))
                            if match is None:
                                continue
                    try:
                        self.seq.connect_ports(port.addr, self.input.addr)
                    except:
                        print 'Error trying to connect to {}:{} ({})'.format(port.client.name, port.name, port.addr)

    def new_alsa_port(self, port):
        if not port.is_output or alsaseq.SEQ_PORT_CAP_NO_EXPORT in port.caps: return
        if self.ctrl_auto_connect and not self.single_input:
            ports_re = re.compile(self.ctrl_auto_connect)
            match = ports_re.match('{}:{}'.format(port.client.name, port.name))
            if match is not None:
                try:
                    self.seq.connect_ports(port.addr, self.control.addr)
                    return
                except:
                    pass
            match = ports_re.match('{}:{}'.format(port.client.id, port.id))
            if match is not None:
                try:
                    self.seq.connect_ports(port.addr, self.control.addr)
                    return
                except:
                    pass
        try:
            self.seq.connect_ports(port.addr, self.input.addr)
        except Exception as err:
            print 'Wow! {}'.format(err)

    def alsa_conn_event(self, conn, state):
        if conn.dest == self.alsa.control:
            if state:
                try:
                    self.seq.disconnect_ports(conn.src.addr, self.input.addr)
                    print 'Disconnecting port "{}" from automatic monitor, '\
                    'further events will be ignored.'.format(conn.src)
                except:
                    pass
            else:
                try:
                    self.seq.connect_ports(conn.src.addr, self.input.addr)
                    print 'Reconnecting port "{}" to automatic monitor, '\
                    'new events will be processed'.format(conn.src)
                except:
                    pass

    def alsa_midi_event(self, event):
        if not self.single_input and tuple(event.dest) == tuple(self.control.addr):
            cmd = self.ctrl_events.get((event.channel, event.type, event.data1, event.data2))
            if cmd:
                cmd()
            return
        time = self.timer.elapsed()
        if self.single_input:
            cmd = self.ctrl_events.get((event.channel, event.type, event.data1, event.data2))
            if cmd:
                cmd()
                return
        if not self.enabled or self.pattern or event.type in self.ignore_list:
            return
        if not self.event_buffer:
            self.timer.start()
            time = 0
        client_id, port_id = map(int, event.source)
#        client_name = str(self.graph.client_id_dict[client_id])
#        port_name = str(self.graph.port_id_dict[client_id][port_id])
#        if event.type in self.event_type_filter or\
#                client_id in self.client_id_filter or\
#                (client_id, port_id) in self.port_id_filter or\
#                self.port_name_filter.match('{}:{}'.format(client_name, port_name)):
#            return
        source = MidiSource(client_id, port_id)
#        print 'T: {} ({}) > {}'.format(self.timer.nsecsElapsed(), event, event.dest)
        self.event_buffer.append(event, time, source)
        if not self.pattern:
            self.last_event_timer.start()
            self.icon_set(ACTIVE)
            self.icon_timer.start()

#    def last_event_timeout(self):
#        if self.timer.elapsed()/(10**3) < (self.last_event_limit+self.minimum_time):
#        self.clear_buffer()

    def clear_buffer(self):
        self.event_buffer.pattern_created.disconnect()
        self.event_buffer.deleteLater()
        self.event_buffer = MidiBuffer(self.max_size*3, self.event_filter_mode[TRIGGER], self.time_threshold, self.ignore_doublenote)
        self.event_buffer.pattern_created.connect(self.play)
        self.pattern = None

    def play(self, pattern):
        self.pattern = pattern
        for data in pattern:
            data.play.connect(self.output_event)
        print 'playing loop!'
        self.last_event_timer.stop()
        self.icon_timer.stop()
        self.icon_set(PLAY)
        self.fb_send(self.fb_play_events)

    def stop(self):
#        if self.pattern:
#            for data in self.pattern:
#                data.play.disconnect()
        stop_notes, sources = self.event_buffer.stop()
        for noteoff in stop_notes:
            if self.stop_notes:
                self.output_event(noteoff)
        self.stop_events_send(sources)
        self.clear_buffer()
        self.icon_set()
        self.fb_send(self.fb_stop_events)

    def stop_events_send(self, sources):
        for source in sources:
            for event in self.stop_events:
                event.source = source
                self.output_event(event)
#            self.output_event(event)

#    def stop_disable(self):
#        if self.pattern:
#            for data in self.pattern:
#                data.play.disconnect()
#        self.event_buffer.stop()
#        self.clear_buffer()
#        self.enable_set(False)

    def output_event(self, event):
        event = event.get_event()
        source_client, source_port = map(int, event.source)
        conns = self.graph.port_id_dict[source_client][source_port].connections.output
        sent = False
        for conn in conns:
            if conn.dest.client.id == self.seq.client_id: continue
            event.dest = conn.dest.addr
            self.seq.output_event(event)
            sent = True
        if not sent:
            print 'qualcosa non va, non c\'è output! ({}) > {}'.format(event.source, conns)
            return
#        event.source = self.alsa.output.addr
#        event.dest = 0xfe, 0xfd
#        print 'sending event {} (src: {}, dest: {})'.format(event.type, event.source, event.dest)
#        self.seq.output_event(event)
        self.seq.drain_output()

    def fb_send(self, ev_list):
        for ev_type, channel, data1, data2 in ev_list:
            ev_type = eval(ev_type)
            if ev_type != SYSEX:
                event = MidiEvent(ev_type, channel=channel, data1=data1, data2=data2).get_event()
            else:
                event = SysExEvent(0, data1).get_event()
            event.source = self.feedback.addr
            event.dest = 0xfe, 0xfd
            self.seq.output_event(event)
            self.seq.drain_output()


    def show_menu(self, reason):
        if not reason == QtGui.QSystemTrayIcon.Context: return
        QtGui.QIcon.setThemeName(QtGui.QApplication.style().objectName())
        menu = QtGui.QMenu()
        menu.setSeparatorsCollapsible(False)

        header = QtGui.QAction('MOL', self)
        header.setSeparator(True)
        menu.addAction(header)
        toggle = QtGui.QAction('&Enable', self)
        toggle.setCheckable(True)
        toggle.setChecked(True if self.enabled else False)
        toggle.triggered.connect(self.enable_set)
        menu.addAction(toggle)
        if self.event_buffer and self.event_buffer.pattern_set:
            stop = QtGui.QAction('Stop and reset!', self)
            stop.triggered.connect(self.stop)
            menu.addAction(stop)
        sep = QtGui.QAction(self)
        sep.setSeparator(True)
        settings = QtGui.QAction('&Settings...', self)
        settings.triggered.connect(self.show_settings)
        about = QtGui.QAction('&About...', self)
        about.triggered.connect(self.show_about)
        sep2 = QtGui.QAction(self)
        sep2.setSeparator(True)
        quit_item = QtGui.QAction('&Quit', self)
        quit_item.setIcon(QtGui.QIcon.fromTheme('application-exit'))
        quit_item.triggered.connect(self.quit)
        menu.addActions([sep, settings, about, sep2, quit_item])
        menu.exec_(QtGui.QCursor.pos())

    def show_about(self):
        AboutDialog(self).exec_()

    def show_settings(self):
        dialog = SettingsDialog(self)
        res = dialog.exec_()
        if not res: return
        self.settings.setValue('startup_enable', dialog.startup_chk.isChecked())
        self.last_event_limit = dialog.last_event_limit_spin.value()
        self.settings.setValue('last_event_limit', self.last_event_limit)
        self.max_size = dialog.max_size_spin.value()
        self.ignore_doublenote = dialog.ignore_doublenote_chk.isChecked()
        self.settings.setValue('ignore_doublenote', self.ignore_doublenote)

        auto_connect = dialog.auto_connect_group.checkedId()
        if auto_connect & 3:
            #TODO: add alert for changed auto_connect!
            self.auto_connect = auto_connect
#            self.settings.setValue('auto_connect', auto_connect)
        else:
            auto_connect = tuple(str(dialog.auto_connect_model.item(r).text()) for r in range(dialog.auto_connect_model.rowCount()))
            self.auto_connect = auto_connect if auto_connect else 0
        self.settings.setValue('auto_connect', self.auto_connect)
        self.blacklist = tuple(str(dialog.blacklist_model.item(r).text()) for r in range(dialog.blacklist_model.rowCount()))
        self.settings.setValue('blacklist', self.blacklist)

        self.time_threshold = dialog.time_threshold_spin.value()
        self.settings.setValue('time_threshold', self.time_threshold)

        trigger = tuple([dialog.trigger_model.item(r).data(EventRole).toPyObject() for r in range(dialog.trigger_model.rowCount())])
        self.settings.setValue('trigger_events', trigger)
        record = tuple([dialog.record_model.item(r).data(EventRole).toPyObject() for r in range(dialog.record_model.rowCount())])
        self.settings.setValue('record_events', record)
        self.ignore_list = tuple([dialog.ignore_model.item(r).data(EventRole).toPyObject() for r in range(dialog.ignore_model.rowCount())])
        self.settings.setValue('ignore_events', self.ignore_list)
        self.event_filter_mode = {
                                  TRIGGER: trigger, 
                                  RECORD: record, 
                                  IGNORE: self.ignore_list, 
                                  }
        self.event_filter = {ev:dest for dest, ev_tuple in self.event_filter_mode.items() for ev in ev_tuple}

        self.stop_notes = dialog.stop_notes_chk.isChecked()
        self.settings.setValue('stop_notes', self.stop_notes)

        stop_events = []
        while dialog.stop_events_model.rowCount() > 0:
            row = dialog.stop_events_model.takeRow(0)
            ev_type = row[0].data(EventRole).toPyObject()
            if ev_type == SYSEX:
                sysex = row[2].data(SysExRole).toPyObject()
                stop_events.append((str(ev_type), sysex, None, None))
                continue
            chan = row[1].data(IdRole).toPyObject()
            data1 = row[2].data(IdRole).toPyObject()
            data2 = row[3].data(IdRole).toPyObject()
            stop_events.append((str(ev_type), data1, data2, chan))
        self.create_stop_events(stop_events)
        self.settings.setValue('stop_events', stop_events)

        if dialog.ctrl_auto_connect_chk.isChecked():
            ctrl_auto_connect = str(dialog.ctrl_auto_connect_edit.text())
        else:
            ctrl_auto_connect = None
        if ctrl_auto_connect:
            self.ctrl_auto_connect = ctrl_auto_connect
        else:
            self.ctrl_auto_connect = None

        self.settings.setValue('ctrl_auto_connect', self.ctrl_auto_connect)
        self.toggle_mode = dialog.toggle_mode_chk.isChecked()
        self.settings.setValue('toggle_mode', self.toggle_mode)
        self.ctrl_enable_event = RemoteCtrlEvent(dialog.enable_combo.currentIndex(), dialog.enable_param_spin.value(), dialog.enable_value_spin.value(), dialog.enable_chan_spin.value()-1)
        self.settings.setValue('ctrl_enable_event', self.ctrl_enable_event)
        self.ctrl_disable_event = RemoteCtrlEvent(dialog.disable_combo.currentIndex(), dialog.disable_param_spin.value(), dialog.disable_value_spin.value(), dialog.disable_chan_spin.value()-1)
        self.settings.setValue('ctrl_disable_event', self.ctrl_disable_event)
        self.ctrl_stop_event = RemoteCtrlEvent(dialog.stop_combo.currentIndex(), dialog.stop_param_spin.value(), dialog.stop_value_spin.value(), dialog.stop_chan_spin.value()-1)
        self.settings.setValue('ctrl_stop_event', self.ctrl_stop_event)
        self.create_ctrl_events()

        if dialog.fb_auto_connect_chk.isChecked():
            fb_auto_connect = str(dialog.fb_auto_connect_edit.text())
        else:
            fb_auto_connect = None
        if fb_auto_connect:
            self.fb_auto_connect = fb_auto_connect
        else:
            self.fb_auto_connect = None
        self.settings.setValue('fb_auto_connect', self.fb_auto_connect)
        for action in ['enable', 'disable', 'stop', 'play']:
            model = getattr(dialog, 'fb_{}_table'.format(action)).model()
            if model.rowCount() == 0:
                setattr(self, 'fb_{}_events'.format(action), [])
                continue
            ev_list = []
            while model.rowCount() > 0:
                row = model.takeRow(0)
                ev_type = row[0].data(EventRole).toPyObject()
                chan = row[1].data(IdRole).toPyObject()
                if ev_type == SYSEX:
                    data1 = row[2].data(SysExRole).toPyObject()
                else:
                    data1 = row[2].data(IdRole).toPyObject()
                data2 = row[3].data(IdRole).toPyObject()
                ev_list.append((str(ev_type), chan, data1, data2))
            setattr(self, 'fb_{}_events'.format(action), ev_list)
            self.settings.setValue('fb_{}_events'.format(action), ev_list)


    def quit(self):
        QtGui.QApplication.quit()



def main():
    app = QtGui.QApplication(sys.argv)
    app.setOrganizationName('jidesk')
    app.setApplicationName('MOL')
    app.setQuitOnLastWindowClosed(False)
    Looper(app)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()










