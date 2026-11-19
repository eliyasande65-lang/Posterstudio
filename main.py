"""Poster Studio - a mobile poster / content creator built with Kivy.

Features
  * Poster canvas (4:5) with background colour
  * Text items: edit text, size, font, colour, alignment
  * Image items: pick from gallery, brightness / contrast / sharpness
  * Drag, pinch-resize and rotate every item (Scatter)
  * Full colour picker (wheel, sliders, hex) plus quick palette
  * Layers: raise, lower, delete
  * Export to PNG at 2x resolution
"""
import os
import time

from kivy.app import App
from kivy import kivy_data_dir
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.graphics import Color, InstructionGroup, Line, Rectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.colorpicker import ColorPicker
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scatter import Scatter
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.stencilview import StencilView
from kivy.uix.textinput import TextInput
from kivy.utils import get_color_from_hex, platform

from PIL import Image as PILImage
from PIL import ImageEnhance, ImageOps

APP_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(APP_DIR, "fonts")

# ----------------------------------------------------------------- theme --
UI_BG = get_color_from_hex("#14112b")
UI_PANEL = get_color_from_hex("#1d1941")
UI_BTN = get_color_from_hex("#2c2763")
UI_ACCENT = get_color_from_hex("#1fb58f")
UI_TEXT = (1, 1, 1, 1)
SELECT_COLOR = (0.12, 0.71, 0.56, 1)

PALETTE = [
    "#000000", "#ffffff", "#1a1535", "#1fb58f", "#16a34a", "#0ea5e9",
    "#2563eb", "#7c3aed", "#db2777", "#dc2626", "#f97316", "#facc15",
]

POSTER_RATIO = 0.8          # width / height  (4:5)
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


def adjust(img, brightness, contrast, sharpness):
    """Apply Pillow enhancers on the RGB data only (alpha is preserved)."""
    if brightness == 1 and contrast == 1 and sharpness == 1:
        return img
    alpha = img.getchannel("A")
    rgb = img.convert("RGB")
    rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
    rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
    rgb = ImageEnhance.Sharpness(rgb).enhance(sharpness)
    rgb.putalpha(alpha)
    return rgb


def pil_to_texture(img):
    tex = Texture.create(size=img.size, colorfmt="rgba")
    tex.blit_buffer(img.tobytes(), colorfmt="rgba", bufferfmt="ubyte")
    tex.flip_vertical()
    return tex


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
def flat_button(text, on_press=None, bg=UI_BTN, **kw):
    kw.setdefault("font_size", "13sp")
    btn = Button(text=text, background_normal="", background_down="",
                 background_color=bg, color=UI_TEXT, **kw)
    if on_press:
        btn.bind(on_release=lambda *_: on_press())
    return btn


def caption(text, width=dp(84)):
    return Label(text=text, size_hint_x=None, width=width, color=UI_TEXT,
                 font_size="13sp", halign="left", valign="middle",
                 text_size=(width, None))


def labelled_slider(name, lo, hi, value, step=0, on_value=None):
    row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
    cap = caption(name)
    slider = Slider(min=lo, max=hi, value=value, step=step,
                    cursor_size=(dp(24), dp(24)))
    if on_value:
        slider.bind(value=lambda _w, v: on_value(v))
    row.add_widget(cap)
    row.add_widget(slider)
    return row, slider, cap


# ---------------------------------------------------------------- items --
class Item(Scatter):
    """Base class for everything that can be placed on the poster."""
    selected = BooleanProperty(False)

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
        self.bind(selected=self._redraw_sel, size=self._redraw_sel,
                  scale=self._redraw_sel)

    def _redraw_sel(self, *_):
        g = self._sel
        g.clear()
        if self.selected:
            g.add(Color(*SELECT_COLOR))
            g.add(Line(rectangle=(0, 0, self.width, self.height),
                       width=dp(1.6) / max(self.scale, 0.05)))
        # keep the outline above the item's own drawing
        if self._sel_on_canvas:
            self.canvas.remove(g)
        self.canvas.add(g)
        self._sel_on_canvas = True

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            App.get_running_app().select(self)
        return super().on_touch_down(touch)


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


