import io
import tkinter as tk
from pdf2image import convert_from_bytes as cfb
from pdf2image import convert_from_path as cfp
from pdf2image.exceptions import PDFPageCountError
from pathlib import Path
from PIL.ImageTk import PhotoImage, Image


BUTTON_NAMES = {
    "Analog Stick": {"up": "analogStickUp", "down": "analogStickDown",
                     "left": "analogStickLeft", "right": "analogStickRight"},
    "D-Pad": {"up": "up", "down": "down", "left": "left", "right": "right"},
    "Touch Screen": {"x": "touchScreenX", "y": "touchScreenY"}
}


class Region:
    def __init__(self, representation: "Representation", item: dict):
        self.representation = representation
        self._config = item
        self.inputs = self._config["inputs"]
        self.frame = self._config["frame"]

        self.width = self.frame["width"]
        self.height = self.frame["height"]
        self.coords = (self.frame["x"], self.frame["y"])

        if "extendedEdges" in self._config.keys():
            self.extended_edges = self._config["extendedEdges"]
            for key in self.representation.extended_edges.keys():
                if key not in self.extended_edges:
                    self.extended_edges[key] = self.representation.extended_edges[key]
        else:
            self.extended_edges = self.representation.extended_edges

        top = self.extended_edges["top"]
        bottom = self.extended_edges["bottom"]
        left = self.extended_edges["left"]
        right = self.extended_edges["right"]

        self.touch = Image.new("RGBA", (self.width, self.height), "#0000ff80")
        self.extended = Image.new("RGBA", (left+self.width+right, top+self.height+bottom), "#ff000080")

        self._pi_t = PhotoImage(self.touch)
        self._pi_e = PhotoImage(self.extended)

        self._e = self.representation.create_image(self.coords[0]-left, self.coords[1]-top,
                                                   image=self._pi_e, anchor="nw")
        self._t = self.representation.create_image(*self.coords, image=self._pi_t, anchor="nw")

        self.representation.images.update({str(self._t): self})
        self.representation.images.update({str(self._e): self})

    def move(self, delta_x, delta_y):
        self.representation.move(self._e, delta_x, delta_y)
        self.representation.move(self._t, delta_x, delta_y)

    def resize(self, delta_w, delta_h, which=True):
        x1, y1, x2, y2 = self.representation.bbox(self._e)
        self.representation.images.pop(str(self._e))
        self.representation.delete(self._e)

        w = x2-x1
        h = y2-y1
        
        self.extended = self.extended.resize((w+delta_w, h+delta_h))
        self._pi_e = PhotoImage(self.extended)
        self._e = self.representation.create_image(x1, y1, image=self._pi_e, anchor="nw")

        self.representation.images.update({str(self._e): self})
        
        if which:
            x1, y1, x2, y2 = self.representation.bbox(self._t)
            self.representation.images.pop(str(self._t))
            self.representation.delete(self._t)

            w = x2 - x1
            h = y2 - y1
            
            self.touch = self.touch.resize((w+delta_w, h+delta_h))
            self._pi_t = PhotoImage(self.touch)
            self._t = self.representation.create_image(x1, y1, image=self._pi_t, anchor="nw")

            self.representation.images.update({str(self._t): self})


