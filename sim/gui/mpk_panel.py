#!/usr/bin/env python3
"""MPK Mini Plus panel for the hackai-mpk simulator.

Starts Renode headless with its monitor on a TCP port, runs the stock
firmware (sim/mpk.resc) and shows the controller: OLED, pad and button LEDs,
clickable buttons (left click: momentary; right click: latch, to hold
several at once). Two side panels help reverse-engineering:

  - Key matrix: press any row/column position and watch what the firmware does.
  - LED outputs: brightness of the 56 outputs of the shift-register chain.

    make gui            (or: .venv/bin/python sim/gui/mpk_panel.py)
"""

import argparse
import os
import queue
import re
import socket
import sys
import threading
import time
import tomllib
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (QApplication, QDockWidget, QGraphicsPixmapItem,
                               QGraphicsRectItem, QGraphicsScene, QGraphicsView,
                               QGridLayout, QLabel, QMainWindow, QPlainTextEdit,
                               QPushButton, QToolBar, QWidget)

ROOT = Path(__file__).resolve().parents[2]
GUI = Path(__file__).resolve().parent
RENODE = os.environ.get("RENODE", "/opt/renode_1.17.0-portable/renode")
PROMPT = b"(mpk) "
LED_OUTPUTS = 56


# ---------------------------------------------------------------------------
# Renode monitor client
# ---------------------------------------------------------------------------

class Monitor:
    """Talks to the Renode monitor over TCP in a background thread.

    Commands are queued; the thread also polls the OLED and the LEDs.
    Results go to `results` as (kind, value) tuples, which the GUI thread
    drains with a timer. (No Qt signals from this plain Python thread: that
    crashes PySide6.)
    """

    def __init__(self, port, poll_interval=0.05):
        self.port = port
        self.poll_interval = poll_interval
        self.commands = queue.Queue()
        self.results = queue.Queue()
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.running = False

    def send(self, command):
        self.commands.put(command)

    def run(self):
        sock = None
        for _ in range(200):
            try:
                sock = socket.create_connection(("127.0.0.1", self.port), timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        if sock is None:
            self.results.put(("message", "could not connect to the Renode monitor"))
            return
        self.sock = sock
        self.buffer = b""
        self.read_until_prompt(timeout=60)  # banner and the startup script
        self.results.put(("message", "connected to Renode"))

        while self.running:
            while not self.commands.empty():
                command = self.commands.get()
                reply = self.execute(command)
                if reply:
                    self.results.put(("message", f"{command}: {reply}"))
            fb = self.execute("spi2.oled Framebuffer")
            if re.fullmatch(r"[0-9A-F]+", fb or ""):
                self.results.put(("framebuffer", bytes.fromhex(fb)))
            leds = self.execute("spi1.leds Brightness")
            values = (leds or "").split()
            if len(values) == LED_OUTPUTS:
                self.results.put(("leds", [int(v) for v in values]))
            time.sleep(self.poll_interval)
        try:
            self.sock.sendall(b"quit\n")
        except OSError:
            pass

    def execute(self, command):
        self.sock.sendall(command.encode() + b"\n")
        raw = self.read_until_prompt()
        text = raw.decode(errors="replace").replace("\r", "")
        lines = [line for line in text.split("\n") if line.strip()]
        if lines and lines[0].strip().endswith(command):
            lines = lines[1:]  # the monitor echoes the command
        return "\n".join(lines).strip()

    def read_until_prompt(self, timeout=10):
        self.sock.settimeout(timeout)
        while PROMPT not in self.buffer:
            try:
                data = self.sock.recv(65536)
            except socket.timeout:
                break
            if not data:
                break
            self.buffer += data
        head, _, self.buffer = self.buffer.partition(PROMPT)
        return re.sub(rb"\xff[\xfb-\xfe].", b"", head)  # telnet negotiation


# ---------------------------------------------------------------------------
# Panel items
# ---------------------------------------------------------------------------

class LedOverlay(QGraphicsRectItem):
    """A translucent rectangle over an SVG element, tinted by LED brightness.

    `on_press(down)` is called when it is pressed (down=True) and released.
    Left click: momentary. Right click: latch (stays pressed until the next
    right click), so several buttons can be held at once. Latched buttons
    marked `modifier` in the TOML (SHIFT) release themselves after the next
    press of another button.
    """

    def __init__(self, rect, radius=4, on_press=None):
        super().__init__(rect)
        self.radius = radius
        self.on_press = on_press
        self.color = QColor(0, 0, 0, 0)
        self.held = False
        self.latched = False
        self.setPen(Qt.NoPen)
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton if on_press else Qt.NoButton)
        if on_press:
            self.setCursor(Qt.PointingHandCursor)

    def set_color(self, color):
        if color != self.color:
            self.color = color
            self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(self.color))
        if self.latched:
            painter.setPen(QPen(QColor(255, 200, 0), 3))
        elif self.held:
            painter.setPen(QPen(QColor(255, 255, 255, 160), 2))
        else:
            painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), self.radius, self.radius)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.latched = not self.latched
            self.update()
            self.on_press(self.latched)
            return
        if self.latched:
            return  # already held by the latch
        self.held = True
        self.update()
        self.on_press(True)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton or self.latched:
            return
        self.held = False
        self.update()
        self.on_press(False)


