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
from PyQt6.QtCore import (QDateTime, QMutex, QObject, Qt, QThread,
                          pyqtSignal, pyqtSlot)
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (QApplication, QGridLayout, QInputDialog, QLabel,
                             QLineEdit, QMainWindow, QMessageBox, QPushButton,
                             QSpacerItem, QTextEdit, QWidget)

# SETTINGS --------------------------------------------------------------------|
BAUDRATES = [9600, 115200]
DATE_TIME_FORMAT = "MM/dd/yyyy | hh:mm:ss:zzz -> "
PT_DATA_FLAG = "d"  # not used in firmware right now

# Firmware tags
PRESSURE_TAG = ""  # no tag rn
PRESSURE_SEP = ", "
VALVE_TAG = "Toggle PIN"
VALVE_SEP = " "

# Software hashes
PIN = "PIN"
PRESSURE = "PRESS"

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

# DATA DISPLAY HANDLERS -------------------------------------------------------|
class PinFormat:
    """String formatter for live display."""
    
    def __init__(self, pin: str, valveState: str = "CLOSED", pressure: str = "n/a") -> None:
        self.num = pin
        self.valve = valveState
        self.pressure = pressure

    def editValveState(self, valveState: str) -> None:
        """Edits the valve state.
        
        Args:
            valveState(str): the valve state data
        """
        self.valve = valveState

    def editPressure(self, pressure: str) -> None:
        """Edits the pressure.
        
        Args:
            pressure(str): the pressure state data
        """
        self.pressure = pressure

    def __str__(self) -> str:
        return f"Pin {self.num}: {self.valve} | {self.pressure} PSI"

class ValveStateUpdater:
    """Valve state updater interface."""

    def __init__(self, label: QLabel, format: PinFormat) -> None:
        self.label = label
        self.format = format
        self.label.setText(str(self.format))

    def update(self, valveState: str) -> None:
        """Duck typed update function to update valve state.
        
        Args:
            valveState(str): the valve state value
        """
        if valveState == "1":
            self.format.editValveState("OPEN")
            self.label.setStyleSheet("color: green")
        else:
            self.format.editValveState("CLOSED")
            self.label.setStyleSheet("color: black")
        self.label.setText(str(self.format))

