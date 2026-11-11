@echo off
rem Wireshark extcap wrapper for Windows: runs the Python script next to this file.
rem Requires Python 3 in PATH (py launcher) and pyserial (py -m pip install pyserial).
py -3 "%~dp0xn297l_sniffer.py" %*
