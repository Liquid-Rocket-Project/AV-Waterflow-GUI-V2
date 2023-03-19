import sys, time
from PyQt6.QtCore import (
    Qt,
    QDateTime,
    QThread,
    QObject,
    pyqtSignal,
    pyqtSlot,
)
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
    QVBoxLayout, 
)
class MySignal(QObject):
        sig = pyqtSignal(str)

class MyLongThread(QThread):
        def __init__(self, parent = None):
                QThread.__init__(self, parent)
                self.exiting = False
                self.signal = MySignal()

        def run(self):
                end = time.time()+10
                while self.exiting==False:
                        sys.stdout.write('*')
                        sys.stdout.flush()
                        time.sleep(1)
                        now = time.time()
                        if now>=end:
                                self.exiting=True
                self.signal.sig.emit('OK')

class MyThread(QThread):
        def __init__(self, parent = None):
                QThread.__init__(self, parent)
                self.exiting = False

        def run(self):
                while self.exiting==False:
                        sys.stdout.write('.')
                        sys.stdout.flush()
                        time.sleep(1)

class MainWindow(QMainWindow):
        def __init__(self, parent=None):
                QMainWindow.__init__(self,parent)
                self.centralwidget = QWidget(self)
                self.batchbutton = QPushButton('Start batch',self)
                self.longbutton = QPushButton('Start long (10 seconds) operation',self)
                self.label1 = QLabel('Continuos batch')
                self.label2 = QLabel('Long batch')
                self.vbox = QVBoxLayout()
                self.vbox.addWidget(self.batchbutton)
                self.vbox.addWidget(self.longbutton)
                self.vbox.addWidget(self.label1)
                self.vbox.addWidget(self.label2)
                self.setCentralWidget(self.centralwidget)
                self.centralwidget.setLayout(self.vbox)
                self.mythread = MyThread()
                self.longthread = MyLongThread()
                self.batchbutton.clicked.connect(self.handletoggle)
                self.longbutton.clicked.connect(self.longoperation)
                self.mythread.started.connect(self.started)
                self.mythread.finished.connect(self.finished)
                #self.mythread.terminated.connect(self.terminated)
                self.longthread.signal.sig.connect(self.longoperationcomplete)

        def started(self):
                self.label1.setText('Continuous batch started')

        def finished(self):
                self.label1.setText('Continuous batch stopped')

        def terminated(self):
                self.label1.setText('Continuous batch terminated')

        def handletoggle(self):
                if self.mythread.isRunning():
                        self.mythread.exiting=True
                        self.batchbutton.setEnabled(False)
                        while self.mythread.isRunning():
                                time.sleep(0.01)
                                continue
                        self.batchbutton.setText('Start batch')
                        self.batchbutton.setEnabled(True)
                else:
                        self.mythread.exiting=False
                        self.mythread.start()
                        self.batchbutton.setEnabled(False)
                        while not self.mythread.isRunning():
                                time.sleep(0.01)
                                continue
                        self.batchbutton.setText('Stop batch')
                        self.batchbutton.setEnabled(True)

        def longoperation(self):
                if not self.longthread.isRunning():
                        self.longthread.exiting=False
                        self.longthread.start()
                        self.label2.setText('Long operation started')
                        self.longbutton.setEnabled(False)

        def longoperationcomplete(self,data):
                self.label2.setText('Long operation completed with: '+data)
                self.longbutton.setEnabled(True)

if __name__=='__main__':
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec())