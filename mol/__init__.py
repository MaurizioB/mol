#!/usr/bin/env python2.7
# *-* coding: utf-8 *-*

import sys
from os import path
from pyalsa import alsaseq
from PyQt4 import QtCore, QtGui
import icons
from classes import *
from midiutils import *


clientname = 'MOL'

defaults = {
            'max_rec': 20, 
            'minimum_time': 2, 
            'last_event_limit': 5, 
            'tick_res': 960, 
            'stop_events': [(123, 0), (64, 0)]
            }

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


class Looper(QtCore.QObject):
    def __init__(self, parent=None):
        QtCore.QObject.__init__(self, parent)

        self.trayicon = QtGui.QSystemTrayIcon(QtGui.QIcon(':/systray/loop-base.svg'), parent)
        self.trayicon.show()
        self.trayicon.activated.connect(self.show_menu)

        #settings will go here
        self.last_event_limit = defaults['last_event_limit']
        self.minimum_time = defaults['minimum_time']

        self.alsa_thread = QtCore.QThread()
        self.alsa = AlsaMidi(self)
        self.alsa.moveToThread(self.alsa_thread)
        self.alsa.stopped.connect(self.alsa_thread.quit)
        self.alsa_thread.started.connect(self.alsa.run)
        self.alsa.midi_signal.connect(self.alsa_midi_event)
        self.alsa.port_start.connect(self.new_alsa_port)
#        self.alsa.conn_register.connect(self.alsa_conn_event)
        self.alsa_thread.start()
        self.seq = self.alsa.seq
        self.input = self.alsa.input
        self.port_discovery()

        self.enabled = True
        self.pattern = None

        self.timer = QtCore.QElapsedTimer()
        self.last_event_timer = QtCore.QTimer()
        self.last_event_timer.setInterval(self.last_event_limit*1000)
        self.last_event_timer.setSingleShot(True)
        self.last_event_timer.timeout.connect(self.last_event_timeout)

        self.event_buffer = MidiBuffer()
        self.event_buffer.pattern_created.connect(self.play)

    def enable_set(self, state):
        self.enabled = state

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
        try:
            self.seq.connect_ports(port.addr, self.input.addr)
        except Exception as err:
            print 'Wow! {}'.format(err)

    def last_event_timeout(self):
        if self.timer.elapsed()/(10**3) < (self.last_event_limit+self.minimum_time):
#            self.icon_set()
            self.event_buffer.pattern_created.disconnect()
            self.event_buffer.deleteLater()
            self.event_buffer = MidiBuffer()
            self.event_buffer.pattern_created.connect(self.play)
            return

    def play(self, pattern):
        self.pattern = pattern
        for data in pattern:
            data.play.connect(self.output_event)
        print 'playing!'

    def stop(self):
        if self.pattern:
            for data in self.pattern:
                data.play.disconnect()
        self.event_buffer.stop()
        self.event_buffer.pattern_created.disconnect()
        self.event_buffer.deleteLater()
        self.event_buffer = MidiBuffer()
        self.event_buffer.pattern_created.connect(self.play)

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


    def alsa_midi_event(self, event):
        if not self.enabled: return
        if not self.event_buffer:
            self.timer.start()
        time = self.timer.elapsed()
        client_id, port_id = map(int, event.source)
        client_name = str(self.graph.client_id_dict[client_id])
        port_name = str(self.graph.port_id_dict[client_id][port_id])
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
#        settings = QtGui.QAction('&Settings...', self)
#        settings.triggered.connect(self.settings_dialog.show)
#        sep2 = QtGui.QAction(self)
#        sep2.setSeparator(True)
        quit_item = QtGui.QAction('&Quit', self)
        quit_item.setIcon(QtGui.QIcon.fromTheme('application-exit'))
        quit_item.triggered.connect(self.quit)
        menu.addActions([sep, quit_item])
        menu.exec_(QtGui.QCursor.pos())

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










