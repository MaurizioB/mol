MOL \_ MIDI Organic Looper
==========================

MOL is a simple MIDI looper which does not aim to work like standard
sequenced loopers.

It just takes what you play and, once it recognizes a repetition, it
plays.

This is just a preliminary release, might not work at all ;)

Features
--------

-  Simple enough...
-  Automatically connects and receive MIDI events from any ALSA MIDI
   source
-  Repetitions are recognized with a 100ms threshold
-  Loop is played to the ports the source is already connected to.

Requirements
------------

-  Python 2.7
-  PyQt4 at least version 4.11.1
-  pyalsa

Usage
-----

There is not an installation procedure yet, just run the script in the
main repository directory:

::

    $ ./moloop

After that, MOL will be in your system tray, from there you can
enable/disable event listening, quit MOL or stop a playing loop (this
will reset the buffer, and MOL will be ready to listen to a new loop).

Future
------

-  MIDI control for enabling/disabling/stopping.
-  MIDI input/output device selection/filtering.
-  JACK support?
