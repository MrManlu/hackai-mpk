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

from PySide6.QtCore import QPointF, QProcess, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (QApplication, QDockWidget, QGraphicsEllipseItem,
                               QGraphicsPixmapItem,
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
        self.midi_count = 0
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
            try:
                count = int(self.execute("midiOut Count"), 0)   # Renode replies in hex
            except ValueError:
                count = self.midi_count
            if count != self.midi_count:
                new = min(count - self.midi_count, 200)
                self.midi_count = count
                lines = self.execute(f"midiOut Messages {new}").splitlines()
                self.results.put(("midi", [l for l in lines if " s  " in l]))
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
# JACK MIDI bridge
# ---------------------------------------------------------------------------

class JackBridge:
    """JACK MIDI ports bridged to the simulated 5-pin DIN MIDI.

    `din_out`: what the firmware sends on USART1 (decoded by `midiOut`).
    `din_in`: events sent to it are injected into USART1, as if they came
    through the DIN IN socket.

    Uses JACK through PipeWire (run the GUI with `pw-jack`, `make gui
    JACK=1`). The ALSA sequencer is deliberately not used: on some kernels
    freeing its clients deadlocks snd-seq (see docs/simulator.md)."""

    NAME = "MPK Mini Plus sim"

    def __init__(self, monitor, log):
        self.client = None
        try:
            import jack
            self.client = jack.Client(self.NAME, no_start_server=True)
        except Exception as error:   # no JACK-Client, or no JACK/PipeWire server
            log(f"JACK MIDI bridge off: {error}")
            return
        self.pending = queue.SimpleQueue()
        self.din_out = self.client.midi_outports.register("din_out")
        self.din_in = self.client.midi_inports.register("din_in")

        @self.client.set_process_callback
        def process(frames):
            self.din_out.clear_buffer()
            while True:
                try:
                    self.din_out.write_midi_event(0, self.pending.get_nowait())
                except queue.Empty:
                    break
            for _, data in self.din_in.incoming_midi_events():
                for byte in bytes(data):
                    monitor.send(f"usart1 WriteChar 0x{byte:02X}")

        self.client.activate()
        log(f'JACK MIDI ports "{self.NAME}:din_out" (firmware DIN OUT) and '
            f'"{self.NAME}:din_in" (to DIN IN)')

    @classmethod
    def disabled(cls):
        bridge = cls.__new__(cls)
        bridge.client = None
        return bridge

    def close(self):
        if self.client:
            self.client.deactivate()
            self.client.close()
            self.client = None

    def send_lines(self, lines):
        """Forward lines of `midiOut Messages` (the hex column) to din_out."""
        if not self.client:
            return
        for line in lines:
            match = re.search(r" s  ((?:[0-9A-F]{2} )+)", line + " ")
            if match:
                self.pending.put(bytes(int(b, 16) for b in match.group(1).split()))


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


def triangle(angle):
    """Wiper of an endless potentiometer: 0..4095..0 over 360 degrees."""
    angle %= 360
    return int(4095 * (angle / 180 if angle < 180 else (360 - angle) / 180))


class KnobItem(QGraphicsEllipseItem):
    """Endless knob: mouse wheel or vertical drag turns it. Drives two
    wipers 90 degrees apart (b lags a when turning clockwise)."""

    def __init__(self, rect, send):
        super().__init__(rect)
        self.send = send
        self.angle = 0.0
        self.last_y = None
        self.setPen(Qt.NoPen)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("Turn: mouse wheel or drag up/down")

    def turn(self, degrees):
        self.angle = (self.angle + degrees) % 360
        self.send(self.angle)
        self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        painter.setPen(QPen(QColor("#444"), 2))
        painter.setBrush(QColor("#1a1a1a"))
        painter.drawEllipse(r)
        painter.save()
        painter.translate(r.center())
        painter.rotate(self.angle)
        painter.setPen(QPen(QColor("#ddd"), 2))
        painter.drawLine(QPointF(0, 0), QPointF(0, -r.height() / 2 + 4))
        painter.restore()

    def wheelEvent(self, event):
        self.turn(6 if event.delta() > 0 else -6)

    def mousePressEvent(self, event):
        self.last_y = event.scenePos().y()

    def mouseMoveEvent(self, event):
        y = event.scenePos().y()
        self.turn((self.last_y - y) * 2)
        self.last_y = y


class EncoderItem(QGraphicsEllipseItem):
    """Detented encoder: mouse wheel or vertical drag turns it (one detent
    per wheel step or per 12 units of drag), click pushes it."""

    def __init__(self, rect, turn, push):
        super().__init__(rect)
        self.turn_cb = turn
        self.push_cb = push
        self.angle = 0.0
        self.last_y = None
        self.dragged = 0.0
        self.setPen(Qt.NoPen)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Turn: mouse wheel or drag up/down · Click: push")

    def turn(self, detents):
        self.angle = (self.angle + 18 * detents) % 360
        self.turn_cb(detents)
        self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        painter.setPen(QPen(QColor("#444"), 2))
        painter.setBrush(QColor("#1a1a1a") if self.last_y is None else QColor("#2c2c2c"))
        painter.drawEllipse(r)
        painter.save()
        painter.translate(r.center())
        painter.rotate(self.angle)
        painter.setPen(QPen(QColor("#999"), 2))
        painter.drawLine(QPointF(0, -r.height() / 2 + 4), QPointF(0, -r.height() / 2 + 10))
        painter.restore()

    def wheelEvent(self, event):
        self.turn(1 if event.delta() > 0 else -1)

    def mousePressEvent(self, event):
        self.last_y = event.scenePos().y()
        self.dragged = 0.0
        self.push_cb(True)
        self.update()

    def mouseMoveEvent(self, event):
        y = event.scenePos().y()
        self.dragged += self.last_y - y
        self.last_y = y
        while abs(self.dragged) >= 12:
            step = 1 if self.dragged > 0 else -1
            self.turn(step)
            self.dragged -= 12 * step

    def mouseReleaseEvent(self, event):
        self.last_y = None
        self.push_cb(False)
        self.update()


BLACK_KEYS = {1, 3, 6, 8, 10}


class KeyItem(QGraphicsRectItem):
    """A keybed key. The click height sets the speed of the key: near the
    front edge (bottom) is fast and loud, near the back is slow and soft.
    Right click latches the key down."""

    def __init__(self, rect, key, press):
        super().__init__(rect)
        self.key = key
        self.press_cb = press
        self.down = False
        self.latched = False
        self.setPen(Qt.NoPen)
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton)
        self.setZValue(2 if key % 12 in BLACK_KEYS else 1)

    def travel_from_y(self, y):
        r = self.rect()
        depth = min(1.0, max(0.0, (y - r.top()) / r.height()))   # 0 back, 1 front
        return int(80000 * (1 - depth) ** 2 + 2000)               # 82 ms .. 2 ms

    def set_down(self, down, travel=6000):
        if down != self.down:
            self.down = down
            self.press_cb(self.key, down, travel)
            self.update()

    def paint(self, painter, option, widget=None):
        if self.down:
            painter.setBrush(QColor(60, 140, 255, 110 if self.key % 12 in BLACK_KEYS else 80))
            painter.setPen(QPen(QColor(255, 200, 0), 3) if self.latched else Qt.NoPen)
            painter.drawRoundedRect(self.rect(), 2, 2)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.latched = not self.latched
            self.set_down(self.latched, self.travel_from_y(event.scenePos().y()))
            return
        if not self.latched:
            self.set_down(True, self.travel_from_y(event.scenePos().y()))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self.latched:
            self.set_down(False)