def element_rect(renderer, element_id):
    return renderer.transformForElement(element_id).mapRect(renderer.boundsOnElement(element_id))


class PanelView(QGraphicsView):
    def __init__(self, config, monitor, log):
        super().__init__()
        self.config = config
        self.monitor = monitor
        self.log = log
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#18181a"))

        self.renderer = QSvgRenderer(str(GUI / "mpk_mini_plus.svg"))
        scene = QGraphicsScene(self)
        panel = QGraphicsSvgItem()
        panel.setSharedRenderer(self.renderer)
        scene.addItem(panel)
        self.setScene(scene)

        oled = config["oled"]
        self.oled_size = (oled["width"], oled["height"])
        self.oled_color = QColor(oled["color"])
        self.oled_rect = element_rect(self.renderer, oled["id"])
        self.oled_item = QGraphicsPixmapItem()
        self.oled_item.setPos(self.oled_rect.topLeft())
        self.oled_item.setTransformationMode(Qt.FastTransformation)
        scene.addItem(self.oled_item)

        self.pads = []
        for n in range(1, 9):
            item = LedOverlay(element_rect(self.renderer, f"pad{n}"), radius=5)
            scene.addItem(item)
            self.pads.append(item)

        self.buttons = {}
        for name, info in config["buttons"].items():
            matrix = info.get("matrix")
            press = (lambda down, m=matrix, n=name: self.press_button(n, m, down))
            item = LedOverlay(element_rect(self.renderer, name), radius=3, on_press=press)
            item.setToolTip(f"{name}\nLED: {info.get('led', '?')}  matrix: {matrix or '?'}")
            scene.addItem(item)
            self.buttons[name] = (item, info)

    LEGEND = "Click: press  ·  Right-click: hold / release  (SHIFT: until the next button)"

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def drawForeground(self, painter, rect):
        # Usage hint in the bottom-right corner of the view, in viewport
        # coordinates so it stays put whatever the zoom.
        painter.save()
        painter.resetTransform()
        painter.setPen(QColor(150, 150, 155))
        font = painter.font()
        font.setPointSizeF(8.5)
        painter.setFont(font)
        area = self.viewport().rect().adjusted(0, 0, -10, -6)
        painter.drawText(area, Qt.AlignRight | Qt.AlignBottom, self.LEGEND)
        painter.restore()

    def press_button(self, name, matrix, down):
        if matrix is None:
            self.log(f"{name}: key matrix position unknown "
                     "(set it in sim/gui/mpk_mini_plus.toml)")
            return
        verb = "Press" if down else "Release"
        self.log(f"{verb.lower()} {name} (matrix {matrix[0]},{matrix[1]})")
        self.monitor.send(f"keys {verb} {matrix[0]} {matrix[1]}")
        # Sticky modifiers (SHIFT): a latched modifier is released after the
        # next press of any other button, like on-screen keyboards.
        if not down and not self.buttons[name][1].get("modifier"):
            for other, (item, info) in self.buttons.items():
                if info.get("modifier") and item.latched and other != name:
                    item.latched = False
                    item.update()
                    self.press_button(other, info.get("matrix"), False)

    def show_framebuffer(self, data):
        # The framebuffer is already Qt's 1-bit format: MSB = leftmost pixel.
        w, h = self.oled_size
        image = QImage(data, w, h, w // 8, QImage.Format_Mono).copy()
        image.setColorTable([QColor(0, 0, 0).rgb(), self.oled_color.rgb()])
        pixmap = QPixmap.fromImage(image).scaled(
            int(self.oled_rect.width()), int(self.oled_rect.height()),
            Qt.IgnoreAspectRatio, Qt.FastTransformation)
        self.oled_item.setPixmap(pixmap)

    def show_leds(self, values):
        pads = self.config["pads"]
        r_off, g_off, b_off = pads["rgb_offsets"]
        for item, triplet in zip(self.pads, pads["triplet"]):
            base = pads["first_output"] + 3 * triplet
            rgb = [values[base + off] for off in (r_off, g_off, b_off)]
            level = max(rgb)
            item.set_color(QColor(*(min(255, v * 255 // 100) for v in rgb),
                                  min(220, 60 + level * 2) if level else 0))
        for item, info in self.buttons.values():
            led = info.get("led")
            if isinstance(led, int):
                # Single-colour LED: shown in a warm white.
                v = values[led]
                item.set_color(QColor(255, 80, 40, min(200, v * 2)) if v else QColor(0, 0, 0, 0))
            elif isinstance(led, dict):
                # Multi-colour LED: {red = output, green = output, blue = output}.
                rgb = [values[led[c]] if c in led else 0 for c in ("red", "green", "blue")]
                level = max(rgb)
                item.set_color(QColor(*(min(255, v * 255 // 100) for v in rgb), min(220, level * 2))
                               if level else QColor(0, 0, 0, 0))


# ---------------------------------------------------------------------------
# Reverse-engineering panels
# ---------------------------------------------------------------------------

class MatrixButton(QPushButton):
    """Left click: momentary press. Right click: latch / unlatch."""

    def __init__(self, row, column, monitor):
        super().__init__(f"{row},{column}")
        self.command = f"{row} {column}"
        self.monitor = monitor
        self.latched = False
        self.pressed.connect(lambda: self.latched or monitor.send(f"keys Press {self.command}"))
        self.released.connect(lambda: self.latched or monitor.send(f"keys Release {self.command}"))

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.latched = not self.latched
            verb = "Press" if self.latched else "Release"
            self.monitor.send(f"keys {verb} {self.command}")
            self.setStyleSheet("background: #e8b400; font-weight: bold;" if self.latched else "")
            return
        super().mousePressEvent(event)


class MatrixPanel(QWidget):
    """Grid of all key matrix positions. Left click: hold while the mouse is
    down. Right click: latch the key (to hold several at once)."""

    def __init__(self, rows, columns, monitor):
        super().__init__()
        layout = QGridLayout(self)
        for c in range(columns):
            layout.addWidget(QLabel(f"PC{8 + c}", alignment=Qt.AlignCenter), 0, c + 1)
        for r in range(rows):
            layout.addWidget(QLabel(f"row {r}"), r + 1, 0)
            for c in range(columns):
                layout.addWidget(MatrixButton(r, c, monitor), r + 1, c + 1)


class LedPanel(QWidget):
    """The 56 outputs of the LED chain, 8 per byte, with their brightness."""

    def __init__(self):
        super().__init__()
        layout = QGridLayout(self)
        layout.setSpacing(2)
        self.cells = []
        for k in range(LED_OUTPUTS):
            cell = QLabel(str(k), alignment=Qt.AlignCenter)
            cell.setMinimumSize(30, 22)
            layout.addWidget(cell, k // 8, k % 8)
            self.cells.append(cell)
        self.show_leds([0] * LED_OUTPUTS)

    def show_leds(self, values):
        for k, (cell, v) in enumerate(zip(self.cells, values)):
            shade = 40 + v * 2
            fg = "#000" if v > 50 else "#ccc"
            cell.setStyleSheet(f"background: rgb({shade},{shade // 2},{shade // 3}); color: {fg};"
                               "border-radius: 3px;")
            cell.setToolTip(f"output {k}: {v} %")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, port):
        super().__init__()
        self.setWindowTitle("hackai-mpk · MPK Mini Plus simulator")
        with open(GUI / "mpk_mini_plus.toml", "rb") as f:
            config = tomllib.load(f)

        self.renode = QProcess(self)
        self.renode.setWorkingDirectory(str(ROOT))
        self.renode.setProcessChannelMode(QProcess.MergedChannels)
        self.renode.readyReadStandardOutput.connect(self.renode_output)
        self.renode.start(RENODE, ["--disable-gui", "--plain", "--port", str(port), "-e",
                                   "include @sim/mpk.resc; include @sim/quiet.resc; start"])

        self.monitor = Monitor(port)
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setMaximumBlockCount(2000)
        self.panel = PanelView(config, self.monitor, self.log.appendPlainText)
        self.setCentralWidget(self.panel)

        self.add_dock("Log", self.log, Qt.BottomDockWidgetArea)
        self.leds = LedPanel()
        self.add_dock("LED outputs", self.leds, Qt.RightDockWidgetArea)
        matrix = config["matrix"]
        self.add_dock("Key matrix", MatrixPanel(matrix["rows"], matrix["columns"], self.monitor),
                      Qt.RightDockWidgetArea)

        toolbar = QToolBar()
        self.addToolBar(toolbar)
        toolbar.addAction("Pause", lambda: self.monitor.send("pause"))
        toolbar.addAction("Continue", lambda: self.monitor.send("start"))
        toolbar.addAction("Reset", lambda: self.monitor.send("machine Reset"))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.drain_results)
        self.timer.start(30)
        self.monitor.start()
        self.resize(1500, 720)

    def drain_results(self):
        latest = {}
        while not self.monitor.results.empty():
            kind, value = self.monitor.results.get()
            if kind == "message":
                self.log.appendPlainText(value)
            else:
                latest[kind] = value  # only the newest frame matters
        if "framebuffer" in latest:
            self.panel.show_framebuffer(latest["framebuffer"])
        if "leds" in latest:
            self.panel.show_leds(latest["leds"])
            self.leds.show_leds(latest["leds"])

    def add_dock(self, title, widget, area):
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)

    def renode_output(self):
        text = bytes(self.renode.readAllStandardOutput()).decode(errors="replace")
        for line in text.replace("\r", "").splitlines():
            if "WARNING" in line or "ERROR" in line or "rror" in line:
                self.log.appendPlainText(line)

    def closeEvent(self, event):
        self.monitor.stop()
        self.renode.waitForFinished(2000)
        if self.renode.state() != QProcess.NotRunning:
            self.renode.kill()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=4321, help="Renode monitor port")
    parser.add_argument("--screenshot", type=Path, metavar="PNG",
                        help="save a screenshot after --seconds and quit (for tests)")
    parser.add_argument("--seconds", type=float, default=20)
    args = parser.parse_args()
    app = QApplication(sys.argv)
    window = MainWindow(args.port)
    window.show()
    if args.screenshot:
        def capture():
            window.grab().save(str(args.screenshot))
            window.close()
        QTimer.singleShot(int(args.seconds * 1000), capture)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
