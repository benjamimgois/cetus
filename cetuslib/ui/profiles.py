"""Profile tree widgets for Cetus."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QTreeWidget


__all__ = ['SshProfilesTree', 'SerialProfilesTree']


class SshProfilesTree(QTreeWidget):
    """QTreeWidget with internal drag-and-drop reordering of SSH profiles."""
    reordered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

    def dragEnterEvent(self, event):
        item = self.currentItem()
        if item is not None:
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        item = self.currentItem()
        if item is None:
            event.ignore()
            return
        pos = event.position().toPoint()
        target = self.itemAt(pos)
        if item.parent() is None:
            # Dragging a group — only valid over another group header
            if target is not None and target is not item and target.parent() is None:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def dropEvent(self, event):
        dragged = self.currentItem()
        if dragged is None:
            event.ignore()
            return

        pos = event.position().toPoint()
        target = self.itemAt(pos)
        if target is None or target is dragged:
            event.ignore()
            return

        indicator = self.dropIndicatorPosition()

        # --- Group drag: reorder entire group among sibling groups ---
        if dragged.parent() is None:
            # Resolve target to a group header
            target_group = target if target.parent() is None else target.parent()
            if target_group is dragged:
                event.ignore()
                return
            root = self.invisibleRootItem()
            dragged_idx = root.indexOfChild(dragged)
            target_idx = root.indexOfChild(target_group)
            insert_idx = target_idx + 1 if indicator == QAbstractItemView.DropIndicatorPosition.BelowItem else target_idx
            root.takeChild(dragged_idx)
            if dragged_idx < insert_idx:
                insert_idx -= 1
            root.insertChild(insert_idx, dragged)
            dragged.setExpanded(True)
            self.setCurrentItem(dragged)
            event.accept()
            self.reordered.emit()
            return

        # --- Profile drag: existing logic ---
        if target.parent() is None:
            # Dropped on a group header → append at end of that group
            target_group = target
            insert_idx = target_group.childCount()
        else:
            target_group = target.parent()
            idx = target_group.indexOfChild(target)
            insert_idx = idx + 1 if indicator == QAbstractItemView.DropIndicatorPosition.BelowItem else idx

        old_parent = dragged.parent()
        old_idx = old_parent.indexOfChild(dragged)

        old_parent.takeChild(old_idx)

        if target_group is old_parent and old_idx < insert_idx:
            insert_idx -= 1

        target_group.insertChild(insert_idx, dragged)
        target_group.setExpanded(True)
        self.setCurrentItem(dragged)

        event.accept()
        self.reordered.emit()


class SerialProfilesTree(QTreeWidget):
    """QTreeWidget with internal drag-and-drop reordering of Serial profiles."""
    reordered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

    def dragEnterEvent(self, event):
        item = self.currentItem()
        if item is not None and item.parent() is not None:
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        item = self.currentItem()
        if item is not None and item.parent() is not None:
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        dragged = self.currentItem()
        if dragged is None or dragged.parent() is None:
            event.ignore()
            return
        pos = event.position().toPoint()
        target = self.itemAt(pos)
        if target is None or target is dragged:
            event.ignore()
            return
        indicator = self.dropIndicatorPosition()
        if target.parent() is None:
            target_group = target
            insert_idx = target_group.childCount()
        else:
            target_group = target.parent()
            idx = target_group.indexOfChild(target)
            insert_idx = idx + 1 if indicator == QAbstractItemView.DropIndicatorPosition.BelowItem else idx
        old_parent = dragged.parent()
        old_idx = old_parent.indexOfChild(dragged)
        old_parent.takeChild(old_idx)
        if target_group is old_parent and old_idx < insert_idx:
            insert_idx -= 1
        target_group.insertChild(insert_idx, dragged)
        target_group.setExpanded(True)
        self.setCurrentItem(dragged)
        event.accept()
        self.reordered.emit()