class ImageItem(Item):
    def __init__(self, pil_img, **kw):
        super().__init__(**kw)
        self.full = pil_img
        self.small = pil_img.copy()
        self.small.thumbnail((MAX_PREVIEW, MAX_PREVIEW), LANCZOS)
        self.brightness = 1.0
        self.contrast = 1.0
        self.sharpness = 1.0
        self._job = None
        w, h = pil_img.size
        k = dp(240) / max(w, h)
        self.size = (w * k, h * k)
        with self.canvas:
            Color(1, 1, 1, 1)
            self._rect = Rectangle(texture=pil_to_texture(pil_img),
                                   pos=(0, 0), size=self.size)
        self.bind(size=lambda *_: setattr(self._rect, "size", self.size))

    def set_adjust(self, brightness=None, contrast=None, sharpness=None):
        if brightness is not None:
            self.brightness = brightness
        if contrast is not None:
            self.contrast = contrast
        if sharpness is not None:
            self.sharpness = sharpness
        self._apply(self.small)                       # instant, low-res
        if self._job is not None:
            self._job.cancel()
        self._job = Clock.schedule_once(lambda _dt: self._apply(self.full),
                                        0.3)          # sharp, after pause

    def _apply(self, source):
        out = adjust(source, self.brightness, self.contrast, self.sharpness)
        self._rect.texture = pil_to_texture(out)


# --------------------------------------------------------------- poster --
class Poster(StencilView):
    """Clipped drawing surface; this widget is what gets exported."""
    bg_color = ListProperty([1, 1, 1, 1])

    def __init__(self, **kw):
        super().__init__(**kw)
        self._last_pos = tuple(self.pos)
        with self.canvas.before:
            self._c = Color(*self.bg_color)
            self._r = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update, size=self._update, bg_color=self._update)

    def _update(self, *_):
        self._r.pos = self.pos
        self._r.size = self.size
        self._c.rgba = self.bg_color
        dx = self.x - self._last_pos[0]
        dy = self.y - self._last_pos[1]
        self._last_pos = (self.x, self.y)
        if dx or dy:                       # items follow the poster
            for child in self.children:
                child.pos = (child.x + dx, child.y + dy)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        handled = super().on_touch_down(touch)
        if not handled:
            App.get_running_app().select(None)
        return handled


# --------------------------------------------------------------- panels --
class HomePanel(BoxLayout):
    def __init__(self, **kw):
        super().__init__(padding=dp(14), **kw)
        self.add_widget(Label(
            text=("Add text or an image from the bar below.\n"
                  "Drag to move. Pinch to resize and rotate.\n"
                  "Tap an item to edit it. Tap empty space to deselect."),
            color=(1, 1, 1, 0.8), font_size="13sp", halign="center",
            valign="middle"))


class TextPanel(BoxLayout):
    def __init__(self, app, **kw):
        super().__init__(orientation="vertical", spacing=dp(6),
                         padding=dp(8), **kw)
        self.app = app
        self.item = None
        self._lock = False
        self.input = TextInput(multiline=True, size_hint_y=None,
                               height=dp(70), font_size="15sp",
                               hint_text="Type your text")
        self.input.bind(text=self._on_text)
        self.add_widget(self.input)
        row, self.size_slider, _ = labelled_slider(
            "Size", 16, 220, 56, 1, self._on_size)
        self.add_widget(row)
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.font_btn = flat_button("Font", self._pick_font)
        btns.add_widget(self.font_btn)
        btns.add_widget(flat_button("Colour", self._pick_color))
        self.align_btn = flat_button("Align: centre", self._cycle_align)
        btns.add_widget(self.align_btn)
        self.add_widget(btns)

    def bind_item(self, item):
        self._lock = True
        self.item = item
        self.input.text = item.raw_text
        self.size_slider.value = item.label.font_size
        self.align_btn.text = "Align: " + {"center": "centre"}.get(
            item.label.halign, item.label.halign)
        self._lock = False

    def _on_text(self, _w, value):
        if not self._lock and self.item:
            self.item.set_text(value)

    def _on_size(self, value):
        if not self._lock and self.item:
            self.item.label.font_size = value

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
            self.app.pick_color(
                self.item.label.color,
                lambda c: setattr(self.item.label, "color", c))

    def _cycle_align(self):
        if not self.item:
            return
        order = ["center", "left", "right"]
        cur = self.item.label.halign
        nxt = order[(order.index(cur) + 1) % 3] if cur in order else "center"
        self.item.label.halign = nxt
        self.align_btn.text = "Align: " + {"center": "centre"}.get(nxt, nxt)


class ImagePanel(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", spacing=dp(6),
                         padding=dp(8), **kw)
        self.item = None
        self._lock = False
        r1, self.s_bright, self.c_bright = labelled_slider(
            "Brightness", 0, 2, 1, 0.01, lambda v: self._set(brightness=v))
        r2, self.s_contrast, self.c_contrast = labelled_slider(
            "Contrast", 0, 2, 1, 0.01, lambda v: self._set(contrast=v))
        r3, self.s_sharp, self.c_sharp = labelled_slider(
            "Sharpness", 0, 3, 1, 0.01, lambda v: self._set(sharpness=v))
        for r in (r1, r2, r3):
            self.add_widget(r)
        self.add_widget(flat_button("Reset adjustments", self._reset,
                                    size_hint_y=None, height=dp(44)))

    def bind_item(self, item):
        self._lock = True
        self.item = item
        self.s_bright.value = item.brightness
        self.s_contrast.value = item.contrast
        self.s_sharp.value = item.sharpness
        self._lock = False

    def _set(self, **kw):
        if self._lock or not self.item:
            return
        self.item.set_adjust(**kw)

    def _reset(self):
        if not self.item:
            return
        self.s_bright.value = 1
        self.s_contrast.value = 1
        self.s_sharp.value = 1


