import sys
import json
import os
import uuid
import shutil
from PySide6.QtWidgets import (QApplication, QMainWindow, QGraphicsView, QGraphicsScene,
                             QGraphicsItem, QGraphicsRectItem, QDialog, QVBoxLayout,
                             QHBoxLayout, QTextEdit, QComboBox, QDialogButtonBox, 
                             QLabel, QToolBar, QFileDialog, QInputDialog, QMessageBox,
                             QListWidget, QWidget, QSplitter)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPixmap, QColor, QPen, QAction, QIcon, QPainter


class VaultManager:
    """Backend Model: Handles file operations within the 'Vault' structure."""
    def __init__(self):
        self.vault_path = None #self is an instance of the VaultManager class. so if I say Test1 = VaultManager, the these would become Test1.vault_path etc.
        self.active_page_json = None  # Full path to active page's JSON
    
    def set_vault(self, path):
        # if and not are separate. If not means if os.path.isdir is false, then run the command nested within it (os.makedirs)
        if not os.path.isdir(path):
            # This makes the path. os.makedirs can make all missing folders within a path.
            os.makedirs(path)
            # This will link the path to the variable vault_path within the instance of VaultManager
        self.vault_path = path

    def get_all_page_names(self):
        #Returns list of pagenames (filenames without extensions) in the vault.

        # if self.vault_path, which is from above, returns falsy, meaning there is no path and file to read, instead of crashing, it creates an empty list
        # This self.vault_path can return false if, somehow the function gets triggered before I select a working folder
        if not self.vault_path:
            return []
        # split the files at the extension (.something), extract unit 0 in the list for files within self.vault_path (working folder), if the file ends with .json
        return [os.path.splitext(f)[0] for f in os.listdir(self.vault_path) if f.endswith('.json')]

    def import_background(self, source_image_path, pagename=None):
        """Copies an image to the vault and creates its sidecar JSON."""
        #Same as above.
        if not self.vault_path:
            return None
        
        #if pagename is falsy
        if not pagename:
            # splitext is same as above, but now, os.path.basename results in a single file, which source_image_path points to. Then, extract the unit 0 in the list
            base = os.path.splitext(os.path.basename(source_image_path))[0]
            unique_suffix = uuid.uuid4().hex[:6]
            pagename = f"{base}_{unique_suffix}"

        # 1. Copy image to Vault
        dest_image_name = f"{pagename}{os.path.splitext(source_image_path)[1]}"
        dest_image_path = os.path.join(self.vault_path, dest_image_name)
        shutil.copy2(source_image_path, dest_image_path)

        # 2. Create corresponding JSON
        dest_json_path = os.path.join(self.vault_path, f"{pagename}.json")
        initial_data = {
            "pagename": pagename,
            "background_image": dest_image_name,
            "regions": [] # List of {rect, comments, link_target_json}
        }
        with open(dest_json_path, 'w') as f:
            json.dump(initial_data, f, indent=4)

        return dest_json_path

    def load_page_data(self, json_path):
        """Loads data from a page JSON file."""
        if not os.path.exists(json_path):
            return None
        try:
            with open(json_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {json_path}: {e}")
            return None

    def save_page_data(self, json_path, background_image_name, region_items_data):
        """Saves current canvas state to the page JSON file."""
        data = {
            "pagename": os.path.splitext(os.path.basename(json_path))[0],
            "background_image": background_image_name,
            "regions": region_items_data
        }
        with open(json_path, 'w') as f:
            json.dump(data, f, indent=4)


class AnnotationRegion(QGraphicsRectItem):
    """View/Controller: An interactive rectangular region on the canvas."""
    def __init__(self, rect, comments="", link_target=None):
        super().__init__(rect)
        self.comments = comments
        self.link_target_json = link_target  # Filename of linked page's JSON (e.g., 'icon2.json')
        self.set_interaction_style()

    def set_interaction_style(self):
        """Visual distinctness based on linking."""
        pen = QPen(Qt.black, 1, Qt.DashLine)
        if self.link_target_json:
            # Highlight as a clickable Link
            pen.setColor(QColor(0, 150, 0, 200)) # Green
            self.setBrush(QColor(0, 150, 0, 30))
        else:
            # Regular annotation
            pen.setColor(QColor(0, 0, 200, 150)) # Blue
            self.setBrush(QColor(0, 0, 200, 20)) # Translucent Blue
        self.setPen(pen)

    def to_dict(self):
        """Serializes its state for JSON saving."""
        r = self.rect()
        return {
            "rect": [r.x(), r.y(), r.width(), r.height()],
            "comments": self.comments,
            "link_target_json": self.link_target_json
        }


class AnnotationEditor(QDialog):
    """View: A standard Qt Dialog to edit comments and set links."""
    def __init__(self, parent, comments, current_link, vault_page_list):
        super().__init__(parent)
        self.setWindowTitle("Edit Annotation")
        self.layout = QVBoxLayout(self)

        self.layout.addWidget(QLabel("Text Comments (Supports Copy/Paste):"))
        self.text_edit = QTextEdit(self)
        self.text_edit.setPlainText(comments)
        self.layout.addWidget(self.text_edit)

        self.layout.addWidget(QLabel("Link to Page (Changes Diagram):"))
        self.link_combo = QComboBox(self)
        self.link_combo.addItem("None", None)
        for page in vault_page_list:
            self.link_combo.addItem(page, f"{page}.json")
        
        # Set current selection
        idx = self.link_combo.findData(current_link)
        if idx != -1:
            self.link_combo.setCurrentIndex(idx)
        self.layout.addWidget(self.link_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.layout.addWidget(buttons)

    def get_data(self):
        return self.text_edit.toPlainText(), self.link_combo.currentData()


class DiagramScene(QGraphicsScene):
    """View/Controller: Manages items, drawing regions, and interactions."""
    MODES = {'Navigate': 0, 'DrawRegion': 1}

    def __init__(self, parent_main_window):
        super().__init__()
        self.app = parent_main_window
        self.mode = self.MODES['Navigate']
        self.current_drawing_rect = None
        self.start_point = None

    def set_mode(self, mode_name):
        self.mode = self.MODES[mode_name]

    def mousePressEvent(self, event):
        if self.mode == self.MODES['DrawRegion'] and event.button() == Qt.LeftButton:
            # Start drawing a new interactive region
            self.start_point = event.scenePos()
            self.current_drawing_rect = self.addRect(QRectF(self.start_point, self.start_point))
            pen = QPen(Qt.red, 2)
            pen.setStyle(Qt.DotLine)
            self.current_drawing_rect.setPen(pen)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.mode == self.MODES['DrawRegion'] and self.current_drawing_rect:
            # Update the rectangle being drawn
            rect = QRectF(self.start_point, event.scenePos()).normalized()
            self.current_drawing_rect.setRect(rect)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.mode == self.MODES['DrawRegion'] and event.button() == Qt.LeftButton and self.current_drawing_rect:
            # Drawing finished: Capture data and replace temp rectangle
            rect = self.current_drawing_rect.rect()
            if rect.width() > 5 and rect.height() > 5:
                # Open Editor immediately to capture comments/links
                self.app.edit_region_item_data(None, rect)
            self.removeItem(self.current_drawing_rect) # Remove temporary line
            self.current_drawing_rect = None
            self.app.set_navigate_mode() # Revert to navigation
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.scenePos(), self.app.graphics_view.transform())
        if isinstance(item, AnnotationRegion):
            if self.mode == self.MODES['Navigate']:
                if item.link_target_json:
                    # Execute Page Navigation
                    self.app.save_active_page()
                    target_path = os.path.join(self.app.backend.vault_path, item.link_target_json)
                    self.app.load_diagram_page(target_path)
                else:
                    # Standard Edit of existing region
                    self.app.edit_region_item_data(item)
        else:
            super().mouseDoubleClickEvent(event)


class DiagramWindow(QMainWindow):
    """View Main Controller: Sets up UI and connects backend."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Interactive Icon Diagrammer (Vault Style)")
        self.resize(1100, 700)

        self.backend = VaultManager()
        self.background_filename = None

        self.init_ui()

    def init_ui(self):
        # 1. Main UI Splitter Layout (Sidebar | Main Canvas View)
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        # ---- FILE BROWSER SIDEBAR PANEL ----
        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(5, 5, 5, 5)

        sidebar_label = QLabel("Vault Pages File Browser")
        sidebar_label.setStyleSheet("font-weight: bold;")
        sidebar_layout.addWidget(sidebar_label)

        self.file_list_widget = QListWidget()
        self.file_list_widget.itemClicked.connect(self.on_sidebar_item_clicked)
        sidebar_layout.addWidget(self.file_list_widget)
        
        # Add sidebar panel to the splitter framework
        splitter.addWidget(sidebar_widget)

        # ---- CANVAS ENVIRONMENT ----
        self.scene = DiagramScene(self)
        self.graphics_view = QGraphicsView(self.scene)
        
        # FIXED rendering optimizations via QPainter class flags
        self.graphics_view.setRenderHint(QPainter.Antialiasing)
        self.graphics_view.setRenderHint(QPainter.SmoothPixmapTransform)
        
        splitter.addWidget(self.graphics_view)

        # Distribute screen width layout (20% sidebar panel, 80% canvas)
        splitter.setSizes([200, 800])

        # 2. Toolbar Configuration
        self.toolbar = QToolBar("Main Toolbar", self)
        self.addToolBar(self.toolbar)

        # File adjustments
        import_act = QAction("Import Background Image (New Page)...", self)
        import_act.triggered.connect(self.import_new_page_workflow)
        self.toolbar.addAction(import_act)

        save_act = QAction("Save Page", self)
        save_act.triggered.connect(self.save_active_page)
        self.toolbar.addAction(save_act)
        
        self.toolbar.addSeparator()

        # Interaction Mode selectors
        self.nav_mode_act = QAction("Mode: Navigate/View (Double-Click Link)", self)
        self.nav_mode_act.setCheckable(True)
        self.nav_mode_act.triggered.connect(self.set_navigate_mode)
        self.toolbar.addAction(self.nav_mode_act)

        self.draw_mode_act = QAction("Mode: Draw Interactive Region (Click-Drag)", self)
        self.draw_mode_act.setCheckable(True)
        self.draw_mode_act.triggered.connect(self.set_draw_mode)
        self.toolbar.addAction(self.draw_mode_act)

        self.set_navigate_mode()

    def refresh_file_browser(self):
        """Scans the backend vault directory and updates the sidebar file list widget."""
        self.file_list_widget.blockSignals(True) # Prevent unexpected item triggers during sync
        self.file_list_widget.clear()
        
        pages = self.backend.get_all_page_names()
        for page in pages:
            self.file_list_widget.addItem(page)

        # If a file is open, highlight it automatically in the browser list
        if self.backend.active_page_json:
            current_name = os.path.splitext(os.path.basename(self.backend.active_page_json))[0]
            items = self.file_list_widget.findItems(current_name, Qt.MatchExactly)
            if items:
                self.file_list_widget.setCurrentItem(items[0])

        self.file_list_widget.blockSignals(False)

    def on_sidebar_item_clicked(self, item):
        """Triggered when a user clicks a file name entry inside the sidebar list panel."""
        page_name = item.text()
        target_json_path = os.path.join(self.backend.vault_path, f"{page_name}.json")
        
        if self.backend.active_page_json != target_json_path:
            self.save_active_page()
            self.load_diagram_page(target_json_path)

    def set_navigate_mode(self):
        self.scene.set_mode('Navigate')
        self.nav_mode_act.setChecked(True)
        self.draw_mode_act.setChecked(False)
        self.graphics_view.setCursor(Qt.ArrowCursor)

    def set_draw_mode(self):
        self.scene.set_mode('DrawRegion')
        self.nav_mode_act.setChecked(False)
        self.draw_mode_act.setChecked(True)
        self.graphics_view.setCursor(Qt.CrossCursor)

    def import_new_page_workflow(self):
        if not self.backend.vault_path:
            QMessageBox.warning(self, "No Vault", "Please open or create a Vault folder first.")
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "Import Background Image", "", "Images (*.png *.jpg)")
        if not file_path:
            return

        new_json_path = self.backend.import_background(file_path)
        if new_json_path:
            self.load_diagram_page(new_json_path)
            self.refresh_file_browser() # Update list with newly built sidecar page

    def load_diagram_page(self, json_path):
        """Loads a full diagram scene from a Vault JSON path."""
        data = self.backend.load_page_data(json_path)
        if not data:
            return

        self.backend.active_page_json = json_path
        self.background_filename = data['background_image']
        
        # 1. Clear current scene
        self.scene.clear()

        # 2. Add Background Image
        img_path = os.path.join(self.backend.vault_path, self.background_filename)
        if os.path.exists(img_path):
            pixmap = QPixmap(img_path)
            bg_item = self.scene.addPixmap(pixmap)
            bg_item.setZValue(-1) # Ensure background is behind annotations
            self.scene.setSceneRect(pixmap.rect())
        else:
            QMessageBox.critical(self, "Error", f"Could not find background image: {img_path}")

        # 3. Add saved Annotation Regions
        for region_data in data['regions']:
            x, y, w, h = region_data['rect']
            rect = QRectF(x, y, w, h)
            item = AnnotationRegion(rect, region_data['comments'], region_data['link_target_json'])
            self.scene.addItem(item)

        self.setWindowTitle(f"Editing: {data['pagename']} ({self.backend.vault_path})")
        
        # Keep sidebar highlight selection context matching current canvas page
        self.refresh_file_browser()

    def edit_region_item_data(self, item=None, new_rect=None):
        """Handles creating/editing region data via AnnotationEditor."""
        comments = ""
        link = None
        pages = self.backend.get_all_page_names()

        if item:
            comments = item.comments
            link = item.link_target_json
            pages = [p for p in pages if p != os.path.splitext(os.path.basename(self.backend.active_page_json))[0]]

        dialog = AnnotationEditor(self, comments, link, pages)
        if dialog.exec():
            new_comments, new_link = dialog.get_data()
            if item:
                item.comments = new_comments
                item.link_target_json = new_link
                item.set_interaction_style()
            elif new_rect:
                new_item = AnnotationRegion(new_rect, new_comments, new_link)
                self.scene.addItem(new_item)
            self.save_active_page()

    def save_active_page(self):
        """Backend Save: Saves the current scene state to the JSON sidecar."""
        if not self.backend.active_page_json:
            return
        
        region_items = []
        for item in self.scene.items():
            if isinstance(item, AnnotationRegion):
                region_items.append(item.to_dict())

        self.backend.save_page_data(self.backend.active_page_json, self.background_filename, region_items)
        print(f"Saved: {self.backend.active_page_json}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    window = DiagramWindow()

    # Define Obsidian-style 'Vault' folder location
    vault_folder = QFileDialog.getExistingDirectory(window, "Select or Create Vault Folder (where diagrams are stored)")
    if vault_folder:
        window.backend.set_vault(vault_folder)
        
        # Populate sidebar on launch
        window.refresh_file_browser()
        
        # Attempt to auto-load initial page if files are already found inside vault
        pages = window.backend.get_all_page_names()
        if pages:
            window.load_diagram_page(os.path.join(vault_folder, f"{pages[0]}.json"))
            
        window.show()
    else:
        sys.exit(0)

    sys.exit(app.exec())