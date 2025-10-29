# main.py
import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from ffx_pro import ConverterApp

def main():
    app = QApplication(sys.argv)
    window = ConverterApp()

    # Set icon from resource
    window.setWindowIcon(QIcon(":/assets/icons/icon.png"))

    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