class WheelItem(QGraphicsRectItem):
    """Pitch or modulation wheel: drag up/down. With `spring`, it goes back
    to rest when released (pitch)."""

    def __init__(self, rect, info, send):
        super().__init__(rect)
        self.info = info
        self.send = send
        span = info["max"] - info["min"]
        self.position = (info["rest"] - info["min"]) / span   # 0 = bottom, 1 = top
        self.setPen(Qt.NoPen)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setCursor(Qt.SizeVerCursor)

    def value(self):
        return int(self.info["min"] + self.position * (self.info["max"] - self.info["min"]))

    def set_from_y(self, y):
        r = self.rect()
        self.position = min(1.0, max(0.0, (r.bottom() - y) / r.height()))
        self.send(self.value())
        self.update()

    def paint(self, painter, option, widget=None):
        r = self.rect()
        y = r.bottom() - self.position * r.height()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(220, 220, 220, 200))
        painter.drawRoundedRect(QRectF(r.left() + 4, y - 3, r.width() - 8, 6), 2, 2)

    def mousePressEvent(self, event):
        self.set_from_y(event.scenePos().y())

    def mouseMoveEvent(self, event):
        self.set_from_y(event.scenePos().y())

    def mouseReleaseEvent(self, event):
        if self.info.get("spring"):
            span = self.info["max"] - self.info["min"]
            self.position = (self.info["rest"] - self.info["min"]) / span
            self.send(self.value())
            self.update()


