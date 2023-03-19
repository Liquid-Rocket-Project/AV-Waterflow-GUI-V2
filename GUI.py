"""
Author: Nick Fan
Date: 3/17/2023
Description: GUI program to run waterflow testing.
To be paired with Waterflow-Testbench Firmware.
"""


import re
import serial
import serial.tools.list_ports
import sys
import time

from PyQt6.QtCore import Qt, QDateTime
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QWidget,
    QLineEdit,
    QTextEdit,
    QSpacerItem,
    QMessageBox,
    QInputDialog,
)
from queue import Empty, Queue
from threading import Timer, Thread

# SETTINGS --------------------------------------------------------------------|
BAUDRATE = 9600
DATE_TIME_FORMAT = "MM/dd/yyyy | hh:mm:ss:zzz -> "

# CONSTANTS -------------------------------------------------------------------|
MIN_SIZE = 500
LINE_HEIGHT = 35
SETTING_WIDTH = 150
BOX_SIZE = 300
WINDOW_ICON_P = "./src/octoLogo.png"
ERROR_ICON_P = "./src/errorIcon.png"
WARNING_ICON_P = "./src/warningIcon.png"
WARNING = 0
ERROR = 1
MESSAGE_LABELS = ("Warning", "Error")
DATE = QDateTime.currentDateTime().toString("MM-dd-yy")
START_TIME = QDateTime.currentDateTime().toString("MM-dd-yy-hh-mm")


# SERIAL HELPER ---------------------------------------------------------------|
class SerialComm:
    """Serial Com Manager."""

    def __init__(self, com: str, baudrate: int) -> None:
        self.port = com
        self.baudrate = baudrate
        self.connection = serial.Serial(self.port, self.baudrate, timeout=0.05)

    def receiveMessage(self) -> str:
        """Read from serial com if there is data in."""
        if not self.connection.is_open:
            self.connection.open()
        try:
            data = str(self.connection.readall().decode("ascii"))
            if data:
                return data
        except serial.SerialException:
            pass
        return ""

    def readEolLine(self) -> str:
        """Reads line specifically using LF for eol.

        Reference: lou
        https://stackoverflow.com/questions/16470903/pyserial-2-6-specify-end-of-line-in-readline
        """
        eol = b'\n'
        eolLen = len(eol)
        line = bytearray()
        while True:
            c = self.connection.read(1)
            if c:
                line += c
                if line[-eolLen:] == eol:
                    break
            else:
                break
        return str(line.decode("ascii"))

    def sendMessage(self, message: str) -> bool:
        """Write to serial com."""
        if not self.connection.is_open:
            self.connection.open()
        try:
            self.connection.write(message.encode("utf-8"))
            time.sleep(.002)
            return True
        except serial.SerialException:
            return False

    def close(self):
        """Close connection."""
        self.connection.close()