class Representation(tk.Canvas):
    """Custom Editor Class

    This is a custom class that helps manage Regions and general configurations for each `Representation`

    Parameters
    ----------
    mapping_size : dict
        Current `Representation`'s `mapping_size`
    extended_edges : dict
        Current `Representation`'s default `extended_edges` which fills a :class:`Region`'s extended_edges if one of
        them isn't defined.
    assets : dict
        Current `Representation`'s image assets. Usually a PNG or PDF

    Attributes
    ----------
    regions : list[Region]
        ``list`` of :class:`Region`s that this `Representation` handles.
    selected : Region
        The currently selected `Region`
    """
    def __init__(self, items: list[dict], mapping_size: dict, extended_edges: dict, assets: dict):
        super().__init__()
        self.regions: list[Region] = []
        self.selected: Region = None
        self.images = {}
        self._sel = ()
        self.selected_data = {"x": 0, "y": 0}

        self._items = items
        self.mapping_size = mapping_size
        self.extended_edges = extended_edges
        self.assets = assets

        key = next(iter(self.assets.keys()))
        size = tuple(self.mapping_size.values())
        try:
            if "resizable" in self.assets:
                if self.master.OTYPE == "dir":
                    image = cfp(Path(self.master.wd.parent / self.assets[key]), size=size, fmt="png")[0]
                else:
                    image = cfb(self.master.zfile.read(self.assets[key]), size=size, fmt="png")[0]
            else:
                if self.master.OTYPE == "dir":
                    image = Image.open(self.master.wd.parent / self.assets[key]).resize(size)
                else:
                    image = Image.open(io.BytesIO(self.master.zfile.read(self.assets[key]))).resize(size)
        except (PDFPageCountError, KeyError) as e:
            if isinstance(e, KeyError):
                raise SystemExit("Couldn't get the correct key!")
            else:
                raise SystemExit("Couldn't get PDF information! Check your Poppler version.")

        self._bg_image = PhotoImage(image)
        self.create_image(0, 0, image=self._bg_image, anchor="nw", tag="nodrag")

        for item in self._items:
            self.regions.append(Region(self, item))

        self.bind("<Button-1>", self.select_region)
        self.bind("<Escape>", self.deselect_region)
        self.bind("<ButtonRelease-1>", self.drag_stop)
        self.bind("<B1-Motion>", self.drag)
        for bind in ["<Left>", "<Right>", "<Up>", "<Down>"]:
            self.bind(bind, self.move_region)
            self.bind(bind, self.resize_region, "+")

    def statusbar_updater(self):
        try:
            key = next(key for key, value in BUTTON_NAMES.items() if value == self.selected.inputs)
        except StopIteration:
            if isinstance(self.selected.inputs, list):
                if len(self.selected.inputs) > 1:
                    key = ", ".join([i.capitalize() for i in self.selected.inputs])
                else:
                    key = self.selected.inputs[0].capitalize()
            else:
                key = self.selected.inputs

        x1, y1, x2, y2 = self.bbox(self._sel)
        self.master.cur_selected.set(f"{key} | X: {x1} Y: {y1} | W: {x2 - x1} H: {y2 - y1}")

    def select_region(self, event):
        sel = self.find_closest(event.x, event.y)
        if "nodrag" in self.gettags(sel):
            return

        self._sel = sel
        self.selected = self.images[f"{sel[0]}"]
        if (self.selected._e,) == self._sel:
            for bind in ["<Left>", "<Right>", "<Up>", "<Down>"]:
                self.unbind(bind)
                self.bind(bind, self.resize_extended)
        else:
            for bind in ["<Left>", "<Right>", "<Up>", "<Down>"]:
                self.unbind(bind)
                self.bind(bind, self.move_region)
                self.bind(bind, self.resize_region, "+")
        self.selected_data = {"x": event.x, "y": event.y}

        self.statusbar_updater()

    def deselect_region(self, _):
        if self.selected is None:
            return
        self.selected = None
        self._sel = ()
        self.master.cur_selected.set("")

    def drag(self, event):
        delta_x = event.x - self.selected_data["x"]
        delta_y = event.y - self.selected_data["y"]

        self.selected.move(delta_x, delta_y)

        self.selected_data = {"x": event.x, "y": event.y}

        self.statusbar_updater()

    def drag_stop(self, _):
        self.selected_data = {"x": 0, "y": 0}

    def move_region(self, event):
        if self.selected is None:
            return
        if event.keysym == "Right" and not bool(0x1 & event.state):
            self.selected.move(1, 0)
        elif event.keysym == "Left" and not bool(0x1 & event.state):
            self.selected.move(-1, 0)
        elif event.keysym == "Up" and not bool(0x1 & event.state):
            self.selected.move(0, -1)
        elif event.keysym == "Down" and not bool(0x1 & event.state):
            self.selected.move(0, 1)

        self.statusbar_updater()

    def resize_region(self, event):
        if self.selected is None:
            return
        if event.keysym == "Right" and bool(0x1 & event.state):
            self.selected.resize(1, 0)
        elif event.keysym == "Left" and bool(0x1 & event.state):
            self.selected.resize(-1, 0)
        elif event.keysym == "Up" and bool(0x1 & event.state):
            self.selected.resize(0, -1)
        elif event.keysym == "Down" and bool(0x1 & event.state):
            self.selected.resize(0, 1)

