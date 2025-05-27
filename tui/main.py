import serial
import serial.tools.list_ports
import threading
import npyscreen
import re
import time


def choose_serial_port():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("❌ No serial ports found.")
        exit(1)

    print("🔌 Available serial ports:")
    for i, p in enumerate(ports):
        print(f"  {i}: {p.device} - {p.description}")

    if len(ports) == 1:
        print(f"➡️  Automatically selected: {ports[0].device}")
        return ports[0].device

    idx = input("Select port number: ")
    try:
        return ports[int(idx)].device
    except:
        print("❌ Invalid selection.")
        exit(1)


SERIAL_PORT = choose_serial_port()
BAUD_RATE = 115200


class SerialHandler:
    def __init__(self, port, baud):
        self.ser = serial.Serial(port, baud, timeout=1)
        self.lock = threading.Lock()
        self.listeners = []
        self.running = True
        threading.Thread(target=self.read_loop, daemon=True).start()

    def read_loop(self):
        while self.running:
            try:
                line = self.ser.readline().decode(errors='ignore').strip()
                if line:
                    for listener in self.listeners:
                        listener(line)
            except Exception as e:
                print("Serial error:", e)

    def write(self, msg):
        with self.lock:
            self.ser.write((msg + "\n").encode())

    def add_listener(self, func):
        self.listeners.append(func)

    def close(self):
        self.running = False
        self.ser.close()


class DeautherApp(npyscreen.NPSAppManaged):
    def onStart(self):
        self.serial_handler = SerialHandler(SERIAL_PORT, BAUD_RATE)
        self.networks = []
        self.addForm("MAIN", MainForm, name="BW16 Deauther Controller")

    def onCleanExit(self):
        self.serial_handler.close()


class MainForm(npyscreen.FormBaseNew):
    def create(self):
        self.status = self.add(npyscreen.FixedText, value="Status: Ready", editable=False)
        self.network_list = self.add(npyscreen.MultiSelect, max_height=12, name="WiFi Networks (space to select/deselect):", values=[])

        self.add(npyscreen.ButtonPress, name="[S] Scan", when_pressed_function=self.do_scan)
        self.add(npyscreen.ButtonPress, name="[A] Start Attack", when_pressed_function=self.do_attack)
        self.add(npyscreen.ButtonPress, name="[W] Stop", when_pressed_function=self.do_stop)
        self.add(npyscreen.ButtonPress, name="[+] Select All", when_pressed_function=self.select_all)
        self.add(npyscreen.ButtonPress, name="[-] Deselect All", when_pressed_function=self.deselect_all)

        self.frames_input = self.add(npyscreen.TitleText, name="Frames per target:", value="5")
        self.delay_input = self.add(npyscreen.TitleText, name="Delay (ms):", value="5")
        self.add(npyscreen.ButtonPress, name="[C] Set Config", when_pressed_function=self.set_config)
        self.add(npyscreen.ButtonPress, name="[Q] Quit", when_pressed_function=self.quit_app)

        self.scan_results = []
        self.attack_running = False
        self.attack_counter = 0
        self.attack_total = 0

        self.parentApp.serial_handler.add_listener(self.serial_event)

        self.update_thread = threading.Thread(target=self.update_status, daemon=True)
        self.update_thread.start()

        # 🔑 Shortcut handling:
        self.add_handlers({
            ord('s'): self.do_scan,
            ord('a'): self.do_attack,
            ord('w'): self.do_stop,
            ord('c'): self.set_config,
            ord('+'): self.select_all,
            ord('-'): self.deselect_all,
            ord('q'): self.quit_app,
        })


    def afterEditing(self):
        # Automatically scan after UI starts
        self.do_scan()

    def update_status(self):
        while True:
            time.sleep(1)
            if self.attack_running and self.attack_total > 0:
                self.attack_counter = (self.attack_counter + 1) % self.attack_total
                msg = f"⚡ Attacking {self.attack_counter + 1} of {self.attack_total}"
                self.status.value = f"Status: {msg}"
                self.status.display()

    def do_scan(self, *args, **keywords):
        self.scan_results.clear()
        self.network_list.values = []
        self.network_list.display()
        self.status.value = "Status: Scanning..."
        self.status.display()
        self.parentApp.serial_handler.write("SCAN")

    def do_attack(self, *args, **keywords):
        sel = self.network_list.value
        if not sel:
            self.status.value = "Status: Select at least one network"
            self.status.display()
            return

        cmd = "DEAUTH " + ",".join(str(i) for i in sel)
        self.parentApp.serial_handler.write(cmd)
        self.attack_total = len(sel)
        self.attack_counter = 0
        self.attack_running = True

    def do_stop(self, *args, **keywords):
        self.parentApp.serial_handler.write("STOP")
        self.attack_running = False
        self.status.value = "Status: Attack stopped"
        self.status.display()

    def set_config(self, *args, **keywords):
        frames = self.frames_input.value.strip()
        delay = self.delay_input.value.strip()
        if frames.isdigit():
            self.parentApp.serial_handler.write(f"SET FRAMES {frames}")
        if delay.isdigit():
            self.parentApp.serial_handler.write(f"SET DELAY {delay}")
        self.status.value = "Status: Config updated"
        self.status.display()
    def select_all(self, *args, **kwargs):
        self.network_list.value = list(range(len(self.network_list.values)))
        self.network_list.display()
        self.status.value = "Status: All networks selected"
        self.status.display()

    def deselect_all(self, *args, **kwargs):
        self.network_list.value = []
        self.network_list.display()
        self.status.value = "Status: Selection cleared"
        self.status.display()


    def serial_event(self, line):
        if "SCAN_RESULT" in line:
            try:
                ssid = re.search(r'SSID="([^"]*)"', line).group(1)
                bssid = re.search(r'BSSID="([^"]*)"', line).group(1)
                rssi = int(re.search(r'RSSI=(-?\d+)', line).group(1))
                ch = re.search(r'CH=(\d+)', line).group(1)

                entry = {
                    "ssid": ssid or "**HIDDEN**",
                    "bssid": bssid,
                    "rssi": rssi,
                    "ch": ch
                }

                self.scan_results.append(entry)

            except Exception as e:
                self.status.value = f"Parse error: {e}"
                self.status.display()

        elif "DONE" in line:
            # Sort by signal strength (descending)
            self.scan_results.sort(key=lambda x: x["rssi"], reverse=True)
            self.network_list.values = [
                f"{net['ssid']} | CH:{net['ch']} | RSSI:{net['rssi']} | {net['bssid']}"
                for net in self.scan_results
            ]
            self.network_list.display()
            self.status.value = "Status: Scan complete"
            self.status.display()

        elif "ATTACK_STARTED" in line:
            self.attack_running = True
            self.status.value = "Status: Attack started"
            self.status.display()
        elif "ATTACK_STOPPED" in line:
            self.attack_running = False
            self.status.value = "Status: Attack stopped"
            self.status.display()

    def quit_app(self, *args, **kwargs):
        self.status.value = "Exiting..."
        self.status.display()
        time.sleep(0.5)
        self.parentApp.setNextForm(None)
        self.editing = False


if __name__ == "__main__":
    try:
        DeautherApp().run()
    except Exception as e:
        print("Fatal error:", e)