# MAIN WINDOW -----------------------------------------------------------------|
class WaterflowGUI(QMainWindow):
    """Waterflow GUI for RPM"""

    def __init__(self) -> None:
        """Constructs a new WF GUI window."""
        super().__init__()
        self.setWindowTitle("WaterFlow Control")
        self.setWindowIcon(QIcon(WINDOW_ICON_P))
        self.setMinimumSize(MIN_SIZE * 2, MIN_SIZE)
        self.generalLayout = QGridLayout()
        centralWidget = QWidget()
        centralWidget.setLayout(self.generalLayout)
        self.setCentralWidget(centralWidget)

        self._createSettings()
        self._createDisplayArea()

        # exit program if setup is unsuccessful
        if not self._selectPort() or not self._verifySetupReady():
            sys.exit(1)

        self.serialConnection = self._setupConnection(self.port, BAUDRATE)
        self.serialQueue = Queue()
        self.dataQueue = Queue()

        self.inPreset = False
        self._displayPrint(
            "NEW SESSION: "
            + QDateTime.currentDateTime().toString("hh:mm:ss")
        )
    
    # SERIAL FUNCTIONS

    def _selectPort(self) -> bool:
        """Checks for available ports and asks for a selection."""
        ports = serial.tools.list_ports.comports()
        if len(ports) < 1:
            self.createMessageBox(
                ERROR, 
                "No COM ports available.\n"
                +"Please plug in devices before starting."
            )
            return False

        selection, ok = QInputDialog().getItem(
            self.centralWidget(),
            "COM select",
            "Select a port:",
            [f"{desc}" for name, desc, hwid in ports]
        )
        if not ok:
            return False

        self.port = str(re.findall(r"COM[0-9]+", selection)[0])  # get port

        return True

    def _verifySetupReady(self) -> bool:
        """Double checks to verify it is safe to initialize valve connection."""
        conf = QMessageBox(
            QMessageBox.Icon.Warning,
            "Setup Confirmation",
            "Setup will cause the valves to open and close.\n"
            + "Continue if this is safe, or cancel to exit.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            self.centralWidget(),
        )
        ok = conf.exec()

        if ok == QMessageBox.StandardButton.Cancel:  # check ok/cancel
            return False

        return True

    def _setupConnection(self, selectedPort: str, baud: int) -> SerialComm:
        """Sets up and returns a serial comm."""
        ser = SerialComm(selectedPort, baud)
        ser.sendMessage("12345" + "\n")

        # ensure messages are sending
        valid = False
        while not valid:
            ser.sendMessage("12345" + "\n")
            rec = ser.receiveMessage()
            if str(rec)[:10] != "Toggle PIN":  # verify pin toggle message
                ser.sendMessage("12345" + "\n")
                continue
            valid = True

        return ser

    def _presetRun(self) -> None:
        """Starts a preset toggle/read thread with a timeout."""
        # validate inputs
        if not self.inPreset:
            try:
                seconds = float(self.timeInterval.text())
            except ValueError:
                self.createMessageBox(ERROR, "Time must be a number.")
                return

            # info log
            log = (
                f"{QDateTime.currentDateTime().toString(DATE_TIME_FORMAT)}\n"
                + f"Testname: {self.testName.text()}\n"
                + f"Interval (sec): {self.timeInterval.text()}\n"
                + f"Pins: {self.toggledPins.text()}"
            )
            self._displayPrint(log)

            pins = self.toggledPins.text()
            readThread = Thread(target=self._readIn, args=(pins, seconds,))
            readThread.start()

    def _readIn(self, pins: str, seconds: float) -> None:
        """Reads in from serial until timer runs out."""
        message = pins + "\n"
        self.inPreset = True

        self.serialConnection.sendMessage(message)
        # start timeout
        timeout = Timer(seconds, function=self._endPreset)
        timeout.start()

        # read serial
        while True:
            try:
                cont = self.serialQueue.get(block=False)
                if not cont:
                    # toggle
                    self.serialConnection.sendMessage(pins + "\n")
                    flush = self.serialConnection.receiveMessage()
                    for line in flush.split("\n"):
                        self._displayPrint(self._strFormat(line))

                    # cleanup queue
                    while True:
                        try:
                            self.serialQueue.get(block=False)
                        except Empty:
                            break

                    # exit
                    self.inPreset = False
                    break
            except Empty:
                received = self.serialConnection.readEolLine()
                if not received:
                    continue
                self._displayPrint(self._strFormat(received))

    def _endPreset(self) -> None:
        """Sends stop message to threading queue."""
        if self.inPreset:
            self.serialQueue.put(False)

    def _strFormat(self, string: str) -> str:
        """Returns formatted string for monitor display."""
        return QDateTime.currentDateTime().toString(DATE_TIME_FORMAT) + string.strip()
    
    def _displayPrint(self, output: str) -> None:
        self.monitor.append(output)
        self.monitor.verticalScrollBar().setValue(self.monitor.verticalScrollBar().maximum())
        with open(f"./log/system/{DATE}.txt", "a") as sysLog:
            sysLog.write(output + "\n")

    # Display functions

    @staticmethod
    def createMessageBox(boxType: int, message: str) -> None:
        """Creates error message popup with indicated message."""
        box = QMessageBox()
        if boxType == ERROR:
            box.setWindowIcon(QIcon(ERROR_ICON_P))
        else:
            box.setWindowIcon(QIcon(WARNING_ICON_P))
        box.setWindowTitle(MESSAGE_LABELS[boxType])
        box.setText(f"{MESSAGE_LABELS[boxType]}: {message}")
        box.exec()

    def closeEvent(self, event) -> None:
        """Adds additional functions when closing window."""
        self._displayPrint(
            "-----------------------------------------------------------------------"
        )
        if self.serialConnection.connection.is_open:
            self.serialConnection.close()
    
    def _enterData(self) -> None:
        """Creates input dialog box accepts data."""
        measurement, ok = QInputDialog().getText(
            self.centralWidget(),
            "Data Input", 
            "Please enter datatype and data: ",
        )
        if not ok:
            return
        self._displayPrint(measurement)

    def _createDisplayArea(self) -> None:
        """Create text display area."""
        self.monitor = QTextEdit()
        self.monitor.ensureCursorVisible()
        self.monitor.setReadOnly(True)
        self.monitor.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.generalLayout.addWidget(self.monitor, 0, 0)

    def _createSettings(self):
        """Create right side settings layout."""
        # area setup
        self.settings = QGridLayout()
        title = QLabel("Presets: ")
        bottomSpacer = QSpacerItem(10, 250)

        # input boxes
        self.timeInterval = QLineEdit()
        self.timeInterval.setMaximumHeight(LINE_HEIGHT)
        self.timeInterval.setMaximumWidth(SETTING_WIDTH)
        self.toggledPins = QLineEdit()
        self.toggledPins.setMaximumHeight(LINE_HEIGHT)
        self.toggledPins.setMaximumWidth(SETTING_WIDTH)
        self.measurementUnits = QLineEdit()
        #self.measurementUnits.setMaximumHeight(LINE_HEIGHT)
        #self.measurementUnits.setMaximumWidth(SETTING_WIDTH)
        self.testName = QLineEdit()
        self.testName.setMaximumHeight(LINE_HEIGHT)
        self.testName.setMaximumWidth(2 * SETTING_WIDTH + 10)

        # input buttons
        self.startPresetButton = QPushButton("Start Preset")
        self.startPresetButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.startPresetButton.clicked.connect(self._presetRun)
        self.cancelPresetButton = QPushButton("Cancel Preset")
        self.cancelPresetButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cancelPresetButton.clicked.connect(self._endPreset)
        self.enterDataButton = QPushButton("Enter Data")
        self.enterDataButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.enterDataButton.clicked.connect(self._enterData)

        # settings layout
        self.settings.addWidget(title, 1, 0)
        self.settings.addWidget(QLabel("Interval (sec): "), 2, 0)
        self.settings.addWidget(QLabel("Pins: "), 2, 1)
        self.settings.addWidget(self.timeInterval, 3, 0)
        self.settings.addWidget(self.toggledPins, 3, 1)
        self.settings.addWidget(QLabel("Test Name: "), 4, 0)
        self.settings.addWidget(self.testName, 5, 0, 1, 2)
        self.settings.addWidget(self.startPresetButton, 6, 0)
        self.settings.addWidget(self.cancelPresetButton, 6, 1)
        self.settings.addWidget(self.enterDataButton, 8, 0, 1, 2)
        self.settings.addItem(bottomSpacer, 9, 0)
        self.generalLayout.addLayout(self.settings, 0, 1)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    waterflowDisplay = WaterflowGUI()
    waterflowDisplay.show()
    sys.exit(app.exec())