# ------------------------------------------------------------------ app --
class PosterStudioApp(App):
    title = "Poster Studio"

    def build(self):
        Window.clearcolor = UI_BG
        Window.softinput_mode = "below_target"
        if platform not in ("android", "ios"):
            Window.size = (400, 780)      # phone-shaped window on desktop
        self.fonts = discover_fonts()
        self.sel = None

        root = BoxLayout(orientation="vertical")

        top = BoxLayout(size_hint_y=None, height=dp(52), padding=dp(8),
                        spacing=dp(8))
        top.add_widget(Label(text="Poster Studio", bold=True,
                             font_size="18sp", halign="left",
                             valign="middle"))
        top.add_widget(flat_button("Export", self.export, bg=UI_ACCENT,
                                   size_hint_x=None, width=dp(100)))
        root.add_widget(top)

        self.stage = AnchorLayout()
        self.poster = Poster(size_hint=(None, None))
        self.stage.add_widget(self.poster)
        self.stage.bind(size=self._fit_poster)
        root.add_widget(self.stage)

        self.home_panel = HomePanel()
        self.text_panel = TextPanel(self)
        self.image_panel = ImagePanel()
        self.panel_box = BoxLayout(size_hint_y=None, height=dp(196))
        with self.panel_box.canvas.before:
            Color(*UI_PANEL)
            self._panel_bg = Rectangle()
        self.panel_box.bind(
            pos=lambda *_: setattr(self._panel_bg, "pos", self.panel_box.pos),
            size=lambda *_: setattr(self._panel_bg, "size",
                                    self.panel_box.size))
        root.add_widget(self.panel_box)

        bar = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(4),
                        padding=dp(4))
        bar.add_widget(flat_button("Text", self.add_text))
        bar.add_widget(flat_button("Image", self.add_image))
        bar.add_widget(flat_button("Backdrop", self.pick_background))
        bar.add_widget(flat_button("Up", lambda: self.move_layer(-1)))
        bar.add_widget(flat_button("Down", lambda: self.move_layer(1)))
        bar.add_widget(flat_button("Delete", self.delete_selected,
                                   bg=get_color_from_hex("#8b1e3f")))
        root.add_widget(bar)

        self._show_panel()
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

    def _fit_poster(self, *_):
        w = min(self.stage.width - dp(16),
                (self.stage.height - dp(16)) * POSTER_RATIO)
        w = max(w, dp(50))
        self.poster.size = (w, w / POSTER_RATIO)

    # --------------------------------------------------------- selection --
    def select(self, item):
        if item is self.sel:
            return
        if self.sel is not None:
            self.sel.selected = False
        self.sel = item
        if item is not None:
            item.selected = True
        self._show_panel()

    def _show_panel(self):
        self.panel_box.clear_widgets()
        if isinstance(self.sel, TextItem):
            self.text_panel.bind_item(self.sel)
            self.panel_box.add_widget(self.text_panel)
        elif isinstance(self.sel, ImageItem):
            self.image_panel.bind_item(self.sel)
            self.panel_box.add_widget(self.image_panel)
        else:
            self.panel_box.add_widget(self.home_panel)

    # ------------------------------------------------------------ adding --
    def _place(self, item):
        n = len(self.poster.children) % 5
        self.poster.add_widget(item)
        item.center = (self.poster.center_x + n * dp(14),
                       self.poster.center_y - n * dp(14))
        self.select(item)

    def add_text(self):
        self._place(TextItem("Your text"))

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
        self.pick_color(self.poster.bg_color, self._set_bg)

    def _set_bg(self, color):
        self.poster.bg_color = [color[0], color[1], color[2], 1]

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
        done = flat_button("Done", pop.dismiss, bg=UI_ACCENT,
                           size_hint_y=None, height=dp(46))
        box.add_widget(done)
        pop.content = box
        pop.open()

    def move_layer(self, step):
        item = self.sel
        if item is None:
            return
        kids = self.poster.children        # index 0 is the top layer
        j = kids.index(item) + step
        if j < 0 or j >= len(kids):
            return
        self.poster.remove_widget(item)
        self.poster.add_widget(item, index=j)

    def delete_selected(self):
        item = self.sel
        if item is None:
            return
        self.select(None)
        self.poster.remove_widget(item)

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
