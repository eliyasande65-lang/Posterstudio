"""Poster Studio v2 - a mobile poster / content creator built with Kivy.

Tabs (bottom bar) keep the screen uncluttered, one group of controls at a time:
  Add     text, image and 10 shapes
  Edit    duplicate, delete, lock, centre, reset, rotation, opacity
  Style   controls for the selected item (text / shape / image)
  Layers  raised 3D layer cards, selection, locking and layer ordering
  Page    poster size, background colour and gradient
"""
import math
import os
import time
import threading

from kivy.app import App
from kivy import kivy_data_dir
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.graphics import (Color, Ellipse, InstructionGroup, Line, Mesh,
                           Rectangle, RoundedRectangle)
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.colorpicker import ColorPicker
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup as _KivyPopup
from kivy.uix.scatter import Scatter
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.stencilview import StencilView
from kivy.uix.textinput import TextInput
from kivy.utils import get_color_from_hex, platform

from PIL import Image as PILImage
from PIL import ImageEnhance, ImageOps, ImageChops

APP_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(APP_DIR, "fonts")

# ----------------------------------------------------------------- theme --
# Black chrome: near-black surfaces, graphite metal buttons, silver accents.
UI_BG = get_color_from_hex("#050506")
UI_PANEL = get_color_from_hex("#0b0b0d")
UI_BTN = get_color_from_hex("#25262b")          # graphite metal
UI_ACCENT = get_color_from_hex("#cfd3da")       # polished silver
UI_DANGER = get_color_from_hex("#8a1426")       # dark red metal
UI_STEEL = get_color_from_hex("#3b3e46")        # gunmetal
UI_TEXT = (1, 1, 1, 1)
UI_TEXT_DARK = (0.03, 0.03, 0.04, 1)
UI_SILVER = (0.84, 0.87, 0.92, 1)
UI_EDGE = (0.50, 0.52, 0.58, 1)
SELECT_COLOR = (0.84, 0.88, 0.95, 1)
LOCKED_COLOR = (0.98, 0.62, 0.2, 1)

PALETTE = [
    "#000000", "#ffffff", "#1a1a1d", "#1fb58f", "#16a34a", "#0ea5e9",
    "#2563eb", "#7c3aed", "#db2777", "#dc2626", "#f97316", "#facc15",
]
SHAPE_FILLS = ["#1fb58f", "#0ea5e9", "#f97316", "#7c3aed", "#dc2626",
               "#facc15"]
SHAPES = [
    ("Rect", "rect"), ("Rounded", "round"), ("Circle", "circle"),
    ("Triangle", "triangle"), ("Diamond", "diamond"),
    ("Pentagon", "pentagon"), ("Hexagon", "hexagon"), ("Star", "star"),
    ("Heart", "heart"), ("Line", "line"),
]
RATIOS = [("4:5", 0.8), ("1:1", 1.0), ("9:16", 9 / 16), ("16:9", 16 / 9),
          ("A4", 1 / 1.4142), ("3:4", 0.75)]

MAX_FULL = 1600             # longest side kept for each embedded image
MAX_PREVIEW = 420           # longest side used while a slider is moving

try:
    LANCZOS = PILImage.Resampling.LANCZOS
except AttributeError:      # old Pillow
    LANCZOS = PILImage.LANCZOS


