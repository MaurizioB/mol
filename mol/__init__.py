#!/usr/bin/env python2.7
# *-* coding: utf-8 *-*

import sys, re
from os import path
from pyalsa import alsaseq
from PyQt4 import QtCore, QtGui, uic
import icons
from classes import *
from midiutils import *


clientname = 'MOL'

defaults = {
            'startup_enable': False, 
            'minimum_time': 2, 
            'last_event_limit': 5, 
            'stop_events': [(123, 0), (64, 0)], 
            'toggle_mode': False, 
            'enable_event': (0, 32, 0), 
            'disable_event': (0, 32, 1), 
            'stop_event': (1, 32, 127), 
            }

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

def _load_ui(widget, ui_path):
    return uic.loadUi(path.join(path.dirname(path.abspath(__file__)), ui_path), widget)


class AlsaMidi(QtCore.QObject):
    client_start = QtCore.pyqtSignal(object)
    client_exit = QtCore.pyqtSignal(object)
    port_start = QtCore.pyqtSignal(object)
    port_exit = QtCore.pyqtSignal(object)
    conn_register = QtCore.pyqtSignal(object, bool)
    graph_changed = QtCore.pyqtSignal()
    stopped = QtCore.pyqtSignal()
    midi_signal = QtCore.pyqtSignal(object)

    def __init__(self, main):
        QtCore.QObject.__init__(self)
        self.main = main
        self.active = False
        self.seq = alsaseq.Sequencer(clientname=clientname)
        self.keep_going = True
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
        self.control = self.graph.port_id_dict[self.id][control_id]
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


class SettingsDialog(QtGui.QDialog):
    def __init__(self, main):
        QtGui.QDialog.__init__(self, parent=None)
        _load_ui(self, 'settings.ui')
        self.main = main
        self.settings = main.settings
        self.startup_chk.setChecked(self.settings.value('startup_enable', defaults['startup_enable']).toBool())
        self.last_event_limit_spin.setValue(self.main.last_event_limit)

        self.auto_connect_chk.toggled.connect(self.auto_connect_edit.setEnabled)
        if self.main.auto_connect:
            self.auto_connect_edit.setText(self.main.auto_connect)
            self.auto_connect_chk.setChecked(True)
        self.toggle_chk.setChecked(self.main.toggle_mode)
        self.enable_combo.setCurrentIndex(self.main.enable_event[0])
        self.enable_param_spin.setValue(self.main.enable_event[1])
        self.enable_value_spin.setValue(self.main.enable_event[2])
        self.disable_combo.setCurrentIndex(self.main.enable_event[0])
        self.disable_param_spin.setValue(self.main.disable_event[1])
        self.disable_value_spin.setValue(self.main.disable_event[2])
        self.stop_combo.setCurrentIndex(self.main.stop_event[0])
        self.stop_param_spin.setValue(self.main.stop_event[1])
        self.stop_value_spin.setValue(self.main.stop_event[2])
        self.toggle_chk.toggled.connect(lambda state: [
                                                       self.disable_combo.setEnabled(not state), 
                                                       self.disable_param_spin.setEnabled(not state), 
                                                       self.disable_value_spin.setEnabled(not state)
                                                       ])
        self.toggle_chk.toggled.emit(self.toggle_chk.isChecked())

#    def exec_(self):
#        res = QtGui.QDialog.exec_(self)
#        if not res: return None

class Looper(QtCore.QObject):
    icon_states = {
                   DISABLED: QtGui.QIcon(':/systray/loop-disabled.svg'), 
                   ENABLED: QtGui.QIcon(':/systray/loop-enabled.svg'), 
                   ACTIVE: QtGui.QIcon(':/systray/loop-active.svg'), 
                   PLAY: QtGui.QIcon(':/systray/loop-play.svg'), 
                   }
    def __init__(self, parent=None):
        QtCore.QObject.__init__(self, parent)

        self.alsa_thread = QtCore.QThread()
        self.alsa = AlsaMidi(self)
        self.alsa.moveToThread(self.alsa_thread)
        self.alsa.stopped.connect(self.alsa_thread.quit)
        self.alsa_thread.started.connect(self.alsa.run)
        self.alsa.midi_signal.connect(self.alsa_midi_event)
        self.alsa.port_start.connect(self.new_alsa_port)
        self.alsa.conn_register.connect(self.alsa_conn_event)
