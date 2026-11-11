"""Click to seek, drag to save a slice on a time plot (milliseconds)."""


class PlotNavigation:
    def __init__(self, canvas, seek, select, origin=lambda: 0):
        self.canvas, self.seek, self.select, self.origin = canvas, seek, select, origin
        self.pressed = None
        self.connections = [canvas.mpl_connect("button_press_event", self.press),
                            canvas.mpl_connect("button_release_event", self.release)]

    def press(self, event):
        if event.button == 1 and event.inaxes is not None and event.xdata is not None:
            self.pressed = (event.inaxes, event.xdata, event.x, self.origin())

    def release(self, event):
        pressed, self.pressed = self.pressed, None
        if not pressed or event.button != 1 or event.inaxes is not pressed[0] or event.xdata is None:
            return
        axis, x, pixel, origin = pressed
        left, right = sorted((origin + round(x * 1000), origin + round(event.xdata * 1000)))
        if abs(event.x - pixel) < 5:
            self.seek(left)
        elif right > left:
            self.select(left, right)