# --------------------------------------------------------- image helpers --
def load_pil(path):
    """Open an image file as RGBA, respecting EXIF rotation, size-limited."""
    img = PILImage.open(path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGBA")
    img.thumbnail((MAX_FULL, MAX_FULL), LANCZOS)
    return img


def adjust(img, brightness, contrast, sharpness, saturation):
    """Apply Pillow enhancers on the RGB data only (alpha is preserved)."""
    if brightness == contrast == sharpness == saturation == 1:
        return img
    alpha = img.getchannel("A")
    rgb = img.convert("RGB")
    rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
    rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
    rgb = ImageEnhance.Sharpness(rgb).enhance(sharpness)
    rgb = ImageEnhance.Color(rgb).enhance(saturation)
    rgb.putalpha(alpha)
    return rgb


def pil_to_texture(img):
    tex = Texture.create(size=img.size, colorfmt="rgba")
    tex.blit_buffer(img.tobytes(), colorfmt="rgba", bufferfmt="ubyte")
    tex.flip_vertical()
    return tex


# ---------------------------------------------------------- shape maths --
_POLY_CACHE = {}


def _normalise(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return [((x - x0) / (x1 - x0), (y - y0) / (y1 - y0)) for x, y in pts]


def polygon(kind):
    """Unit-square outline and fan centre for the polygon-type shapes."""
    if kind in _POLY_CACHE:
        return _POLY_CACHE[kind]
    if kind == "triangle":
        pts = [(0.5, 1.0), (0.0, 0.0), (1.0, 0.0)]
    elif kind == "diamond":
        pts = [(0.5, 1.0), (0.0, 0.5), (0.5, 0.0), (1.0, 0.5)]
    elif kind in ("pentagon", "hexagon"):
        n = 5 if kind == "pentagon" else 6
        start = 90 if n == 5 else 0
        pts = _normalise([
            (math.cos(math.radians(start + 360.0 * i / n)),
             math.sin(math.radians(start + 360.0 * i / n)))
            for i in range(n)])
    elif kind == "star":
        pts = []
        for i in range(10):
            r = 1.0 if i % 2 == 0 else 0.42
            a = math.radians(90 + 36 * i)
            pts.append((r * math.cos(a), r * math.sin(a)))
        pts = _normalise(pts)
    elif kind == "heart":
        pts = []
        for i in range(96):
            t = 2 * math.pi * i / 96
            pts.append((16 * math.sin(t) ** 3,
                        13 * math.cos(t) - 5 * math.cos(2 * t)
                        - 2 * math.cos(3 * t) - math.cos(4 * t)))
        pts = _normalise(pts)
    else:
        return None
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    _POLY_CACHE[kind] = (pts, (cx, cy))
    return _POLY_CACHE[kind]


# ----------------------------------------------------------------- fonts --
def discover_fonts():
    """Return [(display name, font_name value)] for the font picker."""
    fonts = [("Roboto", "Roboto")]
    bold = os.path.join(kivy_data_dir, "fonts", "Roboto-Bold.ttf")
    if os.path.exists(bold):
        fonts.append(("Roboto Bold", bold))
    if os.path.isdir(FONT_DIR):
        for fn in sorted(os.listdir(FONT_DIR)):
            if fn.lower().endswith((".ttf", ".otf")):
                name = os.path.splitext(fn)[0].split("-")[0]
                fonts.append((name, os.path.join(FONT_DIR, fn)))
    return fonts


# ------------------------------------------------------------ ui helpers --
def _mix(a, b, t):
    """Linear blend of two RGB(A) tuples."""
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


_WHITE = (1.0, 1.0, 1.0)
_BLACK = (0.0, 0.0, 0.0)
_TEX_CACHE = {}


def metal_texture(tone, pressed=False):
    """1 x N vertical gradient that reads as polished metal.

    Bright top, a darker "horizon" line near the middle, a softer reflected
    band underneath and a dark base - the classic chrome look.
    """
    key = (tuple(round(c, 3) for c in tone[:3]), pressed)
    tex = _TEX_CACHE.get(key)
    if tex is not None:
        return tex
    base = tone[:3]
    top = _mix(base, _WHITE, 0.30)
    mid = _mix(base, _BLACK, 0.30)
    low = _mix(base, _WHITE, 0.04)
    bot = _mix(base, _BLACK, 0.38)
    if pressed:                       # pushed in: darker and inverted
        top, mid, low, bot = (_mix(c, _BLACK, 0.35)
                              for c in (bot, low, mid, top))
    n = 32
    buf = bytearray()
    for i in range(n):                # row 0 is the bottom of the button
        y = 1.0 - i / (n - 1)         # 0 at top .. 1 at bottom
        if y < 0.5:
            c = _mix(top, mid, y / 0.5)
        else:
            c = _mix(low, bot, (y - 0.5) / 0.5)
        buf.extend((int(c[0] * 255), int(c[1] * 255), int(c[2] * 255), 255))
    tex = Texture.create(size=(1, n), colorfmt="rgba")
    tex.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")
    tex.mag_filter = "linear"
    tex.min_filter = "linear"
    _TEX_CACHE[key] = tex
    return tex


class MetalButton(Button):
    """Rounded metallic button: gradient body, top glint, rim and shadow."""
    tone = ListProperty([0.15, 0.15, 0.17, 1])

    def __init__(self, tone=None, **kw):
        kw.pop("background_color", None)
        super().__init__(background_normal="", background_down="",
                         background_color=(0, 0, 0, 0), **kw)
        if tone is not None:
            self.tone = list(tone)
        r = dp(9)
        with self.canvas.before:
            self._sh_c = Color(0, 0, 0, 0.9)
            self._sh = RoundedRectangle(radius=[r])
            Color(1, 1, 1, 1)
            self._body = RoundedRectangle(radius=[r])
            self._glint_c = Color(1, 1, 1, 0.55)
            self._glint = Line(points=[0, 0, 0, 0], width=dp(0.8))
            self._rim_c = Color(*UI_EDGE[:3], 0.55)
            self._rim = Line(rounded_rectangle=(0, 0, 1, 1, r), width=dp(0.9))
        self.bind(pos=self._layout, size=self._layout, tone=self._restyle,
                  state=self._restyle)
        self._restyle()

    def _layout(self, *_):
        x, y = self.pos
        w, h = self.size
        r = dp(9)
        self._sh.pos = (x, y - dp(2))
        self._sh.size = (w, h)
        self._body.pos = (x, y)
        self._body.size = (w, h)
        self._rim.rounded_rectangle = (x, y, w, h, r)
        gy = y + h - dp(2.5)
        self._glint.points = [x + r, gy, x + w - r, gy]

    def _restyle(self, *_):
        pressed = self.state == "down"
        self._body.texture = metal_texture(self.tone, pressed)
        self._glint_c.a = 0.15 if pressed else 0.55
        r, g, b = self.tone[:3]
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        self.color = UI_TEXT_DARK if lum > 0.5 else UI_TEXT


def flat_button(text, on_press=None, bg=UI_BTN, **kw):
    kw.setdefault("font_size", "13sp")
    if len(bg) > 3 and bg[3] == 0:            # fully transparent: plain button
        btn = Button(text=text, background_normal="", background_down="",
                     background_color=bg, color=UI_TEXT, **kw)
    else:
        btn = MetalButton(tone=bg, text=text, **kw)
    if on_press:
        btn.bind(on_release=lambda *_: on_press())
    return btn


class MetalBar(BoxLayout):
    """Dark brushed-metal strip with a hairline highlight on one edge."""

    def __init__(self, edge="top", **kw):
        super().__init__(**kw)
        self._edge_side = edge
        with self.canvas.before:
            Color(1, 1, 1, 1)
            self._bg = Rectangle(texture=metal_texture((0.075, 0.075, 0.085)))
            self._hl_c = Color(0.75, 0.78, 0.85, 0.35)
            self._hl = Line(points=[0, 0, 0, 0], width=dp(0.8))
        self.bind(pos=self._layout, size=self._layout)

    def _layout(self, *_):
        x, y = self.pos
        w, h = self.size
        self._bg.pos = self.pos
        self._bg.size = self.size
        ly = y + h if self._edge_side == "top" else y
        self._hl.points = [x, ly, x + w, ly]


class Popup(_KivyPopup):
    """Kivy popup restyled as a black metal panel with a silver title rule."""

    def __init__(self, **kw):
        kw.setdefault("background", "")
        kw.setdefault("background_color", (0.035, 0.035, 0.042, 0.98))
        kw.setdefault("separator_color", UI_SILVER)
        kw.setdefault("title_color", UI_SILVER)
        kw.setdefault("overlay_color", (0, 0, 0, 0.75))
        super().__init__(**kw)


def caption(text, width=dp(84)):
    return Label(text=text, size_hint_x=None, width=width,
                 color=(0.86, 0.88, 0.92, 1),
                 font_size="13sp", halign="left", valign="middle",
                 text_size=(width, None))


def labelled_slider(name, lo, hi, value, step=0, on_value=None):
    row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
    slider = Slider(min=lo, max=hi, value=value, step=step,
                    cursor_size=(dp(24), dp(24)), value_track=True,
                    value_track_color=UI_SILVER, value_track_width=dp(3))
    if on_value:
        slider.bind(value=lambda _w, v: on_value(v))
    row.add_widget(caption(name))
    row.add_widget(slider)
    return row, slider


def button_grid(buttons, cols):
    rows = (len(buttons) + cols - 1) // cols
    grid = GridLayout(cols=cols, size_hint_y=None, spacing=dp(6),
                      height=rows * dp(44) + (rows - 1) * dp(6))
    for b in buttons:
        grid.add_widget(b)
    return grid


class ScrollPanel(ScrollView):
    """A vertical stack of rows that scrolls when it does not fit."""

    def __init__(self, **kw):
        super().__init__(do_scroll_x=False, bar_width=dp(3),
                         bar_color=(0.82, 0.85, 0.9, 0.9),
                         bar_inactive_color=(0.82, 0.85, 0.9, 0.25), **kw)
        self.col = GridLayout(cols=1, size_hint_y=None, spacing=dp(6),
                              padding=dp(8))
        self.col.bind(minimum_height=self.col.setter("height"))
        self.add_widget(self.col)

    def row(self, widget):
        self.col.add_widget(widget)
        return widget


# ---------------------------------------------------------------- items --
class Item(Scatter):
    """Base class for everything that can be placed on the poster."""
    selected = BooleanProperty(False)
    locked = BooleanProperty(False)

    def __init__(self, **kw):
        kw.setdefault("size_hint", (None, None))
        kw.setdefault("auto_bring_to_front", False)   # keep layer order stable
        kw.setdefault("do_rotation", True)
        kw.setdefault("do_scale", True)
        kw.setdefault("scale_min", 0.1)
        kw.setdefault("scale_max", 12.0)
        super().__init__(**kw)
        self._sel = InstructionGroup()
        self._sel_on_canvas = False
        self.bind(selected=self._redraw_sel, locked=self._redraw_sel,
                  size=self._redraw_sel, scale=self._redraw_sel)

    # ---- selection outline
    def _redraw_sel(self, *_):
        g = self._sel
        g.clear()
        if self.selected:
            k = 1.0 / max(self.scale, 0.05)
            # dark under-stroke + bright stroke: visible on any background
            g.add(Color(0, 0, 0, 0.85))
            g.add(Line(rectangle=(0, 0, self.width, self.height),
                       width=dp(2.8) * k))
            g.add(Color(*(LOCKED_COLOR if self.locked else SELECT_COLOR)))
            g.add(Line(rectangle=(0, 0, self.width, self.height),
                       width=dp(1.3) * k))
        if self._sel_on_canvas:            # keep the outline on top
            self.canvas.remove(g)
        self.canvas.add(g)
        self._sel_on_canvas = True

    # ---- locking
    def set_locked(self, value):
        self.locked = value
        self.do_translation = not value
        self.do_rotation = not value
        self.do_scale = not value

    # ---- touches
    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            App.get_running_app().select(self)
            if self.locked:
                return True                # swallow: do not hit items below
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if self.selected:
            App.get_running_app().item_changed()
        return result

    # ---- helpers used by the app
    def title(self):
        return "Item"

    def clone(self):
        raise NotImplementedError

    def resize_keep_center(self, w=None, h=None):
        c = self.center
        self.size = (w if w is not None else self.width,
                     h if h is not None else self.height)
        self.center = c


class TextItem(Item):
    def __init__(self, text="Your text", **kw):
        super().__init__(**kw)
        self.raw_text = text
        self.label = Label(text=text, font_size=56, color=(0, 0, 0, 1),
                           size_hint=(None, None), halign="center",
                           valign="middle")
        self.label.bind(texture_size=self._fit)
        self.add_widget(self.label)
        self._fit()

    def _fit(self, *_):
        pad = dp(10)
        tw = max(self.label.texture_size[0], dp(24))
        th = max(self.label.texture_size[1], dp(24))
        center = self.center
        self.label.size = (tw, th)
        self.label.pos = (pad, pad)
        self.size = (tw + 2 * pad, th + 2 * pad)
        self.center = center          # grow around the middle, not the corner

    def set_text(self, value):
        self.raw_text = value
        self.label.text = value if value else " "

    def title(self):
        first = (self.raw_text or "").strip().split("\n")[0]
        return "Text: " + (first[:18] or "(empty)")

    def clone(self):
        t = TextItem(self.raw_text)
        s, d = self.label, t.label
        d.font_name = s.font_name
        d.font_size = s.font_size
        d.color = list(s.color)
        d.halign = s.halign
        d.outline_width = s.outline_width
        d.outline_color = list(s.outline_color)
        t.opacity = self.opacity
        return t


class ShapeItem(Item):
    fill = ListProperty([0.12, 0.71, 0.56, 1])
    stroke = ListProperty([0.05, 0.05, 0.06, 1])
    stroke_w = NumericProperty(0)
    radius = NumericProperty(24)

    DEFAULT_SIZE = {
        "rect": (200, 120), "round": (200, 120), "line": (220, 8),
        "heart": (150, 140),
    }

    def __init__(self, kind="rect", **kw):
        super().__init__(**kw)
        self.kind = kind
        self._shape = InstructionGroup()
        self.canvas.add(self._shape)
        w, h = self.DEFAULT_SIZE.get(kind, (150, 150))
        self.size = (dp(w), dp(h))
        self.bind(size=self._draw, fill=self._draw, stroke=self._draw,
                  stroke_w=self._draw, radius=self._draw)
        self._draw()

    def _draw(self, *_):
        g = self._shape
        g.clear()
        w, h = self.size
        if w <= 0 or h <= 0:
            return
        k = self.kind
        g.add(Color(*self.fill))
        poly = polygon(k)
        if k in ("rect", "line"):
            g.add(Rectangle(pos=(0, 0), size=(w, h)))
        elif k == "round":
            r = max(0, min(self.radius, w / 2, h / 2))
            g.add(RoundedRectangle(pos=(0, 0), size=(w, h), radius=[r]))
        elif k == "circle":
            g.add(Ellipse(pos=(0, 0), size=(w, h)))
        elif poly:
            pts, (cx, cy) = poly
            verts = [cx * w, cy * h, 0, 0]
            for x, y in pts + [pts[0]]:
                verts += [x * w, y * h, 0, 0]
            g.add(Mesh(vertices=verts, indices=list(range(len(verts) // 4)),
                       mode="triangle_fan"))
        if self.stroke_w > 0:
            g.add(Color(*self.stroke))
            lw = self.stroke_w
            if k in ("rect", "line"):
                g.add(Line(rectangle=(0, 0, w, h), width=lw))
            elif k == "round":
                r = max(0, min(self.radius, w / 2, h / 2))
                g.add(Line(rounded_rectangle=(0, 0, w, h, r), width=lw))
            elif k == "circle":
                g.add(Line(ellipse=(0, 0, w, h), width=lw))
            elif poly:
                flat = []
                for x, y in poly[0]:
                    flat += [x * w, y * h]
                g.add(Line(points=flat, width=lw, close=True))

    def title(self):
        names = dict((v, n) for n, v in SHAPES)
        return "Shape: " + names.get(self.kind, self.kind)

    def clone(self):
        s = ShapeItem(self.kind)
        s.size = self.size
        s.fill = list(self.fill)
        s.stroke = list(self.stroke)
        s.stroke_w = self.stroke_w
        s.radius = self.radius
        s.opacity = self.opacity
        return s


class ImageItem(Item):
    def __init__(self, pil_img, **kw):
        super().__init__(**kw)
        self.full = pil_img
        self.small = pil_img.copy()
        self.small.thumbnail((MAX_PREVIEW, MAX_PREVIEW), LANCZOS)
        self.brightness = 1.0
        self.contrast = 1.0
        self.sharpness = 1.0
        self.saturation = 1.0
        self._job = None
        w, h = pil_img.size
        k = dp(240) / max(w, h)
        self.size = (w * k, h * k)
        with self.canvas:
            Color(1, 1, 1, 1)
            self._rect = Rectangle(texture=pil_to_texture(pil_img),
                                   pos=(0, 0), size=self.size)
        self.bind(size=lambda *_: setattr(self._rect, "size", self.size))

    def set_adjust(self, **kw):
        for name in ("brightness", "contrast", "sharpness", "saturation"):
            if kw.get(name) is not None:
                setattr(self, name, kw[name])
        self._apply(self.small)                       # instant, low-res
        if self._job is not None:
            self._job.cancel()
        self._job = Clock.schedule_once(lambda _dt: self._apply(self.full),
                                        0.3)          # sharp, after pause

    def reset_adjust(self):
        self.brightness = self.contrast = 1.0
        self.sharpness = self.saturation = 1.0
        self._apply(self.full)

    def flip(self):
        self.full = ImageOps.mirror(self.full)
        self.small = ImageOps.mirror(self.small)
        self._apply(self.full)

    def _apply(self, source):
        out = adjust(source, self.brightness, self.contrast,
                     self.sharpness, self.saturation)
        self._rect.texture = pil_to_texture(out)

    def remove_color_background(self, color, tolerance=38, feather=18):
        """Remove pixels close to an RGB colour, preserving existing transparency.

        This is a lightweight offline colour-key remover, not semantic AI
        segmentation. It works best with plain/solid backgrounds.
        """
        base = self.full.convert("RGBA")
        rgb = base.convert("RGB")
        target = PILImage.new("RGB", rgb.size, tuple(int(v) for v in color[:3]))
        diff = ImageChops.difference(rgb, target)
        distance = ImageChops.lighter(
            ImageChops.lighter(diff.getchannel("R"), diff.getchannel("G")),
            diff.getchannel("B")
        )
        tolerance = max(0, min(255, int(tolerance)))
        feather = max(0, min(255, int(feather)))
        if feather == 0:
            mask = distance.point(lambda value: 0 if value <= tolerance else 255)
        else:
            edge = tolerance + feather
            mask = distance.point(
                lambda value: 0 if value <= tolerance else
                255 if value >= edge else
                int((value - tolerance) * 255 / max(1, feather))
            )
        alpha = ImageChops.multiply(base.getchannel("A"), mask)
        base.putalpha(alpha)
        self.full = base
        self.small = base.copy()
        self.small.thumbnail((MAX_PREVIEW, MAX_PREVIEW), LANCZOS)
        self._apply(self.full)

    def apply_ai_background_result(self, result):
        """Install a completed optional rembg result on the UI thread."""
        self.full = result.convert("RGBA")
        self.small = self.full.copy()
        self.small.thumbnail((MAX_PREVIEW, MAX_PREVIEW), LANCZOS)
        self._apply(self.full)

    def title(self):
        return "Image"

    def clone(self):
        i = ImageItem(self.full)
        i.size = self.size
        i.brightness, i.contrast = self.brightness, self.contrast
        i.sharpness, i.saturation = self.sharpness, self.saturation
        i._apply(i.full)
        i.opacity = self.opacity
        return i


# --------------------------------------------------------------- poster --
class Poster(StencilView):
    """Clipped drawing surface; this widget is what gets exported."""
    bg_color = ListProperty([1, 1, 1, 1])
    bg_color2 = ListProperty([0.12, 0.71, 0.56, 1])
    bg_gradient = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        self._last_pos = tuple(self.pos)
        self._last_size = tuple(self.size)
        with self.canvas.before:
            self._c = Color(*self.bg_color)
            self._r = Rectangle(pos=self.pos, size=self.size)
            self._gc = Color(1, 1, 1, 0)
            self._gr = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update, size=self._update,
                  bg_color=self._update, bg_color2=self._update,
                  bg_gradient=self._update)

    def _grad_texture(self):
        n = 64
        c1 = [int(v * 255) for v in self.bg_color]      # top
        c2 = [int(v * 255) for v in self.bg_color2]     # bottom
        buf = bytearray()
        for i in range(n):                              # row 0 = bottom
            t = i / (n - 1)
            for k in range(3):
                buf.append(int(c2[k] + (c1[k] - c2[k]) * t))
            buf.append(255)
        tex = Texture.create(size=(1, n), colorfmt="rgba")
        tex.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")
        tex.mag_filter = "linear"
        tex.min_filter = "linear"
        return tex

    def _update(self, *_):
        for rect in (self._r, self._gr):
            rect.pos = self.pos
            rect.size = self.size
        self._c.rgba = self.bg_color
        self._gc.rgba = (1, 1, 1, 1 if self.bg_gradient else 0)
        if self.bg_gradient:
            self._gr.texture = self._grad_texture()
        # items keep their relative place when the poster moves or resizes
        ox, oy = self._last_pos
        ow, oh = self._last_size
        nx, ny = self.pos
        nw, nh = self.size
        self._last_pos = (nx, ny)
        self._last_size = (nw, nh)
        if (ox, oy, ow, oh) == (nx, ny, nw, nh):
            return
        if ow > 1 and oh > 1:
            for child in self.children:
                cx, cy = child.center
                child.center = (nx + (cx - ox) / ow * nw,
                                ny + (cy - oy) / oh * nh)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        handled = super().on_touch_down(touch)
        if not handled:
            App.get_running_app().select(None)
        return handled


# ----------------------------------------------------------------- tabs --
class ShapeIconButton(MetalButton):
    """Metal button that shows the shape itself instead of its name."""

    def __init__(self, kind, on_press=None, **kw):
        super().__init__(tone=UI_BTN, **kw)
        self.kind = kind
        self._icon = InstructionGroup()
        self.canvas.after.add(self._icon)
        self.bind(pos=self._draw_icon, size=self._draw_icon)
        if on_press:
            self.bind(on_release=lambda *_: on_press())
        self._draw_icon()

    def _draw_icon(self, *_):
        g = self._icon
        g.clear()
        s = min(self.width, self.height) * 0.52
        if s <= 0:
            return
        k = self.kind
        cx, cy = self.center
        g.add(Color(0.90, 0.92, 0.96, 1))
        if k == "rect":
            w, h = s * 1.2, s * 0.8
            g.add(Rectangle(pos=(cx - w / 2, cy - h / 2), size=(w, h)))
        elif k == "round":
            w, h = s * 1.2, s * 0.8
            g.add(RoundedRectangle(pos=(cx - w / 2, cy - h / 2),
                                   size=(w, h), radius=[s * 0.25]))
        elif k == "circle":
            g.add(Ellipse(pos=(cx - s / 2, cy - s / 2), size=(s, s)))
        elif k == "line":
            w, h = s * 1.4, max(dp(3), s * 0.12)
            g.add(Rectangle(pos=(cx - w / 2, cy - h / 2), size=(w, h)))
        else:
            poly = polygon(k)
            if not poly:
                return
            pts, (px, py) = poly
            x0, y0 = cx - s / 2, cy - s / 2
            verts = [x0 + px * s, y0 + py * s, 0, 0]
            for x, y in pts + [pts[0]]:
                verts += [x0 + x * s, y0 + y * s, 0, 0]
            g.add(Mesh(vertices=verts, indices=list(range(len(verts) // 4)),
                       mode="triangle_fan"))


class AddTab(ScrollPanel):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        buttons = [flat_button("Text", app.add_text, bg=UI_ACCENT),
                   flat_button("Image", app.add_image, bg=UI_ACCENT)]
        grid = button_grid(buttons, 2)
        self.row(grid)
        shapes = [ShapeIconButton(kind, lambda k=kind: app.add_shape(k))
                  for _name, kind in SHAPES]
        self.row(button_grid(shapes, 4))


class EditTab(ScrollPanel):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.item = None
        self._lock = False
        self.lock_btn = flat_button("Lock", self._toggle_lock)
        self.row(button_grid([
            flat_button("Duplicate", app.duplicate, bg=UI_ACCENT),
            flat_button("Delete", app.delete_selected, bg=UI_DANGER),
            self.lock_btn,
            flat_button("Centre H", lambda: app.centre(True, False)),
            flat_button("Centre V", lambda: app.centre(False, True)),
            flat_button("Reset", self._reset),
        ], 3))
        r1, self.rot = labelled_slider("Rotation", -180, 180, 0, 1,
                                       self._on_rot)
        r2, self.opa = labelled_slider("Opacity", 0.05, 1, 1, 0.01,
                                       self._on_opacity)
        self.row(r1)
        self.row(r2)

    def bind_item(self, item):
        self.item = item
        self.col.disabled = item is None
        if item is None:
            return
        self.sync()

    def sync(self):
        item = self.item
        if item is None:
            return
        self._lock = True
        self.rot.value = max(-180, min(180, round(item.rotation)))
        self.opa.value = item.opacity
        self.lock_btn.text = "Unlock" if item.locked else "Lock"
        self._lock = False

    def _on_rot(self, value):
        if not self._lock and self.item and not self.item.locked:
            self.item.rotation = value

    def _on_opacity(self, value):
        if not self._lock and self.item:
            self.item.opacity = value

    def _toggle_lock(self):
        if self.item:
            self.item.set_locked(not self.item.locked)
            self.sync()

    def _reset(self):
        if self.item and not self.item.locked:
            self.item.rotation = 0
            self.item.scale = 1
            self.item.opacity = 1
            self.sync()


class TextStyle(ScrollPanel):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.item = None
        self._lock = False
        self.input = TextInput(multiline=True, size_hint_y=None,
                               height=dp(70), font_size="15sp",
                               hint_text="Type your text",
                               background_normal="", background_active="",
                               background_color=(0.03, 0.03, 0.035, 1),
                               foreground_color=(0.95, 0.96, 0.98, 1),
                               hint_text_color=(0.5, 0.52, 0.57, 1),
                               cursor_color=UI_SILVER,
                               selection_color=(0.84, 0.87, 0.92, 0.35),
                               padding=(dp(10), dp(8)))
        with self.input.canvas.after:
            Color(*UI_EDGE[:3], 0.6)
            self._in_rim = Line(rectangle=(0, 0, 1, 1), width=dp(0.9))
        self.input.bind(
            pos=lambda w, _v: setattr(self._in_rim, "rectangle",
                                      (w.x, w.y, w.width, w.height)),
            size=lambda w, _v: setattr(self._in_rim, "rectangle",
                                       (w.x, w.y, w.width, w.height)))
        self.input.bind(text=self._on_text)
        self.row(self.input)
        r, self.size_slider = labelled_slider("Size", 16, 220, 56, 1,
                                              self._on_size)
        self.row(r)
        self.align_btn = flat_button("Align: centre", self._cycle_align)
        self.row(button_grid([
            flat_button("Font", self._pick_font),
            flat_button("Colour", self._pick_color),
            self.align_btn,
        ], 3))
        r, self.out_slider = labelled_slider("Outline", 0, 12, 0, 1,
                                             self._on_outline)
        self.row(r)
        self.row(button_grid([
            flat_button("Outline colour", self._pick_outline)], 1))

    def bind_item(self, item):
        self._lock = True
        self.item = item
        self.input.text = item.raw_text
        self.size_slider.value = item.label.font_size
        self.out_slider.value = item.label.outline_width or 0
        self.align_btn.text = "Align: " + {"center": "centre"}.get(
            item.label.halign, item.label.halign)
        self._lock = False

    def _on_text(self, _w, value):
        if not self._lock and self.item:
            self.item.set_text(value)

    def _on_size(self, value):
        if not self._lock and self.item:
            self.item.label.font_size = value

    def _on_outline(self, value):
        if not self._lock and self.item:
            self.item.label.outline_width = int(value)

    def _pick_font(self):
        if not self.item:
            return
        box = GridLayout(cols=1, size_hint_y=None, spacing=dp(4))
        box.bind(minimum_height=box.setter("height"))
        pop = Popup(title="Choose a font", size_hint=(0.9, 0.7))
        for name, font in self.app.fonts:
            b = flat_button(name, font_size="20sp", size_hint_y=None,
                            height=dp(54))
            b.font_name = font
            b.bind(on_release=lambda _b, f=font, p=pop: self._set_font(f, p))
            box.add_widget(b)
        scroll = ScrollView()
        scroll.add_widget(box)
        pop.content = scroll
        pop.open()

    def _set_font(self, font, pop):
        if self.item:
            self.item.label.font_name = font
        pop.dismiss()

    def _pick_color(self):
        if self.item:
            item = self.item
            self.app.pick_color(item.label.color,
                                lambda c: setattr(item.label, "color", c))

    def _pick_outline(self):
        if self.item:
            item = self.item
            self.app.pick_color(
                item.label.outline_color,
                lambda c: setattr(item.label, "outline_color", c))

    def _cycle_align(self):
        if not self.item:
            return
        order = ["center", "left", "right"]
        cur = self.item.label.halign
        nxt = order[(order.index(cur) + 1) % 3] if cur in order else "center"
        self.item.label.halign = nxt
        self.align_btn.text = "Align: " + {"center": "centre"}.get(nxt, nxt)


class ShapeStyle(ScrollPanel):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.item = None
        self._lock = False
        self.row(button_grid([
            flat_button("Fill colour", self._pick_fill),
            flat_button("Outline colour", self._pick_stroke),
        ], 2))
        r, self.sw = labelled_slider("Outline", 0, 30, 0, 1, self._on_sw)
        self.row(r)
        r, self.wd = labelled_slider("Width", 8, 700, 150, 1,
                                     lambda v: self._on_dim(w=v))
        self.row(r)
        r, self.ht = labelled_slider("Height", 8, 700, 150, 1,
                                     lambda v: self._on_dim(h=v))
        self.row(r)
        self.radius_row, self.rad = labelled_slider("Corners", 0, 150, 24, 1,
                                                    self._on_rad)
        self.row(self.radius_row)

    def bind_item(self, item):
        self._lock = True
        self.item = item
        self.sw.value = item.stroke_w
        self.wd.value = item.width / dp(1)
        self.ht.value = item.height / dp(1)
        self.rad.value = item.radius / dp(1)
        self.radius_row.disabled = item.kind != "round"
        self._lock = False

    def _on_sw(self, value):
        if not self._lock and self.item:
            self.item.stroke_w = value

    def _on_dim(self, w=None, h=None):
        if not self._lock and self.item:
            self.item.resize_keep_center(
                dp(w) if w is not None else None,
                dp(h) if h is not None else None)

    def _on_rad(self, value):
        if not self._lock and self.item:
            self.item.radius = dp(value)

    def _pick_fill(self):
        if self.item:
            item = self.item
            self.app.pick_color(item.fill,
                                lambda c: setattr(item, "fill", c))

    def _pick_stroke(self):
        if self.item:
            item = self.item
            if item.stroke_w == 0:
                item.stroke_w = dp(4)
                self.sw.value = item.stroke_w
            self.app.pick_color(item.stroke,
                                lambda c: setattr(item, "stroke", c))


class ImageStyle(ScrollPanel):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.item = None
        self._lock = False
        specs = [("Brightness", "brightness", 0, 2),
                 ("Contrast", "contrast", 0, 2),
                 ("Sharpness", "sharpness", 0, 3),
                 ("Saturation", "saturation", 0, 2)]
        self.sliders = {}
        for label, key, lo, hi in specs:
            r, s = labelled_slider(
                label, lo, hi, 1, 0.01,
                lambda v, k=key: self._set(**{k: v}))
            self.sliders[key] = s
            self.row(r)
        self.row(button_grid([
            flat_button("Flip", self._flip),
            flat_button("Reset adjustments", self._reset),
        ], 2))
        self.row(button_grid([
            flat_button("Remove BG (colour)", self._remove_colour_bg,
                        bg=UI_ACCENT),
            flat_button("AI Remove BG", self._remove_ai_bg,
                        bg=UI_STEEL),
        ], 2))

    def bind_item(self, item):
        self._lock = True
        self.item = item
        for key, s in self.sliders.items():
            s.value = getattr(item, key)
        self._lock = False

    def _remove_colour_bg(self):
        if not self.item:
            return
        item = self.item
        sample = item.full.convert("RGB").getpixel((0, 0))
        picker = ColorPicker(size_hint_y=0.62)
        picker.color = [sample[0] / 255, sample[1] / 255,
                        sample[2] / 255, 1]
        controls = BoxLayout(orientation="vertical", spacing=dp(5),
                            padding=dp(8))
        row1, tolerance = labelled_slider("Tolerance", 0, 180, 38, 1)
        row2, feather = labelled_slider("Soft edge", 0, 100, 18, 1)
        controls.add_widget(picker)
        controls.add_widget(row1)
        controls.add_widget(row2)
        controls.add_widget(Label(
            text="Removes matching colours throughout the image. Best for "
                 "plain backgrounds; internal areas of the same colour "
                 "may also become transparent.",
            size_hint_y=None, height=dp(48), font_size="11sp",
            color=(1, 1, 1, 0.8), halign="center"
        ))
        pop = Popup(title="Colour background remover",
                    content=controls, size_hint=(0.94, 0.88))
        controls.add_widget(flat_button(
            "Apply removal",
            lambda: (item.remove_color_background(
                picker.color, tolerance.value, feather.value), pop.dismiss()),
            bg=UI_ACCENT, size_hint_y=None, height=dp(46)
        ))
        pop.open()

    def _remove_ai_bg(self):
        if not self.item:
            return
        item = self.item
        self.app = App.get_running_app()
        self.app.notify("AI background removal is starting. It requires the "
                        "optional rembg package and its model.")
        def worker():
            try:
                from rembg import remove
                result = remove(item.full.copy()).convert("RGBA")
                Clock.schedule_once(
                    lambda _dt: self._finish_ai(item, result, None), 0)
            except Exception as exc:
                Clock.schedule_once(
                    lambda _dt, error=str(exc): self._finish_ai(
                        item, None, error), 0)
        threading.Thread(target=worker, daemon=True).start()

    def _finish_ai(self, item, result, error):
        if error:
            App.get_running_app().notify(
                "AI removal unavailable. Install/package rembg and its "
                "runtime/model first.\n%s" % error)
            return
        if item in App.get_running_app().poster.children:
            item.apply_ai_background_result(result)
            App.get_running_app().notify("AI background removed.")

    def _set(self, **kw):
        if not self._lock and self.item:
            self.item.set_adjust(**kw)

    def _flip(self):
        if self.item:
            self.item.flip()

    def _reset(self):
        if not self.item:
            return
        self._lock = True
        for s in self.sliders.values():
            s.value = 1
        self._lock = False
        self.item.reset_adjust()


class HintPanel(BoxLayout):
    def __init__(self, text, **kw):
        super().__init__(padding=dp(14), **kw)
        self.add_widget(Label(text=text, color=(1, 1, 1, 0.8),
                              font_size="13sp", halign="center",
                              valign="middle"))


class LayerCard(BoxLayout):
    """Raised dark layer tile with a clear selected state and lock action."""
    selected = BooleanProperty(False)

    def __init__(self, item, on_select, on_lock, **kw):
        super().__init__(orientation="horizontal", size_hint_y=None,
                         height=dp(58), spacing=dp(7),
                         padding=(dp(8), dp(6)), **kw)
        self.item = item
        self.on_select = on_select
        self.on_lock = on_lock
        with self.canvas.before:
            self._shadow_c = Color(0, 0, 0, 0.95)
            self._shadow = RoundedRectangle(radius=[dp(10)])
            self._panel_c = Color(0.085, 0.085, 0.095, 1)
            self._panel = RoundedRectangle(radius=[dp(10)])
            self._edge_c = Color(0.34, 0.35, 0.40, 1)
            self._edge = Line(rounded_rectangle=(0, 0, 1, 1, dp(10)),
                              width=1)
            self._accent_c = Color(*SELECT_COLOR)
            self._accent = RoundedRectangle(radius=[dp(3)])
        self.bind(pos=self._draw_card, size=self._draw_card,
                  selected=self._draw_card)
        self._draw_card()
        title = item.title() + ("  •  LOCKED" if item.locked else "")
        self.title_btn = flat_button(
            title, lambda: self.on_select(item), bg=(0, 0, 0, 0),
            halign="left", valign="middle"
        )
        self.title_btn.text_size = (None, None)
        self.add_widget(self.title_btn)
        self.lock_btn = flat_button(
            "UNLOCK" if item.locked else "LOCK",
            lambda: self.on_lock(item), bg=UI_BTN,
            size_hint_x=None, width=dp(66), font_size="10sp"
        )
        self.add_widget(self.lock_btn)

    def _draw_card(self, *_):
        x, y = self.pos
        w, h = self.size
        self._shadow.pos = (x + dp(1), y - dp(3))
        self._shadow.size = (w - dp(2), h)
        self._panel.pos = (x, y + dp(2))
        self._panel.size = (w, h - dp(3))
        self._edge.rounded_rectangle = (x, y + dp(2), w, h - dp(3), dp(10))
        self._accent.pos = (x + dp(3), y + dp(10))
        self._accent.size = (dp(4), h - dp(19))
        self._accent_c.rgba = SELECT_COLOR if self.selected else (
            0.22, 0.23, 0.26, 1)
        self._panel_c.rgba = ((0.17, 0.175, 0.195, 1) if self.selected
                              else (0.085, 0.085, 0.095, 1))


class LayersTab(ScrollPanel):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app

    def refresh(self):
        app = self.app
        self.col.clear_widgets()
        self.row(button_grid([
            flat_button("Up", lambda: app.move_layer(-1)),
            flat_button("Down", lambda: app.move_layer(1)),
            flat_button("To top", lambda: app.move_layer(-10 ** 6)),
            flat_button("To bottom", lambda: app.move_layer(10 ** 6)),
        ], 4))
        kids = list(app.poster.children)       # index 0 is the top layer
        if not kids:
            self.row(Label(text="No items yet.", size_hint_y=None,
                           height=dp(40), color=(1, 1, 1, 0.7),
                           font_size="13sp"))
        for item in kids:
            card = LayerCard(
                item,
                on_select=lambda it: app.select(it),
                on_lock=lambda it: self._toggle_lock(it),
            )
            card.selected = item is app.sel
            self.row(card)

    def _toggle_lock(self, item):
        item.set_locked(not item.locked)
        self.refresh()


class PageTab(ScrollPanel):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.row(Label(text="Poster size", size_hint_y=None, height=dp(22),
                       color=(1, 1, 1, 0.8), font_size="12sp"))
        self.row(button_grid([
            flat_button(name, lambda r=ratio: app.set_ratio(r))
            for name, ratio in RATIOS], 3))
        self.row(Label(text="Background", size_hint_y=None, height=dp(22),
                       color=(1, 1, 1, 0.8), font_size="12sp"))
        self.grad_btn = flat_button("Gradient: off", self._toggle_gradient)
        self.row(button_grid([
            flat_button("Colour", app.pick_background),
            flat_button("Colour 2", app.pick_background2),
            self.grad_btn,
        ], 3))

    def _toggle_gradient(self):
        poster = self.app.poster
        poster.bg_gradient = not poster.bg_gradient
        self.grad_btn.text = "Gradient: on" if poster.bg_gradient \
            else "Gradient: off"


# ------------------------------------------------------------------ app --
TAB_NAMES = [("add", "Add"), ("edit", "Edit"), ("style", "Style"),
             ("layers", "Layers"), ("page", "Page")]


class PosterStudioApp(App):
    title = "Poster Studio"

    def build(self):
        Window.clearcolor = UI_BG
        Window.softinput_mode = "below_target"
        if platform not in ("android", "ios"):
            Window.size = (400, 780)      # phone-shaped window on desktop
        self.fonts = discover_fonts()
        self.sel = None
        self.ratio = 0.8
        self._fill_index = 0
        self.current_tab = "add"

        root = BoxLayout(orientation="vertical")

        top = MetalBar(edge="bottom", size_hint_y=None, height=dp(52),
                       padding=dp(8), spacing=dp(8))
        top.add_widget(Label(text="POSTER STUDIO", bold=True,
                             font_size="17sp", color=UI_SILVER,
                             halign="left", valign="middle"))
        top.add_widget(flat_button("Export", self.export, bg=UI_ACCENT,
                                   size_hint_x=None, width=dp(100)))
        root.add_widget(top)

        self.stage = AnchorLayout()
        self.poster = Poster(size_hint=(None, None))
        self.stage.add_widget(self.poster)
        self.stage.bind(size=self._fit_poster)
        root.add_widget(self.stage)

        self.add_tab = AddTab(self)
        self.edit_tab = EditTab(self)
        self.layers_tab = LayersTab(self)
        self.page_tab = PageTab(self)
        self.text_style = TextStyle(self)
        self.shape_style = ShapeStyle(self)
        self.image_style = ImageStyle()
        self.hint = HintPanel("Select an item to style it.\n"
                              "Tap an item on the poster, or add one "
                              "from the Add tab.")

        self.panel_box = BoxLayout(size_hint_y=None, height=dp(200))
        with self.panel_box.canvas.before:
            Color(*UI_PANEL)
            self._panel_bg = Rectangle()
            Color(0.75, 0.78, 0.85, 0.35)
            self._panel_hl = Line(points=[0, 0, 0, 0], width=dp(0.8))

        def _panel_layout(*_):
            b = self.panel_box
            self._panel_bg.pos = b.pos
            self._panel_bg.size = b.size
            ly = b.y + b.height
            self._panel_hl.points = [b.x, ly, b.right, ly]

        self.panel_box.bind(pos=_panel_layout, size=_panel_layout)
        root.add_widget(self.panel_box)

        bar = MetalBar(edge="top", size_hint_y=None, height=dp(54),
                       spacing=dp(4), padding=dp(4))
        self.tab_buttons = {}
        for key, label in TAB_NAMES:
            b = flat_button(label, lambda k=key: self.show_tab(k),
                            font_size="14sp")
            self.tab_buttons[key] = b
            bar.add_widget(b)
        root.add_widget(bar)

        self.show_tab("add")
        return root

    def on_start(self):
        if platform == "android":
            try:
                from android.permissions import request_permissions
                request_permissions([
                    "android.permission.READ_EXTERNAL_STORAGE",
                    "android.permission.WRITE_EXTERNAL_STORAGE",
                    "android.permission.READ_MEDIA_IMAGES",
                ])
            except Exception as exc:      # permission prompt is best effort
                print("permission request failed:", exc)

    # ------------------------------------------------------------ layout --
    def _fit_poster(self, *_):
        avail_w = self.stage.width - dp(16)
        avail_h = self.stage.height - dp(16)
        w = max(min(avail_w, avail_h * self.ratio), dp(50))
        self.poster.size = (w, w / self.ratio)

    def set_ratio(self, ratio):
        self.ratio = ratio
        self._fit_poster()

    # -------------------------------------------------------------- tabs --
    def show_tab(self, name):
        self.current_tab = name
        self._refresh_panel()

    def _paint_tabs(self):
        for key, b in self.tab_buttons.items():
            b.tone = list(UI_ACCENT if key == self.current_tab else UI_BTN)

    def _panel_widget(self):
        tab = self.current_tab
        if tab == "add":
            return self.add_tab
        if tab == "edit":
            self.edit_tab.bind_item(self.sel)
            return self.edit_tab
        if tab == "layers":
            self.layers_tab.refresh()
            return self.layers_tab
        if tab == "page":
            return self.page_tab
        sel = self.sel
        if isinstance(sel, TextItem):
            widget = self.text_style
        elif isinstance(sel, ShapeItem):
            widget = self.shape_style
        elif isinstance(sel, ImageItem):
            widget = self.image_style
        else:
            return self.hint
        widget.bind_item(sel)
        return widget

    def _refresh_panel(self):
        self._paint_tabs()
        widget = self._panel_widget()
        kids = self.panel_box.children
        if not (len(kids) == 1 and kids[0] is widget):
            self.panel_box.clear_widgets()
            self.panel_box.add_widget(widget)

    # --------------------------------------------------------- selection --
    def select(self, item):
        if item is self.sel:
            return
        if self.sel is not None:
            self.sel.selected = False
        self.sel = item
        if item is not None:
            item.selected = True
            if self.current_tab in ("add", "page"):
                self.current_tab = "style"
        self._refresh_panel()

    def item_changed(self):
        if self.current_tab == "edit" and self.sel is not None:
            self.edit_tab.sync()

    # ------------------------------------------------------------ adding --
    def _place(self, item):
        n = len(self.poster.children) % 5
        self.poster.add_widget(item)
        item.center = (self.poster.center_x + n * dp(14),
                       self.poster.center_y - n * dp(14))
        self.select(item)
        self._refresh_panel()

    def add_text(self):
        self._place(TextItem("Your text"))

    def add_shape(self, kind):
        shape = ShapeItem(kind)
        shape.fill = get_color_from_hex(
            SHAPE_FILLS[self._fill_index % len(SHAPE_FILLS)])
        self._fill_index += 1
        self._place(shape)

    def add_image(self):
        pop = Popup(title="Add image", size_hint=(0.85, None),
                    height=dp(210))
        box = BoxLayout(orientation="vertical", spacing=dp(10),
                        padding=dp(10))
        box.add_widget(flat_button(
            "Gallery", lambda: (pop.dismiss(), self.pick_gallery()),
            font_size="16sp"))
        box.add_widget(flat_button(
            "Browse files", lambda: (pop.dismiss(), self.browse_files()),
            font_size="16sp"))
        pop.content = box
        pop.open()

    def pick_gallery(self):
        try:
            from plyer import filechooser
            filechooser.open_file(
                on_selection=self._on_picked, multiple=False,
                filters=[["Images", "*.png", "*.jpg", "*.jpeg", "*.webp",
                          "*.bmp"]])
        except Exception as exc:
            print("system picker unavailable:", exc)
            self.browse_files()

    @mainthread
    def _on_picked(self, selection):
        if selection:
            self.load_image(selection[0])

    def browse_files(self):
        if platform == "android":
            start = "/storage/emulated/0"
            for sub in ("Pictures", "DCIM"):
                cand = os.path.join(start, sub)
                if os.path.isdir(cand):
                    start = cand
                    break
        else:
            start = os.path.expanduser("~")
        exts = ["png", "jpg", "jpeg", "webp", "bmp"]
        patterns = ["*." + e for e in exts] + ["*." + e.upper() for e in exts]
        fc = FileChooserIconView(path=start, filters=patterns)
        pop = Popup(title="Choose an image", size_hint=(0.95, 0.85))
        box = BoxLayout(orientation="vertical", spacing=dp(6))
        box.add_widget(fc)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        row.add_widget(flat_button("Cancel", pop.dismiss))

        def choose():
            if fc.selection:
                pop.dismiss()
                self.load_image(fc.selection[0])

        row.add_widget(flat_button("Add", choose, bg=UI_ACCENT))
        box.add_widget(row)
        pop.content = box
        pop.open()

    def load_image(self, path):
        try:
            pil = load_pil(path)
        except Exception as exc:
            self.notify("Could not open that image.\n%s" % exc)
            return
        self._place(ImageItem(pil))

    # ----------------------------------------------------------- editing --
    def pick_background(self):
        self.pick_color(self.poster.bg_color,
                        lambda c: setattr(self.poster, "bg_color",
                                          [c[0], c[1], c[2], 1]))

    def pick_background2(self):
        self.pick_color(self.poster.bg_color2,
                        lambda c: setattr(self.poster, "bg_color2",
                                          [c[0], c[1], c[2], 1]))

    def pick_color(self, initial, callback):
        """Open the colour popup; callback(rgba) fires live as it changes."""
        picker = ColorPicker(size_hint_y=0.62)
        picker.color = list(initial)
        picker.bind(color=lambda _w, c: callback(list(c)))
        grid = GridLayout(cols=6, size_hint_y=0.2, spacing=dp(4))
        for hex_code in PALETTE:
            rgba = get_color_from_hex(hex_code)
            sw = Button(background_normal="", background_down="",
                        background_color=rgba)
            sw.bind(on_release=lambda _b, c=rgba: setattr(picker, "color", c))
            grid.add_widget(sw)
        pop = Popup(title="Pick a colour", size_hint=(0.95, 0.9))
        box = BoxLayout(orientation="vertical", spacing=dp(6))
        box.add_widget(picker)
        box.add_widget(grid)
        box.add_widget(flat_button("Done", pop.dismiss, bg=UI_ACCENT,
                                   size_hint_y=None, height=dp(46)))
        pop.content = box
        pop.open()

    def duplicate(self):
        item = self.sel
        if item is None:
            return
        new = item.clone()
        self.poster.add_widget(new)
        new.scale = item.scale
        new.rotation = item.rotation
        cx, cy = item.center
        new.center = (cx + dp(18), cy - dp(18))
        self.select(new)
        self._refresh_panel()

    def centre(self, horizontal, vertical):
        item = self.sel
        if item is None or item.locked:
            return
        cx, cy = item.center
        item.center = (self.poster.center_x if horizontal else cx,
                       self.poster.center_y if vertical else cy)

    def move_layer(self, step):
        item = self.sel
        if item is None:
            return
        kids = self.poster.children        # index 0 is the top layer
        j = max(0, min(len(kids) - 1, kids.index(item) + step))
        if kids.index(item) == j:
            return
        self.poster.remove_widget(item)
        self.poster.add_widget(item, index=j)
        self._refresh_panel()

    def delete_selected(self):
        item = self.sel
        if item is None:
            return
        self.select(None)
        self.poster.remove_widget(item)
        self._refresh_panel()

    # ------------------------------------------------------------ export --
    def export_dir(self):
        folder = None
        if platform == "android":
            try:
                from android.storage import primary_external_storage_path
                folder = os.path.join(primary_external_storage_path(),
                                      "Pictures", "PosterStudio")
            except Exception:
                folder = None
        else:
            folder = os.path.join(os.path.expanduser("~"), "PosterStudio")
        for cand in (folder, self.user_data_dir):
            if not cand:
                continue
            try:
                os.makedirs(cand, exist_ok=True)
                probe = os.path.join(cand, ".probe")
                with open(probe, "w") as fh:
                    fh.write("ok")
                os.remove(probe)
                return cand
            except Exception:
                continue
        return self.user_data_dir

    def export(self):
        self.select(None)
        path = os.path.join(self.export_dir(),
                            time.strftime("poster_%Y%m%d_%H%M%S.png"))
        try:
            self.poster.export_to_png(path, scale=2)
        except Exception as exc:
            self.notify("Export failed.\n%s" % exc)
            return
        self._scan_media(path)
        self.notify("Saved to:\n%s" % path)

    @staticmethod
    def _scan_media(path):
        if platform != "android":
            return
        try:
            from jnius import autoclass
            scanner = autoclass("android.media.MediaScannerConnection")
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            scanner.scanFile(activity, [path], None, None)
        except Exception as exc:
            print("media scan failed:", exc)

    def notify(self, message):
        lbl = Label(text=message, halign="center", font_size="14sp")
        lbl.bind(width=lambda w, v: setattr(w, "text_size", (v - dp(20), None)))
        pop = Popup(title="Poster Studio", content=lbl, size_hint=(0.85, 0.3))
        pop.open()
        Clock.schedule_once(lambda _dt: pop.dismiss(), 3.5)


if __name__ == "__main__":
    PosterStudioApp().run()
