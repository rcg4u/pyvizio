"""Extended PyQt GUI for pyvizio with auth/pair and generic command executor.

Adds fields for auth token, PIN, challenge token/type, device type selection,
a status type dropdown, and a generic command input to run arbitrary Vizio methods.
"""

from typing import Optional

try:
    from PyQt5 import QtWidgets
    from PyQt5.QtCore import Qt, pyqtSignal
except Exception:
    try:
        from PySide2 import QtWidgets
        from PySide2.QtCore import Qt, Signal as pyqtSignal
    except Exception:
        raise ImportError("PyQt5 or PySide2 is required to run the GUI")

from pyvizio import Vizio, VizioAsync
from pyvizio.helpers import async_to_sync


class ExtendedWindow(QtWidgets.QMainWindow):
    devices_discovered = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("pyvizio GUI - Extended")
        self.resize(900, 600)

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

        # Auth / Pairing controls
        left.addWidget(QtWidgets.QLabel("Auth / Pairing"))
        form = QtWidgets.QFormLayout()
        self.device_type_combo = QtWidgets.QComboBox()
        self.device_type_combo.addItems(["tv", "speaker", "crave360"])
        form.addRow("Device Type:", self.device_type_combo)

        self.auth_token_edit = QtWidgets.QLineEdit()
        form.addRow("Auth Token:", self.auth_token_edit)
        # keep displayed token in sync and allow easy copy/paste
        self.auth_token_edit.textChanged.connect(self.on_auth_token_changed)
        # also enable controls automatically when a token exists
        self.auth_token_edit.textChanged.connect(lambda t: self.set_controls_enabled(bool(t.strip())))

        # Displayed (read-only) token and copy button
        display_h = QtWidgets.QHBoxLayout()
        self.display_token_edit = QtWidgets.QLineEdit()
        self.display_token_edit.setReadOnly(True)
        display_h.addWidget(self.display_token_edit)
        self.copy_token_btn = QtWidgets.QPushButton("Copy")
        self.copy_token_btn.clicked.connect(self.copy_token)
        display_h.addWidget(self.copy_token_btn)
        form.addRow("Displayed Token:", display_h)

        # Small status area for pairing/auth messages (replaces pop-up notifications)
        self.auth_status = QtWidgets.QLabel("")
        self.auth_status.setWordWrap(True)
        form.addRow("Auth Status:", self.auth_status)

        self.challenge_type_spin = QtWidgets.QSpinBox()
        self.challenge_type_spin.setMinimum(0)
        self.challenge_type_spin.setMaximum(9999)
        form.addRow("Challenge Type:", self.challenge_type_spin)

        self.challenge_token_edit = QtWidgets.QLineEdit()
        form.addRow("Challenge Token:", self.challenge_token_edit)

        self.pin_edit = QtWidgets.QLineEdit()
        form.addRow("PIN:", self.pin_edit)

        left.addLayout(form)

        pair_row = QtWidgets.QHBoxLayout()
        pair_start_btn = QtWidgets.QPushButton("Start Pair")
        pair_start_btn.clicked.connect(self.pair_start)
        pair_row.addWidget(pair_start_btn)
        pair_stop_btn = QtWidgets.QPushButton("Stop Pair")
        pair_stop_btn.clicked.connect(self.pair_stop)
        pair_row.addWidget(pair_stop_btn)
        pair_finish_btn = QtWidgets.QPushButton("Finish Pair")
        pair_finish_btn.clicked.connect(self.pair_finish)
        pair_row.addWidget(pair_finish_btn)

        left.addLayout(pair_row)

        # Saved devices list (allow multiple TVs to be stored)
        left.addWidget(QtWidgets.QLabel("Saved devices:"))
        self.saved_devices_list = QtWidgets.QListWidget()
        left.addWidget(self.saved_devices_list)

        saved_row = QtWidgets.QHBoxLayout()
        save_btn = QtWidgets.QPushButton("Save Selected")
        save_btn.clicked.connect(self.save_selected_device)
        saved_row.addWidget(save_btn)
        remove_btn = QtWidgets.QPushButton("Remove Saved")
        remove_btn.clicked.connect(self.remove_saved_device)
        saved_row.addWidget(remove_btn)
        left.addLayout(saved_row)

        # load saved devices from disk
        try:
            self.saved_devices_path = __import__('os').path.join(__import__('os').path.dirname(__file__), 'devices.json')
        except Exception:
            self.saved_devices_path = 'devices.json'
        self.load_saved_devices()
        # favorites for current device (list of app names)
        self.favorites = []

        # when a saved device is selected, handle it
        self.saved_devices_list.itemSelectionChanged.connect(self.on_saved_selected)

        main_layout.addLayout(left, 1)

        # Right: controls and output
        # connect discovery signal
        self.devices_discovered.connect(self.on_devices_discovered)
        # start background discovery shortly after startup
        import threading
        threading.Thread(target=self._background_discover, daemon=True).start()
        right = QtWidgets.QVBoxLayout()

        self.status_label = QtWidgets.QLabel("No device selected")
        right.addWidget(self.status_label)

        connect_row = QtWidgets.QHBoxLayout()
        self.connect_btn = QtWidgets.QPushButton("Connect Selected")
        self.connect_btn.clicked.connect(self.connect_selected)
        connect_row.addWidget(self.connect_btn)

        self.refresh_status_btn = QtWidgets.QPushButton("Refresh Status")
        self.refresh_status_btn.clicked.connect(self.refresh_status)
        connect_row.addWidget(self.refresh_status_btn)

        right.addLayout(connect_row)

        # Manual connect area (for networks without working discovery)
        manual_row = QtWidgets.QHBoxLayout()
        self.manual_ip_edit = QtWidgets.QLineEdit()
        self.manual_ip_edit.setPlaceholderText("IP[:PORT]")
        manual_row.addWidget(self.manual_ip_edit)
        self.manual_name_edit = QtWidgets.QLineEdit()
        self.manual_name_edit.setPlaceholderText("Name (optional)")
        manual_row.addWidget(self.manual_name_edit)
        self.manual_auth_edit = QtWidgets.QLineEdit()
        self.manual_auth_edit.setPlaceholderText("Auth token (optional)")
        manual_row.addWidget(self.manual_auth_edit)
        self.manual_connect_btn = QtWidgets.QPushButton("Manual Connect")
        self.manual_connect_btn.clicked.connect(self.manual_connect)
        manual_row.addWidget(self.manual_connect_btn)
        right.addLayout(manual_row)

        # Status type dropdown
        status_layout = QtWidgets.QHBoxLayout()
        status_layout.addWidget(QtWidgets.QLabel("Status Type:"))
        self.status_type_combo = QtWidgets.QComboBox()
        self.status_type_combo.addItems([
            "All",
            "Power",
            "Volume",
            "Input",
            "App",
            "Charging",
            "Battery",
            "Version",
            "ESN",
            "Serial",
        ])
        status_layout.addWidget(self.status_type_combo)
        right.addLayout(status_layout)

        # Command buttons
        cmds_group = QtWidgets.QGroupBox("Quick Commands")
        cmds_layout = QtWidgets.QGridLayout()

        self.power_on_btn = QtWidgets.QPushButton("Power On")
        self.power_on_btn.clicked.connect(lambda: self.exec_and_show("pow_on"))
        cmds_layout.addWidget(self.power_on_btn, 0, 0)
        self.power_off_btn = QtWidgets.QPushButton("Power Off")
        self.power_off_btn.clicked.connect(lambda: self.exec_and_show("pow_off"))
        cmds_layout.addWidget(self.power_off_btn, 0, 1)
        self.power_toggle_btn = QtWidgets.QPushButton("Power Toggle")
        self.power_toggle_btn.clicked.connect(lambda: self.exec_and_show("pow_toggle"))
        cmds_layout.addWidget(self.power_toggle_btn, 0, 2)

        self.vol_up_btn = QtWidgets.QPushButton("Vol +")
        self.vol_up_btn.clicked.connect(lambda: self.exec_and_show("vol_up", 1))
        cmds_layout.addWidget(self.vol_up_btn, 1, 0)
        self.vol_down_btn = QtWidgets.QPushButton("Vol -")
        self.vol_down_btn.clicked.connect(lambda: self.exec_and_show("vol_down", 1))
        cmds_layout.addWidget(self.vol_down_btn, 1, 1)

        self.ch_up_btn = QtWidgets.QPushButton("Ch +")
        self.ch_up_btn.clicked.connect(lambda: self.exec_and_show("ch_up", 1))
        cmds_layout.addWidget(self.ch_up_btn, 2, 0)
        self.ch_down_btn = QtWidgets.QPushButton("Ch -")
        self.ch_down_btn.clicked.connect(lambda: self.exec_and_show("ch_down", 1))
        cmds_layout.addWidget(self.ch_down_btn, 2, 1)
        self.ch_prev_btn = QtWidgets.QPushButton("Ch Prev")
        self.ch_prev_btn.clicked.connect(lambda: self.exec_and_show("ch_prev"))
        cmds_layout.addWidget(self.ch_prev_btn, 2, 2)

        self.mute_toggle_btn = QtWidgets.QPushButton("Mute Toggle")
        self.mute_toggle_btn.clicked.connect(lambda: self.exec_and_show("mute_toggle"))
        cmds_layout.addWidget(self.mute_toggle_btn, 3, 0)

        self.play_btn = QtWidgets.QPushButton("Play")
        self.play_btn.clicked.connect(lambda: self.exec_and_show("play"))
        cmds_layout.addWidget(self.play_btn, 3, 1)
        self.pause_btn = QtWidgets.QPushButton("Pause")
        self.pause_btn.clicked.connect(lambda: self.exec_and_show("pause"))
        cmds_layout.addWidget(self.pause_btn, 3, 2)

        cmds_group.setLayout(cmds_layout)
        right.addWidget(cmds_group)

        # Directional pad (arrow keys + OK)
        nav_group = QtWidgets.QGroupBox("Navigation")
        nav_layout = QtWidgets.QGridLayout()
        self.nav_up = QtWidgets.QPushButton("↑")
        self.nav_up.clicked.connect(lambda: self.send_direction('UP'))
        nav_layout.addWidget(self.nav_up, 0, 1)
        self.nav_left = QtWidgets.QPushButton("←")
        self.nav_left.clicked.connect(lambda: self.send_direction('LEFT'))
        nav_layout.addWidget(self.nav_left, 1, 0)
        self.nav_ok = QtWidgets.QPushButton("OK")
        self.nav_ok.clicked.connect(lambda: self.send_direction('OK'))
        nav_layout.addWidget(self.nav_ok, 1, 1)
        self.nav_right = QtWidgets.QPushButton("→")
        self.nav_right.clicked.connect(lambda: self.send_direction('RIGHT'))
        nav_layout.addWidget(self.nav_right, 1, 2)
        self.nav_down = QtWidgets.QPushButton("↓")
        self.nav_down.clicked.connect(lambda: self.send_direction('DOWN'))
        nav_layout.addWidget(self.nav_down, 2, 1)
        nav_group.setLayout(nav_layout)
        right.addWidget(nav_group)

        # Inputs and Apps
        io_layout = QtWidgets.QHBoxLayout()
        inputs_box = QtWidgets.QVBoxLayout()
        inputs_box.addWidget(QtWidgets.QLabel("Inputs:"))
        self.inputs_combo = QtWidgets.QComboBox()
        inputs_box.addWidget(self.inputs_combo)
        self.input_btn = QtWidgets.QPushButton("Set Input")
        self.input_btn.clicked.connect(self.set_input)
        inputs_box.addWidget(self.input_btn)
        io_layout.addLayout(inputs_box)

        apps_box = QtWidgets.QVBoxLayout()
        apps_box.addWidget(QtWidgets.QLabel("Apps:"))
        self.apps_combo = QtWidgets.QComboBox()
        apps_box.addWidget(self.apps_combo)
        self.launch_app_btn = QtWidgets.QPushButton("Launch App")
        self.launch_app_btn.clicked.connect(self.launch_app)
        apps_box.addWidget(self.launch_app_btn)
        # Favorite apps (up to 6) and Add Favorite button
        fav_row = QtWidgets.QHBoxLayout()
        self.add_fav_btn = QtWidgets.QPushButton("Add to Favorites")
        self.add_fav_btn.clicked.connect(self.add_selected_app_to_favorites)
        apps_box.addWidget(self.add_fav_btn)
        self.fav_buttons = []
        favs_layout = QtWidgets.QHBoxLayout()
        for i in range(6):
            b = QtWidgets.QPushButton("-")
            b.setEnabled(False)
            b.setFixedWidth(80)
            b.clicked.connect(lambda _, idx=i: self.favorite_button_clicked(idx))
            self.fav_buttons.append(b)
            favs_layout.addWidget(b)
        apps_box.addLayout(favs_layout)
        io_layout.addLayout(apps_box)

        right.addLayout(io_layout)

        # Generic command executor
        right.addWidget(QtWidgets.QLabel("Execute arbitrary command (e.g. get_esn, get_version, setting audio Bass 5):"))
        cmd_row = QtWidgets.QHBoxLayout()
        # Dropdown of available commands (populated from Vizio class)
        self.cmd_combo = QtWidgets.QComboBox()
        try:
            cmds = [m for m in dir(Vizio) if callable(getattr(Vizio, m)) and not m.startswith('_')]
            cmds.sort()
            self.cmd_combo.addItem("")
            for c in cmds:
                self.cmd_combo.addItem(c)
        except Exception:
            pass
        self.cmd_combo.currentIndexChanged.connect(lambda: self.cmd_input.setPlaceholderText(f"Args (space-separated) for {self.cmd_combo.currentText()}"))
        cmd_row.addWidget(self.cmd_combo)
        self.cmd_input = QtWidgets.QLineEdit()
        self.cmd_input.setPlaceholderText("If dropdown is blank, enter full command and args here")
        cmd_row.addWidget(self.cmd_input)
        self.cmd_run_btn = QtWidgets.QPushButton("Run")
        self.cmd_run_btn.clicked.connect(self.run_command)
        cmd_row.addWidget(self.cmd_run_btn)
        right.addLayout(cmd_row)

        # Manual volume set controls
        vol_row = QtWidgets.QHBoxLayout()
        vol_row.addWidget(QtWidgets.QLabel("Set Volume:"))
        self.volume_spin = QtWidgets.QSpinBox()
        self.volume_spin.setRange(0, 100)
        self.volume_spin.setValue(20)
        vol_row.addWidget(self.volume_spin)
        self.set_volume_btn = QtWidgets.QPushButton("Set")
        self.set_volume_btn.clicked.connect(self.set_volume)
        vol_row.addWidget(self.set_volume_btn)
        right.addLayout(vol_row)

        # Output box
        right.addWidget(QtWidgets.QLabel("Output:"))
        self.output = QtWidgets.QTextEdit()
        self.output.setReadOnly(True)
        right.addWidget(self.output, 1)

        main_layout.addLayout(right, 2)

        # Signals
        self.devices_list.itemSelectionChanged.connect(self.on_device_selected)
        self.set_controls_enabled(False)

    def set_controls_enabled(self, enabled: bool):
        for w in [
            self.connect_btn,
            self.refresh_status_btn,
            self.power_on_btn,
            self.power_off_btn,
            self.power_toggle_btn,
            self.vol_up_btn,
            self.vol_down_btn,
            self.ch_up_btn,
            self.ch_down_btn,
            self.ch_prev_btn,
            self.mute_toggle_btn,
            self.play_btn,
            self.pause_btn,
            self.inputs_combo,
            self.input_btn,
            self.apps_combo,
            self.launch_app_btn,
            self.add_fav_btn,
            self.cmd_combo,
            self.cmd_input,
            self.cmd_run_btn,
            self.volume_spin,
            self.set_volume_btn,
        ]:
            w.setEnabled(enabled)
        # favorite buttons are separate list
        for b in getattr(self, 'fav_buttons', []):
            b.setEnabled(enabled and bool(self.favorites))

    def discover_devices(self):
        # synchronous discovery from UI with verbose status updates
        self.devices_list.clear()
        try:
            self.auth_status.setText("Discovery: starting (UI)...")
            devices = Vizio.discovery_zeroconf(5)
            self.auth_status.setText(f"Discovery: zeroconf found {len(devices) if devices else 0}")
            if not devices:
                self.auth_status.setText("Discovery: zeroconf found none, trying SSDP...")
                devices = Vizio.discovery_ssdp(5)
                self.auth_status.setText(f"Discovery: ssdp found {len(devices) if devices else 0}")
        except Exception as e:
            self.auth_status.setText(f"Discover Error: {e}")
            return

        for dev in devices:
            item = QtWidgets.QListWidgetItem(f"{getattr(dev, 'name', '')} ({getattr(dev, 'ip', '')})")
            item.setData(Qt.UserRole, dev)
            self.devices_list.addItem(item)

    def _background_discover(self):
        # run discovery in background thread and emit results along with a log
        log_lines = []
        devices = []
        try:
            log_lines.append("Background discovery starting...")
            devices = Vizio.discovery_zeroconf(5)
            log_lines.append(f"Zeroconf found {len(devices) if devices else 0}")
            if not devices:
                log_lines.append("Zeroconf found none, trying SSDP...")
                devices = Vizio.discovery_ssdp(5)
                log_lines.append(f"SSDP found {len(devices) if devices else 0}")
        except Exception as e:
            devices = []
            log_lines.append(f"Discovery exception: {e}")
        payload = {'devices': devices, 'log': "\n".join(log_lines)}
        self.devices_discovered.emit(payload)

    def on_devices_discovered(self, payload):
        # update UI with discovered devices (runs in main thread via signal)
        if isinstance(payload, dict):
            devices = payload.get('devices', [])
            log = payload.get('log', '')
        else:
            devices = payload
            log = ''

        if log:
            # show the verbose discovery log in the auth status area
            self.auth_status.setText(log)

        if not devices:
            if not log:
                self.auth_status.setText("Background discovery found no devices")
            return
        self.devices_list.clear()
        for dev in devices:
            item = QtWidgets.QListWidgetItem(f"{getattr(dev, 'name', '')} ({getattr(dev, 'ip', '')})")
            item.setData(Qt.UserRole, dev)
            self.devices_list.addItem(item)
        combined = f"Background discovery: found {len(devices)} device(s)"
        if log:
            combined = combined + "\n" + log
        self.auth_status.setText(combined)

    def load_saved_devices(self):
        import json, os
        self.saved_devices = []
        try:
            if os.path.exists(self.saved_devices_path):
                with open(self.saved_devices_path, 'r', encoding='utf-8') as fh:
                    self.saved_devices = json.load(fh) or []
        except Exception:
            self.saved_devices = []

        self.saved_devices_list.clear()
        for dev in self.saved_devices:
            name = f"{dev.get('name', '')} ({dev.get('ip', '')})"
            item = QtWidgets.QListWidgetItem(name)
            item.setData(Qt.UserRole, dev)
            self.saved_devices_list.addItem(item)

    def save_saved_devices(self):
        import json
        try:
            with open(self.saved_devices_path, 'w', encoding='utf-8') as fh:
                json.dump(self.saved_devices, fh, indent=2)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Save Error", f"Failed to save devices: {e}")

    def save_selected_device(self):
        # take current selected discovery device and save full info needed for auth
        items = self.devices_list.selectedItems()
        if not items:
            self.auth_status.setText("No discovered device selected to save")
            return
        dev = items[0].data(Qt.UserRole)
        ip = getattr(dev, 'ip', '')
        port = getattr(dev, 'port', None)
        dev_dict = {
            'name': getattr(dev, 'name', ''),
            'ip': ip,
            'port': port,
            'device_type': self.device_type_combo.currentText(),
            'auth_token': self.auth_token_edit.text().strip(),
            'saved_at': __import__('datetime').datetime.utcnow().isoformat(),
            'favorites': self.favorites,
        }

        # attempt to enrich with serial, esn, version (helps identify device and validate token)
        try:
            temp_v = None
            # prefer existing connected vizio if it matches
            if self.vizio and getattr(self.selected_device, 'ip', None) == ip:
                temp_v = self.vizio
            else:
                ip_with_port = f"{ip}:{port}" if port else ip
                temp_v = Vizio("pyvizio-gui", ip_with_port, getattr(dev, 'name', ''), "", self.device_type_combo.currentText(), timeout=3)

            try:
                serial = temp_v.get_serial_number()
                if serial:
                    dev_dict['serial_number'] = serial
            except Exception:
                pass
            try:
                esn = temp_v.get_esn()
                if esn:
                    dev_dict['esn'] = esn
            except Exception:
                pass
            try:
                version = temp_v.get_version()
                if version:
                    dev_dict['version'] = version
            except Exception:
                pass
        except Exception:
            # ignore enrich failures
            pass

        # include any unique id from discovery object if available
        udn = getattr(dev, 'UDN', None) or getattr(dev, 'udn', None) or getattr(dev, 'UDN', None)
        if udn:
            dev_dict['udn'] = udn

        # avoid duplicates by ip/port; replace existing entry if present
        replaced = False
        for i, d in enumerate(self.saved_devices):
            if d.get('ip') == dev_dict['ip'] and d.get('port') == dev_dict['port']:
                self.saved_devices[i] = dev_dict
                replaced = True
                break
        if not replaced:
            self.saved_devices.append(dev_dict)

        self.save_saved_devices()
        self.load_saved_devices()
        self.auth_status.setText("Device saved with auth info (if available)")

    def remove_saved_device(self):
        items = self.saved_devices_list.selectedItems()
        if not items:
            QtWidgets.QMessageBox.warning(self, "Remove Saved", "No saved device selected")
            return
        dev = items[0].data(Qt.UserRole)
        self.saved_devices = [d for d in self.saved_devices if not (d.get('ip') == dev.get('ip') and d.get('port') == dev.get('port'))]
        self.save_saved_devices()
        self.load_saved_devices()
        QtWidgets.QMessageBox.information(self, "Remove Saved", "Saved device removed")

    def on_saved_selected(self):
        items = self.saved_devices_list.selectedItems()
        if not items:
            return
        dev = items[0].data(Qt.UserRole)
        # set selected_device to the dict so connect_selected can use it
        self.selected_device = dev
        self.status_label.setText(f"Selected (saved): {dev.get('name', '')} @ {dev.get('ip', '')}")
        # populate auth token and device type from saved
        if dev.get('auth_token'):
            self.auth_token_edit.setText(dev.get('auth_token'))
        if dev.get('device_type'):
            idx = self.device_type_combo.findText(dev.get('device_type'))
            if idx >= 0:
                self.device_type_combo.setCurrentIndex(idx)

        # Populate Manual Connect fields (IP, Name, Auth) from saved device
        try:
            port = dev.get('port')
            ip = dev.get('ip') or ''
            ip_text = f"{ip}:{port}" if port else ip
            self.manual_ip_edit.setText(ip_text or "")
        except Exception:
            pass
        try:
            self.manual_name_edit.setText(dev.get('name', '') or "")
        except Exception:
            pass
        try:
            if dev.get('auth_token'):
                self.manual_auth_edit.setText(dev.get('auth_token'))
        except Exception:
            pass

        # load favorites if present
        self.favorites = dev.get('favorites', []) or []
        try:
            self.update_favorite_buttons()
        except Exception:
            pass

    def on_device_selected(self):
        items = self.devices_list.selectedItems()
        if not items:
            self.selected_device = None
            self.status_label.setText("No device selected")
            self.set_controls_enabled(False)
            return

        self.selected_device = items[0].data(Qt.UserRole)
        # support both object-like discovery results and dicts
        name = getattr(self.selected_device, 'name', '') if not isinstance(self.selected_device, dict) else self.selected_device.get('name', '')
        ip = getattr(self.selected_device, 'ip', '') if not isinstance(self.selected_device, dict) else self.selected_device.get('ip', '')
        self.status_label.setText(f"Selected: {name} @ {ip}")

        # Populate manual connect fields with discovered device info; include auth token if available
        try:
            port = getattr(self.selected_device, 'port', None) if not isinstance(self.selected_device, dict) else self.selected_device.get('port')
            ip_text = f"{ip}:{port}" if port else ip
            self.manual_ip_edit.setText(ip_text or "")
        except Exception:
            pass
        try:
            self.manual_name_edit.setText(name or "")
        except Exception:
            pass
        # attempt to find an auth token on the discovery object (attr or dict keys)
        auth = None
        try:
            if isinstance(self.selected_device, dict):
                auth = self.selected_device.get('auth_token') or self.selected_device.get('auth') or self.selected_device.get('token')
            else:
                auth = getattr(self.selected_device, 'auth_token', None) or getattr(self.selected_device, 'auth', None) or getattr(self.selected_device, 'token', None)
        except Exception:
            auth = None
        if auth:
            try:
                self.manual_auth_edit.setText(str(auth))
            except Exception:
                pass

    def connect_selected(self):
        if not self.selected_device:
            return
        ip = getattr(self.selected_device, 'ip', None)
        port = getattr(self.selected_device, 'port', None)
        if port:
            ip = f"{ip}:{port}"

        auth_token = self.auth_token_edit.text().strip()
        device_type = self.device_type_combo.currentText().strip()

        try:
            self.vizio = Vizio("pyvizio-gui", ip, getattr(self.selected_device, 'name', ''), auth_token, device_type, timeout=5)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Connect Error", str(e))
            return

        self.set_controls_enabled(True)
        self.refresh_status()
        self.populate_inputs()
        self.populate_apps()

    def manual_connect(self):
        ip_text = self.manual_ip_edit.text().strip()
        if not ip_text:
            self.auth_status.setText("Enter IP to manually connect")
            return
        name = self.manual_name_edit.text().strip() or "Manual Vizio"
        auth = self.manual_auth_edit.text().strip()
        device_type = self.device_type_combo.currentText().strip()
        try:
            # Create Vizio instance using provided IP (may include :port)
            self.vizio = Vizio("pyvizio-gui", ip_text, name, auth, device_type, timeout=5)
            if auth:
                self.auth_token_edit.setText(auth)
            self.set_controls_enabled(bool(auth))
            self.auth_status.setText(f"Connected to {ip_text}")
            self.status_label.setText(f"Connected: {name} @ {ip_text}")
            self.populate_inputs()
            self.populate_apps()
        except Exception as e:
            self.auth_status.setText(f"Manual connect error: {e}")

    def refresh_status(self):
        if not self.vizio:
            return
        stype = self.status_type_combo.currentText()
        out = []
        try:
            if stype in ("All", "Power"):
                power = self.vizio.get_power_state()
                out.append(f"Power: {power}")
            if stype in ("All", "Volume"):
                vol = self.vizio.get_current_volume()
                out.append(f"Volume: {vol}")
            if stype in ("All", "Input"):
                inp = self.vizio.get_current_input()
                out.append(f"Input: {inp}")
            if stype in ("All", "App"):
                app = self.vizio.get_current_app()
                out.append(f"App: {app}")
            if stype in ("All", "Charging"):
                ch = self.vizio.get_charging_status()
                out.append(f"Charging: {ch}")
            if stype in ("All", "Battery"):
                batt = self.vizio.get_battery_level()
                out.append(f"Battery: {batt}")
            if stype in ("All", "Version"):
                ver = self.vizio.get_version()
                out.append(f"Version: {ver}")
            if stype in ("All", "ESN"):
                esn = self.vizio.get_esn()
                out.append(f"ESN: {esn}")
            if stype in ("All", "Serial"):
                sn = self.vizio.get_serial_number()
                out.append(f"Serial: {sn}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Status Error", str(e))
            return

        self.output.append("\n".join(out))

    def pair_start(self):
        # start pairing against the selected device (not localhost)
        if not self.selected_device:
            self.auth_status.setText("No device selected for pairing")
            return

        ip = getattr(self.selected_device, 'ip', None)
        port = getattr(self.selected_device, 'port', None)
        if port:
            ip = f"{ip}:{port}"

        try:
            temp_v = Vizio("pyvizio-gui", ip, getattr(self.selected_device, 'name', ''), "", self.device_type_combo.currentText(), timeout=5)
            temp = temp_v.start_pair()
            # start_pair returns BeginPairResponse with ch_type and token attributes
            if temp is not None:
                self.challenge_type_spin.setValue(int(getattr(temp, 'ch_type', 0) or 0))
                self.challenge_token_edit.setText(str(getattr(temp, 'token', '')))
                self.auth_status.setText(f"Pair started: challenge type={getattr(temp, 'ch_type', '')}, token={getattr(temp, 'token', '')}")
            else:
                self.auth_status.setText("Start pair returned no data")
        except Exception as e:
            self.auth_status.setText(f"Pair Error: {e}")

    def pair_stop(self):
        if not self.vizio:
            # attempt to create temp ephemeral Vizio if ip from selected device is available
            if not self.selected_device:
                self.auth_status.setText("No device selected to stop pairing")
                return
            ip = getattr(self.selected_device, 'ip', None)
            port = getattr(self.selected_device, 'port', None)
            if port:
                ip = f"{ip}:{port}"
            try:
                Vizio("pyvizio-gui", ip, getattr(self.selected_device, 'name', '')).stop_pair()
                self.auth_status.setText("Pair stop sent")
            except Exception as e:
                self.auth_status.setText(f"Pair Stop Error: {e}")
            return

        try:
            self.vizio.stop_pair()
            self.auth_status.setText("Pair stop sent")
        except Exception as e:
            self.auth_status.setText(f"Pair Stop Error: {e}")

    def pair_finish(self):
        # ch_type, token, pin
        try:
            ch_type = int(self.challenge_type_spin.value())
            token = int(self.challenge_token_edit.text().strip()) if self.challenge_token_edit.text().strip() else 0
            pin = self.pin_edit.text().strip()
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Pair Finish", "Invalid challenge/token values")
            return

        # Need a Vizio instance to call pair; create temporary using selected device
        if not self.vizio:
            if not self.selected_device:
                QtWidgets.QMessageBox.warning(self, "Pair Finish", "No device selected")
                return
            ip = getattr(self.selected_device, 'ip', None)
            port = getattr(self.selected_device, 'port', None)
            if port:
                ip = f"{ip}:{port}"
            try:
                temp_v = Vizio("pyvizio-gui", ip, getattr(self.selected_device, 'name', ''), "", self.device_type_combo.currentText(), timeout=5)
                res = temp_v.pair(ch_type, token, pin)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Pair Finish Error", str(e))
                return
        else:
            try:
                res = self.vizio.pair(ch_type, token, pin)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Pair Finish Error", str(e))
                return

        if res is not None and getattr(res, 'auth_token', None):
            token = str(getattr(res, 'auth_token'))
            self.auth_token_edit.setText(token)
            # if currently connected, update the Vizio instance to use the new token
            try:
                if self.vizio:
                    self.vizio._auth_token = token
            except Exception:
                pass
            self.auth_status.setText(f"Paired successfully. Auth token set.")
            # enable controls now that we have auth
            self.set_controls_enabled(True)
        else:
            # Fallback: if user already filled an auth token manually, accept it
            manual_token = self.auth_token_edit.text().strip()
            if manual_token:
                # ensure current Vizio instance uses it
                try:
                    if self.vizio:
                        self.vizio._auth_token = manual_token
                except Exception:
                    pass
                self.auth_status.setText("No token returned from device; using manually-entered Auth Token")
                self.set_controls_enabled(True)
            else:
                self.auth_status.setText("Pair Finish: No auth token returned")

    def populate_inputs(self):
        if not self.vizio:
            return
        try:
            inputs = self.vizio.get_inputs_list()
            self.inputs_combo.clear()
            if inputs:
                for i in inputs:
                    name = getattr(i, 'name', None) or getattr(i, 'meta_name', None)
                    self.inputs_combo.addItem(name)
        except Exception:
            pass

    def set_input(self):
        if not self.vizio:
            return
        name = self.inputs_combo.currentText()
        if not name:
            return
        try:
            self.vizio.set_input(name)
            self.output.append(f"Set input to {name}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Input Error", str(e))

    def populate_apps(self):
        # populate apps list from public apps registry; update favorite buttons after
        try:
            apps = async_to_sync(VizioAsync.get_apps_list)()
            self.apps_combo.clear()
            if apps:
                for a in apps:
                    self.apps_combo.addItem(str(a))
        except Exception:
            pass
        # refresh favorites UI
        try:
            self.update_favorite_buttons()
        except Exception:
            pass

    def add_selected_app_to_favorites(self):
        app = self.apps_combo.currentText()
        if not app:
            self.auth_status.setText("No app selected to add to favorites")
            return
        if app in self.favorites:
            self.auth_status.setText(f"App '{app}' already in favorites")
            return
        if len(self.favorites) >= 6:
            self.auth_status.setText("Favorites full (6). Remove one before adding")
            return
        self.favorites.append(app)
        self.update_favorite_buttons()
        # persist to saved device entry if applicable
        try:
            self.save_favorites_to_saved_devices()
        except Exception:
            pass
        self.auth_status.setText(f"Added '{app}' to favorites")

    def update_favorite_buttons(self):
        # update the UI text and enabled state for favorite buttons
        for i in range(6):
            b = self.fav_buttons[i]
            if i < len(self.favorites):
                b.setText(self.favorites[i])
                b.setEnabled(True if self.vizio else True)
            else:
                b.setText("-")
                b.setEnabled(False)

    def favorite_button_clicked(self, idx: int):
        if idx < 0 or idx >= len(self.favorites):
            return
        app = self.favorites[idx]
        if not app:
            return
        # launch the app (attempt) using current Vizio connection; if not connected, try to connect
        try:
            if not self.vizio:
                # attempt to connect to the selected saved device if present
                if isinstance(self.selected_device, dict) and self.selected_device.get('ip'):
                    ip = self.selected_device.get('ip')
                    port = self.selected_device.get('port')
                    if port:
                        ip = f"{ip}:{port}"
                    auth_token = self.auth_token_edit.text().strip()
                    device_type = self.device_type_combo.currentText().strip()
                    self.vizio = Vizio("pyvizio-gui", ip, self.selected_device.get('name', ''), auth_token, device_type, timeout=5)
                    self.set_controls_enabled(bool(auth_token))
            if self.vizio:
                self.vizio.launch_app(app)
                self.output.append(f"Launched favorite app {app}")
        except Exception as e:
            self.auth_status.setText(f"Failed to launch favorite: {e}")

    def save_favorites_to_saved_devices(self):
        # if the currently selected saved device exists in saved_devices, update its favorites list
        if not isinstance(self.selected_device, dict):
            return
        ip = self.selected_device.get('ip')
        port = self.selected_device.get('port')
        for d in self.saved_devices:
            if d.get('ip') == ip and d.get('port') == port:
                d['favorites'] = self.favorites
                self.save_saved_devices()
                self.load_saved_devices()
                return

    def launch_app(self):
        if not self.vizio:
            return
        app = self.apps_combo.currentText()
        if not app:
            return
        try:
            self.vizio.launch_app(app)
            self.output.append(f"Launched app {app}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Launch Error", str(e))

    def exec_and_show(self, method_name: str, *args):
        if not self.vizio:
            QtWidgets.QMessageBox.warning(self, "Execute", "No device connected")
            return
        try:
            meth = getattr(self.vizio, method_name)
        except AttributeError:
            QtWidgets.QMessageBox.warning(self, "Execute", f"Unknown method: {method_name}")
            return
        try:
            res = meth(*args)
            self.output.append(f"> {method_name} {args} -> {res}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Execute Error", str(e))

    def run_command(self):
        if not self.vizio:
            QtWidgets.QMessageBox.warning(self, "Command", "No device connected")
            return
        # If a command is selected in the dropdown, use it; otherwise parse full text
        selected = self.cmd_combo.currentText().strip() if hasattr(self, 'cmd_combo') else ''
        if selected:
            args_txt = self.cmd_input.text().strip()
            parts = [selected] + (args_txt.split() if args_txt else [])
        else:
            txt = self.cmd_input.text().strip()
            if not txt:
                return
            parts = txt.split()
        cmd = parts[0]
        args = []
        for p in parts[1:]:
            # try int conversion
            try:
                args.append(int(p))
            except ValueError:
                args.append(p)
        try:
            if not hasattr(self.vizio, cmd):
                QtWidgets.QMessageBox.warning(self, "Command", f"Unknown command: {cmd}")
                return
            meth = getattr(self.vizio, cmd)
            res = meth(*args)
            display = f"> {cmd} {' '.join(map(str, args))} -> {res}"
            self.output.append(display)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Command Error", str(e))

    def set_volume(self):
        # Set audio 'volume' setting to specified level
        if not self.vizio:
            QtWidgets.QMessageBox.warning(self, "Set Volume", "No device connected")
            return
        try:
            val = int(self.volume_spin.value())
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Set Volume", "Invalid volume value")
            return
        try:
            # set_audio_setting(setting_name, new_value)
            res = self.vizio.set_audio_setting("volume", val)
            self.output.append(f"> set_audio_setting volume {val} -> {res}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Set Volume Error", str(e))

    def send_direction(self, key_name: str):
        # Send navigation key via remote API
        if not self.vizio:
            self.auth_status.setText("No device connected to send navigation commands")
            return
        try:
            # use the Vizio.remote method
            res = self.vizio.remote(key_name)
            self.output.append(f"> NAV {key_name} -> {res}")
        except Exception as e:
            self.auth_status.setText(f"Navigation error: {e}")

    def keyPressEvent(self, event):
        # Capture arrow keys and Enter to control the TV
        try:
            key = event.key()
            if key == Qt.Key_Up:
                self.send_direction('UP')
                return
            if key == Qt.Key_Down:
                self.send_direction('DOWN')
                return
            if key == Qt.Key_Left:
                self.send_direction('LEFT')
                return
            if key == Qt.Key_Right:
                self.send_direction('RIGHT')
                return
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self.send_direction('OK')
                return
        except Exception:
            pass
        super().keyPressEvent(event)


    def on_auth_token_changed(self, text):
        # update displayed token whenever auth field changes
        try:
            self.display_token_edit.setText(text)
        except Exception:
            pass

    def copy_token(self):
        try:
            QtWidgets.QApplication.clipboard().setText(self.display_token_edit.text())
            self.auth_status.setText("Auth token copied to clipboard")
        except Exception as e:
            self.auth_status.setText(f"Copy failed: {e}")


def apply_dark_theme(app):
    # Minimal dark stylesheet
    sheet = """
    QWidget { background: #2b2b2b; color: #dcdcdc; font-family: Segoe UI, Arial; }
    QLineEdit, QTextEdit, QComboBox, QSpinBox { background: #3c3c3c; color: #ffffff; border: 1px solid #555555; }
    QPushButton { background: #4b6eaf; color: white; border-radius: 4px; padding: 6px; }
    QPushButton:disabled { background: #555555; color: #999999; }
    QGroupBox { border: 1px solid #444444; margin-top: 6px; }
    QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px 0 3px; }
    QLabel { color: #dcdcdc; }
    QListWidget { background: #313131; border: 1px solid #444; }
    QScrollBar:vertical { background: #262626; width: 12px; }
    """
    app.setStyleSheet(sheet)


def run_gui():
    app = QtWidgets.QApplication([])
    apply_dark_theme(app)
    w = ExtendedWindow()
    w.show()
    app.exec_()


if __name__ == '__main__':
    run_gui()
