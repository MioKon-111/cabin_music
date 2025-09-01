import sys
from PyQt5.QtWidgets import QApplication, QWidget, QLabel

class SimpleWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Simple Window")
        self.setGeometry(100, 100, 300, 200)
        label = QLabel("Hello, PyQt5!", self)
        label.move(100, 100)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SimpleWindow()
    window.show()
    sys.exit(app.exec_())