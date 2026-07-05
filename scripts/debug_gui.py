import sys
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import FluentWindow


print("Creating App...")
app = QApplication(sys.argv)

print("Creating Window...")
w = FluentWindow()
print("Success!")
