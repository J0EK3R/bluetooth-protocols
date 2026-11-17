"""
Wireshark extcap control channel (interface toolbar).

Wireshark passes two pipes to the extcap program: --extcap-control-in (the
extcap reads user input from the toolbar) and --extcap-control-out (the
extcap writes updates for the toolbar). Messages in both directions have the
same frame format:

    'T'  | length (3 bytes, big endian) | control number (1) | command (1) | payload
    sync   length counts control number + command + payload

This module only does the framing and the transport (a reader and a writer
thread, so a slow or absent Wireshark never blocks the capture). What the
controls mean is defined by the interface in xn297l_sniffer.py.
"""

import queue
import threading

SYNC = b"T"

# Commands (values of the extcap control protocol)
CMD_INITIALIZED = 0     # Wireshark -> extcap: toolbar is ready
CMD_SET = 1             # Wireshark -> extcap: user changed a control / extcap -> Wireshark: set value
CMD_ADD = 2             # extcap -> Wireshark: add an entry to a selector ("value\0display")
CMD_REMOVE = 3          # extcap -> Wireshark: remove a selector entry (payload = value)
CMD_ENABLE = 4          # extcap -> Wireshark: enable a control
CMD_DISABLE = 5         # extcap -> Wireshark: disable a control
CMD_STATUSBAR = 6       # extcap -> Wireshark: text in the status bar
CMD_INFORMATION = 7     # extcap -> Wireshark: information dialog
CMD_WARNING = 8         # extcap -> Wireshark: warning dialog
CMD_ERROR = 9           # extcap -> Wireshark: error dialog

HEADER_LEN = 6          # 'T' + 3 byte length + control number + command
LENGTH_MAX = 0xFFFFFF   # the length field has 3 bytes


def encode_message(control: int, command: int, payload=b"") -> bytes:
    """Build one control message. A str payload is encoded as UTF-8."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    length = len(payload) + 2           # control number and command are part of the length
    if length > LENGTH_MAX:
        raise ValueError("control message too long")
    return SYNC + length.to_bytes(3, "big") + bytes([control & 0xFF, command & 0xFF]) + payload


def add_entry_message(control: int, value: str, display: str) -> bytes:
    """ADD message for a selector: payload is 'value', a NUL byte and the display text."""
    return encode_message(control, CMD_ADD, value + "\0" + display)


class MessageDecoder:
    """Incremental decoder: feed() raw bytes, get complete messages back.

    A message is a tuple (control, command, payload). Bytes that do not start
    a frame (no 'T') are skipped so a corrupted stream recovers.
    """

    def __init__(self):
        self.buffer = b""

    def feed(self, data: bytes) -> list:
        self.buffer += data
        messages = []
        while True:
            start = self.buffer.find(SYNC)
            if start < 0:
                self.buffer = b""                   # no frame start in the buffer
                break
            if start > 0:
                self.buffer = self.buffer[start:]   # drop garbage before the frame
            if len(self.buffer) < HEADER_LEN:
                break                               # header not complete yet
            length = int.from_bytes(self.buffer[1:4], "big")
            if length < 2:                          # invalid length: skip this 'T'
                self.buffer = self.buffer[1:]
                continue
            total = 4 + length
            if len(self.buffer) < total:
                break                               # payload not complete yet
            messages.append((self.buffer[4], self.buffer[5], self.buffer[6:total]))
            self.buffer = self.buffer[total:]
        return messages


class ControlChannel:
    """Reader and writer threads for the two control pipes.

    incoming: queue of (control, command, payload) tuples from Wireshark.
    send():   queue a message for Wireshark (never blocks).
    Both pipes are opened in the threads because open() blocks until Wireshark
    has opened its end.
    """

    def __init__(self, in_path: str, out_path: str):
        self.in_path = in_path
        self.out_path = out_path
        self.incoming = queue.Queue()
        self._outgoing = queue.Queue()
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._read_loop, daemon=True),
            threading.Thread(target=self._write_loop, daemon=True),
        ]

    def start(self) -> None:
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._outgoing.put(None)            # wake the writer

    def send(self, control: int, command: int, payload=b"") -> None:
        self._outgoing.put(encode_message(control, command, payload))

    def send_raw(self, message: bytes) -> None:
        self._outgoing.put(message)

    def poll(self):
        """Next message from Wireshark or None."""
        try:
            return self.incoming.get_nowait()
        except queue.Empty:
            return None

    def _read_loop(self) -> None:
        decoder = MessageDecoder()
        try:
            with open(self.in_path, "rb", buffering=0) as pipe:
                while not self._stop.is_set():
                    data = pipe.read(4096)
                    if not data:                # EOF: Wireshark closed the pipe
                        break
                    for message in decoder.feed(data):
                        self.incoming.put(message)
        except OSError:
            pass                                # pipe gone: capture continues without toolbar

    def _write_loop(self) -> None:
        try:
            with open(self.out_path, "wb", buffering=0) as pipe:
                while not self._stop.is_set():
                    message = self._outgoing.get()
                    if message is None:
                        break
                    pipe.write(message)
        except OSError:
            pass                                # pipe gone