#        self.alsa.conn_register.connect(self.alsa_conn_event)
        self.alsa_thread.start()
        self.seq = self.alsa.seq
        self.input = self.alsa.input
        self.control = self.alsa.control
        self.port_discovery()

        #settings will go here
        self.settings = QtCore.QSettings()
        self.last_event_limit = int(self.settings.value('last_event_limit', defaults['last_event_limit']).toPyObject())
        self.minimum_time = self.settings.value('minimum_time', defaults['minimum_time']).toPyObject()
        self.enabled = self.settings.value('startup_enable', defaults['startup_enable']).toBool()
        self.auto_connect = str(self.settings.value('auto_connect', 'Virtual').toPyObject())
        self.connect_control()
        self.toggle_mode = self.settings.value('toggle_mode', defaults['toggle_mode']).toBool()
        self.enable_event = self.settings.value('enable_event', defaults['enable_event']).toPyObject()
        self.disable_event = self.settings.value('disable_event', defaults['disable_event']).toPyObject()
        self.stop_event = self.settings.value('stop_event', defaults['stop_event']).toPyObject()
        self.create_ctrl_events()

        self.pattern = None

        self.trayicon = QtGui.QSystemTrayIcon(self.icon_states[ENABLED if self.enabled else DISABLED], parent)
        self.trayicon.show()
        self.trayicon.activated.connect(self.show_menu)

        self.timer = QtCore.QElapsedTimer()
        self.last_event_timer = QtCore.QTimer()
        self.last_event_timer.setInterval(self.last_event_limit*1000)
        self.last_event_timer.setSingleShot(True)
        self.last_event_timer.timeout.connect(self.last_event_timeout)

        self.icon_timer = QtCore.QTimer()
        self.icon_timer.setInterval(200)
        self.icon_timer.setSingleShot(True)
#        self.icon_timer.timeout.connect(self.icon_set)

        self.event_buffer = MidiBuffer()
        self.event_buffer.pattern_created.connect(self.play)

    def connect_control(self):
        ports = self.auto_connect.replace(',', '|')
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
                    self.seq.connect_ports(port_map, self.alsa.control.addr)
                except Exception as err:
                    print err
                    print 'error trying to connect to address {}:{}'.format(*port_map)

    def create_ctrl_events(self):
        if self.toggle_mode:
            self.ctrl_events = {
                        (_id_to_event[self.enable_event[0]], self.enable_event[1], self.enable_event[2]): self.enable_toggle, 
                        (_id_to_event[self.stop_event[0]], self.stop_event[1], self.stop_event[2]): self.stop, 
                        }
        else:
            self.ctrl_events = {
                        (_id_to_event[self.enable_event[0]], self.enable_event[1], self.enable_event[2]): lambda: self.enable_set(True), 
                        (_id_to_event[self.disable_event[0]], self.disable_event[1], self.disable_event[2]): lambda: self.enable_set(False), 
                        (_id_to_event[self.stop_event[0]], self.stop_event[1], self.stop_event[2]): self.enable_set, 
                        }

    def icon_set(self, state=None):
        print state
        if state is None:
            if self.enabled:
                state = ENABLED
            elif self.pattern:
                state = PLAY
            else:
                state = DISABLED
        print 'setting {}'.format(state)
        self.trayicon.setIcon(self.icon_states[state])

    def enable_set(self, state):
        self.enabled = state
        self.clear_buffer()
        if not state and self.pattern:
            for data in self.pattern:
                data.play.disconnect()
        self.event_buffer.stop()
        self.icon_set()

    def enable_toggle(self):
        self.enable_set(not self.enabled)

    def port_discovery(self):
        for client_id, port_dict in self.graph.port_id_dict.items():
            if client_id == 0: continue
            for port_id, port in port_dict.items():