class JoystickItem(QGraphicsEllipseItem):
    """X/Y joystick: drag; springs back to the centre."""

    def __init__(self, rect, info, send):
        super().__init__(rect)
        self.info = info
        self.send = send
        self.offset = QPointF(0, 0)
        self.setPen(Qt.NoPen)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setCursor(Qt.OpenHandCursor)

    def axis_value(self, d):
        i = self.info
        return int(i["rest"] + d * ((i["max"] - i["rest"]) if d > 0 else (i["rest"] - i["min"])))

    def move_to(self, pos):
        radius = self.info["radius"]
        d = pos - self.rect().center()
        length = (d.x() ** 2 + d.y() ** 2) ** 0.5
        if length > radius:
            d = d * (radius / length)
        self.offset = d
        self.send(self.axis_value(d.x() / radius), self.axis_value(-d.y() / radius))
        self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        painter.setPen(QPen(QColor("#111"), 2))
        painter.setBrush(QColor("#d01a1a"))
        painter.drawEllipse(r.translated(self.offset * 0.35))

    def mousePressEvent(self, event):
        self.move_to(event.scenePos())

    def mouseMoveEvent(self, event):
        self.move_to(event.scenePos())

    def mouseReleaseEvent(self, event):
        self.move_to(self.rect().center())


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

        analog = config.get("analog", {})
        pads = analog.get("pads", {})
        self.pads = []
        for n in range(1, 9):
            inputs = pads.get(f"pad{n}")
            press = (lambda down, i=inputs, n=n: self.press_pad(n, i, down)) if inputs else None
            item = LedOverlay(element_rect(self.renderer, f"pad{n}"), radius=5, on_press=press)
            scene.addItem(item)
            self.pads.append(item)
        self.pad_pressure = pads.get("pressure", 3500)

        self.analog_items = []
        for name, info in analog.get("knobs", {}).items():
            send = (lambda angle, i=info: self.set_knob(i, angle))
            item = KnobItem(element_rect(self.renderer, name), send)
            scene.addItem(item)
            # Knobs are not sent at connect: any initial value looks like a
            # turn to the firmware. The first turn from the GUI jumps once.
            self.analog_items.append((item, lambda: None))
        for name, info in analog.get("wheels", {}).items():
            send = (lambda value, i=info: self.set_input(i["input"], value))
            item = WheelItem(element_rect(self.renderer, name), info, send)
            scene.addItem(item)
            self.analog_items.append((item, lambda it=item: it.send(it.value())))
        self.keys = []
        for k in range(37):
            item = KeyItem(element_rect(self.renderer, f"key{k}"), k, self.press_key)
            scene.addItem(item)
            self.keys.append(item)
        self.setFocusPolicy(Qt.StrongFocus)

        encoder = config.get("encoder")
        if encoder:
            push = encoder["push"]
            item = EncoderItem(
                element_rect(self.renderer, encoder["id"]),
                lambda detents: self.monitor.send(f"encoder Turn {detents}"),
                lambda down, p=push: self.monitor.send(
                    f"keys {'Press' if down else 'Release'} {p[0]} {p[1]}"))
            scene.addItem(item)
        joystick = analog.get("joystick")
        if joystick:
            send = (lambda x, y, j=joystick: (self.set_input(j["x"], x), self.set_input(j["y"], y)))
            item = JoystickItem(element_rect(self.renderer, joystick["id"]), joystick, send)
            scene.addItem(item)
            self.analog_items.append((item, lambda it=item: it.move_to(it.rect().center())))

        self.buttons = {}
        for name, info in config["buttons"].items():
            matrix = info.get("matrix")
            press = (lambda down, m=matrix, n=name: self.press_button(n, m, down))
            item = LedOverlay(element_rect(self.renderer, name), radius=3, on_press=press)
            item.setToolTip(f"{name}\nLED: {info.get('led', '?')}  matrix: {matrix or '?'}")
            scene.addItem(item)
            self.buttons[name] = (item, info)

    LEGEND = ("Click: press  ·  Right-click: hold / release (SHIFT: until the next button)"
              "  ·  Keys: click lower = louder\n"
              "Knobs, encoder: wheel or drag (encoder click: push)  ·  Wheels, joystick: drag"
              "  ·  Computer keyboard: A W S E D F T G Y H U J K O L")

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
        font.setPointSizeF(8)
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

    # Computer keyboard: one octave and a bit from the lowest C of the keybed.
    COMPUTER_KEYS = {Qt.Key_A: 0, Qt.Key_W: 1, Qt.Key_S: 2, Qt.Key_E: 3, Qt.Key_D: 4,
                     Qt.Key_F: 5, Qt.Key_T: 6, Qt.Key_G: 7, Qt.Key_Y: 8, Qt.Key_H: 9,
                     Qt.Key_U: 10, Qt.Key_J: 11, Qt.Key_K: 12, Qt.Key_O: 13, Qt.Key_L: 14}

    def press_key(self, key, down, travel):
        if down:
            self.monitor.send(f"keys KeyDown {key} {travel}")
        else:
            self.monitor.send(f"keys KeyUp {key}")

    def keyPressEvent(self, event):
        key = self.COMPUTER_KEYS.get(event.key())
        if key is not None and not event.isAutoRepeat():
            self.keys[key].set_down(True, 6000)
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        key = self.COMPUTER_KEYS.get(event.key())
        if key is not None and not event.isAutoRepeat():
            if not self.keys[key].latched:
                self.keys[key].set_down(False)
            return
        super().keyReleaseEvent(event)

    def set_input(self, position, value):
        self.monitor.send(f"adc1 SetInput {position[0]} {position[1]} {int(value)}")

    def set_knob(self, info, angle):
        self.set_input(info["a"], triangle(angle))
        self.set_input(info["b"], triangle(angle - 90))

    def press_pad(self, n, inputs, down):
        self.log(f"{'press' if down else 'release'} pad{n}")
        for position in inputs:
            self.set_input(position, self.pad_pressure if down else 0)

    def send_analog_rest(self):
        """Put every analog control in its rest position (called on connect)."""
        for _, send_rest in self.analog_items:
            send_rest()

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
    def __init__(self, port, jack=False):
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
        self.midi = QPlainTextEdit(readOnly=True)
        self.midi.setMaximumBlockCount(2000)
        self.midi.setStyleSheet("font-family: monospace;")
        self.add_dock("MIDI OUT (DIN)", self.midi, Qt.BottomDockWidgetArea)
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

        self.midi_bridge = (JackBridge(self.monitor, self.log.appendPlainText) if jack
                            else JackBridge.disabled())

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.drain_results)
        self.timer.start(30)
        self.monitor.start()
        self.resize(1500, 720)

    def drain_results(self):
        latest = {}
        while not self.monitor.results.empty():
            kind, value = self.monitor.results.get()
            if kind == "midi":
                for line in value:
                    self.midi.appendPlainText(line)
                self.midi_bridge.send_lines(value)
                continue
            if kind == "message":
                self.log.appendPlainText(value)
                if value == "connected to Renode":
                    self.panel.send_analog_rest()
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
        self.midi_bridge.close()
        self.monitor.stop()
        self.renode.waitForFinished(2000)
        if self.renode.state() != QProcess.NotRunning:
            self.renode.kill()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=4321, help="Renode monitor port")
    parser.add_argument("--jack", action="store_true",
                        help="bridge the simulated DIN MIDI to JACK ports (run under pw-jack)")
    parser.add_argument("--screenshot", type=Path, metavar="PNG",
                        help="save a screenshot after --seconds and quit (for tests)")
    parser.add_argument("--seconds", type=float, default=20)
    args = parser.parse_args()
    app = QApplication(sys.argv)
    window = MainWindow(args.port, jack=args.jack)
    window.show()
    if args.screenshot:
        def capture():
            window.grab().save(str(args.screenshot))
            window.close()
        QTimer.singleShot(int(args.seconds * 1000), capture)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
