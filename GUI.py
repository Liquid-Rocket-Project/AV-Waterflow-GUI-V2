"""
Author: Nick Fan
Date: 3/17/2023
Description: GUI program to run waterflow testing.
To be paired with Waterflow-Testbench Firmware.
"""


import re
import sys
import time
from threading import Timer

import serial
import serial.tools.list_ports
from PyQt6.QtCore import QDateTime, QObject, Qt, QThread, QMutex, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QApplication, QGridLayout, QInputDialog, QLabel,
                             QLineEdit, QMainWindow, QMessageBox, QPushButton,
                             QSpacerItem, QTextEdit, QWidget)

# SETTINGS --------------------------------------------------------------------|
BAUDRATE = 9600
DATE_TIME_FORMAT = "MM/dd/yyyy | hh:mm:ss:zzz -> "
PIN_INIT = "12345"

# CONSTANTS -------------------------------------------------------------------|
DATE = QDateTime.currentDateTime().toString("MM-dd-yy")
START_TIME = QDateTime.currentDateTime().toString("MM-dd-yy-hh-mm")
SYS_LOG_FILE = f"./log/system/{DATE}.txt"
WINDOW_ICON_P = "./src/octoLogo.png"
ERROR_ICON_P = "./src/errorIcon.png"
WARNING_ICON_P = "./src/warningIcon.png"

SIZE = 500
LINE_HEIGHT = 35
SETTING_WIDTH = 150
BOX_SIZE = 300
WARNING = 0
ERROR = 1
MESSAGE_LABELS = ("Warning", "Error")

# SERIAL HELPER ---------------------------------------------------------------|
class SerialComm:
    """Serial Com Manager."""

    def __init__(self, com: str, baudrate: int) -> None:
        """Creates new serial com manager.

        Args:
            com(str): the COM port
            baudrate(int): the baudrate
        """
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
        eol = b"\n"
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
        """Writes to serial com."""
        if not self.connection.is_open:
            self.connection.open()
        try:
            self.connection.write(message.encode("utf-8"))
            time.sleep(0.002)
            return True
        except serial.SerialException:
            return False

    def close(self):
        """Closes the com connection."""
        self.connection.close()


class SerialWorker(QObject):
    """GUI Serial Manager Thread."""

    msg = pyqtSignal(str)
    cleanup = pyqtSignal()

    def __init__(self, connection: SerialComm, lock: QMutex, pins: str, parent=None) -> None:
        """Constructs new Serial Worker.

        Args:
            connection(SerialComm): the serial connection to use
            pins(str): pins to toggle
            parent(QObject): optional parent
        """
        super().__init__(parent)
        self.serialConnection = connection
        self.pins = pins
        self.mutex = lock
        self.program = True

    def setPins(self, newPins: str) -> None:
        """Sets new pins.

        Args:
            newPins(str): a new set of pins to toggle.
        """
        self.pins = newPins

    def run(self) -> None:
        """Sends initial toggle and continuously reads
        until indicated to stop, then toggles again."""
        # read serial
        while self.program:
            if self.mutex.tryLock():
                received = self.serialConnection.readEolLine()
                time.sleep(0.05)
                self.mutex.unlock()
                time.sleep(0.02)
                if not received:
                    continue
                self.msg.emit(received)
        self.cleanup.emit()

    def sendToggle(self, pins: str | None = None) -> None:
        """Sends message and indicates preset state."""
        if pins:
            message = pins + "\n"
        else:
            message = self.pins + "\n"
        while True:
            if self.mutex.tryLock():
                self.serialConnection.sendMessage(message)
                self.mutex.unlock()
                break


