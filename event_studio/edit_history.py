"""Bounded, transactional history for ROI and slice edits, without copying events."""

from copy import deepcopy
from functools import wraps


def record_edit(label):
    def decorate(function):
        @wraps(function)
        def edited(owner, *args, **kwargs):
            history = getattr(owner, "edit_history", None)
            if history is None or history.restoring or history.depth:
                return function(owner, *args, **kwargs)
            before = history.snapshot()
            history.depth += 1
            try:
                return function(owner, *args, **kwargs)
            finally:
                history.depth -= 1
                history.commit(label, before)
        return edited
    return decorate


class EditHistory:
    def __init__(self, owner):
        self.owner = owner
        self.undo_stack = []
        self.redo_stack = []
        self.restoring = False
        self.depth = 0
        self.gesture = None

    def snapshot(self):
        o = self.owner
        return deepcopy({"rois": o.rois, "slices": o.slices,
                         "active": o.active_roi_index, "loop": o.loop_slice_index,
                         "selected": o.slice_list.currentRow(),
                         "overlays": o.chk_show_rois.isChecked()})

    @staticmethod
    def content(state):
        return state["rois"], state["slices"], state["overlays"], state["loop"]

    def commit(self, label, before):
        if self.gesture is not None or self.restoring:
            return
        after = self.snapshot()
        if self.content(before) != self.content(after):
            self.undo_stack.append((label, before, after))
            self.undo_stack = self.undo_stack[-100:]
            self.redo_stack.clear()
            self.update_actions()

    def begin_gesture(self, label):
        if self.gesture is None:
            self.gesture = (label, self.snapshot())

    def end_gesture(self):
        if self.gesture is not None:
            label, before = self.gesture
            self.gesture = None
            self.commit(label, before)

    def restore(self, state):
        o = self.owner
        state = deepcopy(state)
        self.restoring = True
        try:
            o.rois, o.slices = state["rois"], state["slices"]
            o.active_roi_index, o.loop_slice_index = state["active"], state["loop"]
            o.chk_show_rois.setChecked(state["overlays"])
            o._candidate_roi = None
            o.view.clear_roi()
            o.compare_view.clear_roi()
            o._slice_stats_cache = None
            o._rebuild_roi_list()
            o._rebuild_slice_list()
            o.slice_list.setCurrentRow(state["selected"])
            o._push_rois_to_view()
            o._update_timeline_slice_regions()
            o._update_roi_status_label()
            o._render_from_ui()
            o._refresh_analysis_panel()
        finally:
            self.restoring = False

    def undo(self):
        self.end_gesture()
        if self.undo_stack:
            change = self.undo_stack.pop()
            self.restore(change[1])
            self.redo_stack.append(change)
            self.update_actions()

    def redo(self):
        if self.redo_stack:
            change = self.redo_stack.pop()
            self.restore(change[2])
            self.undo_stack.append(change)
            self.update_actions()

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.gesture = None
        self.update_actions()

    def update_actions(self):
        for action, stack, verb in ((self.owner.undo_action, self.undo_stack, "Undo"),
                                    (self.owner.redo_action, self.redo_stack, "Redo")):
            action.setEnabled(bool(stack))
            action.setText(verb + (" " + stack[-1][0] if stack else ""))
