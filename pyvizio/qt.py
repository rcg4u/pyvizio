"""Simple PyQt GUI for pyvizio.

Provides discovery and basic controls (power, volume, inputs, mute).
This is intentionally minimal and uses the synchronous Vizio wrapper so the UI
does not need to manage asyncio.
"""

from typing import Optional

try:
    from PyQt5 import QtWidgets
    from PyQt5.QtCore import Qt
except Exception:
    try:
        from PySide2 import QtWidgets
        from PySide2.QtCore import Qt
    except Exception:
        raise ImportError("PyQt5 or PySide2 is required to run the GUI")

from pyvizio import Vizio, VizioAsync
from pyvizio.helpers import async_to_sync


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pyvizio GUI")
        self.resize(700, 400)

        self.vizio: Optional[Vizio] = None
        self.selected_device = None

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        main_layout = QtWidgets.QHBoxLayout(central)

        # Left: devices list
        left = QtWidgets.QVBoxLayout()
        self.devices_list = QtWidgets.QListWidget()
        left.addWidget(QtWidgets.QLabel("Discovered devices:"))
        left.addWidget(self.devices_list)

        discover_btn = QtWidgets.QPushButton("Discover")
        discover_btn.clicked.connect(self.discover_devices)
        left.addWidget(discover_btn)

        main_layout.addLayout(left, 1)

        # Right: controls
        right = QtWidgets.QVBoxLayout()

        self.status_label = QtWidgets.QLabel("No device selected")
        right.addWidget(self.status_label)

        btn_row = QtWidgets.QHBoxLayout()
        self.power_btn = QtWidgets.QPushButton("Power Toggle")
        self.power_btn.clicked.connect(self.power_toggle)
        btn_row.addWidget(self.power_btn)

        self.mute_btn = QtWidgets.QPushButton("Mute Toggle")
        self.mute_btn.clicked.connect(self.mute_toggle)
        btn_row.addWidget(self.mute_btn)

        right.addLayout(btn_row)

        vol_row = QtWidgets.QHBoxLayout()
        self.vol_up_btn = QtWidgets.QPushButton("Vol +")
        self.vol_up_btn.clicked.connect(lambda: self.change_volume(True))
        vol_row.addWidget(self.vol_up_btn)

        self.vol_down_btn = QtWidgets.QPushButton("Vol -")
        self.vol_down_btn.clicked.connect(lambda: self.change_volume(False))
        vol_row.addWidget(self.vol_down_btn)

        right.addLayout(vol_row)

        right.addWidget(QtWidgets.QLabel("Inputs:"))
        self.inputs_combo = QtWidgets.QComboBox()
        right.addWidget(self.inputs_combo)
        self.input_btn = QtWidgets.QPushButton("Set Input")
        self.input_btn.clicked.connect(self.set_input)
        right.addWidget(self.input_btn)

        right.addWidget(QtWidgets.QLabel("Apps:"))
        self.apps_combo = QtWidgets.QComboBox()
        right.addWidget(self.apps_combo)
        self.launch_app_btn = QtWidgets.QPushButton("Launch App")
        self.launch_app_btn.clicked.connect(self.launch_app)
        right.addWidget(self.launch_app_btn)

        refresh_row = QtWidgets.QHBoxLayout()
        self.refresh_status_btn = QtWidgets.QPushButton("Refresh Status")
        self.refresh_status_btn.clicked.connect(self.refresh_status)
        refresh_row.addWidget(self.refresh_status_btn)

        self.connect_btn = QtWidgets.QPushButton("Connect Selected")
        self.connect_btn.clicked.connect(self.connect_selected)
        refresh_row.addWidget(self.connect_btn)

        right.addLayout(refresh_row)

        main_layout.addLayout(right, 2)

        # Signals
        self.devices_list.itemSelectionChanged.connect(self.on_device_selected)

        # Disable controls until connected
        self.set_controls_enabled(False)

    def set_controls_enabled(self, enabled: bool):
        for w in [
            self.power_btn,
            self.mute_btn,
            self.vol_up_btn,
            self.vol_down_btn,
            self.inputs_combo,
            self.input_btn,
            self.apps_combo,
            self.launch_app_btn,
            self.refresh_status_btn,
        ]:
            w.setEnabled(enabled)

    def discover_devices(self):
        self.devices_list.clear()
        try:
            devices = Vizio.discovery_zeroconf(5)
            if not devices:
                devices = Vizio.discovery_ssdp(5)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Discover Error", str(e))
            return

        for dev in devices:
            # store device object in QListWidgetItem for easy retrieval
            item = QtWidgets.QListWidgetItem(f"{getattr(dev, 'name', '')} ({getattr(dev, 'ip', '')})")
            item.setData(Qt.UserRole, dev)
            self.devices_list.addItem(item)

    def on_device_selected(self):
        items = self.devices_list.selectedItems()
        if not items:
            self.selected_device = None
            self.status_label.setText("No device selected")
            self.set_controls_enabled(False)
            return

        self.selected_device = items[0].data(Qt.UserRole)
        self.status_label.setText(f"Selected: {getattr(self.selected_device, 'name', '')} @ {getattr(self.selected_device, 'ip', '')}")

    def connect_selected(self):
        if not self.selected_device:
            return
        ip = getattr(self.selected_device, 'ip', None)
        port = getattr(self.selected_device, 'port', None)
        if port:
            ip = f"{ip}:{port}"

        try:
            # create synchronous Vizio wrapper (no auth token by default)
            self.vizio = Vizio("pyvizio-gui", ip, getattr(self.selected_device, 'name', ''), "", timeout=5)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Connect Error", str(e))
            return

        self.set_controls_enabled(True)
        self.refresh_status()
        # populate inputs and apps lazily
        self.populate_inputs()
        self.populate_apps()

    def refresh_status(self):
        if not self.vizio:
            return
        try:
            power = self.vizio.get_power_state()
            vol = self.vizio.get_current_volume()
            inp = self.vizio.get_current_input()
            self.status_label.setText(f"Power: {power} | Vol: {vol} | Input: {inp}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Status Error", str(e))

    def power_toggle(self):
        if not self.vizio:
            return
        try:
            self.vizio.pow_toggle()
            self.refresh_status()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Power Error", str(e))

    def mute_toggle(self):
        if not self.vizio:
            return
        try:
            self.vizio.mute_toggle()
            self.refresh_status()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Mute Error", str(e))

    def change_volume(self, up: bool):
        if not self.vizio:
            return
        try:
            if up:
                self.vizio.vol_up(1)
            else:
                self.vizio.vol_down(1)
            self.refresh_status()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Volume Error", str(e))

    def populate_inputs(self):
        if not self.vizio:
            return
        try:
            inputs = self.vizio.get_inputs_list()
            self.inputs_combo.clear()
            if inputs:
                for i in inputs:
                    # InputItem has name attribute
                    name = getattr(i, 'name', None) or getattr(i, 'meta_name', None)
                    self.inputs_combo.addItem(name)
        except Exception:
            # ignore inputs population errors
            pass

    def set_input(self):
        if not self.vizio:
            return
        name = self.inputs_combo.currentText()
        if not name:
            return
        try:
            self.vizio.set_input(name)
            self.refresh_status()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Input Error", str(e))

    def populate_apps(self):
        # Vizio.get_apps_list is async on VizioAsync; use helper to call it synchronously
        try:
            apps = async_to_sync(VizioAsync.get_apps_list)()
            self.apps_combo.clear()
            if apps:
                for a in apps:
                    self.apps_combo.addItem(str(a))
        except Exception:
            # ignore apps population errors
            pass

    def launch_app(self):
        if not self.vizio:
            return
        app = self.apps_combo.currentText()
        if not app:
            return
        try:
            self.vizio.launch_app(app)
            self.refresh_status()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Launch Error", str(e))


def run_gui():
    app = QtWidgets.QApplication([])
    w = MainWindow()
    w.show()
    app.exec_()


if __name__ == '__main__':
    run_gui()