# MAIN WINDOW -----------------------------------------------------------------|
class WaterflowGUI(QMainWindow):
    """Waterflow GUI for RPM"""

    serialInterrupt = pyqtSignal()

    def __init__(self) -> None:
        """Constructs a new Waterflow GUI window."""
        super().__init__()
        self.setWindowTitle("WaterFlow Control")
        self.setWindowIcon(QIcon(WINDOW_ICON_P))
        self.setFixedSize(SIZE * 2, SIZE)
        self.generalLayout = QGridLayout()
        centralWidget = QWidget()
        centralWidget.setLayout(self.generalLayout)
        self.setCentralWidget(centralWidget)

        self.createSettings()
        self.createDisplayArea()

        # exit program if setup is unsuccessful
        if not self.selectPort() or not self.verifySetupReady():
            sys.exit(1)

        # setup and connect serial with serial manager thread
        self.threadingSetup()

        self.inPreset = False
        self.displayPrint(
            "NEW SESSION: " + QDateTime.currentDateTime().toString("hh:mm:ss"),
            reformat=False
        )

    # SERIAL FUNCTIONS

    def threadingSetup(self) -> None:
        """Sets up threading, serial worker and signals/slots."""
        self.serialThread = QThread()
        self.serialConnection = self.setupConnection(self.port, BAUDRATE)
        self.serialLock = QMutex()
        self.serialWorker = SerialWorker(self.serialConnection, self.serialLock, "")
        self.serialWorker.moveToThread(self.serialThread)
        self.serialThread.started.connect(self.serialWorker.run)
        self.serialWorker.cleanup.connect(self.serialThread.quit)
        self.serialWorker.msg.connect(self.displayPrint)
        self.serialInterrupt.connect(self.endPreset)
        self.serialThread.start()

    def selectPort(self) -> bool:
        """Checks for available ports and asks for a selection.

        Returns:
            bool: True setup is successful, False otherwise
        """
        ports = serial.tools.list_ports.comports()
        if len(ports) < 1:
            self.createMessageBox(
                ERROR,
                "No COM ports available.\nPlease plug in devices before starting.",
            )
            return False

        selection, ok = QInputDialog().getItem(
            self.centralWidget(),
            "COM select",
            "Select a port:",
            [f"{desc}" for name, desc, hwid in ports],
        )
        if not ok:
            return False

        self.port = str(re.findall(r"COM[0-9]+", selection)[0])  # get port

        return True

    def verifySetupReady(self) -> bool:
        """Double checks to verify it is safe to initialize valve connection.

        Returns:
            bool: True if the user is ready for setup, false if not.
        """
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

    def setupConnection(self, selectedPort: str, baud: int) -> SerialComm:
        """Sets up and returns a serial comm.

        Args:
            seletedPort(str): the selected COM port
            baud(int): the desired baudrate
        Returns:
            SerialComm: a serial connection object
        """
        ser = SerialComm(selectedPort, baud)
        ser.sendMessage(PIN_INIT + "\n")

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

    def presetRun(self) -> None:
        """Starts a preset toggle/read thread with a timeout."""
        if not self.inPreset:
            # validate inputs
            try:
                seconds = float(self.timeInterval.text())
            except ValueError:
                self.createMessageBox(ERROR, "Time must be a number.")
                return
            pins = self.toggledPins.text()
            if len(set(pins)) < len(pins):
                self.createMessageBox(ERROR, "Duplicate pin detected - please try again.")
                return
            self.displayAccessEnabled(False)
            # info log
            log = (
                f"\n{QDateTime.currentDateTime().toString(DATE_TIME_FORMAT)}\n"
                + f"Testname: {self.testName.text()}\n"
                + f"Interval (sec): {self.timeInterval.text()}\n"
                + f"Pins: {self.toggledPins.text()}"
            )
            self.displayPrint(log, reformat=False)

            # thread timeout and reading
            self.serialWorker.setPins(self.toggledPins.text())
            self.inPreset = True
            self.serialWorker.sendToggle()
            self.timeout = Timer(seconds, function=self.sendInterrupt)
            self.timeout.start()

    def endPreset(self) -> None:
        """Stops threading loop."""
        if self.inPreset:
            self.serialWorker.sendToggle()
            self.timeout.cancel()
            self.inPreset = False
            self.enterData()
            self.displayAccessEnabled(True)

    def sendSpecificToggle(self) -> None:
        self.serialWorker.sendToggle(self.specificCommand.text())

    def sendInterrupt(self) -> None:
        """Emits serial stop signal."""
        self.serialInterrupt.emit()

    def displayAccessEnabled(self, access: bool) -> None:
        """Enables or disables display access.

        Args:
            access(bool): True to enable display access, false to disable.
        """
        self.enterDataButton.setEnabled(access)
        self.startPresetButton.setEnabled(access)
        self.sendCommandButton.setEnabled(access)
        self.testName.setReadOnly(not access)
        self.timeInterval.setReadOnly(not access)
        self.toggledPins.setReadOnly(not access)

    def strFormat(self, string: str) -> str:
        """Returns formatted string for monitor display.

        Args:
            string(str): the string to format

        Returns:
            str: the formatted string
        """
        return QDateTime.currentDateTime().toString(DATE_TIME_FORMAT) + string.strip()

    @pyqtSlot(str)
    def displayPrint(self, string: str, reformat=True) -> None:
        """Displays to monitor and logs data.

        Args:
            string(str): the string to display and log
        """
        if reformat:
            string = self.strFormat(string)
        self.monitor.append(string)
        self.monitor.verticalScrollBar().setValue(
            self.monitor.verticalScrollBar().maximum()
        )
        with open(SYS_LOG_FILE, "a") as sysLog:
            sysLog.write(string + "\n")

    # Display functions

    @staticmethod
    def createMessageBox(boxType: int, message: str) -> None:
        """Creates error message popup with indicated message.

        Args:
            boxType(int): the type of message box to create
            message(str): the message to display in the box
        """
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
        with open(SYS_LOG_FILE, "a") as sysLog:
            sysLog.write(
                "---------------------------------------------------------------------------\n"
            )
        self.serialWorker.program = False
        time.sleep(0.1)
        if self.serialConnection.connection.is_open:
            self.serialConnection.close()

    def enterData(self) -> None:
        """Creates input dialog box accepts data."""
        measurement, ok = QInputDialog().getText(
            self.centralWidget(),
            "Data Input",
            "Please enter datatype and data: ",
        )
        if not ok:
            return
        self.displayPrint(measurement)

    def createDisplayArea(self) -> None:
        """Create text display area."""
        self.monitor = QTextEdit()
        self.monitor.ensureCursorVisible()
        self.monitor.setReadOnly(True)
        self.monitor.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.generalLayout.addWidget(self.monitor, 0, 0)

    @staticmethod
    def createTextField(width: int, height: int) -> QLineEdit:
        label = QLineEdit()
        label.setMaximumSize(width, height)
        return label

    def createSettings(self):
        """Create right side settings layout."""
        # area setup
        self.settings = QGridLayout()
        title = QLabel("Presets: ")
        bottomSpacer = QSpacerItem(10, 150)

        # input boxes
        self.timeInterval = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)
        self.toggledPins = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)
        self.testName = self.createTextField(2 * SETTING_WIDTH + 10, LINE_HEIGHT)
        self.specificCommand = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)

        # pin labels
        self.pin1 = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)
        self.pin2 = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)
        self.pin3 = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)
        self.pin4 = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)
        self.pin5 = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)

        # input buttons
        self.startPresetButton = QPushButton("Start Preset")
        self.startPresetButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.startPresetButton.clicked.connect(self.presetRun)
        self.cancelPresetButton = QPushButton("Cancel Preset")
        self.cancelPresetButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cancelPresetButton.clicked.connect(self.sendInterrupt)
        self.enterDataButton = QPushButton("Enter Data")
        self.enterDataButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.enterDataButton.clicked.connect(self.enterData)
        self.sendCommandButton = QPushButton("Send Command")
        self.sendCommandButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sendCommandButton.clicked.connect(self.sendSpecificToggle)

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
        self.settings.addWidget(QLabel("Toggle Pins: "), 9, 0)
        self.settings.addWidget(self.specificCommand, 10, 0)
        self.settings.addWidget(self.sendCommandButton, 11, 0)
        self.settings.addWidget(QLabel("Pin Control Equivalencies: "), 12, 0)
        self.settings.addWidget(QLabel("Pin 1: "), 13, 0)
        self.settings.addWidget(self.pin1, 13, 1)
        self.settings.addWidget(QLabel("Pin 2: "), 14, 0)
        self.settings.addWidget(self.pin2, 14, 1)
        self.settings.addWidget(QLabel("Pin 3: "), 15, 0)
        self.settings.addWidget(self.pin3, 15, 1)
        self.settings.addWidget(QLabel("Pin 4: "), 16, 0)
        self.settings.addWidget(self.pin4, 16, 1)
        self.settings.addWidget(QLabel("Pin 5: "), 17, 0)
        self.settings.addWidget(self.pin5, 17, 1)
        self.settings.addItem(bottomSpacer, 18, 0)
        self.generalLayout.addLayout(self.settings, 0, 1)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    waterflowDisplay = WaterflowGUI()
    waterflowDisplay.show()
    sys.exit(app.exec())