#                if port.is_output and port != self.alsa.output and not alsaseq.SEQ_PORT_CAP_NO_EXPORT in port.caps:
                if port.is_output and not alsaseq.SEQ_PORT_CAP_NO_EXPORT in port.caps:
                    try:
                        self.seq.connect_ports(port.addr, self.input.addr)
                    except:
                        print 'Error trying to connect to {}:{} ({})'.format(port.client.name, port.name, port.addr)

    def new_alsa_port(self, port):
        if not port.is_output or alsaseq.SEQ_PORT_CAP_NO_EXPORT in port.caps: return
        if self.auto_connect:
            ports_re = re.compile(self.auto_connect)
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
#        source_tuple = (conn.src.client.name, conn.src.name, conn.src.addr)
#        source = MidiSource(*source_tuple)
#        dest_tuple = (conn.dest.client.name, conn.dest.name, conn.dest.addr)
#        event = ConnectionEvent(source_tuple, dest_tuple, state)

    def alsa_midi_event(self, event):
        if tuple(event.dest) == tuple(self.alsa.control.addr):
            print 'evento ricevuto sulla porta control, analizzo e scarto'
            res = self.ctrl_events.get((event.type, event.data1, event.data2))
            if res:
                res()
            return
        if not self.enabled or self.pattern: return
        if not self.event_buffer:
            self.timer.start()
        time = self.timer.elapsed()
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
        self.last_event_timer.start()
#        self.icon_set(EVENT)
#        self.icon_timer.start()
#        self.icon_timer_saved.stop()
        if not self.pattern:
            self.icon_set(ACTIVE)
            self.icon_timer.start()

    def last_event_timeout(self):
        if self.timer.elapsed()/(10**3) < (self.last_event_limit+self.minimum_time):
#            self.icon_set()
            self.clear_buffer()
            return

    def clear_buffer(self):
        print 'clearing buffer'
        self.event_buffer.pattern_created.disconnect()
        self.event_buffer.deleteLater()
        self.event_buffer = MidiBuffer()
        self.event_buffer.pattern_created.connect(self.play)
        self.pattern = None

    def play(self, pattern):
        self.pattern = pattern
        for data in pattern:
            data.play.connect(self.output_event)
        print 'playing!'
        self.icon_timer.stop()
        self.icon_set(PLAY)

    def stop(self):
        if self.pattern:
            for data in self.pattern:
                data.play.disconnect()
        self.event_buffer.stop()
        self.clear_buffer()
        self.icon_set()

    def stop_disable(self):
        if self.pattern:
            for data in self.pattern:
                data.play.disconnect()
        self.event_buffer.stop()
        self.enable_set(False)

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
            print 'qualcosa non va, non c\'è output!'
            return
#        event.source = self.alsa.output.addr
#        event.dest = 0xfe, 0xfd
#        print 'sending event {} (src: {}, dest: {})'.format(event.type, event.source, event.dest)
#        self.seq.output_event(event)
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
        sep2 = QtGui.QAction(self)
        sep2.setSeparator(True)
        quit_item = QtGui.QAction('&Quit', self)
        quit_item.setIcon(QtGui.QIcon.fromTheme('application-exit'))
        quit_item.triggered.connect(self.quit)
        menu.addActions([sep, settings, sep2, quit_item])
        menu.exec_(QtGui.QCursor.pos())

    def show_settings(self):
        dialog = SettingsDialog(self)
        res = dialog.exec_()
        if not res: return
        self.settings.setValue('startup_enable', dialog.startup_chk.isChecked())
        self.last_event_limit = dialog.last_event_limit_spin.value()
        self.settings.setValue('last_event_limit', self.last_event_limit)
        self.auto_connect = str(dialog.auto_connect_edit.text())
        self.settings.setValue('auto_connect', self.auto_connect)
        self.toggle_mode = dialog.toggle_chk.isChecked()
        self.settings.setValue('toggle_mode', self.toggle_mode)
        self.enable_event = (dialog.enable_combo.currentIndex(), dialog.enable_param_spin.value(), dialog.enable_value_spin.value())
        self.settings.setValue('enable_event', self.enable_event)
        self.disable_event = (dialog.disable_combo.currentIndex(), dialog.disable_param_spin.value(), dialog.disable_value_spin.value())
        self.settings.setValue('disable_event', self.disable_event)
        self.stop_event = (dialog.stop_combo.currentIndex(), dialog.stop_param_spin.value(), dialog.stop_value_spin.value())
        self.settings.setValue('stop_event', self.stop_event)
        self.create_ctrl_events()


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