class PressureUpdater:
    """Valve pressure updater interface."""

    def __init__(self, label: QLabel, format: PinFormat) -> None:
        self.label = label
        self.format = format
        self.label.setText(str(self.format))
    
    def update(self, pressure: str) -> None:
        """Duck typed update function to update valve pressure.
        
        Args:
            pressure(str): the pressure state value
        """
        self.format.editPressure(pressure)
        self.label.setText(str(self.format))

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

        EoL readline by: lou under CC BY-SA 3.0
        src: https://stackoverflow.com/questions/16470903/pyserial-2-6-specify-end-of-line-in-readline
        Changes have been made to adjust for integration in this program.
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
    error = pyqtSignal()

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
        self.pins = newPins + PT_DATA_FLAG

    def run(self) -> None:
        """Sends initial toggle and continuously reads
        until indicated to stop, then toggles again."""
        # read serial
        error = False
        while self.program:
            if not error:
                if self.mutex.tryLock():

                    try:
                        received = self.serialConnection.readEolLine()
                    except (serial.SerialException, UnicodeDecodeError):
                        self.error.emit()
                        error = True
                        received = None

                    time.sleep(0.05)
                    self.mutex.unlock()
                    time.sleep(0.02)
                    if not received:
                        continue
                    self.msg.emit(received)
    
        self.cleanup.emit()

    def sendToggle(self, pins: str | None = None) -> None:
        """Sends message, which by default is the pins instance variable.
        
        Args:
            pins(str): optional argument to indicate pins to toggle.
        """
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
        if not self.selectPort() or not self.selectBaud() or not self.verifySetupReady():
            sys.exit(1)

        # setup and connect serial with serial manager thread
        self.threadingSetup()

        self.inPreset = False
        self.displayPrint(
            "NEW SESSION: " + QDateTime.currentDateTime().toString("hh:mm:ss"),
            reformat=False
        )

        self.screenAccess = True
        self.toggleScreenLock()

    # SERIAL FUNCTIONS

    def threadingSetup(self) -> None:
        """Sets up threading, serial worker and signals/slots.
        
        *Serial Window Core
        """
        self.serialThread = QThread()
        self.serialConnection = self.setupConnection(self.port, self.baud)
        self.serialLock = QMutex()
        self.serialWorker = SerialWorker(self.serialConnection, self.serialLock, "")
        self.serialWorker.moveToThread(self.serialThread)
        self.serialThread.started.connect(self.serialWorker.run)
        self.serialWorker.cleanup.connect(self.serialThread.quit)
        self.serialWorker.error.connect(self.errorExit)
        self.serialWorker.msg.connect(self.displayControl)
        self.serialInterrupt.connect(self.endPreset)
        self.serialThread.start()

    def selectPort(self) -> bool:
        """Checks for available ports and asks for a selection.

        Returns:
            bool: True setup is successful, False otherwise
        
        *Serial Window Core
        """
        ports = serial.tools.list_ports.comports()
        if len(ports) < 1:
            self.createMessageBox(
                ERROR,
                "No COM ports available.\nPlease plug in devices before starting.",
            )
            return False
        
        warning = (
            "ATTENTION:\nWhen selecting a port, look for \"Arduino\" or \"Serial-USB\" "
            + "If you do not see an option like this, please cancel and check your USB connection."
        )
        conf = QMessageBox(
            QMessageBox.Icon.Warning,
            "Setup Confirmation",
            warning,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            self.centralWidget(),
        )

        conf.exec()

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

    def selectBaud(self) -> bool:
        """Asks for selection of a baudrate.

        Returns:
            bool: True setup is successful, False otherwise
        """
        selection, ok = QInputDialog().getItem(
            self.centralWidget(),
            "Baudrate select", 
            "Select a baudrate:",
            [str(rate) for rate in BAUDRATES],
        )

        if not ok:
            return False
        try:
            self.baud = int(selection)
        except ValueError:
            error = QMessageBox(
                QMessageBox.Icon.Critical,
                "Setup Error",
                "Setup error detected! Exiting program.",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                self.centralWidget(),
            )
            error.exec()
            return False
        return True

    def verifySetupReady(self) -> bool:
        """Double checks to verify it is safe to initialize valve connection.

        Returns:
            bool: True if the user is ready for setup, false if not.
        
        *Serial Window Core
        """
        warning = (
            "Please be aware that clicking buttons once "
            + "the GUI initiates may cause valves to open. "
            + "Do NOT continue unless ALL valve operations are safe."
        )
        conf = QMessageBox(
            QMessageBox.Icon.Warning,
            "Setup Confirmation",
            warning,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            self.centralWidget(),
        )
        conf.setDefaultButton(QMessageBox.StandardButton.Cancel)
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
        
        *Serial Window Core
        """
        ser = SerialComm(selectedPort, baud)
        return ser

    def errorExit(self) -> None:
        """Starts exit sequence on handling of a serial exception."""
        self.createMessageBox(ERROR, "Serial exception detected! Program will now close.")
        self.close()

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
            self.displayAccessPresetToggle(False)
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
        """Stops preset loop."""
        if self.inPreset:
            self.serialWorker.sendToggle()
            self.timeout.cancel()
            self.inPreset = False
            self.enterData()
            self.displayAccessPresetToggle(True)

    def sendSpecificToggle(self) -> None:
        """Sends a specific message to toggle without starting a preset.
        
        *Serial Window Core
        """
        command = self.specificCommand.text()
        if len(set(command)) < len(command):
            self.createMessageBox(ERROR, "Duplicate pin detected - please try again.")
            return
        self.serialWorker.sendToggle(command)

    def sendInterrupt(self) -> None:
        """Emits serial stop signal.
        
        *Serial Window Core
        """
        self.serialInterrupt.emit()

    def displayAccessPresetToggle(self, access: bool) -> None:
        """Enables or disables display access.

        Args:
            access(bool): True to enable display access, false to disable.
        """
        self.enterDataButton.setEnabled(access)
        self.startPresetButton.setEnabled(access)
        self.sendCommandButton.setEnabled(access)
        self.screenLock.setEnabled(access)
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

    def displayPrint(self, string: str, reformat=True) -> None:
        """Displays to monitor and logs data.

        Args:
            string(str): the string to display and log
            reformat(bool | None): add strFormat if True, otherwise do not
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
        self.monitor.setReadOnly(True)
        self.monitor.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.generalLayout.addWidget(self.monitor, 0, 0)

    def toggleScreenLock(self) -> None:
        """Locks or unlocks all fields on the screen, including buttons and text."""
        self.screenAccess = not self.screenAccess
        self.enterDataButton.setEnabled(self.screenAccess)
        self.startPresetButton.setEnabled(self.screenAccess)
        self.sendCommandButton.setEnabled(self.screenAccess)
        self.cancelPresetButton.setEnabled(self.screenAccess)
        self.testName.setReadOnly(not self.screenAccess)
        self.timeInterval.setReadOnly(not self.screenAccess)
        self.toggledPins.setReadOnly(not self.screenAccess)
        self.specificCommand.setReadOnly(not self.screenAccess)

        self.pin1.setReadOnly(not self.screenAccess)
        self.pin2.setReadOnly(not self.screenAccess)
        self.pin3.setReadOnly(not self.screenAccess)
        self.pin4.setReadOnly(not self.screenAccess)
        self.pin5.setReadOnly(not self.screenAccess)

    def parseData(self, data: str) -> list[tuple]:
        """Parses incoming data to destination/value pairs.

        Args:
            data(str): the incoming data
        
        Returns:
            list[tuple]: a list of tuples with destination/value pairs
        
        *Serial Window Core
        """
        if VALVE_TAG in data:
            pin, value = data.strip(VALVE_TAG).split(VALVE_SEP)
            return [(PIN + pin, value)]
        if PRESSURE_SEP in data:
            readings = []
            for i, val in enumerate(data.split(PRESSURE_SEP)):
                readings.append((f"{PRESSURE}{i + 1}", val))
            return readings
        return []

    def updateDisplay(self, dataset: list) -> None:
        """Updates display values in the window dictionaries.
        
        Args:
            dataset(list): list of parsed data in the format destination, value
        
        *Serial Window Core
        """
        for dest, value in dataset:
            try:
                self.dynamicLabels[dest].update(value.strip())
            except KeyError:
                continue

    @pyqtSlot(str)
    def displayControl(self, string: str) -> None:
        """Prints to display monitor, parses data, and updates live labels.

        Args:
            string(str): the incoming data
        
        *Serial Window Core
        """
        if self.inPreset:
            self.displayPrint(string)
        data = self.parseData(string)
        self.updateDisplay(data)

    @staticmethod
    def createTextField(width: int, height: int) -> QLineEdit:
        """Creates a text field.
        
        Args:
            width(int): maximum width
            height(int): maximum height
        """
        label = QLineEdit()
        label.setMaximumSize(width, height)
        return label

    @staticmethod
    def createButton(label: str, function) -> QPushButton:
        """Creates a button.
        
        Args:
            label(str): the button label
            function: the function to connect the button to
        
        Returns:
            QPushButton: the created button
        """
        button = QPushButton(label)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(function)
        return button

    def createSettings(self):
        """Create right side settings layout."""
        # area setup (all of the lines and buttons should prob be made dictionary accessible)
        self.settings = QGridLayout()
        title = QLabel("Presets: ")
        bottomSpacer = QSpacerItem(10, 100)

        # input boxes
        self.timeInterval = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)
        self.toggledPins = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)
        self.testName = self.createTextField(2 * SETTING_WIDTH + 10, LINE_HEIGHT)
        self.specificCommand = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)

        # pin marking labels
        self.pin1 = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)
        self.pin2 = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)
        self.pin3 = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)
        self.pin4 = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)
        self.pin5 = self.createTextField(SETTING_WIDTH, LINE_HEIGHT)

        # status labels
        self.dynamicLabels = {}
        for i in range (1, 6):
            label = QLabel(f"{i}")
            formatter = PinFormat(f"{i}")
            self.dynamicLabels[f"{PIN}{i}"] = ValveStateUpdater(label, formatter)
            self.dynamicLabels[f"{PRESSURE}{i}"] = PressureUpdater(label, formatter)

        # input buttons
        self.startPresetButton = self.createButton("Start Preset", self.presetRun)
        self.cancelPresetButton = self.createButton("Cancel Preset", self.sendInterrupt)
        self.enterDataButton = self.createButton("Enter Data", self.enterData)
        self.sendCommandButton = self.createButton("Send Command", self.sendSpecificToggle)
        self.screenLock = self.createButton("Toggle Lock", self.toggleScreenLock)

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
        self.settings.addWidget(QLabel("Safety Lock: "), 9, 1)
        self.settings.addWidget(self.screenLock, 10, 1)
        self.settings.addWidget(QLabel("Pin Control Equivalencies: "), 12, 0)
        pinBegin = 13
        for i in range (0, 5):
            self.settings.addWidget(self.dynamicLabels[f"{PIN}{i + 1}"].label, pinBegin + i, 0)

        #testLabel = QLabel()
        #image = QPixmap("./src/octoLogo.png")
        #testLabel.setPixmap(image)
        #self.settings.addWidget(testLabel, 13, 0, 10, 2)

        self.settings.addWidget(self.pin1, 13, 1)
        self.settings.addWidget(self.pin2, 14, 1)
        self.settings.addWidget(self.pin3, 15, 1)
        self.settings.addWidget(self.pin4, 16, 1)
        self.settings.addWidget(self.pin5, 17, 1)
        self.settings.addWidget(QLabel(f"*Note: Timestamps on data in are not 100 % accurate."), 18, 0, 1, 2)
        self.settings.addItem(bottomSpacer, 19, 0)
        self.generalLayout.addLayout(self.settings, 0, 1)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    waterflowDisplay = WaterflowGUI()
    waterflowDisplay.show()
    sys.exit(app.exec())
