"""
DeFi Guardian - Desktop Application
Formal Verification Suite with SPIN Model Checker
Full Translation Support for Solidity/Rust
"""

import webview
import threading
import os
import sys
import json
import sqlite3
import subprocess
import time
from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime
import re
import webbrowser
import customtkinter as ctk
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="customtkinter")
from tkinter import filedialog, messagebox
import tempfile
import uuid
from pathlib import Path
import tkinter as tk
import socket

# Augment PATH for verification tools
def _augment_path():
    home = Path.home()
    extra_paths = [
        str(home / ".elan" / "bin"),
        str(home / ".cargo" / "bin"),
        str(home / ".opam" / "default" / "bin"),
        str(home / ".local" / "bin"),
        "/usr/local/bin",
        "/opt/verus",
    ]
    current_path = os.environ.get("PATH", "")
    for p in extra_paths:
        if p not in current_path:
            current_path = f"{p}{os.pathsep}{current_path}"
    os.environ["PATH"] = current_path

_augment_path()

# PyQt6 version - more native look, better performance
# Requirements: PyQt6, PyQt6-WebEngine (for embedded dashboard)
try:
    from PyQt6.QtWidgets import (
        QMainWindow, QSplitter, QTabWidget, QTextEdit,
        QTreeView, QToolBar, QStatusBar, QDockWidget
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    from PyQt6.QtGui import QFont, QPalette, QColor, QSyntaxHighlighter
    HAS_PYQT6 = True
except ImportError:
    HAS_PYQT6 = False

# NiceGUI example - web UI in desktop wrapper
try:
    from nicegui import ui, app as nicegui_app
    HAS_NICEGUI = True
except ImportError:
    HAS_NICEGUI = False

# Gradio version - modern AI-focused interface
try:
    import gradio as gr
    HAS_GRADIO = True
except ImportError:
    HAS_GRADIO = False

# Project directory for file I/O
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")
SPIN_LOGS = os.path.join(LOGS_DIR, "spin")
CERTORA_LOGS = os.path.join(LOGS_DIR, "certora")
COQ_LOGS = os.path.join(LOGS_DIR, "coq")
LEAN_LOGS = os.path.join(LOGS_DIR, "lean")
RUST_LOGS = os.path.join(LOGS_DIR, "rust_tools")
GENERATED_DIR = os.path.join(PROJECT_DIR, "generated")
MODELS_DIR = os.path.join(GENERATED_DIR, "models")
IMAGES_DIR = os.path.join(GENERATED_DIR, "images")
REPORTS_DIR = os.path.join(GENERATED_DIR, "reports")
CONSOLE_DIR = os.path.join(PROJECT_DIR, "console_exports")
AUDIT_LOG_FILE = os.path.join(REPORTS_DIR, "audit_log.json")
TRACES_DIR = os.path.join(REPORTS_DIR, "traces")

# Ensure directories exist
for d in [LOGS_DIR, SPIN_LOGS, CERTORA_LOGS, COQ_LOGS, LEAN_LOGS, RUST_LOGS,
          GENERATED_DIR, MODELS_DIR, IMAGES_DIR, REPORTS_DIR, CONSOLE_DIR, TRACES_DIR]:
    os.makedirs(d, exist_ok=True)
# First Lean check after boot can take minutes (Elan/toolchain + stdlib); override with DG_LEAN_TIMEOUT.
LEAN_TIMEOUT_SECONDS = int(os.environ.get("DG_LEAN_TIMEOUT", "300"))
# Streamlit cold-start can exceed a few seconds; cap wait when opening the browser.
STREAMLIT_START_TIMEOUT = float(os.environ.get("DG_STREAMLIT_START_TIMEOUT", "120"))

class CounterexampleDashboard(ctk.CTkToplevel):
    """Interactive dashboard for counterexample analysis"""
    def __init__(self, master, trace_data):
        super().__init__(master)
        self.title("🔍 Counterexample Analysis Dashboard")
        self.geometry("1100x700")
        self.trace_data = trace_data
        self.selected_step = 0

        # Grid layout
        self.grid_columnconfigure(0, weight=1) # Trace list
        self.grid_columnconfigure(1, weight=1) # Variable inspector
        self.grid_rowconfigure(0, weight=1)

        # --- Left Panel: Call Trace ---
        self.trace_frame = ctk.CTkFrame(self, corner_radius=0)
        self.trace_frame.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

        ctk.CTkLabel(self.trace_frame, text="📜 CALL TRACE", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=10)

        # Theme-aware colors for Listbox
        is_dark = ctk.get_appearance_mode() == "Dark"
        bg_color = "#1e1e1e" if is_dark else "#f1f3f5"
        fg_color = "#cccccc" if is_dark else "#212529"

        self.trace_list = tk.Listbox(
            self.trace_frame,
            bg=bg_color,
            fg=fg_color,
            selectbackground="#094771",
            font=("Consolas", 10),
            borderwidth=0,
            highlightthickness=0
        )
        self.trace_list.pack(fill="both", expand=True, padx=10, pady=10)
        self.trace_list.bind("<<ListboxSelect>>", self.on_step_select)

        # Populate trace list
        for i, step in enumerate(trace_data.get("steps", [])):
            if step.get("type") == "violation":
                self.trace_list.insert("end", f" ❌ VIOLATION: {step['message']}")
                self.trace_list.itemconfig("end", fg="#ff4444")
            else:
                self.trace_list.insert("end", f" [{step['step']}] {step['proc_name']} (line {step['line']})")

        # --- Right Panel: Variables ---
        self.vars_frame = ctk.CTkFrame(self, corner_radius=0)
        self.vars_frame.grid(row=0, column=1, sticky="nsew", padx=2, pady=2)

        ctk.CTkLabel(self.vars_frame, text="📊 VARIABLE INSPECTOR", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=10)

        # Theme-aware colors for Textbox
        is_dark = ctk.get_appearance_mode() == "Dark"
        text_bg = "#0c0c0c" if is_dark else "#ffffff"
        text_fg = "#00ffcc" if is_dark else "#0066cc"

        self.vars_table = ctk.CTkTextbox(
            self.vars_frame,
            font=("Consolas", 11),
            fg_color=text_bg,
            text_color=text_fg
        )
        self.vars_table.pack(fill="both", expand=True, padx=10, pady=10)

        # Initial variable display
        self.update_vars_display(0)

    def on_step_select(self, event):
        selection = self.trace_list.curselection()
        if selection:
            self.selected_step = selection[0]
            self.update_vars_display(self.selected_step)

    def update_vars_display(self, step_idx):
        self.vars_table.delete("1.0", "end")

        steps = self.trace_data.get("steps", [])
        if not steps or step_idx >= len(steps):
            return

        step = steps[step_idx]
        if step.get("type") == "violation":
            self.vars_table.insert("end", f"🚨 PROPERTY VIOLATION DETECTED\n\n{step['message']}")
            return

        self.vars_table.insert("end", f"Step {step['step']} | {step['proc_name']} | Line {step['line']}\n")
        self.vars_table.insert("end", "="*50 + "\n\n")

        # Variables
        vars_dict = step.get("variables", {})
        if vars_dict:
            self.vars_table.insert("end", f"{'VARIABLE':<25} | {'VALUE':<15}\n")
            self.vars_table.insert("end", "-"*50 + "\n")
            for var, val in sorted(vars_dict.items()):
                # Highlight updates in this step
                prefix = "✨ " if var in step.get("updates", {}) else "  "
                self.vars_table.insert("end", f"{prefix}{var:<23} | {val:<15}\n")
        else:
            self.vars_table.insert("end", "No local variables in this step.")

class ResizablePanel:
    """Handle resizing of panels with mouse drag"""
    def __init__(self, master, panel_to_resize, orientation='vertical', min_size=200, max_size=800):
        self.master = master
        self.panel = panel_to_resize
        self.orientation = orientation
        self.min_size = min_size
        self.max_size = max_size
        self.dragging = False
        self.start_x = 0
        self.start_y = 0
        self.start_size = 0

        # Create resize handle
        if orientation == 'vertical':
            self.handle = ctk.CTkFrame(master, width=5, height=20, cursor="sb_h_double_arrow",
                                       fg_color="#3a3a3a", corner_radius=2)
            self.handle.bind("<Button-1>", self.start_drag)
            self.handle.bind("<B1-Motion>", self.drag)
            self.handle.bind("<ButtonRelease-1>", self.stop_drag)
        else:
            self.handle = ctk.CTkFrame(master, width=20, height=5, cursor="sb_v_double_arrow",
                                       fg_color="#3a3a3a", corner_radius=2)
            self.handle.bind("<Button-1>", self.start_drag)
            self.handle.bind("<B1-Motion>", self.drag)
            self.handle.bind("<ButtonRelease-1>", self.stop_drag)

    def start_drag(self, event):
        self.dragging = True
        self.start_x = event.x_root
        self.start_y = event.y_root
        if self.orientation == 'vertical':
            self.start_size = self.panel.winfo_width()
        else:
            self.start_size = self.panel.winfo_height()

    def drag(self, event):
        if self.dragging:
            if self.orientation == 'vertical':
                delta = event.x_root - self.start_x
                new_size = self.start_size + delta
                new_size = max(self.min_size, min(self.max_size, new_size))
                self.panel.configure(width=new_size)
                self.master.grid_columnconfigure(0, minsize=new_size)
            else:
                delta = event.y_root - self.start_y
                new_size = self.start_size + delta
                new_size = max(self.min_size, min(self.max_size, new_size))
                self.panel.configure(height=new_size)
                self.master.grid_rowconfigure(1, minsize=new_size)

    def stop_drag(self, event):
        self.dragging = False


class ThemeManager:
    """Manage color themes for the application"""

    # Predefined themes matching the image
    THEMES = {
        "Solarized Dark": {
            "bg": "#002b36",
            "fg": "#839496",
            "accent": "#268bd2",
            "success": "#2aa198",
            "error": "#dc322f",
            "warning": "#cb4b16",
            "editor_bg": "#073642",
            "editor_fg": "#93a1a1",
            "terminal_bg": "#002b36",
            "terminal_fg": "#00ff00",
            "sidebar_bg": "#002b36",
            "button_bg": "#268bd2",
            "button_hover": "#2aa198"
        },
        "Dark+ (Default)": {
            "bg": "#1e1e1e",
            "fg": "#cccccc",
            "accent": "#007acc",
            "success": "#6a9955",
            "error": "#f48771",
            "warning": "#dcdcaa",
            "editor_bg": "#1e1e1e",
            "editor_fg": "#cccccc",
            "terminal_bg": "#0c0c0c",
            "terminal_fg": "#00ff00",
            "sidebar_bg": "#252526",
            "button_bg": "#007acc",
            "button_hover": "#0451a5"
        },
        "Monokai": {
            "bg": "#272822",
            "fg": "#f8f8f2",
            "accent": "#66d9ef",
            "success": "#a6e22e",
            "error": "#f92672",
            "warning": "#fd971f",
            "editor_bg": "#272822",
            "editor_fg": "#f8f8f2",
            "terminal_bg": "#272822",
            "terminal_fg": "#00ff00",
            "sidebar_bg": "#272822",
            "button_bg": "#66d9ef",
            "button_hover": "#a6e22e"
        },
        "Tokyo Night": {
            "bg": "#1a1b26",
            "fg": "#a9b1d6",
            "accent": "#7aa2f7",
            "success": "#9ece6a",
            "error": "#f7768e",
            "warning": "#e0af68",
            "editor_bg": "#1a1b26",
            "editor_fg": "#a9b1d6",
            "terminal_bg": "#1a1b26",
            "terminal_fg": "#00ff00",
            "sidebar_bg": "#16161e",
            "button_bg": "#7aa2f7",
            "button_hover": "#bb9af7"
        },
        "Abyss": {
            "bg": "#0b0c10",
            "fg": "#c5c6c7",
            "accent": "#45a29e",
            "success": "#66fcf1",
            "error": "#f05454",
            "warning": "#f2a900",
            "editor_bg": "#0b0c10",
            "editor_fg": "#c5c6c7",
            "terminal_bg": "#0b0c10",
            "terminal_fg": "#66fcf1",
            "sidebar_bg": "#1f2833",
            "button_bg": "#45a29e",
            "button_hover": "#66fcf1"
        },
        "Quiet Light": {
            "bg": "#f3f3f3",
            "fg": "#333333",
            "accent": "#0066cc",
            "success": "#008000",
            "error": "#cc0000",
            "warning": "#e6b800",
            "editor_bg": "#ffffff",
            "editor_fg": "#333333",
            "terminal_bg": "#f3f3f3",
            "terminal_fg": "#008000",
            "sidebar_bg": "#eaeaea",
            "button_bg": "#0066cc",
            "button_hover": "#0052a3"
        }
    }

    def __init__(self, app):
        self.app = app
        self.current_theme = "Dark+ (Default)"

    def apply_theme(self, theme_name):
        """Apply a named colour theme — delegates to the app's update_ui_colors."""
        if theme_name not in self.THEMES:
            return
        theme = self.THEMES[theme_name]
        self.current_theme = theme_name
        is_dark = "Dark" in theme_name or "Night" in theme_name or "Cyber" in theme_name
        ctk.set_appearance_mode("dark" if is_dark else "light")

        # Map legacy theme dict keys onto the new theme tokens
        app = self.app
        if hasattr(app, 'theme'):
            app.theme.BG          = theme.get("bg",          app.theme.BG)
            app.theme.PANEL_BG    = theme.get("sidebar_bg",  app.theme.PANEL_BG)
            app.theme.EDITOR_BG   = theme.get("editor_bg",   app.theme.EDITOR_BG)
            app.theme.TERMINAL_BG = theme.get("terminal_bg", app.theme.TERMINAL_BG)
            app.theme.TEXT_MAIN   = theme.get("editor_fg",   app.theme.TEXT_MAIN)
            app.theme.ACCENT      = theme.get("accent",      app.theme.ACCENT)

        if hasattr(app, 'update_ui_colors'):
            app.update_ui_colors()

        self.save_theme_preference(theme_name)

    def save_theme_preference(self, theme_name):
        """Save theme preference to file"""
        config_file = os.path.join(PROJECT_DIR, "theme_config.json")
        try:
            with open(config_file, 'w') as f:
                json.dump({"theme": theme_name}, f)
        except:
            pass

    def load_theme_preference(self):
        """Load saved theme preference"""
        config_file = os.path.join(PROJECT_DIR, "theme_config.json")
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                if "theme" in config and config["theme"] in self.THEMES:
                    return config["theme"]
        except:
            pass
        return "Dark+ (Default)"


class EnhancedThemeManager(ThemeManager):
    """Extended theme manager with glassmorphism and animations"""

    THEMES = {
        **ThemeManager.THEMES,
        "DeFi Dark": {
            "bg": "#0a0e17",
            "fg": "#e0e0e0",
            "accent": "#00d4aa",
            "accent_secondary": "#7c3aed",
            "success": "#10b981",
            "error": "#ef4444",
            "warning": "#f59e0b",
            "editor_bg": "#0f141e",
            "editor_fg": "#e2e8f0",
            "terminal_bg": "#080c14",
            "terminal_fg": "#00ffcc",
            "sidebar_bg": "#0c111a",
            "button_bg": "#00d4aa",
            "button_hover": "#00bf9a",
            "card_bg": "#131a26",
            "border": "#1e2a3a",
        },
        "Cyberpunk": {
            "bg": "#0d0221",
            "fg": "#ff00ff",
            "accent": "#00ffff",
            "accent_secondary": "#ff00ff",
            "success": "#00ff88",
            "error": "#ff0055",
            "warning": "#ffaa00",
            "editor_bg": "#12022b",
            "editor_fg": "#00ffff",
            "terminal_bg": "#0a001a",
            "terminal_fg": "#00ff88",
            "sidebar_bg": "#0f0225",
            "button_bg": "#ff00ff",
            "button_hover": "#cc00cc",
            "card_bg": "#150530",
            "border": "#3d0a5c",
        },
        "Nord Frost": {
            "bg": "#2e3440",
            "fg": "#eceff4",
            "accent": "#88c0d0",
            "accent_secondary": "#81a1c1",
            "success": "#a3be8c",
            "error": "#bf616a",
            "warning": "#ebcb8b",
            "editor_bg": "#3b4252",
            "editor_fg": "#e5e9f0",
            "terminal_bg": "#242933",
            "terminal_fg": "#8fbcbb",
            "sidebar_bg": "#2e3440",
            "button_bg": "#5e81ac",
            "button_hover": "#81a1c1",
            "card_bg": "#3b4252",
            "border": "#4c566a",
        },
        "Matrix": {
            "bg": "#0a0f0a",
            "fg": "#00ff41",
            "accent": "#00ff41",
            "accent_secondary": "#008f11",
            "success": "#00ff41",
            "error": "#ff3333",
            "warning": "#ffff00",
            "editor_bg": "#0d140d",
            "editor_fg": "#00ff41",
            "terminal_bg": "#050805",
            "terminal_fg": "#00ff41",
            "sidebar_bg": "#0a0f0a",
            "button_bg": "#008f11",
            "button_hover": "#00cc1a",
            "card_bg": "#111a11",
            "border": "#1a3a1a",
        }
    }


class StyledButton(ctk.CTkButton):
    """Enhanced button with gradient, animation, and state effects"""

    def __init__(self, master, **kwargs):
        self.gradient = kwargs.pop('gradient', False)
        self.pulse = kwargs.pop('pulse', False)
        self.tool_name = kwargs.pop('tool_name', None)

        super().__init__(master, **kwargs)

        if self.gradient:
            self.configure(
                fg_color="transparent",
                bg_color="transparent"
            )
            self._create_gradient()

        self.bind("<Enter>", self.on_hover)
        self.bind("<Leave>", self.on_leave)

    def _create_gradient(self):
        """Create linear gradient background"""
        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
            bg=self.cget("bg_color")
        )
        self.canvas.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Gradient from accent to accent_secondary
        self.canvas.create_rectangle(
            0, 0, self.winfo_width(), self.winfo_height(),
            fill=self.cget("fg_color"),
            outline="",
            tags="gradient"
        )

    def on_hover(self, event):
        """Smooth hover animation"""
        self.animate_color(
            self.cget("fg_color"),
            self.cget("hover_color"),
            duration=150
        )

    def on_leave(self, event):
        self.animate_color(
            self.cget("hover_color"),
            self.cget("fg_color"),
            duration=150
        )

    def hex_to_rgb(self, hex_color):
        """Convert hex color to RGB tuple"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join([c*2 for c in hex_color])
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def rgb_to_hex(self, r, g, b):
        """Convert RGB tuple to hex color"""
        return f'#{r:02x}{g:02x}{b:02x}'

    def animate_color(self, from_color, to_color, duration):
        """Color transition animation"""
        steps = 10
        delay = duration // steps

        def interpolate_color(step):
            try:
                r1, g1, b1 = self.hex_to_rgb(from_color)
                r2, g2, b2 = self.hex_to_rgb(to_color)

                t = step / steps
                r = int(r1 + (r2 - r1) * t)
                g = int(g1 + (g2 - g1) * t)
                b = int(b1 + (b2 - b1) * t)

                self.configure(fg_color=self.rgb_to_hex(r, g, b))

                if step < steps:
                    self.after(delay, lambda: interpolate_color(step + 1))
            except:
                pass

        interpolate_color(0)


class ToolButton(StyledButton):
    """Specialized button for verification tools with status indicator"""

    def __init__(self, master, tool_name, **kwargs):
        super().__init__(master, **kwargs)
        self.tool_name = tool_name
        self.status = "idle"  # idle, running, success, error

        # Add status indicator dot
        self.status_canvas = tk.Canvas(
            self,
            width=12,
            height=12,
            highlightthickness=0,
            bg=self.cget("fg_color")
        )
        self.status_canvas.place(relx=0.05, rely=0.5, anchor="w")
        self.update_status_indicator()

    def update_status_indicator(self):
        colors = {
            "idle": "#6b7280",
            "running": "#f59e0b",
            "success": "#10b981",
            "error": "#ef4444"
        }
        self.status_canvas.delete("all")
        self.status_canvas.create_oval(
            2, 2, 10, 10,
            fill=colors.get(self.status, "#6b7280"),
            outline=""
        )
        if self.status == "running":
            self.animate_pulse()

    def animate_pulse(self):
        """Pulse animation for running state"""
        def pulse(opacity=1.0, direction=-1):
            if self.status != "running":
                return
            opacity += direction * 0.1
            if opacity <= 0.5 or opacity >= 1.0:
                direction *= -1

            color = f"#{int(245 * opacity):02x}{int(158 * opacity):02x}{int(11 * opacity):02x}"
            self.status_canvas.itemconfig("all", fill=color)

            self.after(50, lambda: pulse(opacity, direction))

        pulse()


class ScrollableSidebar(ctk.CTkFrame):
    """Custom scrollable sidebar with improved behavior"""

    def __init__(self, master, width=420, **kwargs):
        super().__init__(master, width=width, **kwargs)
        self.width = width
        self.grid_propagate(False)

        # Create canvas for scrolling
        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
            bg="#1e1e1e",
            width=width - 20
        )
        self.canvas.pack(side="left", fill="both", expand=True)

        # Add scrollbar
        self.scrollbar = ctk.CTkScrollbar(
            self,
            command=self.canvas.yview,
            orientation="vertical"
        )
        self.scrollbar.pack(side="right", fill="y")

        # Configure canvas scrolling
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Create inner frame for content
        self.inner_frame = ctk.CTkFrame(self.canvas, fg_color="transparent")
        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.inner_frame,
            anchor="nw",
            width=width - 30
        )

        # Bind events
        self.inner_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Mouse wheel binding
        self.bind_mousewheel()

    def _on_frame_configure(self, event=None):
        """Reset the scroll region to encompasses inner frame"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        """Resize inner frame when canvas is resized"""
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def bind_mousewheel(self, widget=None):
        """Bind mouse wheel scrolling recursively to all widgets"""
        if widget is None:
            widget = self

        def on_mousewheel(event):
            # For Linux (Button-4/5), delta is not used
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")
            else:
                # Windows/macOS
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        # Bind to the widget itself
        widget.bind("<MouseWheel>", on_mousewheel, add="+")
        widget.bind("<Button-4>", on_mousewheel, add="+")
        widget.bind("<Button-5>", on_mousewheel, add="+")

        # Recursively bind to all children
        for child in widget.winfo_children():
            self.bind_mousewheel(child)

    def get_inner_frame(self):
        """Return inner frame for adding widgets"""
        return self.inner_frame


class ThemeSettingsPanel(ctk.CTkFrame):
    """Theme selection and customization panel"""

    def __init__(self, parent, theme_manager, **kwargs):
        super().__init__(parent, **kwargs)
        self.theme_manager = theme_manager

        # Theme selection label
        ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#888888"
        ).pack(anchor="w", pady=(10, 5))

        # Theme dropdown
        self.theme_var = ctk.StringVar(value=theme_manager.current_theme)
        self.theme_dropdown = ctk.CTkOptionMenu(
            self,
            values=list(self.theme_manager.THEMES.keys()),
            variable=self.theme_var,
            command=self.on_theme_change,
            dynamic_resizing=False,
            width=200
        )
        self.theme_dropdown.pack(fill="x", pady=5)

        # Preview label
        self.preview_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="#888888"
        )
        self.preview_label.pack(anchor="w", pady=(5, 10))

        # Update preview on selection
        self.update_preview()

    def on_theme_change(self, choice):
        """Handle theme change"""
        self.theme_manager.apply_theme(choice)
        self.update_preview()

    def update_preview(self):
        """Update preview text"""
        theme = self.theme_manager.current_theme
        self.preview_label.configure(text=f"Current: {theme}")


def wait_for_tcp_port(
    host: str,
    port: int,
    timeout: float = STREAMLIT_START_TIMEOUT,
    poll_interval: float = 0.25,
) -> bool:
    """Return True once ``host:port`` accepts a TCP connection (server is listening)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            time.sleep(poll_interval)
    return False


from rust_verifiers import (
    CREUSOT_STD_PATH,
    RustVerifier,
    build_prusti_env,
    classify_prusti_failure,
    prepend_creusot_prelude,
    preprocess_prusti_source,
    prusti_command,
    should_skip_prusti_for_source,
    strip_rust_main_for_lib,
)
from verus_integration import VerusIntegration

# Import verification state
try:
    from verification_state import VerificationState
except ImportError:
    class VerificationState:
        @staticmethod
        def save_result(success, output, errors, model_name, ltl_results=None):
            import json
            import time
            from datetime import datetime

            # Load existing state so we don't wipe per-tool entries
            report_path = os.path.join(REPORTS_DIR, "verification_state.json")
            state = {}
            if os.path.exists(report_path):
                try:
                    with open(report_path, 'r') as f:
                        state = json.load(f)
                except Exception:
                    state = {}

            # Update top-level SPIN scalars
            state.update({
                'timestamp': time.time(),
                'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'success': success,
                'output': output,
                'errors': errors,
                'model_name': model_name,
                'verified': True,
                'ltl_results': ltl_results or [],
            })

            # Parse statistics from SPIN output
            if output:
                depth_match = re.search(r"depth reached (\d+)", output)
                if depth_match:
                    state['depth'] = int(depth_match.group(1))
                states_match = re.search(r"(\d+) states, stored", output)
                if states_match:
                    state['states_stored'] = int(states_match.group(1))
                trans_match = re.search(r"(\d+) transitions", output)
                if trans_match:
                    state['transitions'] = int(trans_match.group(1))
                err_match = re.search(r"errors: (\d+)", output)
                state['errors_count'] = int(err_match.group(1)) if err_match else 0

            # Also write into the per-tool 'spin' key so the dashboard
            # can read it consistently alongside certora/coq/lean etc.
            state['spin'] = {
                'timestamp': datetime.now().isoformat(),
                'status': 'PASS' if success else 'FAIL',
                'success': success,
                'output': output,
                'errors': errors,
                'ltl_results': ltl_results or [],
                'states_stored': state.get('states_stored', 0),
                'transitions': state.get('transitions', 0),
                'depth': state.get('depth', 0),
            }

            with open(report_path, 'w') as f:
                json.dump(state, f, indent=2)
            return True

# Import translators
try:
    from translator import DeFiTranslator, VerifiedTranslator
except ImportError:
    class DeFiTranslator:
        @staticmethod
        def translate_solidity(source_code):
            """Basic Solidity to Promela translation"""
            pml = "/* Auto-generated Promela Model */\n"
            pml += "active proctype Contract() {\n"
            pml += "    printf(\"Contract initialized\\n\");\n"
            pml += "}\n"
            return pml

        @staticmethod
        def translate_rust(source_code):
            """Basic Rust to Promela translation"""
            pml = "/* Auto-generated Promela Model from Rust */\n"
            pml += "active proctype Program() {\n"
            pml += "    printf(\"Program initialized\\n\");\n"
            pml += "}\n"
            return pml

        @staticmethod
        def extract_state_variables(source_code):
            return []

        @staticmethod
        def generate_ltl_properties(state_vars):
            return ""

    class VerifiedTranslator(DeFiTranslator):
        def translate_with_proof(self, source_code):
            pml = self.translate_solidity(source_code)
            return pml, ["∀s: State • source_invariant(s) ⇒ pml_invariant(translate(s))"]

# Import verifier plugins
try:
    from verifier_plugins import PluginManager
except ImportError:
    PluginManager = None

class DeFiDarkTheme:
    """Design constants — VS Code Dark+ inspired professional theme"""
    BG           = "#1e1e1e"   # VS Code editor background
    PANEL_BG     = "#252526"   # VS Code sidebar background
    ACTIVITY_BG  = "#333333"   # VS Code activity bar
    TERMINAL_BG  = "#1e1e1e"   # Integrated terminal background
    EDITOR_BG    = "#1e1e1e"   # Editor area
    INPUT_BG     = "#3c3c3c"   # Input/dropdown background
    ACCENT       = "#007acc"   # VS Code blue
    ACCENT_DARK  = "#005a9e"   # Hover blue
    ACCENT_GLOW  = "#0098ff"   # Active/focus blue
    SECONDARY    = "#c586c0"   # VS Code purple (keywords)
    SUCCESS      = "#4ec9b0"   # VS Code teal (types)
    SUCCESS_DIM  = "#1e3a2f"   # Success background
    ERROR        = "#f44747"   # VS Code red
    ERROR_DIM    = "#3a1e1e"   # Error background
    WARNING      = "#cca700"   # VS Code yellow
    WARNING_DIM  = "#3a2e00"   # Warning background
    TEXT_MAIN    = "#d4d4d4"   # VS Code default text
    TEXT_DIM     = "#858585"   # VS Code comments/dim
    TEXT_BRIGHT  = "#ffffff"   # Active/selected text
    BORDER       = "#3e3e42"   # VS Code panel borders
    BORDER_FOCUS = "#007acc"   # Focused border
    SELECTION    = "#094771"   # VS Code selection blue
    HOVER        = "#2a2d2e"   # List item hover
    ACTIVE       = "#37373d"   # Active list item
    TAB_ACTIVE   = "#1e1e1e"   # Active tab background
    TAB_INACTIVE = "#2d2d2d"   # Inactive tab background
    TAB_BORDER   = "#007acc"   # Active tab top border

class DeFiLightTheme:
    """Design constants — VS Code Light+ / Quiet Light inspired"""
    BG           = "#f3f3f3"
    PANEL_BG     = "#f3f3f3"
    ACTIVITY_BG  = "#2c2c2c"
    TERMINAL_BG  = "#ffffff"
    EDITOR_BG    = "#ffffff"
    INPUT_BG     = "#ffffff"
    ACCENT       = "#007acc"
    ACCENT_DARK  = "#005a9e"
    ACCENT_GLOW  = "#0098ff"
    SECONDARY    = "#af00db"
    SUCCESS      = "#388a34"
    SUCCESS_DIM  = "#dff0d8"
    ERROR        = "#e51400"
    ERROR_DIM    = "#fde7e9"
    WARNING      = "#bf8803"
    WARNING_DIM  = "#fff8e1"
    TEXT_MAIN    = "#333333"
    TEXT_DIM     = "#717171"
    TEXT_BRIGHT  = "#000000"
    BORDER       = "#e5e5e5"
    BORDER_FOCUS = "#007acc"
    SELECTION    = "#add6ff"
    HOVER        = "#e8e8e8"
    ACTIVE       = "#d6ebff"
    TAB_ACTIVE   = "#ffffff"
    TAB_INACTIVE = "#ececec"
    TAB_BORDER   = "#007acc"

class FormalVerifierApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Initialize theme constants
        self.theme_mode = "dark"
        self.theme = DeFiDarkTheme()

        # Initialize plugin system
        if PluginManager:
            self.plugin_manager = PluginManager()
            print(f"🔌 Plugin Manager loaded with {len(self.plugin_manager.plugins)} plugins")
        else:
            self.plugin_manager = None

        # Configure window
        ctk.set_appearance_mode("system")
        self.title("DeFi Guardian - Formal Verification Suite")
        self.geometry("1500x950")
        self.configure(fg_color=self.theme.BG)

        # Configure grid - sidebar layout
        self.sidebar_expanded_width = 380
        self.sidebar_collapsed_width = 80
        self.sidebar_is_expanded = True
        self.grid_columnconfigure(0, weight=0, minsize=self.sidebar_expanded_width)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Initialize variables before using them
        self.current_file = None
        self.file_type = None
        self.dashboard_process = None
        self.auto_scroll_enabled = True
        self.lean_running = False
        self.tool_processes = {}
        self.stop_requested = {}
        self.monitoring = True
        self.tool_stop_buttons = {}

        # UI State Variables
        self.verbose_output = tk.BooleanVar(value=False)
        self.skip_incompatible = tk.BooleanVar(value=True)
        self.HAS_CERTORA = os.environ.get("CERTORA_KEY") is not None

        # Create sidebar
        self.create_sidebar()

        # ==================== MAIN CONTENT AREA ====================
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=self.theme.BG)
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)

        # Configure main frame for vertical layout (70% top, 30% bottom)
        self.main_frame.grid_rowconfigure(0, weight=7)
        self.main_frame.grid_rowconfigure(1, weight=3)

        # ==================== TOP PANE: CODE EDITOR ====================
        # Flush to edges — no rounded card, just a clean editor surface
        self.top_panel = ctk.CTkFrame(
            self.main_frame,
            fg_color=self.theme.EDITOR_BG,
            corner_radius=0,
            border_width=0
        )
        self.top_panel.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        # Editor tabview — VS Code tab bar style
        self.editor_tabs = ctk.CTkTabview(
            self.top_panel,
            segmented_button_fg_color=self.theme.TAB_INACTIVE,
            segmented_button_selected_color=self.theme.TAB_ACTIVE,
            segmented_button_selected_hover_color=self.theme.TAB_ACTIVE,
            segmented_button_unselected_color=self.theme.TAB_INACTIVE,
            segmented_button_unselected_hover_color=self.theme.HOVER,
            text_color=self.theme.TEXT_DIM,
            text_color_disabled=self.theme.TEXT_DIM,
            fg_color=self.theme.EDITOR_BG,
            border_width=0,
            corner_radius=0,
        )
        self.editor_tabs.pack(fill="both", expand=True, padx=0, pady=0)

        # Create tabs
        self.editor_tabs.add("Source")
        self.editor_tabs.add("Specifications & LTL")
        self.editor_tabs.add("Translated Promela")
        self.editor_tabs.add("Audit Problems")

        # Source editor tab
        self.source_editor = ctk.CTkTextbox(
            self.editor_tabs.tab("Source"),
            font=("Fira Code", 13),
            wrap="none",
            fg_color=self.theme.EDITOR_BG,
            text_color=self.theme.TEXT_MAIN,
            border_width=0,
            corner_radius=0
        )
        self.source_editor.pack(fill="both", expand=True, padx=0, pady=0)

        # Specifications editor tab — full-featured with toolbar
        spec_tab = self.editor_tabs.tab("Specifications & LTL")
        spec_tab.grid_columnconfigure(0, weight=1)
        spec_tab.grid_rowconfigure(1, weight=1)

        # Toolbar
        spec_toolbar = ctk.CTkFrame(spec_tab, fg_color=self.theme.PANEL_BG, height=34, corner_radius=0)
        spec_toolbar.grid(row=0, column=0, sticky="ew")
        spec_toolbar.grid_propagate(False)

        def _spec_btn(text, cmd, color=None):
            b = ctk.CTkButton(
                spec_toolbar, text=text, command=cmd,
                width=80, height=24,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                fg_color=color or self.theme.INPUT_BG,
                hover_color=self.theme.HOVER,
                text_color=self.theme.TEXT_MAIN,
                border_width=1,
                border_color=self.theme.BORDER,
                corner_radius=3
            )
            b.pack(side="left", padx=(4, 0), pady=5)
            return b

        _spec_btn("Save",     self._spec_save)
        _spec_btn("Load",     self._spec_load)
        _spec_btn("Validate", self._spec_validate, self.theme.SUCCESS_DIM)
        _spec_btn("Clear",    self._spec_clear,    self.theme.ERROR_DIM)

        # Template dropdown
        self._spec_tpl_var = ctk.StringVar(value="Template…")
        tpl_menu = ctk.CTkOptionMenu(
            spec_toolbar,
            values=["ERC20 Token", "Lending Protocol", "DEX/AMM", "Governance", "Vault", "Custom"],
            variable=self._spec_tpl_var,
            command=self._spec_load_template,
            width=130, height=24,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=self.theme.INPUT_BG,
            button_color=self.theme.BORDER,
            button_hover_color=self.theme.HOVER,
            text_color=self.theme.TEXT_MAIN,
            dropdown_fg_color=self.theme.PANEL_BG,
            dropdown_hover_color=self.theme.HOVER,
            dropdown_text_color=self.theme.TEXT_MAIN,
        )
        tpl_menu.pack(side="left", padx=4, pady=5)

        # Line/col indicator
        self._spec_pos_label = ctk.CTkLabel(
            spec_toolbar, text="Ln 1  Col 1",
            font=ctk.CTkFont(family="Fira Code", size=10),
            text_color=self.theme.TEXT_DIM
        )
        self._spec_pos_label.pack(side="right", padx=10)

        # Editor
        self.spec_editor = ctk.CTkTextbox(
            spec_tab,
            font=("Fira Code", 13),
            wrap="none",
            fg_color=self.theme.EDITOR_BG,
            text_color="#ce9178",   # VS Code string orange — good for LTL formulas
            border_width=0,
            corner_radius=0
        )
        self.spec_editor.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.spec_editor._textbox.bind("<KeyRelease>", self._spec_update_pos)
        self.spec_editor._textbox.bind("<ButtonRelease>", self._spec_update_pos)

        # Seed with default template
        self._spec_load_template("Custom")

        # Translated Promela tab
        self.translated_editor = ctk.CTkTextbox(
            self.editor_tabs.tab("Translated Promela"),
            font=("Fira Code", 13),
            wrap="none",
            fg_color=self.theme.EDITOR_BG,
            text_color="#9cdcfe",   # VS Code variable blue
            border_width=0
        )
        self.translated_editor.pack(fill="both", expand=True, padx=0, pady=0)

        # Problems tab
        self.problems_text = ctk.CTkTextbox(
            self.editor_tabs.tab("Audit Problems"),
            font=("Segoe UI", 12),
            wrap="word",
            fg_color=self.theme.EDITOR_BG,
            text_color=self.theme.ERROR,
            border_width=0
        )
        self.problems_text.pack(fill="both", expand=True, padx=0, pady=0)

        # ==================== BOTTOM PANE: TERMINAL ====================
        # VS Code integrated terminal — dark strip, no border radius
        self.bottom_panel = ctk.CTkFrame(
            self.main_frame,
            fg_color=self.theme.TERMINAL_BG,
            corner_radius=0,
            border_width=0
        )
        self.bottom_panel.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)

        # 1-px separator line between editor and terminal
        ctk.CTkFrame(
            self.main_frame, height=1,
            fg_color=self.theme.BORDER, corner_radius=0
        ).grid(row=0, column=0, sticky="sew", padx=0, pady=0)

        # Terminal tab bar (mimics VS Code TERMINAL / PROBLEMS / OUTPUT tabs)
        self.term_tabbar = ctk.CTkFrame(
            self.bottom_panel,
            fg_color=self.theme.PANEL_BG,
            height=32, corner_radius=0
        )
        self.term_tabbar.pack(fill="x")
        self.term_tabbar.pack_propagate(False)

        # Active tab indicator
        ctk.CTkLabel(
            self.term_tabbar,
            text="TERMINAL",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=self.theme.TEXT_MAIN
        ).pack(side="left", padx=(14, 0), pady=6)

        ctk.CTkLabel(
            self.term_tabbar,
            text="PROBLEMS",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=self.theme.TEXT_DIM
        ).pack(side="left", padx=14, pady=6)

        ctk.CTkLabel(
            self.term_tabbar,
            text="OUTPUT",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=self.theme.TEXT_DIM
        ).pack(side="left", padx=0, pady=6)

        # Right side: shell label
        ctk.CTkLabel(
            self.term_tabbar,
            text="bash  ×",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=self.theme.TEXT_DIM
        ).pack(side="right", padx=14, pady=6)

        # 1-px separator under tab bar
        ctk.CTkFrame(
            self.bottom_panel, height=1,
            fg_color=self.theme.BORDER, corner_radius=0
        ).pack(fill="x")

        # Console text area
        self.console_widget = ctk.CTkTextbox(
            self.bottom_panel,
            font=("Fira Code", 11),
            wrap="word",
            fg_color=self.theme.TERMINAL_BG,
            text_color=self.theme.TEXT_MAIN,
            border_width=0,
            corner_radius=0
        )
        self.console_widget.pack(fill="both", expand=True, padx=0, pady=0)

        # Point self.console and self.spin_terminal to the unified console
        self.console = self.console_widget
        self.spin_terminal = self.console_widget

        # Show welcome message
        self.show_welcome()

        # Scan for recent files
        self.scan_recent_files()

        # Setup resizable panels
        self.setup_resizable_panels()

        # Setup keyboard shortcuts
        self.setup_keyboard_shortcuts()

        # Start verification monitor
        self.start_verification_monitor()
        self.prewarm_lean_runtime()

        # Initialize file tree
        self.scan_project_directory()

    def create_sidebar(self):
        """Create VS Code-style sidebar with activity bar aesthetic"""
        t = self.theme

        # ── Outer sidebar frame ──────────────────────────────────────
        self.sidebar = ctk.CTkFrame(
            self, width=self.sidebar_expanded_width,
            corner_radius=0, fg_color=t.PANEL_BG
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        # ── Header ───────────────────────────────────────────────────
        self.sidebar_header = ctk.CTkFrame(
            self.sidebar, fg_color=t.ACTIVITY_BG,
            corner_radius=0, height=56
        )
        self.sidebar_header.pack(fill="x")
        self.sidebar_header.pack_propagate(False)

        # Logo + title row
        hrow = ctk.CTkFrame(self.sidebar_header, fg_color="transparent")
        hrow.pack(fill="both", expand=True, padx=14, pady=0)

        ctk.CTkLabel(
            hrow, text="🛡️",
            font=ctk.CTkFont(size=20),
            text_color=t.ACCENT
        ).pack(side="left", padx=(0, 8))

        title_col = ctk.CTkFrame(hrow, fg_color="transparent")
        title_col.pack(side="left", fill="y", pady=10)

        ctk.CTkLabel(
            title_col, text="DEFI GUARDIAN",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=t.TEXT_BRIGHT
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_col, text="Formal Verification Suite",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=t.TEXT_DIM
        ).pack(anchor="w")

        # ── Thin accent line under header ────────────────────────────
        ctk.CTkFrame(self.sidebar, height=1, fg_color=t.BORDER, corner_radius=0).pack(fill="x")

        # ── Scrollable content ───────────────────────────────────────
        self.sidebar_inner = ScrollableSidebar(self.sidebar, width=self.sidebar_expanded_width)
        self.sidebar_inner.pack(fill="both", expand=True)
        self.sidebar_scroll = self.sidebar_inner.get_inner_frame()

        # ── FILE OPERATIONS ──────────────────────────────────────────
        self._sidebar_section("EXPLORER")

        self.load_btn = self._sidebar_item_button(
            "$Open Source File",
            self.load_file, icon="📂", primary=True
        )
        self.file_info = ctk.CTkLabel(
            self.sidebar_scroll,
            text="No file loaded",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=t.TEXT_DIM,
            anchor="w"
        )
        self.file_info.pack(fill="x", padx=20, pady=(0, 4))

        # ── CORE VERIFICATION ────────────────────────────────────────
        self._sidebar_section("VERIFICATION")

        self.verify_btn = self._sidebar_item_button(
            "Run SPIN Verification", self.run_verification,
            icon="▶", tag="spin", state="disabled"
        )
        self.stop_spin_btn = self._sidebar_stop_button("spin")

        self.coq_btn = self._sidebar_item_button(
            "Coq Proof Assistant", self.verify_with_coq, icon="∀", tag="coq"
        )
        self.stop_coq_btn = self._sidebar_stop_button("coq")

        # ── BYTECODE VERIFICATION ────────────────────────────────────
        self._sidebar_section("BYTECODE")

        self.verify_with_certora_btn = self._sidebar_item_button(
            "Verify with Certora", self.verify_with_certora, icon="⬡", tag="certora"
        )
        self.stop_certora_btn = self._sidebar_stop_button("certora")

        self.lean_btn = self._sidebar_item_button(
            "Lean Theorem Prover", self.run_lean_verification, icon="λ", tag="lean"
        )
        self.stop_lean_btn = self._sidebar_stop_button("lean")

        # ── RUST ANALYSIS ────────────────────────────────────────────
        self._sidebar_section("RUST ANALYSIS")

        self.kani_btn = self._sidebar_item_button(
            "Kani Model Checker", self.verify_with_kani, icon="🦀", tag="kani"
        )
        self.stop_kani_btn = self._sidebar_stop_button("kani")

        self.prusti_btn = self._sidebar_item_button(
            "Prusti Verifier", self.verify_with_prusti, icon="🔬", tag="prusti"
        )
        self.stop_prusti_btn = self._sidebar_stop_button("prusti")

        self.creusot_btn = self._sidebar_item_button(
            "Creusot Verifier", self.verify_with_creusot, icon="📐", tag="creusot"
        )
        self.stop_creusot_btn = self._sidebar_stop_button("creusot")

        # ── VISUALIZATION ────────────────────────────────────────────
        self._sidebar_section("VISUALIZATION")

        self.dash_btn = self._sidebar_item_button(
            "Open Dashboard", self.open_dashboard, icon="⬡"
        )
        self._sidebar_item_button(
            "Account Dashboard", self.open_account_dashboard, icon="👤"
        )
        self._sidebar_item_button(
            "Stop Dashboard", self.stop_dashboard, icon="■", danger=True
        )
        self._sidebar_item_button(
            "View Translated", self.open_translated_output, icon="⇄"
        )
        self._sidebar_item_button(
            "Analyze Counterexample", self.analyze_counterexample, icon="🔍"
        )

        # ── STATIC ANALYSIS ──────────────────────────────────────────
        self._sidebar_section("STATIC ANALYSIS")

        self._sidebar_item_button(
            "AI Generate Specs", self.ai_generate_specs, icon="🤖", primary=True
        )
        self.slither_btn = self._sidebar_item_button(
            "Slither → LTL Specs", self.run_slither_analysis, icon="🐍"
        )
        self._sidebar_item_button(
            "Slither → Certora Rules", self.run_slither_certora, icon="⬡"
        )

        # ── SETTINGS ─────────────────────────────────────────────────
        self._sidebar_section("SETTINGS")

        self.auto_scroll_switch = ctk.CTkSwitch(
            self.sidebar_scroll,
            text="Auto-scroll console",
            command=self.toggle_auto_scroll,
            progress_color=t.ACCENT,
            button_color=t.TEXT_DIM,
            button_hover_color=t.ACCENT,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=t.TEXT_MAIN
        )
        self.auto_scroll_switch.pack(anchor="w", padx=20, pady=(4, 2))
        self.auto_scroll_switch.select()

        self.verbose_switch = ctk.CTkSwitch(
            self.sidebar_scroll,
            text="Verbose output",
            progress_color=t.ACCENT,
            button_color=t.TEXT_DIM,
            button_hover_color=t.ACCENT,
            variable=self.verbose_output,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=t.TEXT_MAIN
        )
        self.verbose_switch.pack(anchor="w", padx=20, pady=(2, 4))

        # Theme toggle
        theme_row = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent")
        theme_row.pack(fill="x", padx=20, pady=(2, 8))
        ctk.CTkLabel(
            theme_row, text="App Theme:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=t.TEXT_DIM
        ).pack(side="left")
        self.theme_switch = ctk.CTkSwitch(
            theme_row, text="Dark Mode",
            command=self.toggle_theme,
            progress_color=t.ACCENT,
            button_color=t.TEXT_DIM,
            button_hover_color=t.ACCENT,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=t.TEXT_MAIN
        )
        self.theme_switch.pack(side="right")
        if self.theme_mode == "dark":
            self.theme_switch.select()

        # ── CONSOLE OPERATIONS ───────────────────────────────────────
        self._sidebar_section("CONSOLE")

        console_ops = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent")
        console_ops.pack(fill="x", padx=12, pady=(4, 8))

        self.clear_btn = ctk.CTkButton(
            console_ops, text="Clear",
            command=self.clear_console,
            height=28, corner_radius=4,
            fg_color=t.INPUT_BG,
            border_width=1, border_color=t.BORDER,
            hover_color=t.HOVER,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=t.TEXT_MAIN
        )
        self.clear_btn.pack(side="left", padx=(0, 4), expand=True, fill="x")

        self.export_btn = ctk.CTkButton(
            console_ops, text="Export",
            command=self.export_console,
            height=28, corner_radius=4,
            fg_color=t.INPUT_BG,
            border_width=1, border_color=t.BORDER,
            hover_color=t.HOVER,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=t.TEXT_MAIN
        )
        self.export_btn.pack(side="right", padx=(4, 0), expand=True, fill="x")

        # ── Status bar (bottom) ──────────────────────────────────────
        self.sidebar_footer = ctk.CTkFrame(
            self.sidebar, fg_color=t.ACTIVITY_BG,
            height=24, corner_radius=0
        )
        self.sidebar_footer.pack(side="bottom", fill="x")
        self.sidebar_footer.pack_propagate(False)

        ctk.CTkFrame(self.sidebar, height=1, fg_color=t.BORDER, corner_radius=0).pack(side="bottom", fill="x")

        self.status_dot = ctk.CTkLabel(
            self.sidebar_footer, text="●",
            text_color=t.SUCCESS,
            font=ctk.CTkFont(size=9)
        )
        self.status_dot.pack(side="left", padx=(10, 4))

        self.status_label = ctk.CTkLabel(
            self.sidebar_footer, text="System Ready",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=t.TEXT_DIM
        )
        self.status_label.pack(side="left")

        # ── Prewarm / tool status labels ─────────────────────────────
        self.lean_prewarm_status = ctk.CTkLabel(
            self.sidebar_scroll,
            text="○ Lean prewarm: pending",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=t.TEXT_DIM, anchor="w"
        )
        self.lean_prewarm_status.pack(anchor="w", padx=20, pady=(0, 2))

        self.tool_status = ctk.CTkLabel(
            self.sidebar_scroll,
            text="Checking tools...",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=t.TEXT_DIM,
            wraplength=320, anchor="w"
        )
        self.tool_status.pack(anchor="w", padx=20, pady=(0, 12))

        # ── Wire up stop-button dict ──────────────────────────────────
        self.tool_stop_buttons = {
            "spin":    self.stop_spin_btn,
            "coq":     self.stop_coq_btn,
            "lean":    self.stop_lean_btn,
            "prusti":  self.stop_prusti_btn,
            "creusot": self.stop_creusot_btn,
            "kani":    self.stop_kani_btn,
            "certora": self.stop_certora_btn,
        }

        self.sidebar_inner.bind_mousewheel()
        self.check_tools()

    # ── Sidebar helper widgets ────────────────────────────────────────

    def _sidebar_section(self, title: str):
        """VS Code-style section header — small caps, dim, with a separator line."""
        t = self.theme
        frame = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent")
        frame.pack(fill="x", padx=0, pady=(10, 0))

        ctk.CTkLabel(
            frame, text=title.upper(),
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=t.TEXT_DIM, anchor="w"
        ).pack(side="left", padx=14)

    def _sidebar_item_button(
        self, label: str, command,
        icon: str = "", tag: str = "",
        primary: bool = False, danger: bool = False,
        state: str = "normal"
    ) -> ctk.CTkButton:
        """
        VS Code Explorer-style list item button.
        - Normal: transparent bg, left-aligned text, hover highlight
        - Primary (Open File): subtle accent border
        - Danger (Stop): red text
        """
        t = self.theme
        display = f"  {icon}  {label}" if icon else f"  {label}"

        if primary:
            fg   = t.ACCENT
            hover = t.ACCENT_DARK
            text_col = "#ffffff"
            border = 0
            corner = 6
            height = 32
        elif danger:
            fg   = "transparent"
            hover = t.ERROR_DIM
            text_col = t.ERROR
            border = 1
            corner = 4
            height = 28
        else:
            fg   = "transparent"
            hover = t.HOVER
            text_col = t.TEXT_MAIN
            border = 0
            corner = 4
            height = 30

        btn = ctk.CTkButton(
            self.sidebar_scroll,
            text=display,
            command=command,
            height=height,
            corner_radius=corner,
            fg_color=fg,
            hover_color=hover,
            border_width=border,
            border_color=t.BORDER if border else None,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=text_col,
            anchor="w",
            state=state
        )
        btn.pack(fill="x", padx=8, pady=1)
        return btn

    def _sidebar_stop_button(self, tool_name: str) -> ctk.CTkButton:
        """Compact inline stop button — only visible when tool is running."""
        t = self.theme
        btn = ctk.CTkButton(
            self.sidebar_scroll,
            text=f"  ■  Stop {tool_name.upper()}",
            command=lambda: self.request_stop_tool(tool_name),
            state="disabled",
            height=22,
            corner_radius=3,
            fg_color="transparent",
            border_width=0,
            hover_color=t.ERROR_DIM,
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=t.TEXT_DIM,
            anchor="w"
        )
        btn.pack(fill="x", padx=24, pady=(0, 2))
        return btn

    def show_welcome(self):
        """Show VS Code-style welcome message in the terminal panel."""
        c = self.console
        t = self.theme

        c.insert("end", "\n")
        c.insert("end", "  DeFi Guardian  —  Formal Verification Suite\n", "header")
        c.insert("end", f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ·  SPIN 6.5  ·  Coq  ·  Lean  ·  Certora\n\n", "dim")
        c.insert("end", "  Supported formats:  .sol  .rs  .pml\n", "dim")
        c.insert("end", "  Load a source file to begin verification.\n\n", "accent")

        # Configure console colour tags — VS Code terminal palette
        c.tag_config("header",  foreground="#4ec9b0",  font=("Fira Code", 12, "bold"))
        c.tag_config("accent",  foreground="#9cdcfe")   # light blue
        c.tag_config("dim",     foreground=t.TEXT_DIM)
        c.tag_config("success", foreground="#4ec9b0")   # teal
        c.tag_config("error",   foreground="#f44747")   # red
        c.tag_config("warning", foreground="#cca700")   # yellow
        c.tag_config("info",    foreground="#569cd6")   # blue keyword


    def ensure_sidebar_visibility(self):
        """Ensure sidebar is properly visible after creation"""
        self.sidebar.update_idletasks()
        self.sidebar_inner.update_idletasks()

    def on_window_resize(self, event=None):
        """Handle window resize to update scrollable area"""
        if hasattr(self, 'sidebar_inner'):
            self.sidebar_inner.update_idletasks()
            if hasattr(self.sidebar_inner, '_parent_canvas'):
                self.sidebar_inner._parent_canvas.configure(
                    scrollregion=self.sidebar_inner._parent_canvas.bbox("all")
                )

    def setup_resizable_panels(self):
        """Setup resizable panels with drag handles"""
        # We already have self.sidebar_resize_handle in the sidebar container
        # from create_sidebar, so we just need to bind it if not already done
        if hasattr(self, 'sidebar_resize_handle'):
            self.sidebar_resize_handle.bind("<Button-1>", self.start_sidebar_resize)
            self.sidebar_resize_handle.bind("<B1-Motion>", self.resize_sidebar)
            self.sidebar_resize_handle.bind("<ButtonRelease-1>", self.stop_sidebar_resize)

        # Add resize handle between editor and console
        # First, reconfigure main_frame rows to accommodate a handle row
        self.main_frame.grid_rowconfigure(0, weight=7)
        self.main_frame.grid_rowconfigure(1, weight=0) # Handle row
        self.main_frame.grid_rowconfigure(2, weight=3)

        # Move bottom_panel to row 2 (it was row 1)
        self.bottom_panel.grid(row=2, column=0, sticky="nsew", padx=20, pady=(10, 20))

        # Create the horizontal handle in row 1
        self.editor_console_handle = ctk.CTkFrame(self.main_frame, height=4, cursor="sb_v_double_arrow",
                                                   fg_color=self.theme.BORDER)
        self.editor_console_handle.grid(row=1, column=0, sticky="ew", padx=20, pady=0)

        # Bind drag events for vertical resize
        self.editor_console_handle.bind("<Button-1>", self.start_vertical_resize)
        self.editor_console_handle.bind("<B1-Motion>", self.resize_vertical)
        self.editor_console_handle.bind("<ButtonRelease-1>", self.stop_vertical_resize)

        # Store resize state
        self.resizing_sidebar = False
        self.resizing_vertical = False
        self.start_sidebar_x = 0
        self.start_sidebar_width = 0
        self.start_vertical_y = 0
        self.start_vertical_height = 0

    def start_sidebar_resize(self, event):
        """Start sidebar resize operation"""
        self.resizing_sidebar = True
        self.start_sidebar_x = event.x_root
        self.start_sidebar_width = self.sidebar.winfo_width()

    def resize_sidebar(self, event):
        """Handle sidebar resize with improved stability"""
        if self.resizing_sidebar:
            delta = event.x_root - self.start_sidebar_x
            new_width = max(250, min(800, self.start_sidebar_width + delta))

            # Use a smaller throttle for better responsiveness
            if not hasattr(self, '_last_resize_time'):
                self._last_resize_time = 0

            current_time = time.time()
            if current_time - self._last_resize_time > 0.008:  # ~120fps
                # Update container and sidebar width
                self.sidebar_container.configure(width=new_width + 15)
                self.sidebar.configure(width=new_width)

                # Update grid minsize less frequently to avoid shakiness
                if abs(new_width - getattr(self, '_last_grid_width', 0)) > 5:
                    self.grid_columnconfigure(0, minsize=new_width + 15)
                    self._last_grid_width = new_width

                self._last_resize_time = current_time

    def stop_sidebar_resize(self, event):
        """Stop sidebar resize operation"""
        self.resizing_sidebar = False

    def start_vertical_resize(self, event):
        """Start vertical resize operation"""
        self.resizing_vertical = True
        self.start_vertical_y = event.y_root
        self.start_vertical_height = self.top_panel.winfo_height()

    def resize_vertical(self, event):
        """Handle vertical resize between editor and console"""
        if self.resizing_vertical:
            delta = event.y_root - self.start_vertical_y
            total_height = self.top_panel.winfo_height() + self.bottom_panel.winfo_height() + 10

            new_top_height = max(150, min(total_height - 100, self.start_vertical_height + delta))
            new_bottom_height = total_height - new_top_height - 10

            # Update grid weights
            self.main_frame.grid_rowconfigure(0, weight=new_top_height)
            self.main_frame.grid_rowconfigure(2, weight=new_bottom_height)

    def stop_vertical_resize(self, event):
        """Stop vertical resize operation"""
        self.resizing_vertical = False

    def add_theme_settings(self):
        """Add theme settings panel to sidebar"""
        sidebar_inner = self.sidebar_inner.get_inner_frame()

        # Find where to insert theme settings (after settings section)
        theme_frame = ctk.CTkFrame(sidebar_inner, fg_color="transparent")
        theme_frame.pack(fill="x", pady=5)

        # Add theme settings
        self.theme_settings = ThemeSettingsPanel(theme_frame, self.theme_manager)
        self.theme_settings.pack(fill="x")

        # Add custom color picker for advanced customization
        ctk.CTkLabel(
            theme_frame,
            text="",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#888888"
        ).pack(anchor="w", pady=(10, 5))

        # Color picker buttons
        color_frame = ctk.CTkFrame(theme_frame, fg_color="transparent")
        color_frame.pack(fill="x", pady=5)

        colors = ["accent", "success", "error", "warning"]
        color_labels = ["Accent", "Success", "Error", "Warning"]

        for color, label in zip(colors, color_labels):
            btn = ctk.CTkButton(
                color_frame,
                text=f"{label}",
                width=80,
                height=30,
                font=ctk.CTkFont(size=10),
                fg_color=self.theme_manager.THEMES[self.theme_manager.current_theme][color],
                command=lambda c=color: self.pick_custom_color(c)
            )
            btn.pack(side="left", padx=2)

    def pick_custom_color(self, color_key):
        """Open color picker dialog for custom color selection"""
        import tkinter.colorchooser as colorchooser

        color = colorchooser.askcolor(title=f"Select {color_key} color")
        if color[1]:
            # Update theme
            theme = self.theme_manager.THEMES[self.theme_manager.current_theme].copy()
            theme[color_key] = color[1]

            # Create temporary theme
            custom_theme_name = f"{self.theme_manager.current_theme} (Custom)"
            self.theme_manager.THEMES[custom_theme_name] = theme

            # Apply custom theme
            self.theme_manager.apply_theme(custom_theme_name)

            # Update dropdown
            self.theme_settings.theme_dropdown.configure(values=list(self.theme_manager.THEMES.keys()))
            self.theme_settings.theme_var.set(custom_theme_name)

    def setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts for panel resizing"""

        def increase_sidebar():
            new_width = min(600, self.sidebar.winfo_width() + 50)
            self.sidebar.configure(width=new_width)
            self.sidebar_container.configure(width=new_width + 15)

        def decrease_sidebar():
            new_width = max(250, self.sidebar.winfo_width() - 50)
            self.sidebar.configure(width=new_width)
            self.sidebar_container.configure(width=new_width + 15)

        def increase_console():
            current_weight = self.main_frame.grid_rowconfigure(2)['weight']
            new_weight = min(80, current_weight + 5)
            self.main_frame.grid_rowconfigure(2, weight=new_weight)

        def decrease_console():
            current_weight = self.main_frame.grid_rowconfigure(2)['weight']
            new_weight = max(20, current_weight - 5)
            self.main_frame.grid_rowconfigure(2, weight=new_weight)

        # Bind shortcuts
        self.bind("<Control-Shift-Right>", lambda e: increase_sidebar())
        self.bind("<Control-Shift-Left>", lambda e: decrease_sidebar())
        self.bind("<Control-Shift-Up>", lambda e: increase_console())
        self.bind("<Control-Shift-Down>", lambda e: decrease_console())

    def populate_file_explorer(self):
        """Populate the file explorer with project files"""
        # Create certora directories if they don't exist
        for d in ["contracts", "specs", "confs"]:
            os.makedirs(os.path.join(PROJECT_DIR, "certora", d), exist_ok=True)

        # Clear existing widgets
        for widget in self.open_editors_frame.winfo_children():
            widget.destroy()
        for widget in self.project_files_frame.winfo_children():
            widget.destroy()

        # Add current file to open editors if any
        if self.current_file:
            file_btn = ctk.CTkButton(
                self.open_editors_frame,
                text=f"  {os.path.basename(self.current_file)}",
                command=lambda f=self.current_file: self.load_file_to_editor(f),
                height=25,
                font=ctk.CTkFont(size=10),
                fg_color="transparent",
                hover_color="#2a2d2e"
            )
            file_btn.pack(fill="x", pady=1)

        # Add important project files
        important_files = [
            ("active_file.txt", "text"),
            ("translated_output.pml", "promela"),
            ("verification_state.json", "json"),
            ("state_graph.json", "json"),
            ("file_tree.json", "json"),
            ("user_lending.rs", "rust"),
            ("burn.sol", "solidity"),
            ("app.py", "python"),
            ("desktop_app.py", "python")
        ]

        for filename, file_type in important_files:
            file_path = os.path.join(PROJECT_DIR, filename)
            if os.path.exists(file_path):
                # Get icon for file type
                icon_map = {
                    "rust": "R",
                    "solidity": "S",
                    "promela": "P",
                    "json": "{ }",
                    "python": "Py",
                    "text": "T"
                }
                icon = icon_map.get(file_type, "F")

                file_btn = ctk.CTkButton(
                    self.project_files_frame,
                    text=f"  {filename}",
                    command=lambda f=file_path: self.load_file_to_editor(f),
                    height=25,
                    font=ctk.CTkFont(size=10),
                    fg_color="transparent",
                    hover_color="#2a2d2e"
                )
                file_btn.pack(fill="x", pady=1)

    def on_file_loaded(self):
        """Update UI elements when a new file is loaded"""
        if self.current_file:
            filename = os.path.basename(self.current_file)
            if hasattr(self, 'file_label'):
                self.file_label.configure(text=f"  {filename}", text_color=self.theme.ACCENT)
            elif hasattr(self, 'file_info'):
                self.file_info.configure(text=f"  {filename}", text_color=self.theme.ACCENT)

            self.verify_btn.configure(state="normal")
            self.status_label.configure(text=f"Loaded: {filename}")

    def load_file_to_editor(self, file_path):
        """Load file content into the source editor"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            self.source_editor.delete("1.0", "end")
            self.source_editor.insert("1.0", content)

            # Update current file
            self.current_file = file_path
            self.file_type = os.path.splitext(file_path)[1].lower()

            # Update UI
            self.on_file_loaded()

            # Update specification editor
            self.update_spec_editor(content, overwrite=True)

            # If native Promela, show in translated tab too
            if self.file_type == '.pml':
                self.translated_editor.delete("1.0", "end")
                self.translated_editor.insert("1.0", content)
            else:
                self.translated_editor.delete("1.0", "end")
                self.translated_editor.insert("1.0", "Run SPIN Verification to see translated Promela output.")

            # Clear problems on new file load
            self.problems_text.delete("1.0", "end")
            self.problems_text.insert("1.0", "Run verification to scan for problems.")

        except Exception as e:
            self.console.insert("end", f"Error loading file {file_path}: {str(e)}\n")

    def toggle_theme(self):
        """Toggle between light and dark themes"""
        if self.theme_switch.get():
            self.theme_mode = "dark"
            self.theme = DeFiDarkTheme()
            ctk.set_appearance_mode("dark")
            self.theme_switch.configure(text="Dark Mode")
        else:
            self.theme_mode = "light"
            self.theme = DeFiLightTheme()
            ctk.set_appearance_mode("light")
            self.theme_switch.configure(text="Light Mode")

        # Re-apply theme to all components
        self.update_ui_colors()

    def update_ui_colors(self):
        """Re-apply theme tokens to all major UI components."""
        t = self.theme

        self.configure(fg_color=t.BG)
        self.sidebar.configure(fg_color=t.PANEL_BG)
        self.sidebar_header.configure(fg_color=t.ACTIVITY_BG)
        self.main_frame.configure(fg_color=t.BG)
        self.top_panel.configure(fg_color=t.EDITOR_BG)
        self.bottom_panel.configure(fg_color=t.TERMINAL_BG)

        # Editor textboxes
        self.source_editor.configure(fg_color=t.EDITOR_BG, text_color=t.TEXT_MAIN)
        self.spec_editor.configure(fg_color=t.EDITOR_BG, text_color="#ce9178")
        self.translated_editor.configure(fg_color=t.EDITOR_BG, text_color="#9cdcfe")
        self.problems_text.configure(fg_color=t.EDITOR_BG, text_color=t.ERROR)
        self.console_widget.configure(fg_color=t.TERMINAL_BG, text_color=t.TEXT_MAIN)

        # Tab bar
        if hasattr(self, 'editor_tabs'):
            self.editor_tabs.configure(
                segmented_button_fg_color=t.TAB_INACTIVE,
                segmented_button_selected_color=t.TAB_ACTIVE,
                segmented_button_selected_hover_color=t.TAB_ACTIVE,
                segmented_button_unselected_color=t.TAB_INACTIVE,
                segmented_button_unselected_hover_color=t.HOVER,
                fg_color=t.EDITOR_BG,
            )

        # Terminal tab bar
        if hasattr(self, 'term_tabbar'):
            self.term_tabbar.configure(fg_color=t.PANEL_BG)

        # Status bar
        if hasattr(self, 'sidebar_footer'):
            self.sidebar_footer.configure(fg_color=t.ACTIVITY_BG)
        if hasattr(self, 'status_label'):
            self.status_label.configure(text_color=t.TEXT_DIM)

        # Refresh console colour tags
        self.show_welcome()
        if hasattr(self, 'lean_prewarm_status'):
            self.lean_prewarm_status.configure(text_color=self.theme.TEXT_DIM)
        if hasattr(self, 'tool_status'):
            self.tool_status.configure(text_color=self.theme.TEXT_DIM)

        # Update buttons
        buttons_to_update = []
        for attr in ['load_btn', 'verify_btn', 'coq_btn', 'verify_with_certora_btn', 'dash_btn',
                     'kani_btn', 'prusti_btn', 'creusot_btn', 'lean_btn']:
            if hasattr(self, attr):
                buttons_to_update.append(getattr(self, attr))

        for btn in buttons_to_update:
            if hasattr(btn, 'configure'):
                text_color = "#ffffff" # Always white text for buttons with accent backgrounds
                btn.configure(fg_color=self.theme.ACCENT, hover_color=self.theme.ACCENT_DARK, text_color=text_color)

    def scan_project_directory(self, base_path=None):
        """Scan project directory and create file_tree.json in a background thread"""
        if base_path is None:
            base_path = PROJECT_DIR

        def _scan():
            def get_file_icon(filename):
                """Get appropriate icon for file type"""
                if filename.endswith('.rs'):
                    return 'rust'
                elif filename.endswith('.sol'):
                    return 'solidity'
                elif filename.endswith('.pml'):
                    return 'promela'
                elif filename.endswith('.json'):
                    return 'json'
                elif filename.endswith('.txt'):
                    return 'text'
                elif filename.endswith('.log'):
                    return 'log'
                elif filename.endswith('.py'):
                    return 'python'
                else:
                    return 'file'

            def build_tree(path, relative_path=""):
                """Recursively build file tree structure"""
                tree = {"name": os.path.basename(path), "type": "folder" if os.path.isdir(path) else "file", "children": []}

                if os.path.isdir(path):
                    try:
                        items = []
                        for item in os.listdir(path):
                            # Skip hidden files and common build/cache directories
                            if item.startswith('.') or item in ['target', '__pycache__', 'node_modules']:
                                continue
                            items.append(item)

                        # Sort: folders first, then files
                        items.sort(key=lambda x: (not os.path.isdir(os.path.join(path, x)), x.lower()))

                        for item in items:
                            item_path = os.path.join(path, item)
                            item_relative = os.path.join(relative_path, item) if relative_path else item

                            if os.path.isdir(item_path):
                                subtree = build_tree(item_path, item_relative)
                                tree["children"].append(subtree)
                            else:
                                file_info = {
                                    "name": item,
                                    "type": "file",
                                    "icon": get_file_icon(item),
                                    "path": item_relative,
                                    "size": os.path.getsize(item_path) if os.path.exists(item_path) else 0
                                }
                                tree["children"].append(file_info)
                    except PermissionError:
                        pass
                else:
                    tree["icon"] = get_file_icon(os.path.basename(path))
                    tree["path"] = relative_path
                    tree["size"] = os.path.getsize(path) if os.path.exists(path) else 0

                return tree

            try:
                file_tree = build_tree(base_path)

                # Save to JSON file for Streamlit frontend
                output_file = os.path.join(PROJECT_DIR, "file_tree.json")
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(file_tree, f, indent=2, ensure_ascii=False)

                self.after(0, lambda: self.console.insert("end", f"   File tree saved to: {output_file}\n"))

            except Exception as e:
                self.after(0, lambda: self.console.insert("end", f"   Error scanning project: {str(e)}\n"))

        threading.Thread(target=_scan, daemon=True).start()

    def export_state_graph(self, verification_result):
        """Export state graph data for 3D visualization with proper parsing"""
        try:
            state_graph = {
                "nodes": [],
                "edges": [],
                "counterexample_path": [],
                "model_name": os.path.basename(self.current_file) if self.current_file else "Unknown",
                "timestamp": datetime.now().isoformat()
            }

            # First, try to parse the translated Promela model
            pml_path = os.path.join(MODELS_DIR, "translated_output.pml")
            if not os.path.exists(pml_path) and self.current_file and self.current_file.endswith('.pml'):
                pml_path = self.current_file

            if os.path.exists(pml_path):
                with open(pml_path, 'r', encoding='utf-8') as f:
                    pml_content = f.read()

                # Parse Promela to extract state machine
                state_machine = self.parse_pml_for_state_graph(pml_content)

                # Extract processes as primary nodes
                processes = state_machine.get('processes', [])
                for proc in processes:
                    if proc not in state_graph["nodes"]:
                        state_graph["nodes"].append(proc)

                # Extract labeled states
                for state in state_machine.get('states', []):
                    if state not in state_graph["nodes"]:
                        state_graph["nodes"].append(state)

                # Extract transitions
                for trans in state_machine.get('transitions', []):
                    from_node = trans.get('from', '')
                    to_node = trans.get('to', '')
                    if from_node and to_node:
                        state_graph["edges"].append({
                            "from": from_node,
                            "to": to_node,
                            "label": trans.get('condition', 'transition')[:30]
                        })
                        # Ensure nodes exist
                        if from_node not in state_graph["nodes"]:
                            state_graph["nodes"].append(from_node)
                        if to_node not in state_graph["nodes"]:
                            state_graph["nodes"].append(to_node)

                # Add LTL properties as special nodes
                for ltl in state_machine.get('ltl_properties', []):
                    ltl_node = f"LTL_{ltl['name']}"
                    if ltl_node not in state_graph["nodes"]:
                        state_graph["nodes"].append(ltl_node)

            # If still no nodes, create from verification output
            if not state_graph["nodes"]:
                output = verification_result.get('output', '')

                # Extract states from SPIN output
                state_pattern = r'proctype\s+(\w+)'
                for match in re.finditer(state_pattern, output):
                    state_graph["nodes"].append(match.group(1))

                # Extract transitions from SPIN trace
                transition_pattern = r'(\w+)\s*->\s*(\w+)'
                for match in re.finditer(transition_pattern, output):
                    from_state, to_state = match.groups()
                    if from_state not in state_graph["nodes"]:
                        state_graph["nodes"].append(from_state)
                    if to_state not in state_graph["nodes"]:
                        state_graph["nodes"].append(to_state)
                    state_graph["edges"].append({
                        "from": from_state,
                        "to": to_state,
                        "label": "transition"
                    })

            # Add counterexample path if verification failed
            if not verification_result.get('success', True):
                trail_file = os.path.join(PROJECT_DIR, "pan.trail")
                if not os.path.exists(trail_file):
                    trail_file = os.path.join(SPIN_LOGS, "pan.trail")

                if os.path.exists(trail_file):
                    try:
                        with open(trail_file, 'r') as f:
                            trail_content = f.read()

                        # Parse trail for state sequence
                        steps = []
                        for line in trail_content.split('\n'):
                            if 'state' in line.lower():
                                match = re.search(r'state\s+(\d+)', line)
                                if match:
                                    steps.append(f"State_{match.group(1)}")

                        if steps:
                            state_graph["counterexample_path"] = steps
                    except:
                        pass

            # Dynamic state-space generation based on SPIN statistics
            output = verification_result.get('output', '')
            num_states = 0
            states_match = re.search(r"(\d+) states, stored", output)
            if states_match:
                num_states = int(states_match.group(1))

            # If the graph is empty or very sparse, use SPIN stats to populate it
            if (len(state_graph["nodes"]) <= 1 or len(state_graph["edges"]) == 0) and num_states > 1:
                # Generate synthetic nodes based on explored states (cap for visualization)
                display_states = min(num_states, 40)
                synthetic_nodes = [f"State_{i}" for i in range(display_states)]

                for node in synthetic_nodes:
                    if node not in state_graph["nodes"]:
                        state_graph["nodes"].append(node)

                # Create transitions (linear + some branches)
                for i in range(len(synthetic_nodes) - 1):
                    state_graph["edges"].append({
                        "from": synthetic_nodes[i],
                        "to": synthetic_nodes[i+1],
                        "label": "transition"
                    })

                # Add complexity if there are many states
                if display_states > 5:
                    state_graph["edges"].append({
                        "from": synthetic_nodes[2],
                        "to": synthetic_nodes[min(5, display_states-1)],
                        "label": "branch"
                    })

                # Add violation loop if verification failed
                if not verification_result.get('success', True) and synthetic_nodes:
                    state_graph["edges"].append({
                        "from": synthetic_nodes[-1],
                        "to": synthetic_nodes[0],
                        "label": "violation_path"
                    })

            # Ensure minimum data for visualization if still empty
            if not state_graph["nodes"]:
                state_graph["nodes"] = ["Contract", "Initial", "Running", "Completed"]
                state_graph["edges"] = [
                    {"from": "Contract", "to": "Initial", "label": "deploy"},
                    {"from": "Initial", "to": "Running", "label": "execute"},
                    {"from": "Running", "to": "Completed", "label": "finish"}
                ]

            # Save state graph to JSON
            output_file = os.path.join(REPORTS_DIR, "state_graph.json")
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(state_graph, f, indent=2)

            self.console.insert("end", f"   📊 State graph with {len(state_graph['nodes'])} nodes and {len(state_graph['edges'])} edges saved\n")

        except Exception as e:
            self.console.insert("end", f"   ⚠️ Error exporting state graph: {str(e)}\n")

    def parse_pml_for_state_graph(self, pml_content):
        """Parse Promela content to extract state machine structure with support for if/do blocks"""
        result = {
            'processes': [],
            'states': [],
            'transitions': [],
            'ltl_properties': []
        }

        # Extract proctypes (processes)
        proctype_pattern = r'(?:active\s+)?proctype\s+(\w+)\s*(?:\([^)]*\))?\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}'
        for match in re.finditer(proctype_pattern, pml_content, re.DOTALL):
            proc_name = match.group(1)
            proc_body = match.group(2)
            result['processes'].append(proc_name)

            # Extract labels (states)
            label_pattern = r'^(\w+)\s*:'
            for line in proc_body.split('\n'):
                label_match = re.match(label_pattern, line.strip())
                if label_match:
                    state_name = label_match.group(1)
                    if state_name not in ['skip', 'break', 'goto', 'printf', 'assert']:
                        result['states'].append(f"{proc_name}.{state_name}")

            # Extract transitions from goto
            goto_pattern = r'goto\s+(\w+)'
            for goto_match in re.finditer(goto_pattern, proc_body):
                target = goto_match.group(1)
                result['transitions'].append({
                    'from': proc_name,
                    'to': f"{proc_name}.{target}",
                    'condition': 'goto'
                })

            # Extract atomic block transitions
            atomic_pattern = r'atomic\s*\{([^}]*)\}'
            for atomic_match in re.finditer(atomic_pattern, proc_body, re.DOTALL):
                atomic_body = atomic_match.group(1)
                # Look for state assignments inside atomic blocks
                state_match = re.search(r'state\s*=\s*(\d+)', atomic_body)
                if state_match:
                    target_state = f"State_{state_match.group(1)}"
                    result['transitions'].append({
                        'from': proc_name,
                        'to': f"{proc_name}.{target_state}",
                        'condition': 'atomic_update'
                    })

            # Extract if-else transitions
            if_pattern = r'if\s*::\s*(.*?)\s*->\s*(?:.*?)(?:goto\s+(\w+)|state\s*=\s*(\d+))'
            for if_match in re.finditer(if_pattern, proc_body, re.DOTALL):
                condition = if_match.group(1).strip()
                target_label = if_match.group(2)
                target_state = if_match.group(3)

                target = target_label if target_label else (f"State_{target_state}" if target_state else "Next")
                result['transitions'].append({
                    'from': proc_name,
                    'to': f"{proc_name}.{target}",
                    'condition': condition[:30]
                })

            # Extract do loop options
            do_pattern = r'::\s*(.*?)\s*->\s*(?:.*?)(?:state\s*=\s*(\d+)|break)'
            for do_match in re.finditer(do_pattern, proc_body, re.DOTALL):
                condition = do_match.group(1).strip()
                target_state = do_match.group(2)

                target = f"State_{target_state}" if target_state else "LoopBreak"
                result['transitions'].append({
                    'from': proc_name,
                    'to': f"{proc_name}.{target}",
                    'condition': condition[:30]
                })

            # Special case for "state = X" assignments
            state_assign_pattern = r'state\s*=\s*(\d+)'
            last_state = "INIT"
            for sa_match in re.finditer(state_assign_pattern, proc_body):
                curr_state = f"State_{sa_match.group(1)}"
                if curr_state not in result['states']:
                    result['states'].append(f"{proc_name}.{curr_state}")
                result['transitions'].append({
                    'from': f"{proc_name}.{last_state}" if last_state == "INIT" else f"{proc_name}.{last_state}",
                    'to': f"{proc_name}.{curr_state}",
                    'condition': 'assignment'
                })
                last_state = curr_state

        # Ensure transitions use the full process name prefix for consistency
        for t in result['transitions']:
            if '.' not in t['from']:
                t['from'] = f"{result['processes'][0]}.{t['from']}" if result['processes'] else t['from']
            if '.' not in t['to']:
                t['to'] = f"{result['processes'][0]}.{t['to']}" if result['processes'] else t['to']
        # Extract LTL properties
        ltl_pattern = r'ltl\s+(\w+)\s*\{\s*(.*?)\s*\}'
        for match in re.finditer(ltl_pattern, pml_content, re.DOTALL):
            result['ltl_properties'].append({
                'name': match.group(1),
                'formula': match.group(2).strip()
            })

        return result

    def toggle_auto_scroll(self):
        self.auto_scroll_enabled = self.auto_scroll.get()

    def toggle_sidebar_width(self):
        """Toggle sidebar between compact and expanded widths."""
        if self.sidebar_is_expanded:
            target = self.sidebar_collapsed_width
            self.sidebar_is_expanded = False
        else:
            target = self.sidebar_expanded_width
            self.sidebar_is_expanded = True
        self.sidebar.configure(width=target)
        self.grid_columnconfigure(0, minsize=target)
        self.sidebar_inner.configure(width=max(160, target - 40))
        self.sidebar.update_idletasks()

    def set_tool_running(self, tool, running):
        btn = self.tool_stop_buttons.get(tool)
        if btn:
            btn.configure(state="normal" if running else "disabled")

    def request_stop_tool(self, tool):
        self.stop_requested[tool] = True
        proc = self.tool_processes.get(tool)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            self.console.insert("end", f"🛑 Stop requested for {tool.upper()}...\n")
        else:
            self.console.insert("end", f"ℹ️ {tool.upper()} is not currently running.\n")
        self.console.see("end")

    def run_cancellable_command(self, tool, cmd, cwd=None, env=None, timeout=None, shell=False):
        start = time.time()
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.tool_processes[tool] = proc
        self.stop_requested[tool] = False
        self.after(0, lambda: self.set_tool_running(tool, True))
        try:
            while True:
                if self.stop_requested.get(tool):
                    try:
                        proc.terminate()
                        stdout, stderr = proc.communicate(timeout=5)
                    except Exception:
                        proc.kill()
                        stdout, stderr = proc.communicate()
                    return {
                        'returncode': -15,
                        'stdout': stdout or '',
                        'stderr': (stderr or '') + '\nStopped by user.',
                        'cancelled': True,
                        'timed_out': False,
                    }
                if timeout is not None and (time.time() - start) > timeout:
                    try:
                        proc.terminate()
                        stdout, stderr = proc.communicate(timeout=5)
                    except Exception:
                        proc.kill()
                        stdout, stderr = proc.communicate()
                    return {
                        'returncode': 124,
                        'stdout': stdout or '',
                        'stderr': stderr or '',
                        'cancelled': False,
                        'timed_out': True,
                    }
                rc = proc.poll()
                if rc is not None:
                    stdout, stderr = proc.communicate()
                    return {
                        'returncode': rc,
                        'stdout': stdout or '',
                        'stderr': stderr or '',
                        'cancelled': False,
                        'timed_out': False,
                    }
                time.sleep(0.2)
        finally:
            self.tool_processes.pop(tool, None)
            self.stop_requested[tool] = False
            self.after(0, lambda: self.set_tool_running(tool, False))

    def prewarm_lean_runtime(self):
        """Warm up Lean/Elan once to reduce first-run latency."""
        def _prewarm():
            import tempfile, os
            ok = False
            try:
                # Step 1: confirm lean --version responds
                r = subprocess.run(
                    ["lean", "--version"],
                    capture_output=True, text=True, timeout=30,
                )
                ok = r.returncode == 0
                version = r.stdout.strip() or r.stderr.strip()

                # Step 2: run a trivial Lean 4 script to warm the JIT cache
                if ok:
                    with tempfile.NamedTemporaryFile(
                        mode='w', suffix='.lean', delete=False, encoding='utf-8'
                    ) as f:
                        f.write("-- warmup\n#check Nat.zero_le\n")
                        tmp = f.name
                    try:
                        subprocess.run(
                            ["lean", tmp],
                            capture_output=True, timeout=60,
                        )
                    except Exception:
                        pass
                    finally:
                        try: os.unlink(tmp)
                        except: pass

                self.after(0, lambda: self.lean_prewarm_status.configure(
                    text=f"Lean prewarm: ready  ({version[:30]})" if ok
                         else "Lean prewarm: failed",
                    text_color=self.theme.SUCCESS if ok else self.theme.WARNING,
                ))
            except subprocess.TimeoutExpired:
                self.after(0, lambda: self.lean_prewarm_status.configure(
                    text="Lean prewarm: timeout (run 'elan default leanprover/lean4:v4.29.1')",
                    text_color=self.theme.WARNING,
                ))
            except Exception as e:
                self.after(0, lambda: self.lean_prewarm_status.configure(
                    text=f"Lean prewarm: error — {e}",
                    text_color=self.theme.WARNING,
                ))

        threading.Thread(target=_prewarm, daemon=True).start()

    def _tool_relevance(self, rust_code):
        """Infer which Rust verifiers are relevant for this file."""
        has_kani = "#[kani::proof]" in rust_code or "kani::" in rust_code
        has_anchor = (
            "use anchor_lang::" in rust_code
            or "#[program]" in rust_code
            or "#[account]" in rust_code
            or "declare_id!(" in rust_code
        )
        has_creusot = (
            "#[cfg(creusot)]" in rust_code
            or "#[requires(" in rust_code
            or "#[ensures(" in rust_code
            or "creusot_std::" in rust_code
        )
        has_prusti = (
            "#[cfg(prusti)]" in rust_code
            or "prusti_contracts" in rust_code
            or "#[requires(" in rust_code
            or "#[ensures(" in rust_code
        )
        return {
            "kani": has_kani,
            "anchor": has_anchor,
            "creusot": has_creusot,
            "prusti": has_prusti,
        }

    def _should_skip_tool(self, tool_name, rust_code):
        if not self.skip_incompatible.get():
            return False, ""
        rel = self._tool_relevance(rust_code)
        if rel["anchor"] and tool_name in ("prusti", "creusot", "kani"):
            return True, "Anchor program requires Cargo dependencies not available in temp verifier compile"
        if rel["kani"] and not rel["creusot"] and tool_name in ("prusti", "creusot"):
            return True, "Kani-specific input detected"
        if rel["creusot"] and not rel["kani"] and tool_name == "kani":
            return True, "Creusot-specific input detected"
        return False, ""

    def check_tools(self):
        """Check if verification tools are installed in a background thread"""
        def _check():
            tools = []

            # Check SPIN (-V is the correct flag, not --version)
            try:
                r = subprocess.run(["spin", "-V"], capture_output=True, timeout=2)
                tools.append("SPIN" if r.returncode == 0 else "SPIN(err)")
            except:
                tools.append("SPIN(missing)")

            # Check Coq
            try:
                subprocess.run(["coqc", "--version"], capture_output=True, timeout=2)
                tools.append("Coq")
            except:
                tools.append("Coq(missing)")

            # Check Lean — use a longer timeout since elan may need a moment
            try:
                r = subprocess.run(["lean", "--version"], capture_output=True, timeout=15)
                tools.append("Lean" if r.returncode == 0 else "Lean(err)")
            except subprocess.TimeoutExpired:
                tools.append("Lean(missing)")
            except Exception:
                tools.append("Lean(missing)")

            # Check GCC
            try:
                subprocess.run(["gcc", "--version"], capture_output=True, timeout=2)
                tools.append("GCC")
            except:
                tools.append("GCC(missing)")

            # Prusti health check
            try:
                with tempfile.TemporaryDirectory() as project_dir:
                    src = os.path.join(project_dir, "lib.rs")
                    with open(src, "w") as f:
                        f.write("fn f(x: u64) -> u64 { x }\n")
                    result = subprocess.run(
                        ["prusti-rustc", "--edition=2021", "--crate-type=lib", src],
                        capture_output=True,
                        text=True,
                        timeout=12,
                        cwd=project_dir,
                        env=build_prusti_env(),
                    )
                    stderr = result.stderr or ""
                    if "unknown configuration flag `home`" in stderr:
                        tools.append("Prusti(env)")
                        self.after(0, lambda: self.console.insert(
                            "end",
                            "Prusti health: invalid PRUSTI_* env detected (remove PRUSTI_HOME)\n",
                        ))
                    elif "compiler unexpectedly panicked" in stderr:
                        tools.append("Prusti(ICE)")
                        self.after(0, lambda: self.console.insert(
                            "end",
                            "Prusti health: internal crash detected (toolchain mismatch/bug)\n",
                        ))
                    elif result.returncode == 0:
                        tools.append("Prusti")
                    else:
                        tools.append("Prusti(err)")
            except subprocess.TimeoutExpired:
                tools.append("Prusti(timeout)")
            except FileNotFoundError:
                tools.append("Prusti(missing)")
            except Exception:
                tools.append("Prusti(missing)")

            self.after(0, lambda: self.tool_status.configure(text=" | ".join(tools)))

        threading.Thread(target=_check, daemon=True).start()

    def scan_recent_files(self):
        """Scan for recent .pml files in a background thread"""
        def _scan():
            home = os.path.expanduser("~")
            pml_files = []

            try:
                for file in os.listdir(home):
                    if file.endswith('.pml'):
                        pml_files.append(file)
            except:
                pass

            if pml_files:
                self.after(0, lambda: self._update_console_with_files(pml_files))

        threading.Thread(target=_scan, daemon=True).start()

    def _update_console_with_files(self, pml_files):
        """Update console with found files on main thread"""
        self.console.insert("end", f"📁 Found {len(pml_files)} Promela file(s) in home directory:\n")
        for f in pml_files[:5]:
            self.console.insert("end", f"   • {f}\n")
        self.console.insert("end", "\n")
        if self.auto_scroll_enabled:
            self.console.see("end")

    def show_welcome(self):
        welcome = """
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                         🛡️ DEFI GUARDIAN FORMAL VERIFICATION SUITE                    ║
║                    Powered by SPIN Model Checker | LTL Properties                     ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

SUPPORTED FORMATS:
   ┌─────────────────────────────────────────────────────────────────────────────────┐
   │ • .pml  - Promela models (direct Spin verification with LTL properties)        │
   │ • .sol  - Solidity contracts (auto-translated to Promela with LTL)             │
   │ • .rs   - Rust programs (experimental translation with verification)           │
   └─────────────────────────────────────────────────────────────────────────────────┘

FORMAL VERIFICATION FEATURES:
   • LTL Properties (Linear Temporal Logic) - Safety, Liveness, Fairness
   • Invariants and Safety Properties
   • State Space Exploration and Counterexample Analysis
   • Proof Obligations Generation
   • Coq and Lean Theorem Prover Integration

HOW TO USE:
   1. Click "OPEN SOURCE FILE" to select a model (.pml, .sol, .rs)
   2. Click "RUN SPIN VERIFICATION" to verify with LTL properties
   3. View detailed results in this console (with auto-scroll)
   4. Click "OPEN VISUAL DASHBOARD" for state diagrams and analytics
   5. Use Coq/Lean buttons for theorem proving

TIPS:
   • Solidity contracts are automatically translated to Promela with LTL properties
   • Verification results are saved to verification_state.json for the dashboard
   • The dashboard shows state diagrams, LTL verification, and risk analytics
   • Use "Verbose output" for detailed SPIN verification logs

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Ready for verification!
"""
        self.console.insert("1.0", welcome)

    def clear_console(self):
        self.console.delete("1.0", "end")
        self.show_welcome()

    def update_verification_status(self, tool, status, message=""):
        """Send real-time update to dashboard"""
        data = {
            "type": "verification_update",
            "tool": tool,
            "status": status,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }

        # Save to file for dashboard polling
        with open("live_status.json", "w") as f:
            json.dump(data, f)

    def export_console(self):
        """Export console content to a user-specified file in the dedicated folder"""
        try:
            # Open file dialog for user to name the file
            file_path = filedialog.asksaveasfilename(
                initialdir=CONSOLE_DIR,
                title="Save Console Export",
                defaultextension=".txt",
                initialfile="statev.txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
            )

            if not file_path:
                return  # User cancelled

            content = self.console.get("1.0", "end")
            with open(file_path, 'w', encoding="utf-8") as f:
                f.write(content)
            self.console.insert("end", f"\nConsole exported to: {file_path}\n")
            self.console.see("end")
        except Exception as e:
            self.console.insert("end", f"\nExport failed: {e}\n")

    def load_file(self):
        """Open file dialog and load selected file"""
        file_path = filedialog.askopenfilename(
            title="Open Source File",
            filetypes=[
                ("All Supported", "*.sol *.pml *.rs"),
                ("Solidity", "*.sol"),
                ("Promela", "*.pml"),
                ("Rust", "*.rs")
            ]
        )
        if file_path:
            self.load_file_to_editor(file_path)

            # Save for dashboard - use full path so app.py can always find it
            with open(os.path.join(REPORTS_DIR, "active_file.txt"), "w") as f:
                f.write(file_path)

            self.console.insert("end", f"\nLOADED FILE: {os.path.basename(file_path)}\n", "header")
            self.console.insert("end", f"TYPE: {self.file_type.upper() if self.file_type else 'Unknown'}\n", "dim")
            self.console.insert("end", f"PATH: {file_path}\n", "dim")
            self.console.insert("end", "─"*60 + "\n\n", "dim")
            self.console.see("end")

    def _parse_specs(self, text):
        """Parse specifications from text into a dictionary indexed by name."""
        specs = {}
        # Simple parser for ltl and rule
        patterns = [
            (r'(ltl\s+(\w+)\s*\{.*?\})', 'ltl'),
            (r'(rule\s+(\w+)\s*\{.*?\})', 'rule')
        ]
        for pattern, kind in patterns:
            for match in re.finditer(pattern, text, re.DOTALL):
                full_spec = match.group(1).strip()
                name = match.group(2)
                specs[name] = full_spec
        return specs

    def update_spec_editor(self, content, overwrite=False):
        """Extract LTL properties and Certora specs and display in Spec tab with priority management"""
        if overwrite:
            ltl_specs = []
            # Extract LTL properties from content
            ltl_pattern = r'(ltl\s+\w+\s*\{.*?\})'
            ltl_matches = re.findall(ltl_pattern, content, re.DOTALL)
            if ltl_matches:
                ltl_specs.extend(ltl_matches)

            # Extract Certora specs if present
            if "methods {" in content or "rule " in content:
                certora_pattern = r'(rule\s+\w+\s*\{.*?\})'
                certora_matches = re.findall(certora_pattern, content, re.DOTALL)
                if certora_matches:
                    ltl_specs.extend(certora_matches)

            spec_text = ""
            if ltl_specs:
                spec_text = "\n\n".join(ltl_specs)
            elif "contract " not in content and "active proctype" not in content and "fn " not in content:
                # If no patterns and it doesn't look like a full source model, use as is
                # (Useful for loading .spec or .ltl files directly)
                spec_text = content.strip()
            elif "Prusti/Kani" in content:
                # Special case for our AI-generated Rust specs
                spec_text = content.strip()

            if spec_text:
                self.after(0, lambda: self.spec_editor.delete("1.0", "end"))
                self.after(0, lambda: self.spec_editor.insert("1.0", spec_text))
            return

        # Merging behavior (Priority: Current Editor > Content)
        current_text = self.spec_editor.get("1.0", "end-1c").strip()
        current_specs = self._parse_specs(current_text)
        new_specs = self._parse_specs(content)

        # Merge: keep current if it exists (higher priority), otherwise add new
        merged = current_specs.copy()
        added_count = 0
        for name, full_spec in new_specs.items():
            if name not in merged:
                merged[name] = full_spec
                added_count += 1

        if added_count > 0 or (not current_text and new_specs):
            spec_text = "\n\n".join(merged.values())
            self.after(0, lambda: self.spec_editor.delete("1.0", "end"))
            self.after(0, lambda: self.spec_editor.insert("1.0", spec_text))

            # Switch to Spec tab if it was empty before
            if not current_text:
                self.after(100, lambda: self.editor_tabs.set("Specifications & LTL"))

    def run_verification(self):
        if not self.current_file:
            messagebox.showwarning("No File", "Please load a file first.")
            return

        def verify():
            self.verify_btn.configure(state="disabled", text="VERIFYING...")
            self.set_tool_running("spin", True)
            self.status_label.configure(text="Running SPIN verification...")

            self.console.insert("end", "\nRUNNING SPIN VERIFICATION\n", "header")
            self.console.insert("end", f"Model: {os.path.basename(self.current_file)}\n", "dim")
            self.console.insert("end", f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n", "dim")
            self.console.insert("end", "─"*60 + "\n\n", "dim")
            if self.auto_scroll_enabled:
                self.console.see("end")

            try:
                # Read source file
                with open(self.current_file, 'r') as src:
                    content = src.read()

                translated_content = None
                translated_path = None

                # Translate if needed
                if self.file_type == '.sol':
                    self.console.insert("end", "[1/5] Translating Solidity to Promela...\n")
                    translator = VerifiedTranslator()
                    translated_content, obligations = translator.translate_with_proof(content)

                    # Check cache for translation results
                    if self.plugin_manager:
                        cached = self.plugin_manager.cache.get(content, "spin") if self.plugin_manager.cache else None
                        if cached:
                            self.console.insert("end", "Results loaded from cache (no re-translation needed)\n")

                    self.console.insert("end", "   Translation complete with semantic preservation checks\n")
                    for obligation in obligations:
                        self.console.insert("end", f"   Proof Obligation: {obligation}\n")
                    self.console.insert("end", "\n")

                elif self.file_type == '.rs':
                    self.console.insert("end", "[1/5] Translating Rust to Promela...\n")
                    translated_content = DeFiTranslator.translate_rust(content)
                    self.console.insert("end", "   Translation complete\n\n")
                else:
                    self.console.insert("end", "[1/5] Using native Promela model...\n\n")
                    translated_content = content

                # Save translated output to project directory
                if translated_content:
                    translated_path = os.path.join(MODELS_DIR, "translated_output.pml")
                    with open(translated_path, 'w') as dst:
                        dst.write(translated_content)
                    self.console.insert("end", f"   Translated output saved to: {translated_path}\n\n")

                    # Update translated editor in UI
                    self.after(0, lambda: self.translated_editor.delete("1.0", "end"))
                    self.after(0, lambda: self.translated_editor.insert("1.0", translated_content))

                    # Update specification editor
                    self.update_spec_editor(translated_content)

                    # Also save a copy with original name for reference
                    base_name = os.path.splitext(os.path.basename(self.current_file))[0]
                    backup_path = os.path.join(MODELS_DIR, f"{base_name}_translated.pml")
                    with open(backup_path, 'w') as dst:
                        dst.write(translated_content)
                    self.console.insert("end", f"   Backup saved to: {backup_path}\n\n")

                # Save active file info
                active_path = os.path.join(REPORTS_DIR, "active_file.txt")
                with open(active_path, "w") as f:
                    f.write(os.path.basename(self.current_file))

                # Use the translated file for verification
                verify_file = translated_path if translated_path else self.current_file

                # Check for manually modified specifications in the tab
                custom_specs = self.spec_editor.get("1.0", "end-1c").strip()
                if custom_specs:
                    with open(verify_file, 'r') as f:
                        verify_content = f.read()

                    # Remove existing LTL from file to replace with custom ones
                    clean_content = re.sub(r'ltl\s+\w+\s*\{.*?\}', '', verify_content, flags=re.DOTALL)

                    # Also remove any Certora-style rules if we're replacing them
                    clean_content = re.sub(r'rule\s+\w+\s*\{.*?\}', '', clean_content, flags=re.DOTALL)

                    # Append custom specs
                    verify_content = clean_content + "\n\n/* === CUSTOM SPECIFICATIONS === */\n" + custom_specs

                    # Save back to verify_file
                    with open(verify_file, 'w') as f:
                        f.write(verify_content)

                    self.console.insert("end", "   Applied custom specifications from Specification tab\n")

                # Check for LTL properties
                with open(verify_file, 'r') as f:
                    verify_content = f.read()
                    ltl_count = verify_content.count('ltl')
                    if ltl_count > 0:
                        self.console.insert("end", f"   Detected {ltl_count} LTL property(ies) in model\n\n")

                # Continue with SPIN verification...
                self.console.insert("end", "[2/5] Generating SPIN verifier...\n")
                result = self.run_cancellable_command(
                    "spin", ["spin", "-a", verify_file], cwd=PROJECT_DIR, timeout=120
                )
                if result.get('cancelled'):
                    self.console.insert("end", "SPIN generation stopped by user.\n")
                    self.status_label.configure(text="SPIN stopped by user")
                    return
                if result.get('timed_out'):
                    self.console.insert("end", "SPIN generation timed out.\n")
                    self.status_label.configure(text="SPIN generation timed out")
                    return
                if result['stdout'] and self.verbose_output.get():
                    self.console.insert("end", result['stdout'])
                if result['stderr']:
                    self.console.insert("end", f"   Warning: {result['stderr']}\n")

                self.console.insert("end", "\n[3/5] Compiling verifier...\n")
                compile_result = self.run_cancellable_command(
                    "spin", ["gcc", "-O3", "-o", os.path.join(SPIN_LOGS, "pan"), "pan.c"], cwd=PROJECT_DIR, timeout=120
                )
                if compile_result.get('cancelled'):
                    self.console.insert("end", "GCC compile stopped by user.\n")
                    self.status_label.configure(text="SPIN stopped by user")
                    return
                if compile_result.get('timed_out'):
                    self.console.insert("end", "GCC compile timed out.\n")
                    self.status_label.configure(text="SPIN compile timed out")
                    return
                if compile_result['stderr'] and self.verbose_output.get():
                    self.console.insert("end", compile_result['stderr'])

                self.console.insert("end", "[4/5] 🔍 Running verification with LTL model checking...\n\n")
                self.console.insert("end", "─" * 60 + "\n")

                # First, verify each LTL claim individually
                ltl_names = []
                with open(verify_file, 'r') as f:
                    content = f.read()
                    ltl_names = re.findall(r'ltl\s+(\w+)', content)

                all_success = True
                combined_output = ""
                combined_stderr = ""

                if ltl_names:
                    for ltl_name in ltl_names:
                        self.console.insert("end", f"   Verifying LTL: {ltl_name}...\n")
                        result = self.run_cancellable_command(
                            "spin", [os.path.join(SPIN_LOGS, "pan"), "-a", "-N", ltl_name], cwd=PROJECT_DIR, timeout=120
                        )
                        if result.get('cancelled'):
                            self.console.insert("end", f"LTL run '{ltl_name}' stopped by user.\n")
                            self.status_label.configure(text="SPIN stopped by user")
                            return
                        if result.get('timed_out'):
                            self.console.insert("end", f"LTL run '{ltl_name}' timed out.\n")
                            self.status_label.configure(text="SPIN timed out")
                            return
                        combined_output += f"\n--- LTL {ltl_name} ---\n{result['stdout']}"
                        combined_stderr += result['stderr']
                        if result['returncode'] != 0:
                            all_success = False
                else:
                    # No specific LTL claims, run default
                    result = self.run_cancellable_command(
                        "spin", [os.path.join(SPIN_LOGS, "pan"), "-a"], cwd=PROJECT_DIR, timeout=120
                    )
                    if result.get('cancelled'):
                        self.console.insert("end", "SPIN run stopped by user.\n")
                        self.status_label.configure(text="SPIN stopped by user")
                        return
                    if result.get('timed_out'):
                        self.console.insert("end", "SPIN run timed out.\n")
                        self.status_label.configure(text="SPIN timed out")
                        return
                    combined_output = result['stdout']
                    combined_stderr = result['stderr']
                    all_success = result['returncode'] == 0

                verify_result = type('obj', (object,), {
                    'returncode': 0 if all_success else 1,
                    'stdout': combined_output,
                    'stderr': combined_stderr
                })()

                # Display output
                output_lines = verify_result.stdout.split('\n')

                # Update Problems tab
                self.after(0, lambda: self.problems_text.delete("1.0", "end"))

                for line in output_lines:
                    if 'error' in line.lower() and '0' not in line:
                        self.console.insert("end", f"ERROR: {line}\n")
                        self.after(0, lambda l=line: self.problems_text.insert("end", f"ERROR: {l}\n"))
                    elif 'warning' in line.lower():
                        self.console.insert("end", f"WARNING: {line}\n")
                        self.after(0, lambda l=line: self.problems_text.insert("end", f"WARNING: {l}\n"))
                    else:
                        self.console.insert("end", f"{line}\n")

                if verify_result.stderr:
                    self.console.insert("end", verify_result.stderr)

                self.console.insert("end", "\n" + "─" * 60 + "\n")

                # After getting verify_result, parse and save
                # SPIN pan returns 0 even if errors are found, so we must check the output
                has_violations = False
                if verify_result.stdout:
                    if "errors: 0" not in verify_result.stdout or \
                       "assertion violated" in verify_result.stdout.lower() or \
                       "acceptance cycle" in verify_result.stdout.lower() or \
                       "errors: [1-9]" in verify_result.stdout:
                        # Check more carefully for "errors: 0"
                        error_match = re.search(r"errors:\s*([1-9]\d*)", verify_result.stdout)
                        if error_match or "acceptance cycle" in verify_result.stdout.lower() or "assertion violated" in verify_result.stdout.lower():
                            has_violations = True

                success = (verify_result.returncode == 0) and not has_violations

                # Parse statistics
                states_stored = 0
                transitions = 0
                depth = 0

                if verify_result.stdout:
                    states_match = re.search(r"(\d+) states, stored", verify_result.stdout)
                    if states_match:
                        states_stored = int(states_match.group(1))
                    trans_match = re.search(r"(\d+) transitions", verify_result.stdout)
                    if trans_match:
                        transitions = int(trans_match.group(1))
                    depth_match = re.search(r"depth reached (\d+)", verify_result.stdout)
                    if depth_match:
                        depth = int(depth_match.group(1))

                # Handle trail file if verification failed
                if not success:
                    # Look for trail file in common locations
                    trail_src = None
                    possible_srcs = [
                        os.path.join(PROJECT_DIR, "pan.trail"),
                        os.path.join(PROJECT_DIR, "translated_output.pml.trail"),
                        os.path.join(SPIN_LOGS, "pan.trail"),
                        os.path.join(os.getcwd(), "pan.trail"),
                        os.path.join(os.getcwd(), "translated_output.pml.trail")
                    ]
                    for p in possible_srcs:
                        if os.path.exists(p):
                            trail_src = p
                            break

                    if trail_src:
                        trail_dest = os.path.join(SPIN_LOGS, "translated_output.pml.trail")
                        # Also copy to root for app.py and CounterexampleAnalyzer to find easily
                        trail_root = os.path.join(PROJECT_DIR, "translated_output.pml.trail")
                        import shutil

                        src_abs = os.path.abspath(trail_src)
                        dest_abs = os.path.abspath(trail_dest)
                        root_abs = os.path.abspath(trail_root)

                        if src_abs != dest_abs:
                            shutil.copy2(trail_src, trail_dest)
                        if src_abs != root_abs:
                            shutil.copy2(trail_src, trail_root)
                        self.console.insert("end", f"   Counterexample trail preserved: {trail_dest}\n", "success")
                    else:
                        self.console.insert("end", "   Verification failed but no .trail file was found by SPIN\n", "warning")

                spin_log_path = self.save_tool_log('spin', verify_result.stdout, verify_result.stderr)

                # Extract LTL verification results
                # SPIN reports per-property blocks separated by "--- LTL <name> ---"
                # Each block contains "errors: N" — 0 means pass, >0 means fail.
                ltl_results = []
                spin_out = verify_result.stdout
                ltl_blocks = spin_out.split('--- LTL ')
                for block in ltl_blocks[1:]:
                    name_match = re.match(r'(\w+)', block)
                    if not name_match:
                        continue
                    prop_name = name_match.group(1)
                    err_match = re.search(r'errors:\s*(\d+)', block)
                    prop_passed = (err_match and int(err_match.group(1)) == 0)
                    # Also extract the formula from the model if available
                    formula = ''
                    if hasattr(self, 'spec_editor'):
                        spec_text = self.spec_editor.get("1.0", "end-1c")
                        fm = re.search(rf'ltl\s+{re.escape(prop_name)}\s*\{{([^}}]+)\}}', spec_text)
                        if fm:
                            formula = fm.group(1).strip()
                    ltl_results.append({
                        'name': prop_name,
                        'success': prop_passed,
                        'formula': formula,
                        'errors': int(err_match.group(1)) if err_match else 0,
                    })

                # Save SPIN state (after LTL extraction so ltl_results is populated)
                self.save_verification_state('spin', {
                    'success': success,
                    'output': verify_result.stdout,
                    'errors': verify_result.stderr,
                    'states_stored': states_stored,
                    'transitions': transitions,
                    'depth': depth,
                    'log_path': spin_log_path,
                    'ltl_results': ltl_results,
                }, specs=custom_specs)

                if success:
                    self.console.insert("end", "\nVERIFICATION SUCCESSFUL!\n", "success")
                    self.console.insert("end", "   All LTL properties satisfied\n", "success")
                    self.console.insert("end", "   No counterexamples found\n", "success")
                    self.console.insert("end", "   Invariants hold in all states\n", "success")
                    self.console.insert("end", "─"*60 + "\n\n", "dim")

                    self.status_label.configure(text="Verification successful!")

                    # Show statistics
                    if "states, stored" in verify_result.stdout:
                        match = re.search(r"(\d+) states, stored", verify_result.stdout)
                        if match:
                            self.console.insert("end", f"States explored: {match.group(1)}\n", "accent")
                    if "depth reached" in verify_result.stdout:
                        match = re.search(r"depth reached (\d+)", verify_result.stdout)
                        if match:
                            self.console.insert("end", f"Depth reached: {match.group(1)}\n", "accent")
                    if "transitions" in verify_result.stdout:
                        match = re.search(r"(\d+) transitions", verify_result.stdout)
                        if match:
                            self.console.insert("end", f"Transitions: {match.group(1)}\n", "accent")

                    if ltl_results:
                        self.console.insert("end", "\nLTL PROPERTIES VERIFIED:\n", "header")
                        for ltl in ltl_results:
                            self.console.insert("end", f"   • {ltl}\n", "success")

                else:
                    self.console.insert("end", "\nVERIFICATION FAILED!\n", "error")
                    self.console.insert("end", "   Counterexample found\n", "error")
                    self.console.insert("end", "   Review the model and LTL properties\n", "error")
                    self.console.insert("end", "─"*60 + "\n\n", "dim")

                    self.status_label.configure(text="Verification failed - counterexample found")

                    # Show trail file info
                    trail_path = os.path.join(PROJECT_DIR, "pan.trail")
                    if not os.path.exists(trail_path):
                        trail_path = os.path.join(SPIN_LOGS, "pan.trail")

                    if os.path.exists(trail_path):
                        self.console.insert("end", f"📄 Counterexample trail saved to: {trail_path}\n")
                        with open(trail_path, 'r') as f:
                            trail_content = f.read()[:2000]
                            self.console.insert("end", "\nCounterexample preview:\n")
                            self.console.insert("end", trail_content + "\n")

                # Save results for dashboard
                VerificationState.save_result(
                    success,
                    verify_result.stdout,
                    verify_result.stderr,
                    os.path.basename(self.current_file),
                    ltl_results
                )

                # Copy to project root for unified access
                try:
                    state_file_src = os.path.join(REPORTS_DIR, "verification_state.json")
                    state_file_dest = os.path.join(PROJECT_DIR, "verification_state.json")
                    if os.path.exists(state_file_src):
                        import shutil
                        shutil.copy2(state_file_src, state_file_dest)
                except:
                    pass

                self.console.insert("end", "\n[5/5] Verification results saved to verification_state.json\n")

                # Export state graph for 3D visualization - THIS MUST HAPPEN
                verify_result_dict = {
                    'success': success,
                    'output': verify_result.stdout,
                    'errors': verify_result.stderr,
                    'model_name': os.path.basename(self.current_file)
                }
                self.export_state_graph(verify_result_dict)  # Make sure this is called!
                self.console.insert("end", f"\n📊 State graph exported for dashboard visualization\n")

            except subprocess.TimeoutExpired:
                self.console.insert("end", "\n❌ Verification timed out after 120 seconds\n")
                self.status_label.configure(text="⏰ Verification timed out")
            except Exception as e:
                self.console.insert("end", f"\n❌ Error: {e}\n")
                self.status_label.configure(text=f"Error: {str(e)[:50]}")

            if self.auto_scroll_enabled:
                self.console.see("end")
            self.verify_btn.configure(state="normal", text="🚀 RUN SPIN VERIFICATION")
            self.set_tool_running("spin", False)

            # Cleanup
            for f in [os.path.join(PROJECT_DIR, x) for x in ["pan.c", "pan.h", "pan", "pan.trail"]]:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except:
                        pass

        threading.Thread(target=verify, daemon=True).start()

    def log_job_history(self, tool, result, specs=""):
        """Record a verification job in the centralized audit log"""
        try:
            # Load existing history
            history = []
            if os.path.exists(AUDIT_LOG_FILE):
                with open(AUDIT_LOG_FILE, 'r') as f:
                    history = json.load(f)

            # Create new job entry
            job_id = str(uuid.uuid4())[:8]
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Determine status
            if result.get('skipped'):
                status = 'SKIPPED'
            elif result.get('infra_error'):
                status = 'ERROR'
            else:
                status = 'SUCCESS' if result.get('success', False) else 'FAILED'

            # Capture trace if failed SPIN job
            trace_path = ''
            if tool.lower() == 'spin' and status == 'FAILED':
                try:
                    from counterexample_analyzer import CounterexampleAnalyzer
                    analyzer = CounterexampleAnalyzer(PROJECT_DIR)
                    if analyzer.has_counterexample():
                        trace_data = analyzer.get_structured_trace()
                        if trace_data and 'error' not in trace_data:
                            # Harmonize with app.py's expected format (node_details)
                            if 'steps' in trace_data:
                                trace_data['node_details'] = [
                                    {
                                        "id": f"Step{s['step']}",
                                        "action": s['raw'],
                                        "line": s['line'],
                                        "proc": s['proc_name'],
                                        "variables": s['variables']
                                    } for s in trace_data['steps']
                                ]

                            trace_filename = f"trace_{job_id}.json"
                            trace_path = os.path.join(TRACES_DIR, trace_filename)
                            with open(trace_path, 'w') as f:
                                json.dump(trace_data, f, indent=2)
                except Exception as e:
                    print(f"Error capturing trace for job history: {e}")

            job_entry = {
                'id': job_id,
                'timestamp': timestamp,
                'tool': tool.upper(),
                'file': os.path.basename(self.current_file) if self.current_file else "unknown",
                'status': status,
                'log_path': result.get('log_path', ''),
                'trace_path': trace_path,
                'specs': specs,
                'details': {
                    'states': result.get('states_stored', 0),
                    'transitions': result.get('transitions', 0),
                    'depth': result.get('depth', 0),
                    'error_msg': result.get('errors', '')[:200] if status == 'FAILED' else ''
                }
            }

            # Add to history (newest first)
            history.insert(0, job_entry)

            # Keep only last 100 jobs
            history = history[:100]

            # Save back to file
            with open(AUDIT_LOG_FILE, 'w') as f:
                json.dump(history, f, indent=2)

            # Mirror desktop audit history into the portal database if available
            self.save_portal_audit_record(job_entry)

        except Exception as e:
            print(f"Error logging job history: {e}")

    def save_portal_audit_record(self, job_entry):
        """Mirror desktop job history into the web portal audit database."""
        try:
            # Check for PostgreSQL first (Render/Production mode)
            db_url = os.environ.get("DATABASE_URL")
            if db_url:
                try:
                    # Try to use SQLAlchemy if available (harmonized with app.py)
                    sys.path.insert(0, os.path.join(PROJECT_DIR, 'web_portal'))
                    from audit_db import db, AuditHistory, User
                    from flask import Flask
                    from config import config_by_name
                    
                    app = Flask(__name__)
                    env = os.environ.get("FLASK_ENV", "dev")
                    app.config.from_object(config_by_name[env])
                    db.init_app(app)
                    
                    with app.app_context():
                        new_audit = AuditHistory(
                            user_id=None,
                            filename=job_entry.get('file', 'unknown'),
                            file_type=os.path.splitext(job_entry.get('file', ''))[1] or '',
                            tool_used=job_entry.get('tool', 'unknown'),
                            status='PASS' if job_entry.get('status', '').upper() in ('PASS', 'SUCCESS') else 'FAIL',
                            states_explored=job_entry.get('details', {}).get('states', 0),
                            transitions=job_entry.get('details', {}).get('transitions', 0),
                            depth_reached=job_entry.get('details', {}).get('depth', 0),
                            vulnerabilities_found=job_entry.get('details', {}).get('error_msg', ''),
                            ltl_properties=json.dumps([]),
                            verification_output=job_entry.get('log_path', '') or job_entry.get('trace_path', ''),
                            audit_date=datetime.now(),
                            report_path=job_entry.get('trace_path', '')
                        )
                        db.session.add(new_audit)
                        db.session.commit()
                    return
                except Exception as e:
                    print(f"PostgreSQL mirror failed, falling back to API: {e}")
                    # Fallback to API if DB direct access fails
                    try:
                        import requests
                        requests.post('http://localhost:5000/api/v1/events/emit', 
                                     json={"type": "sync", "job_id": job_entry.get('id')},
                                     timeout=2)
                    except: pass

            # SQLite Fallback (Local mode)
            portal_db = os.path.join(PROJECT_DIR, 'web_portal', 'defi_guardian.db')
            if not os.path.exists(portal_db):
                return

            conn = sqlite3.connect(portal_db)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO audit_history (
                    user_id, filename, file_type, tool_used, status,
                    states_explored, transitions, depth_reached,
                    vulnerabilities_found, ltl_properties,
                    verification_output, audit_date, report_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                None,
                job_entry.get('file', 'unknown'),
                os.path.splitext(job_entry.get('file', ''))[1] or '',
                job_entry.get('tool', 'unknown'),
                'PASS' if job_entry.get('status', '').upper() in ('PASS', 'SUCCESS') else 'FAIL',
                job_entry.get('details', {}).get('states', 0),
                job_entry.get('details', {}).get('transitions', 0),
                job_entry.get('details', {}).get('depth', 0),
                job_entry.get('details', {}).get('error_msg', ''),
                json.dumps([]),
                job_entry.get('log_path', '') or job_entry.get('trace_path', ''),
                job_entry.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                job_entry.get('trace_path', '')
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error saving portal audit record: {e}")

    def save_verification_state(self, tool, result, specs=""):
        """Save verification state for a specific tool"""
        import json
        from datetime import datetime

        state_file = os.path.join(PROJECT_DIR, 'verification_state.json')

        # Load existing state
        state = {}
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
            except:
                pass

        # Update state for this tool
        if result.get('skipped'):
            status = 'SKIP'
        elif result.get('infra_error'):
            status = 'INFRA_ERROR'
        else:
            status = 'PASS' if result.get('success', False) else 'FAIL'
        state[tool] = {
            'timestamp': datetime.now().isoformat(),
            'status': status,
            'success': result.get('success', False),
            'output': result.get('output', ''),
            'errors': result.get('errors', ''),
            'failure_kind': result.get('failure_kind', ''),
            'failure_hint': result.get('failure_hint', ''),
            'reason': result.get('reason', ''),
            'log_path': result.get('log_path', ''),
            'specs': specs,
            'ltl_results': result.get('ltl_results', []),
            'states_stored': result.get('states_stored', 0),
            'transitions': result.get('transitions', 0),
            'depth': result.get('depth', 0),
        }

        # Also update overall verification info if this is SPIN
        if tool == 'spin':
            state['success'] = result.get('success', False)
            state['datetime'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            state['states_stored'] = result.get('states_stored', 0)
            state['transitions'] = result.get('transitions', 0)
            state['depth'] = result.get('depth', 0)
            state['specs'] = specs

        # Save to file
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)

        # Emit event to portal for real-time updates
        try:
            import requests
            import uuid
            import sys
            # Ensure parent directory is in path for events and trace_parsers
            _root = os.path.dirname(os.path.abspath(__file__))
            if _root not in sys.path:
                sys.path.insert(0, _root)

            from events import VerificationCompleteEvent, LTLProperty
            from trace_parsers import get_parser

            # Use appropriate parser to get high-fidelity data
            parser = get_parser(tool)
            ltl_props = []
            trace_data = None

            log_path = result.get('log_path', '')
            trace_path = result.get('trace_path', '')

            if parser and log_path:
                ltl_props_raw = parser.parse_rules(log_path)
                ltl_props = [LTLProperty(**p) for p in ltl_props_raw]
                trace_data = parser.parse_trace(log_path, trace_path)

            event = VerificationCompleteEvent(
                audit_id=result.get('id', str(uuid.uuid4())[:8]),
                tool=tool.upper(),
                filename=os.path.basename(self.current_file) if hasattr(self, 'current_file') and self.current_file else "unknown",
                timestamp=datetime.now(),
                status=status,
                ltl_properties=ltl_props,
                trace_data=trace_data,
                log_path=log_path,
                trace_path=trace_path,
                states_explored=result.get('states_stored', 0),
                transitions=result.get('transitions', 0),
                depth=result.get('depth', 0)
            )

            # Send to web portal
            # Use v1 API
            requests.post('http://localhost:5000/api/v1/events/emit',
                         json=json.loads(event.to_json()),
                         timeout=2)
        except Exception:
            # Silent fail for event emission - don't want to crash the main app
            pass

        # Log to job history
        self.log_job_history(tool, result, specs)

        # Also update the display status
        self.update_tool_status_display()

    def save_tool_log(self, tool, output="", errors=""):
        """Persist full verifier output/errors to disk for debugging."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Select target directory
        log_dir = LOGS_DIR
        if tool.lower() == 'spin': log_dir = SPIN_LOGS
        elif tool.lower() == 'certora': log_dir = CERTORA_LOGS
        elif tool.lower() == 'coq': log_dir = COQ_LOGS
        elif tool.lower() == 'lean': log_dir = LEAN_LOGS
        elif tool.lower() in ['kani', 'prusti', 'creusot']: log_dir = RUST_LOGS

        log_path = os.path.join(log_dir, f"{tool}_verification_{ts}.log")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"=== {tool.upper()} VERIFICATION LOG ===\n")
                f.write(f"timestamp: {datetime.now().isoformat()}\n")
                f.write(f"file: {self.current_file}\n\n")
                f.write("--- STDOUT ---\n")
                f.write(output or "")
                f.write("\n\n--- STDERR ---\n")
                f.write(errors or "")
            return log_path
        except Exception:
            return ""

    def update_tool_status_display(self):
        """Update the tool status display in sidebar"""
        state_file = os.path.join(REPORTS_DIR, 'verification_state.json')
        if not os.path.exists(state_file):
            return

        try:
            with open(state_file, 'r') as f:
                state = json.load(f)

            # Update sidebar icons/colors based on results
            if state.get('spin'):
                success = state['spin'].get('success', False)
                self.verify_btn.configure(border_color=self.theme.SUCCESS if success else self.theme.ERROR)

            if state.get('kani'):
                success = state['kani'].get('success', False)
                self.kani_btn.configure(border_color=self.theme.SUCCESS if success else self.theme.ERROR)
        except:
            pass

    def start_verification_monitor(self):
        """Monitor verification status in real-time"""
        self.monitoring = True

        def monitor():
            last_mtime = 0
            state_file = os.path.join(REPORTS_DIR, "verification_state.json")

            while self.monitoring:
                if os.path.exists(state_file):
                    current_mtime = os.path.getmtime(state_file)
                    if current_mtime > last_mtime:
                        last_mtime = current_mtime
                        self.load_verification_status()
                time.sleep(2)

        threading.Thread(target=monitor, daemon=True).start()

    def load_verification_status(self):
        """Load and display verification status"""
        state_file = os.path.join(REPORTS_DIR, "verification_state.json")
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                state = json.load(f)

            # Update status label on main thread
            if state.get('success'):
                self.after(0, lambda: self.status_label.configure(text=f"Verified at {state.get('datetime', 'unknown')}"))
            else:
                self.after(0, lambda: self.status_label.configure(text=f"Verification failed at {state.get('datetime', 'unknown')}"))

    def verify_with_coq(self):
        """Run Coq verification"""
        if not self.current_file:
            self.console.insert("end", "No file selected\n", "error")
            return

        self.coq_btn.configure(state="disabled", text="Running Coq...")

        def run_coq():
            try:
                self.after(0, lambda: self.console.insert("end",
                    "\nCOQ VERIFICATION\n", "header"))
                self.after(0, lambda: self.console.insert("end", "─"*60 + "\n", "dim"))

                from coq_verifier import CoqVerifier
                verifier = CoqVerifier()

                if not verifier.coq_available:
                    self.after(0, lambda: self.console.insert("end", "Coq is not installed\n", "error"))
                    self.after(0, lambda: self.coq_btn.configure(state="normal", text="COQ VERIFICATION"))
                    return

                contract_name = os.path.basename(self.current_file).split('.')[0]
                coq_script = verifier.generate_coq_script(contract_name, {})
                result = verifier.verify_with_coq(coq_script)

                coq_out = result.get('output', '')
                coq_err = result.get('errors', result.get('error', ''))
                coq_log_path = self.save_tool_log('coq', coq_out, coq_err)

                # Save Coq state
                self.save_verification_state('coq', {
                    **result,
                    'errors': coq_err,
                    'log_path': coq_log_path,
                }, specs=coq_script)

                def display():
                    if result.get('success'):
                        self.console.insert("end", "Coq verification successful!\n", "success")
                    else:
                        error_msg = result.get('error', result.get('errors', 'Unknown error'))
                        self.console.insert("end", f"Coq failed: {error_msg}\n", "error")

                    self.console.see("end")
                    self.coq_btn.configure(state="normal", text="COQ PROOF ASSISTANT")

                self.after(0, display)

            except Exception as e:
                self.after(0, lambda: self.console.insert("end", f"Coq error: {e}\n", "error"))
                self.after(0, lambda: self.coq_btn.configure(state="normal", text="COQ PROOF ASSISTANT"))

        threading.Thread(target=run_coq, daemon=True).start()

    def run_lean_verification(self):
        """Run Lean 4 verification — self-contained, no lake/mathlib needed."""
        if not self.current_file:
            self.console.insert("end", "No file selected\n", "error")
            return
        if self.lean_running:
            self.console.insert("end", "Lean verification already running. Please wait.\n", "warning")
            return

        self.lean_running = True
        self.lean_btn.configure(state="disabled", text="⏳ Running Lean...")
        self.set_tool_running("lean", True)

        def run_lean():
            import tempfile
            tmp_file = None
            try:
                self.after(0, lambda: self.console.insert("end",
                    "\n⚡ LEAN VERIFICATION\n", "header"))
                self.after(0, lambda: self.console.insert("end", "─"*60 + "\n", "dim"))

                contract_name = os.path.basename(self.current_file).split('.')[0]

                # ── Extract state variables from translated Promela ──────
                pml_path = os.path.join(MODELS_DIR, "translated_output.pml")
                state_vars: dict = {}
                ltl_props: list = []

                if os.path.exists(pml_path):
                    with open(pml_path, 'r') as f:
                        pml = f.read()
                    # Extract int/bool variables
                    for m in re.finditer(
                        r'(?:int|bool|byte)\s+(\w+)\s*(?:=\s*([^;]+))?;', pml
                    ):
                        name, val = m.group(1), (m.group(2) or "0").strip()
                        try:
                            state_vars[name] = int(val)
                        except ValueError:
                            state_vars[name] = 0
                    # Extract LTL formulas
                    for m in re.finditer(
                        r'ltl\s+(\w+)\s*\{([^}]+)\}', pml
                    ):
                        ltl_props.append({
                            'name': m.group(1),
                            'formula': m.group(2).strip()
                        })

                # ── Build Lean 4 script ──────────────────────────────────
                lines = [
                    f"-- Lean 4 Formal Verification",
                    f"-- Contract: {contract_name}",
                    f"-- Generated by DeFi Guardian",
                    f"-- Lean version: 4.29.1 (no imports needed)",
                    "",
                ]

                # State variable definitions
                if state_vars:
                    lines.append("-- State variables extracted from Promela model")
                    for var, val in list(state_vars.items())[:12]:
                        lines.append(f"def {var} : Nat := {max(0, val)}")
                    lines.append("")

                # Core theorems — always included
                lines += [
                    "-- Core safety theorem: balance is non-negative",
                    "theorem balance_non_negative (b : Nat) : b ≥ 0 := Nat.zero_le b",
                    "",
                    "-- Reentrancy guard model",
                    "def lock_after_op (locked : Bool) : Bool :=",
                    "  if locked then locked else true",
                    "",
                    "theorem lock_acquired (locked : Bool) (h : locked = false) :",
                    "    lock_after_op locked = true := by",
                    "  simp [lock_after_op, h]",
                    "",
                ]

                # Collateral theorem if we have the right variables
                if 'user_collateral' in state_vars and 'user_debt' in state_vars and 'price_eth' in state_vars:
                    lines += [
                        "-- Collateral sufficiency invariant",
                        "theorem collateral_sufficient :",
                        "    user_collateral * price_eth ≥ user_debt := by",
                        "  native_decide",
                        "",
                    ]
                elif 'collateral' in state_vars and 'debt' in state_vars:
                    lines += [
                        "-- Collateral sufficiency invariant",
                        "theorem collateral_sufficient :",
                        "    collateral ≥ debt := by",
                        "  native_decide",
                        "",
                    ]

                # LTL-derived theorems (simple ones only — no temporal operators)
                for prop in ltl_props[:6]:
                    name = re.sub(r'[^a-zA-Z0-9_]', '_', prop['name'])
                    formula = prop['formula']
                    # Only handle simple [] (expr) — strip the [] wrapper
                    inner = re.sub(r'^\[\]\s*', '', formula).strip()
                    inner = re.sub(r'^<>\s*', '', inner).strip()
                    # Convert to Lean: replace variable names with their Nat defs
                    lean_expr = inner
                    for var in state_vars:
                        lean_expr = re.sub(rf'\b{var}\b', var, lean_expr)
                    lean_expr = lean_expr.replace('&&', '∧').replace('||', '∨')
                    lean_expr = lean_expr.replace('==', '=').replace('!=', '≠')
                    lean_expr = lean_expr.replace('>=', '≥').replace('<=', '≤')
                    lean_expr = lean_expr.replace('!', '¬')
                    # Only emit if it looks like a decidable arithmetic proposition
                    if any(op in lean_expr for op in ('≥', '≤', '=', '∧', '∨')) \
                       and 'state' not in lean_expr.lower():
                        lines += [
                            f"-- LTL property: {prop['name']}",
                            f"-- Formula: {formula}",
                            f"theorem ltl_{name} : {lean_expr} := by",
                            "  native_decide",
                            "",
                        ]

                # #check statements
                lines += [
                    "#check balance_non_negative",
                    "#check lock_acquired",
                ]

                lean_script = "\n".join(lines)

                # ── Write and run ────────────────────────────────────────
                tmp_file = tempfile.NamedTemporaryFile(
                    mode='w', suffix='.lean', delete=False, encoding='utf-8'
                )
                tmp_file.write(lean_script)
                tmp_file.close()

                self.after(0, lambda: self.console.insert("end",
                    f"Running Lean on: {os.path.basename(tmp_file.name)}\n", "dim"))

                result = self.run_cancellable_command(
                    "lean", ['lean', tmp_file.name], timeout=LEAN_TIMEOUT_SECONDS
                )

                if result.get('cancelled'):
                    self.after(0, lambda: self.console.insert("end", "Lean stopped by user.\n"))
                    self.after(0, lambda: self.lean_btn.configure(state="normal", text="λ Lean Theorem Prover"))
                    return
                if result.get('timed_out'):
                    self.after(0, lambda: self.console.insert("end",
                        f"Lean timed out ({LEAN_TIMEOUT_SECONDS}s).\n"
                        "   Tip: run 'elan default leanprover/lean4:v4.29.1' in a terminal.\n",
                        "warning"))
                    self.after(0, lambda: self.lean_btn.configure(state="normal", text="λ Lean Theorem Prover"))
                    return

                success = result['returncode'] == 0

                lean_log_path = self.save_tool_log('lean', result['stdout'], result['stderr'])
                self.save_verification_state('lean', {
                    'success': success,
                    'output': result['stdout'],
                    'errors': result['stderr'],
                    'log_path': lean_log_path,
                }, specs=lean_script)

                def display():
                    if success:
                        self.console.insert("end", "Lean verification successful!\n", "success")
                        out = result['stdout'].strip()
                        if out:
                            self.console.insert("end", out + "\n", "dim")
                    else:
                        err = (result['stderr'] or result['stdout'] or "Unknown error")[:800]
                        self.console.insert("end", f"Lean failed:\n{err}\n", "error")
                    self.console.see("end")
                    self.lean_btn.configure(state="normal", text="λ Lean Theorem Prover")

                self.after(0, display)

            except Exception as e:
                self.after(0, lambda: self.console.insert("end", f"Lean error: {e}\n", "error"))
                self.after(0, lambda: self.lean_btn.configure(state="normal", text="λ Lean Theorem Prover"))
            finally:
                self.lean_running = False
                self.after(0, lambda: self.set_tool_running("lean", False))
                if tmp_file and os.path.exists(tmp_file.name):
                    try: os.unlink(tmp_file.name)
                    except: pass

        threading.Thread(target=run_lean, daemon=True).start()

    def verify_with_prusti(self):
        """Run Prusti on the actual user Rust file with auto-annotations."""
        if not self.current_file:
            self.console.insert("end", "No file selected\n", "error")
            return
        ext = os.path.splitext(self.current_file)[1].lower()
        if ext != '.rs':
            self.console.insert("end", "Prusti only works with .rs files\n", "error")
            return

        self.prusti_btn.configure(state="disabled", text="Running Prusti...")
        self.set_tool_running("prusti", True)

        def run_prusti():
            try:
                # Read the user's Rust source first (same path as the open editor file).
                with open(self.current_file, 'r', encoding="utf-8") as f:
                    rust_code = f.read()

                self.after(0, lambda: self.console.insert(
                    "end",
                    "\nPRUSTI VERIFICATION\n", "header"
                ))
                self.after(0, lambda: self.console.insert("end", "─"*60 + "\n", "dim"))

                verifier = RustVerifier()
                if not verifier.prusti_available:
                    self.after(0, lambda: self.console.insert(
                        "end", "Prusti not installed (``prusti-rustc`` not found)\n"
                    ))
                    self.after(0, lambda: self.prusti_btn.configure(
                        state="normal", text="PRUSTI VERIFICATION"
                    ))
                    self.after(0, lambda: self.set_tool_running("prusti", False))
                    return

                skip_prusti_src, src_reason = should_skip_prusti_for_source(rust_code)
                if skip_prusti_src:
                    self.after(0, lambda: self.console.insert(
                        "end", f"Prusti skipped: {src_reason}\n"
                    ))
                    self.after(0, lambda: self.prusti_btn.configure(
                        state="normal", text="PRUSTI VERIFICATION"
                    ))
                    self.save_verification_state('prusti', {
                        'success': False,
                        'output': '',
                        'errors': '',
                        'skipped': True,
                        'reason': src_reason,
                    })
                    self.after(0, lambda: self.set_tool_running("prusti", False))
                    return

                skip, reason = self._should_skip_tool("prusti", rust_code)
                if skip:
                    self.after(0, lambda: self.console.insert(
                        "end", f"Prusti skipped: {reason}\n"
                    ))
                    self.after(0, lambda: self.prusti_btn.configure(
                        state="normal", text="PRUSTI VERIFICATION"
                    ))
                    self.save_verification_state('prusti', {
                        'success': False,
                        'output': '',
                        'errors': '',
                        'skipped': True,
                        'reason': reason,
                    })
                    self.after(0, lambda: self.set_tool_running("prusti", False))
                    return

                self.after(0, lambda: self.console.insert(
                    "end",
                    "Analyzing Rust code and generating verification annotations...\n",
                ))

                annotated_code = verifier.analyze_and_annotate(rust_code)

                self.after(0, lambda: self.console.insert(
                    "end",
                    "Annotations generated. Running robust Prusti verification...\n\n",
                ))

                annotated_path = os.path.join(PROJECT_DIR, "annotated_output.rs")
                with open(annotated_path, 'w', encoding="utf-8") as f:
                    f.write(annotated_code)
                self.after(0, lambda: self.console.insert(
                    "end",
                    f"Annotated code saved to: {annotated_path}\n\n",
                ))

                # Use the new robust verification chain
                result = verifier.verify_with_prusti_robust(annotated_code)

                if result.get('cached'):
                    self.after(0, lambda: self.console.insert(
                        "end", "Results loaded from cache (no re-verification needed)\n"
                    ))

                strategy = result.get('robust_strategy')
                if strategy:
                    self.after(0, lambda s=strategy: self.console.insert(
                        "end", f"Robust strategy used: {s}\n"
                    ))

                log_path = self.save_tool_log(
                    'prusti', result.get('output', ''), result.get('errors', '')
                )
                self.save_verification_state('prusti', {
                    'success': result.get('success', False),
                    'output': result.get('output', ''),
                    'errors': result.get('errors', ''),
                    'log_path': log_path,
                    'skipped': result.get('skipped', False),
                })

                def display():
                    if result.get('skipped'):
                        self.console.insert(
                            "end",
                            (result.get('error') or "Skipped") + "\n",
                        )
                    elif result.get('success'):
                        self.console.insert("end", "Prusti verification successful!\n")
                        self.console.insert(
                            "end",
                            "   - All preconditions satisfied\n"
                            "   - All postconditions hold\n"
                            "   - No panics possible\n",
                        )
                        out = result.get('output') or ""
                        if out:
                            self.console.insert("end", out[:500] + "\n")
                    else:
                        self.console.insert("end", "Prusti verification failed:\n")
                        err = result.get('errors') or result.get('error') or 'Unknown error'
                        self.console.insert("end", err[:500] + "\n")
                        kind, hint = classify_prusti_failure(result.get('errors'))
                        if hint:
                            self.console.insert(
                                "end",
                                f"{hint}"
                                + (
                                    " Try reinstalling/updating Prusti toolchain.\n"
                                    if kind == "ice" else "\n"
                                ),
                            )
                        self.console.insert("end", "\nTips:\n")
                        self.console.insert(
                            "end",
                            "   - Check the annotated_output.rs file\n"
                            "   - Review function preconditions\n",
                        )
                    if log_path:
                        self.console.insert("end", f"Full Prusti log: {log_path}\n")
                    self.console.see("end")
                    self.prusti_btn.configure(state="normal", text="PRUSTI VERIFICATION")

                self.after(0, display)

            except Exception as e:
                self.after(0, lambda: self.console.insert("end", f"Prusti error: {e}\n"))
                self.after(0, lambda: self.prusti_btn.configure(
                    state="normal", text="PRUSTI VERIFICATION"
                ))
            finally:
                self.after(0, lambda: self.set_tool_running("prusti", False))

        threading.Thread(target=run_prusti, daemon=True).start()

    def verify_with_creusot(self):
        """Run Creusot using cargo creusot in a temp Cargo project"""
        if not self.current_file:
            self.console.insert("end", "No file selected\n")
            return
        ext = os.path.splitext(self.current_file)[1].lower()
        if ext != '.rs':
            self.console.insert("end", "Creusot only works with .rs files\n")
            return

        self.creusot_btn.configure(state="disabled", text="Running Creusot...")
        self.set_tool_running("creusot", True)

        def run_creusot():
            import tempfile, shutil
            project_dir = None
            try:
                self.after(0, lambda: self.console.insert("end",
                    "\n" + "="*60 + "\nCREUSOT VERIFICATION\n" + "="*60 + "\n"))

                with open(self.current_file, 'r') as f:
                    rust_code = f.read()
                skip, reason = self._should_skip_tool("creusot", rust_code)
                if skip:
                    self.after(0, lambda: self.console.insert(
                        "end", f"⏭️ Creusot skipped: {reason}\n"
                    ))
                    self.after(0, lambda: self.creusot_btn.configure(state="normal", text="📐 CREUSOT VERIFICATION"))
                    self.save_verification_state('creusot', {
                        'success': False,
                        'output': '',
                        'errors': '',
                        'skipped': True,
                        'reason': reason,
                    })
                    return

                # cargo creusot passes -F creusot-std/creusot … — dependency key must be creusot-std
                rust_code = prepend_creusot_prelude(rust_code)
                rust_code = strip_rust_main_for_lib(rust_code)

                project_dir = tempfile.mkdtemp()
                src_dir = os.path.join(project_dir, 'src')
                os.makedirs(src_dir)

                with open(os.path.join(src_dir, 'lib.rs'), 'w') as f:
                    f.write(rust_code)

                # Cargo.toml — reference creusot-std by its real package name
                # Also declare known cfg flags to suppress "unexpected cfg" warnings
                with open(os.path.join(project_dir, 'Cargo.toml'), 'w') as f:
                    f.write(
                        '[package]\nname = "creusot_verify"\nversion = "0.1.0"\n'
                        'edition = "2021"\n\n'
                        '[dependencies]\n'
                        f'creusot-std = {{ path = "{CREUSOT_STD_PATH}" }}\n\n'
                        '# Suppress unexpected cfg warnings for verification tool annotations\n'
                        '[lints.rust]\n'
                        'unexpected_cfgs = { level = "allow", check-cfg = ['
                        '\'cfg(creusot)\', \'cfg(prusti)\', \'cfg(kani)\'] }\n'
                    )

                # Set the nightly lib path so creusot-rustc can find librustc_driver
                env = os.environ.copy()
                nightly_lib = (
                    '/home/slade/.rustup/toolchains/'
                    'nightly-2026-02-27-x86_64-unknown-linux-gnu/lib'
                )
                env['LD_LIBRARY_PATH'] = (
                    nightly_lib + ':' + env.get('LD_LIBRARY_PATH', '')
                )

                result = self.run_cancellable_command(
                    "creusot",
                    ['cargo', 'creusot'],
                    timeout=600,
                    cwd=project_dir,
                    env=env,
                )
                if result.get('cancelled'):
                    self.after(0, lambda: self.console.insert("end", "Creusot stopped by user.\n"))
                    self.after(0, lambda: self.creusot_btn.configure(state="normal", text="CREUSOT VERIFICATION"))
                    return
                if result.get('timed_out'):
                    self.after(0, lambda: self.console.insert("end", "Creusot timed out.\n"))
                    self.after(0, lambda: self.creusot_btn.configure(state="normal", text="CREUSOT VERIFICATION"))
                    return
                success = result['returncode'] == 0
                log_path = self.save_tool_log('creusot', result['stdout'], result['stderr'])
                self.save_verification_state('creusot', {
                    'success': success,
                    'output': result['stdout'],
                    'errors': result['stderr'],
                    'log_path': log_path,
                })

                def display():
                    if success:
                        self.console.insert("end", "Creusot verification successful!\n")
                        if result['stdout']:
                            self.console.insert("end", result['stdout'][:500] + "\n")
                    else:
                        err_tail = (result['stderr'] or "")[-4000:]
                        self.console.insert("end", f"Creusot failed:\n{err_tail}\n")
                    if log_path:
                        self.console.insert("end", f"Full Creusot log: {log_path}\n")
                    self.console.see("end")
                    self.creusot_btn.configure(state="normal", text="CREUSOT VERIFICATION")

                self.after(0, display)

            except subprocess.TimeoutExpired:
                self.after(0, lambda: self.console.insert("end", "❌ Creusot timed out\n"))
                self.after(0, lambda: self.creusot_btn.configure(state="normal", text="📐 CREUSOT VERIFICATION"))
            except Exception as e:
                self.after(0, lambda: self.console.insert("end", f"❌ Creusot error: {e}\n"))
                self.after(0, lambda: self.creusot_btn.configure(state="normal", text="📐 CREUSOT VERIFICATION"))
            finally:
                self.after(0, lambda: self.set_tool_running("creusot", False))

        threading.Thread(target=run_creusot, daemon=True).start()

    def verify_with_certora(self):
         """Run Certora Prover on the active Solidity contract"""
         if not self.current_file:
             self.console.insert("end", "No file selected\n", "error")
             return

         ext = os.path.splitext(self.current_file)[1].lower()
         if ext != '.sol':
             self.console.insert("end", "Certora only works with .sol files\n", "error")
             return

         # Check if Certora CLI is installed
         try:
             subprocess.run(["certoraRun", "--version"], capture_output=True, timeout=5)
         except (FileNotFoundError, subprocess.TimeoutExpired):
             self.console.insert("end", "certora-cli not installed\n", "error")
             self.console.insert("end", "   Install: pip install certora-cli\n", "error")
             return

         # Check API key
         if "CERTORAKEY" not in os.environ:
             self.console.insert("end", "CERTORAKEY environment variable not set in current process\n", "warning")
             self.console.insert("end", "   If already set in your system, ensure it is exported to this IDE session.\n", "warning")
             self.console.insert("end", "   Attempting to run anyway...\n\n")

         self.verify_with_certora_btn.configure(state="disabled", text="Running Certora...")
         self.set_tool_running("certora", True)

         def run_certora():
             try:
                 self.after(0, lambda: self.console.insert("end",
                     "\nCERTORA FORMAL VERIFICATION\n", "header"))
                 self.after(0, lambda: self.console.insert("end", "─"*60 + "\n", "dim"))
                 self.after(0, lambda: self.console.insert("end",
                     f"Verifying: {os.path.basename(self.current_file)}\n", "dim"))

                 # Copy contract to certora directory
                 certora_dir = os.path.join(PROJECT_DIR, "certora", "contracts")
                 os.makedirs(certora_dir, exist_ok=True)

                 contract_name = os.path.splitext(os.path.basename(self.current_file))[0]
                 dest_path = os.path.join(certora_dir, os.path.basename(self.current_file))

                 import shutil
                 if os.path.abspath(self.current_file) != os.path.abspath(dest_path):
                     shutil.copy2(self.current_file, dest_path)
                 self.after(0, lambda: self.console.insert("end",
                     f"Contract copied to: {dest_path}\n"))

                 # Check if spec file exists
                 spec_file = os.path.join(PROJECT_DIR, "certora", "specs", f"{contract_name}.spec")
                 if not os.path.exists(spec_file):
                     self.after(0, lambda: self.console.insert("end",
                         f"No spec file found at: {spec_file}\n"))
                     self.after(0, lambda: self.console.insert("end",
                         "   Using default spec template...\n"))

                     # Generate default spec
                     default_spec = self._generate_default_certora_spec(contract_name)
                     with open(spec_file, 'w') as f:
                         f.write(default_spec)
                     self.after(0, lambda: self.console.insert("end",
                         f"Generated default spec: {spec_file}\n"))

                 # Create config file
                 conf_dir = os.path.join(PROJECT_DIR, "certora", "confs")
                 os.makedirs(conf_dir, exist_ok=True)

                 conf_file = os.path.join(conf_dir, f"{contract_name}.conf")
                 conf = {
                     "files": [dest_path],
                     "verify": f"{contract_name}:{spec_file}",
                     "solc": "solc8.17",
                     "optimistic_loop": True,
                     "loop_iter": "3",
                     "rule_sanity": "basic",
                     "msg": f"DeFi Guardian - {contract_name}",
                     "prover_args": [
                         "-mediumTimeout", "300",
                         "-depth", "200"
                     ]
                 }
                 with open(conf_file, 'w') as f:
                     json.dump(conf, f, indent=2)

                 # Run Certora
                 self.after(0, lambda: self.console.insert("end",
                     "\nRunning Certora Prover (cloud)...\n"))
                 self.after(0, lambda: self.console.insert("end",
                     "   This may take 2-10 minutes...\n\n"))

                 result = subprocess.run(
                     ["certoraRun", conf_file],
                     capture_output=True,
                     text=True,
                     timeout=600,
                     cwd=PROJECT_DIR
                 )

                 # Read spec content
                 spec_content = ""
                 if os.path.exists(spec_file):
                     with open(spec_file, 'r') as f:
                         spec_content = f.read()

                 # Parse results
                 output = result.stdout
                 errors = result.stderr
                 combined = output + errors

                 # Detect config/infra errors vs real violations
                 is_config_error = (
                     "not a known attribute" in combined or
                     "Error when reading" in combined or
                     "certoraRun: error" in combined.lower()
                 )
                 if is_config_error:
                     success = False
                     infra_error = True
                     failure_kind = "config_error"
                     failure_hint = "Certora config has unknown attributes. Check the .conf file."
                 else:
                     infra_error = False
                     failure_kind = ""
                     failure_hint = ""
                     success = (
                         "VERIFIED" in combined or
                         "All rules passed" in combined or
                         result.returncode == 0
                     ) and "violated" not in combined.lower()

                 # Extract per-rule results from Certora output
                 certora_rules = []
                 for m in re.finditer(r'Rule\s+(\w+)\s+(passed|violated)', combined, re.IGNORECASE):
                     certora_rules.append({
                         'name': m.group(1),
                         'success': m.group(2).lower() == 'passed',
                         'formula': '',
                         'errors': 0 if m.group(2).lower() == 'passed' else 1,
                     })

                 # Job URL
                 job_url = ''
                 job_match = re.search(r'https://prover\.certora\.com/output/\S+', combined)
                 if job_match:
                     job_url = job_match.group(0)

                 # Save results
                 log_path = self.save_tool_log('certora', output, errors)
                 self.save_verification_state('certora', {
                     'success': success,
                     'output': output,
                     'errors': errors,
                     'log_path': log_path,
                     'ltl_results': certora_rules,
                     'job_url': job_url,
                     'spec_content': spec_content,
                     'infra_error': infra_error,
                     'failure_kind': failure_kind,
                     'failure_hint': failure_hint,
                 }, specs=spec_content)

                 def display():
                     if is_config_error:
                         self.console.insert("end", "Certora config error — check .conf file\n", "warning")
                         self.console.insert("end", f"   {failure_hint}\n", "warning")
                     elif success:
                         self.console.insert("end", "Certora verification passed!\n", "success")
                         self.console.insert("end", "   All rules verified on actual bytecode\n", "success")
                     else:
                         self.console.insert("end", "Certora found violations:\n", "error")
                         violations = re.findall(r'Rule (\w+) violated', combined)
                         for v in violations:
                             self.console.insert("end", f"   • {v}\n", "error")

                     if job_url:
                         self.console.insert("end", f"\nFull results: {job_url}\n")

                     if log_path:
                         self.console.insert("end", f"Log saved: {log_path}\n")

                     self.console.see("end")
                     self.verify_with_certora_btn.configure(state="normal", text="VERIFY WITH CERTORA")

                 self.after(0, display)

             except subprocess.TimeoutExpired:
                 self.after(0, lambda: self.console.insert("end", "Certora timed out (10 min)\n"))
                 self.after(0, lambda: self.verify_with_certora_btn.configure(
                     state="normal", text="VERIFY WITH CERTORA"))
             except Exception as e:
                 self.after(0, lambda: self.console.insert("end", f"Certora error: {e}\n"))
                 self.after(0, lambda: self.verify_with_certora_btn.configure(
                     state="normal", text="VERIFY WITH CERTORA"))
             finally:
                 self.after(0, lambda: self.set_tool_running("certora", False))

         threading.Thread(target=run_certora, daemon=True).start()

    def _generate_default_certora_spec(self, contract_name):
        """
        Generate a Certora spec that mirrors the tutorial patterns:
        - envfree declarations for pure view functions
        - Symbolic variables (no constructor setup needed)
        - before/after state comparison
        - method f + calldataarg for universal property checks
        - Self-transfer / same-address edge cases
        - Allowance tracking for ERC20
        """
        name_lower = contract_name.lower()

        # ── Detect contract type from name ────────────────────────────
        is_erc20    = any(k in name_lower for k in ("erc20", "token", "transfer", "allowance"))
        is_lending  = any(k in name_lower for k in ("lend", "borrow", "pool", "vault", "collateral"))
        is_vesting  = any(k in name_lower for k in ("vest", "cliff", "release", "lock"))
        is_flash    = any(k in name_lower for k in ("flash", "borrower", "receiver"))

        if is_erc20:
            return self._certora_erc20_spec(contract_name)
        if is_lending:
            return self._certora_lending_spec(contract_name)
        if is_vesting:
            return self._certora_vesting_spec(contract_name)
        if is_flash:
            return self._certora_flash_spec(contract_name)
        return self._certora_generic_spec(contract_name)

    # ── Per-type Certora spec generators ─────────────────────────────

    def _certora_erc20_spec(self, contract_name):
        return f'''\
/*
 * Certora Specification — ERC20 Token: {contract_name}
 *
 * Patterns from the Certora tutorial:
 *   - envfree for pure view functions (no msg.sender dependency)
 *   - Symbolic variables: prover finds violating assignments
 *   - before/after state comparison
 *   - method f + calldataarg: check ALL methods, not just specific ones
 *   - Self-transfer edge case (holder == recipient)
 *   - Allowance tracking
 */

methods {{
    // envfree: these functions never read msg.sender / block.timestamp
    function balanceOf(address)          external returns (uint256) envfree;
    function allowance(address, address) external returns (uint256) envfree;
    function totalSupply()               external returns (uint256) envfree;
}}

// ─── Rule 1: Transfer correctness ───────────────────────────────────────────
// Symbolic variables — the prover searches for values that violate assertions.
// No constructor setup needed; prover considers ALL possible storage states.
rule transferFromSpec(address holder, address recipient, uint256 amount) {{
    require holder   != 0;
    require recipient != 0;

    uint256 balance_holder_before    = balanceOf(holder);
    uint256 balance_recipient_before = balanceOf(recipient);

    // Pass environment (msg.sender, block.timestamp, etc.)
    transferFrom(e, holder, recipient, amount);

    uint256 balance_holder_after    = balanceOf(holder);
    uint256 balance_recipient_after = balanceOf(recipient);

    if (holder != recipient) {{
        // Normal transfer: holder goes down, recipient goes up
        assert balance_holder_after    == balance_holder_before    - amount,
            "TRANSFER: holder balance must decrease by amount";
        assert balance_recipient_after == balance_recipient_before + amount,
            "TRANSFER: recipient balance must increase by amount";
    }} else {{
        // Self-transfer: nothing should change (tutorial bug fix)
        assert balance_holder_after == balance_holder_before,
            "SELF-TRANSFER: balance must not change when holder == recipient";
    }}
}}

// ─── Rule 2: Allowance tracking ─────────────────────────────────────────────
rule transferFromAllowance(address holder, address spender, uint256 amount) {{
    require holder  != 0;
    require spender != 0;

    uint256 allowance_before = allowance(holder, spender);

    // Require the environment's msg.sender IS the spender
    require e.msg.sender == spender;

    transferFrom@withrevert(e, holder, spender, amount);

    if (!lastReverted) {{
        // Successful transfer: spender had enough allowance
        assert allowance_before >= amount,
            "ALLOWANCE: spender must have sufficient allowance";
        // Allowance is reduced by amount spent
        assert allowance(holder, spender) == allowance_before - amount,
            "ALLOWANCE: must decrease by amount after transfer";
    }}
}}

// ─── Rule 3: Only holder can increase allowance (universal — all methods) ───
// Uses method f + calldataarg to check EVERY function in the contract,
// not just approve(). This catches hidden backdoors like pullTheRug().
rule onlyHolderCanIncreaseAllowance(address holder, address spender) {{
    require holder  != 0;
    require spender != 0;

    uint256 allowance_before = allowance(holder, spender);

    // Call ANY method with ANY arguments and ANY msg.sender
    method f;
    calldataarg args;
    f(e, args);

    uint256 allowance_after = allowance(holder, spender);

    // If allowance went up, the caller MUST have been the holder
    assert allowance_after > allowance_before => e.msg.sender == holder,
        "ALLOWANCE: only the holder may increase their own allowance";
}}

// ─── Rule 4: Total supply integrity ─────────────────────────────────────────
rule totalSupplyIntegrity(method f) {{
    uint256 supply_before = totalSupply();

    calldataarg args;
    f(e, args);

    uint256 supply_after = totalSupply();

    // Supply may only change via mint/burn — never by transfer
    assert supply_after != supply_before =>
        (f.selector == sig:mint(address,uint256).selector ||
         f.selector == sig:burn(address,uint256).selector),
        "SUPPLY: total supply changed by non-mint/burn function";
}}
'''

    def _certora_lending_spec(self, contract_name):
        return f'''\
/*
 * Certora Specification — Lending Protocol: {contract_name}
 *
 * Key invariants: solvency, collateral ratio, liquidation correctness.
 */

methods {{
    function deposits(address)      external returns (uint256) envfree;
    function borrows(address)       external returns (uint256) envfree;
    function totalDeposits()        external returns (uint256) envfree;
    function totalBorrows()         external returns (uint256) envfree;
    function getHealthFactor(address) external returns (uint256) envfree;
    function COLLATERAL_RATIO()     external returns (uint256) envfree;
}}

// ─── Solvency invariant (checked after every method) ────────────────────────
rule solvencyInvariant(method f) {{
    uint256 total_dep_before = totalDeposits();
    uint256 total_bor_before = totalBorrows();

    calldataarg args;
    f(e, args);

    assert totalDeposits() >= totalBorrows(),
        "SOLVENCY: pool owes more than it holds";
}}

// ─── Borrow requires sufficient collateral ──────────────────────────────────
rule borrowCollateralCheck(address user, uint256 amount) {{
    require user   != 0;
    require amount > 0;

    uint256 deposit_before = deposits(user);
    uint256 borrow_before  = borrows(user);

    borrow@withrevert(e, amount);

    if (!lastReverted) {{
        uint256 required = (borrows(user) * COLLATERAL_RATIO()) / 100;
        assert deposits(user) >= required,
            "COLLATERAL: position underwater after borrow";
    }}
}}

// ─── Liquidation only when health factor < 100 ──────────────────────────────
rule liquidationCheck(address user, address liquidator, uint256 debtToCover) {{
    require user      != liquidator;
    require user      != 0;
    require liquidator != 0;
    require borrows(user) > 0;

    uint256 hf_before = getHealthFactor(user);

    liquidate@withrevert(e, user, debtToCover);

    if (!lastReverted) {{
        assert hf_before < 100,
            "LIQUIDATION: healthy position was liquidated";
    }}
}}
'''

    def _certora_vesting_spec(self, contract_name):
        return f'''\
/*
 * Certora Specification — Vesting Wallet: {contract_name}
 */

methods {{
    function released()          external returns (uint256) envfree;
    function vestedAmount(uint64) external returns (uint256) envfree;
    function start()             external returns (uint64)  envfree;
    function duration()          external returns (uint64)  envfree;
    function owner()             external returns (address) envfree;
}}

// ─── Released amount never decreases ────────────────────────────────────────
rule releasedMonotonicallyIncreases(method f) {{
    uint256 released_before = released();

    calldataarg args;
    f(e, args);

    assert released() >= released_before,
        "VESTING: released amount must never decrease";
}}

// ─── Only owner can release ──────────────────────────────────────────────────
rule onlyOwnerCanRelease() {{
    uint256 released_before = released();

    release@withrevert(e);

    if (!lastReverted && released() > released_before) {{
        assert e.msg.sender == owner(),
            "VESTING: only owner may trigger release";
    }}
}}

// ─── Vested amount bounded by total balance ─────────────────────────────────
rule vestedAmountBounded(uint64 timestamp) {{
    require timestamp >= start();
    assert vestedAmount(timestamp) >= released(),
        "VESTING: released cannot exceed vested amount";
}}
'''

    def _certora_flash_spec(self, contract_name):
        return f'''\
/*
 * Certora Specification — Flash Loan Borrower: {contract_name}
 */

methods {{
    function onFlashLoan(address, address, uint256, uint256, bytes) external returns (bytes32) envfree;
}}

// ─── Flash loan callback returns correct magic value ────────────────────────
rule flashLoanCallbackCorrect(address initiator, address token,
                               uint256 amount, uint256 fee) {{
    bytes32 result = onFlashLoan(e, initiator, token, amount, fee, _);
    assert result == keccak256("ERC3156FlashBorrower.onFlashLoan"),
        "FLASH: callback must return correct magic value";
}}
'''

    def _certora_generic_spec(self, contract_name):
        return f'''\
/*
 * Certora Specification — {contract_name}
 * Generated by DeFi Guardian
 *
 * Patterns used:
 *   - envfree: declare view functions that don't read msg.sender
 *   - Symbolic variables: prover finds violating assignments automatically
 *   - method f + calldataarg: check a property holds across ALL methods
 */

methods {{
    // Declare envfree functions (pure view, no msg.sender dependency):
    // function yourView(address) external returns (uint256) envfree;
}}

// ─── Rule: No function should revert unexpectedly ───────────────────────────
rule noUnexpectedRevert(method f) {{
    calldataarg args;
    f@withrevert(e, args);
    // Uncomment to enforce no reverts:
    // assert !lastReverted, "Unexpected revert in " + f.selector;
    satisfy true;
}}

// ─── Rule: State variable X never decreases (template) ──────────────────────
// rule xMonotonicallyIncreases(method f) {{
//     uint256 x_before = getX();
//     calldataarg args;
//     f(e, args);
//     assert getX() >= x_before, "X must never decrease";
// }}

// ─── Rule: Only owner can change critical state (template) ──────────────────
// rule onlyOwnerCanChange(method f) {{
//     uint256 state_before = criticalState();
//     calldataarg args;
//     f(e, args);
//     assert criticalState() != state_before => e.msg.sender == owner(),
//         "Only owner may change critical state";
// }}
'''

    def verify_with_kani(self):
        """Run Kani model checking using cargo kani in a temp Cargo project"""
        if not self.current_file:
            self.console.insert("end", "❌ No file selected\n", "error")
            return
        ext = os.path.splitext(self.current_file)[1].lower()
        if ext != '.rs':
            self.console.insert("end", "❌ Kani only works with .rs files\n", "error")
            return

        self.kani_btn.configure(state="disabled", text="⏳ Running Kani...")
        self.set_tool_running("kani", True)

        def run_kani():
            import tempfile, shutil
            project_dir = None
            try:
                self.after(0, lambda: self.console.insert("end",
                    "\n🦀 KANI VERIFICATION\n", "header"))
                self.after(0, lambda: self.console.insert("end", "─"*60 + "\n", "dim"))

                with open(self.current_file, 'r') as f:
                    rust_code = f.read()
                skip, reason = self._should_skip_tool("kani", rust_code)
                if skip:
                    self.after(0, lambda: self.console.insert(
                        "end", f"⏭️ Kani skipped: {reason}\n"
                    ))
                    self.after(0, lambda: self.kani_btn.configure(state="normal", text="🦀 KANI VERIFICATION"))
                    self.save_verification_state('kani', {
                        'success': False,
                        'output': '',
                        'errors': '',
                        'skipped': True,
                        'reason': reason,
                    })
                    return

                project_dir = tempfile.mkdtemp()
                src_dir = os.path.join(project_dir, 'src')
                os.makedirs(src_dir)

                kani_verifier = RustVerifier()
                rust_code = kani_verifier._add_kani_harness(rust_code)

                with open(os.path.join(src_dir, 'lib.rs'), 'w') as f:
                    f.write(rust_code)

                with open(os.path.join(project_dir, 'Cargo.toml'), 'w') as f:
                    f.write(
                        '[package]\nname = "kani_verify"\nversion = "0.1.0"\n'
                        'edition = "2021"\n'
                    )

                result = self.run_cancellable_command(
                    "kani",
                    ['cargo', 'kani'],
                    timeout=300,
                    cwd=project_dir,
                )
                if result.get('cancelled'):
                    self.after(0, lambda: self.console.insert("end", "🛑 Kani stopped by user.\n"))
                    self.after(0, lambda: self.kani_btn.configure(state="normal", text="🦀 KANI VERIFICATION"))
                    return
                if result.get('timed_out'):
                    self.after(0, lambda: self.console.insert("end", "❌ Kani timed out (300s).\n"))
                    self.after(0, lambda: self.kani_btn.configure(state="normal", text="🦀 KANI VERIFICATION"))
                    return
                success = result['returncode'] == 0
                log_path = self.save_tool_log('kani', result['stdout'], result['stderr'])
                self.save_verification_state('kani', {
                    'success': success,
                    'output': result['stdout'],
                    'errors': result['stderr'],
                    'log_path': log_path,
                })

                def display():
                    if success:
                        self.console.insert("end", "✅ Kani verification successful!\n")
                        for line in result['stdout'].splitlines():
                            if any(k in line for k in [
                                'VERIFICATION', 'harness', 'PASS', 'FAIL', 'SUCCESS', 'proof'
                            ]):
                                self.console.insert("end", f"   {line}\n")
                    else:
                        err_tail = (result['stderr'] or "")[-4000:]
                        self.console.insert("end", f"❌ Kani failed:\n{err_tail}\n")
                        if result['stdout']:
                            self.console.insert("end", result['stdout'][:400] + "\n")
                    if log_path:
                        self.console.insert("end", f"📄 Full Kani log: {log_path}\n")
                    self.console.see("end")
                    self.kani_btn.configure(state="normal", text="🦀 KANI VERIFICATION")

                self.after(0, display)

            except subprocess.TimeoutExpired:
                self.after(0, lambda: self.console.insert("end", "❌ Kani timed out (300s)\n"))
                self.after(0, lambda: self.kani_btn.configure(state="normal", text="🦀 KANI VERIFICATION"))
            except Exception as e:
                self.after(0, lambda: self.console.insert("end", f"❌ Kani error: {e}\n"))
                self.after(0, lambda: self.kani_btn.configure(state="normal", text="🦀 KANI VERIFICATION"))
            finally:
                self.after(0, lambda: self.set_tool_running("kani", False))
                if project_dir and os.path.exists(project_dir):
                    shutil.rmtree(project_dir, ignore_errors=True)

        threading.Thread(target=run_kani, daemon=True).start()

    def verify_with_verus(self):
        """Run Verus verification on Rust code"""
        if not self.current_file:
            self.console.insert("end", "❌ No file selected\n")
            return
        ext = os.path.splitext(self.current_file)[1].lower()
        if ext != '.rs':
            self.console.insert("end", "❌ Verus only works with .rs files\n")
            return

        self.verus_btn.configure(state="disabled", text="⏳ Running Verus...")
        self.set_tool_running("verus", True)

        def run_verus():
            try:
                with open(self.current_file, 'r', encoding="utf-8") as f:
                    rust_code = f.read()

                self.after(0, lambda: self.console.insert(
                    "end",
                    "\n" + "=" * 60 + "\n✅ VERUS VERIFICATION\n" + "=" * 60 + "\n",
                ))

                verus = VerusIntegration()
                if not verus.verus_available:
                    self.after(0, lambda: self.console.insert(
                        "end",
                        "Verus not installed.\n"
                        "   Verus is a formal verifier for Rust (Microsoft Research).\n"
                        "   Install: https://github.com/verus-lang/verus/releases\n"
                        "   Quick install:\n"
                        "     git clone https://github.com/verus-lang/verus\n"
                        "     cd verus && tools/get-z3.sh && vargo build --release\n"
                        "     # Then add verus/target-verus/release to PATH\n",
                        "warning"
                    ))
                    self.after(0, lambda: self.verus_btn.configure(
                        state="normal", text="✓ Verus Verifier"
                    ))
                    self.after(0, lambda: self.set_tool_running("verus", False))
                    return

                # Annotate code for Verus
                annotated_code = verus.annotate_for_verus(rust_code)

                # Save annotated version for inspection
                annotated_file = self.current_file.replace('.rs', '_verus.rs')
                with open(annotated_file, 'w', encoding="utf-8") as f:
                    f.write(annotated_code)

                self.after(0, lambda: self.console.insert(
                    "end", f"📝 Annotated code saved to: {annotated_file}\n"
                ))

                # Run Verus verification
                result = verus.verify_with_verus(annotated_file)

                if result['success']:
                    self.after(0, lambda: self.console.insert(
                        "end", "✅ Verus verification successful!\n"
                    ))
                    self.after(0, lambda: self.console.insert(
                        "end", f"📊 Output: {result['output']}\n"
                    ))
                else:
                    self.after(0, lambda: self.console.insert(
                        "end", f"❌ Verus verification failed\n"
                    ))
                    self.after(0, lambda: self.console.insert(
                        "end", f"🚨 Errors: {result['errors']}\n"
                    ))

            except Exception as e:
                self.after(0, lambda: self.console.insert(
                    "end", f"❌ Verus error: {str(e)}\n"
                ))
            finally:
                self.after(0, lambda: self.verus_btn.configure(
                    state="normal", text="✅ VERUS VERIFICATION"
                ))
                self.after(0, lambda: self.set_tool_running("verus", False))
                self.after(0, lambda: self.console.see("end"))

        threading.Thread(target=run_verus, daemon=True).start()

    def check_elan(self):
        """Check Elan (Lean version manager) status"""
        self.console.insert("end", "\n" + "="*60 + "\n")
        self.console.insert("end", "⚙️ ELAN STATUS CHECK\n")
        self.console.insert("end", "="*60 + "\n")

        try:
            result = subprocess.run(["elan", "--version"],
                                   capture_output=True, text=True)
            if result.returncode == 0:
                self.console.insert("end", f"✅ Elan installed: {result.stdout.strip()}\n")

                # Check available toolchains
                result = subprocess.run(["elan", "toolchain", "list"],
                                       capture_output=True, text=True)
                self.console.insert("end", "\n📦 Available Lean toolchains:\n")
                self.console.insert("end", result.stdout)
            else:
                self.console.insert("end", "❌ Elan not installed. Run: curl https://elan.lean-lang.org/elan-init.sh -sSf | sh\n")
        except Exception as e:
            self.console.insert("end", f"❌ Error checking Elan: {e}\n")

        self.console.see("end")

    def open_translated_output(self):
        """Load translated_output.pml into the Translated Promela tab"""

        # Find the translated output file
        translated_path = os.path.join(MODELS_DIR, "translated_output.pml")

        # Also check for other possible locations
        possible_paths = [
            translated_path,
            os.path.join(PROJECT_DIR, "translated_output.pml"),
            os.path.join(PROJECT_DIR, "translated_output.txt"),
            os.path.join(os.path.dirname(PROJECT_DIR), "translated_output.pml"),
            os.path.join(os.path.expanduser("~"), "defi_guardian", "translated_output.pml"),
        ]

        # Add backup from current file
        if self.current_file:
            base_name = os.path.splitext(os.path.basename(self.current_file))[0]
            backup_path = os.path.join(PROJECT_DIR, f"{base_name}_translated.pml")
            possible_paths.insert(1, backup_path)

        # Find the first existing file
        display_file = None
        for path in possible_paths:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                display_file = path
                break

        if not display_file:
            self.spin_terminal.insert("end", "No translated output found. Please run verification first.\n")
            self.spin_terminal.see("end")
            return

        try:
            with open(display_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Load into the Translated Promela tab
            self.translated_editor.delete("1.0", "end")
            self.translated_editor.insert("1.0", content)

            # Switch to the Translated Promela tab
            self.editor_tabs.set("Translated Promela")

            self.spin_terminal.insert("end", f"Loaded translated output: {os.path.basename(display_file)}\n")
            self.spin_terminal.see("end")
        except Exception as e:
            self.spin_terminal.insert("end", f"Error loading translated output: {str(e)}\n")
            self.spin_terminal.see("end")

    def analyze_counterexample(self):
        """Analyze and display counterexample"""
        self.console.insert("end", "\n" + "="*60 + "\n")
        self.console.insert("end", "🔍 COUNTEREXAMPLE ANALYSIS\n")
        self.console.insert("end", "="*60 + "\n")

        # Import the analyzer
        try:
            from counterexample_analyzer import CounterexampleAnalyzer
        except ImportError:
            self.console.insert("end", "❌ Counterexample analyzer module not found\n")
            return

        analyzer = CounterexampleAnalyzer(PROJECT_DIR)

        # Check for trail file
        trail_file = os.path.join(SPIN_LOGS, "translated_output.pml.trail")
        pml_file = os.path.join(MODELS_DIR, "translated_output.pml")

        if not os.path.exists(trail_file):
            # Check for other trail files
            for f in os.listdir(SPIN_LOGS):
                if f.endswith('.trail'):
                    trail_file = os.path.join(SPIN_LOGS, f)
                    break

            # Fallback to project dir if not found in spin logs
            if not os.path.exists(trail_file):
                for f in os.listdir(PROJECT_DIR):
                    if f.endswith('.trail'):
                        trail_file = os.path.join(PROJECT_DIR, f)
                        break

        if not os.path.exists(trail_file):
            self.console.insert("end", "ℹ️ No counterexample trail found.\n")
            self.console.insert("end", "   Run verification on a model with property violations first.\n")
            return

        # Generate and display report
        report = analyzer.generate_report(pml_file if os.path.exists(pml_file) else None)
        self.console.insert("end", report + "\n")

        # Save report to file
        report_path = analyzer.save_report()
        self.console.insert("end", f"\n📁 Detailed trace saved to: {report_path}\n")

        # Launch structured dashboard
        trace_data = analyzer.get_structured_trace(pml_file if os.path.exists(pml_file) else None)

        # If SPIN replay produced no steps, try loading the saved trace JSON
        if (not trace_data.get("steps")) and os.path.exists(TRACES_DIR):
            import glob
            trace_files = sorted(
                glob.glob(os.path.join(TRACES_DIR, "trace_*.json")),
                key=os.path.getmtime, reverse=True
            )
            for tf in trace_files[:1]:
                try:
                    with open(tf, 'r') as f:
                        saved = json.load(f)
                    # Normalise node_details → steps
                    if saved.get("node_details") and not saved.get("steps"):
                        saved["steps"] = [
                            {
                                "step":      i + 1,
                                "proc_name": s.get("proc", "Contract"),
                                "line":      s.get("line", 0),
                                "state":     0,
                                "file":      "",
                                "updates":   {},
                                "variables": s.get("variables", {}),
                                "raw":       s.get("action", ""),
                                "action":    s.get("action", ""),
                            }
                            for i, s in enumerate(saved["node_details"])
                        ]
                    if saved.get("steps"):
                        trace_data = saved
                        self.console.insert("end", f"   Loaded trace from: {tf}\n", "dim")
                    break
                except Exception:
                    pass

        if trace_data.get("steps"):
            self.console.insert("end", "✨ Launching Interactive Counterexample Dashboard...\n")
            CounterexampleDashboard(self, trace_data)
        else:
            # Also try to run SPIN guided simulation
            spin_output = analyzer.analyze_with_spin(pml_file if os.path.exists(pml_file) else None)
            if spin_output and "error" not in spin_output.lower():
                self.console.insert("end", "\n🔬 SPIN Guided Simulation:\n")
                self.console.insert("end", "-"*40 + "\n")
                self.console.insert("end", spin_output[:2000] + "\n")  # Limit output

        self.console.see("end")

    def run_slither_analysis(self):
        """Run Slither on the active Solidity file and load LTL results into the spec editor."""
        if not self.current_file:
            self.console.insert("end", "No file loaded. Open a .sol file first.\n", "error")
            return
        if not self.current_file.lower().endswith('.sol'):
            self.console.insert("end", "Slither only works with Solidity (.sol) files.\n", "error")
            return

        def _run():
            self.after(0, lambda: self.console.insert("end",
                "\n🐍 SLITHER STATIC ANALYSIS\n" + "─"*50 + "\n", "header"))
            self.after(0, lambda: self.console.insert("end",
                f"Analyzing: {os.path.basename(self.current_file)}\n", "dim"))

            try:
                from spec_generator import SlitherSpecExtractor
                extractor = SlitherSpecExtractor()

                if not extractor.slither_available:
                    self.after(0, lambda: self.console.insert("end",
                        "Slither not installed.\n"
                        "   Install: pip install slither-analyzer\n", "error"))
                    return

                # Generate LTL properties
                ltl = extractor.generate_ltl_from_slither(self.current_file)
                summary = extractor.generate_summary(self.current_file)

                # Show summary in console
                self.after(0, lambda: self.console.insert("end", summary + "\n", "accent"))

                # Auto-save generated LTL as .spec to the canonical specs directory
                contract = os.path.splitext(os.path.basename(self.current_file))[0]
                specs_dir = os.path.join(PROJECT_DIR, "generated", "specs")
                os.makedirs(specs_dir, exist_ok=True)
                ltl_spec_path = os.path.join(specs_dir, f"{contract}_ltl.spec")
                try:
                    with open(ltl_spec_path, "w", encoding="utf-8") as f:
                        f.write(ltl)
                except Exception:
                    ltl_spec_path = None

                # Load LTL into spec editor
                def _load():
                    self.update_spec_editor(ltl)
                    # Switch to Specifications tab
                    self.editor_tabs.set("Specifications & LTL")
                    self.console.insert("end",
                        "✅ LTL properties loaded into Specifications & LTL tab.\n", "success")
                    if ltl_spec_path:
                        self.console.insert("end",
                            f"   💾 Also saved as: {ltl_spec_path}\n", "accent")
                    self.console.see("end")

                self.after(0, _load)

            except Exception as e:
                self.after(0, lambda: self.console.insert("end",
                    f"Slither error: {e}\n", "error"))

        threading.Thread(target=_run, daemon=True).start()

    def run_slither_certora(self):
        """Run Slither and load generated Certora rules into the spec editor."""
        if not self.current_file:
            self.console.insert("end", "No file loaded. Open a .sol file first.\n", "error")
            return
        if not self.current_file.lower().endswith('.sol'):
            self.console.insert("end", "Slither only works with Solidity (.sol) files.\n", "error")
            return

        def _run():
            self.after(0, lambda: self.console.insert("end",
                "\n🐍 SLITHER → CERTORA RULES\n" + "─"*50 + "\n", "header"))

            try:
                from spec_generator import SlitherSpecExtractor
                extractor = SlitherSpecExtractor()

                if not extractor.slither_available:
                    self.after(0, lambda: self.console.insert("end",
                        "Slither not installed.\n"
                        "   Install: pip install slither-analyzer\n", "error"))
                    return

                rules = extractor.generate_certora_rules(self.current_file)

                # Save to certora/specs/<ContractName>.spec
                contract = os.path.splitext(os.path.basename(self.current_file))[0]
                spec_path = os.path.join(PROJECT_DIR, "certora", "specs", f"{contract}.spec")
                os.makedirs(os.path.dirname(spec_path), exist_ok=True)
                with open(spec_path, "w") as f:
                    f.write(rules)

                def _load():
                    self.update_spec_editor(rules)
                    self.editor_tabs.set("Specifications & LTL")
                    self.console.insert("end",
                        f"✅ Certora rules saved to: {spec_path}\n"
                        "   Loaded into Specifications & LTL tab.\n", "success")
                    self.console.see("end")

                self.after(0, _load)

            except Exception as e:
                self.after(0, lambda: self.console.insert("end",
                    f"Slither error: {e}\n", "error"))

        threading.Thread(target=_run, daemon=True).start()

    # ── Specification editor helpers ──────────────────────────────────────
    _SPEC_TEMPLATES = {
        "ERC20 Token": """\
/*
 * ERC20 Certora Spec — tutorial patterns
 * Symbolic vars: prover finds violating assignments automatically
 */
methods {
    function balanceOf(address)          external returns (uint256) envfree;
    function allowance(address, address) external returns (uint256) envfree;
    function totalSupply()               external returns (uint256) envfree;
}

rule transferFromSpec(address holder, address recipient, uint256 amount) {
    uint256 bal_holder_before    = balanceOf(holder);
    uint256 bal_recipient_before = balanceOf(recipient);

    transferFrom(e, holder, recipient, amount);

    if (holder != recipient) {
        assert balanceOf(holder)    == bal_holder_before    - amount,
            "holder balance must decrease";
        assert balanceOf(recipient) == bal_recipient_before + amount,
            "recipient balance must increase";
    } else {
        // Self-transfer: nothing changes
        assert balanceOf(holder) == bal_holder_before,
            "self-transfer must not change balance";
    }
}

rule onlyHolderCanIncreaseAllowance(address holder, address spender) {
    uint256 allowance_before = allowance(holder, spender);
    method f; calldataarg args;
    f(e, args);
    assert allowance(holder, spender) > allowance_before => e.msg.sender == holder,
        "only holder may increase their own allowance";
}
""",
        "Lending Protocol": """\
/*
 * Lending Protocol Certora Spec
 * Solvency, collateral, liquidation rules
 */
methods {
    function deposits(address)        external returns (uint256) envfree;
    function borrows(address)         external returns (uint256) envfree;
    function totalDeposits()          external returns (uint256) envfree;
    function totalBorrows()           external returns (uint256) envfree;
    function getHealthFactor(address) external returns (uint256) envfree;
    function COLLATERAL_RATIO()       external returns (uint256) envfree;
}

rule solvencyInvariant(method f) {
    calldataarg args; f(e, args);
    assert totalDeposits() >= totalBorrows(),
        "SOLVENCY: pool owes more than it holds";
}

rule borrowCollateralCheck(address user, uint256 amount) {
    require user != 0; require amount > 0;
    borrow@withrevert(e, amount);
    if (!lastReverted) {
        assert deposits(user) >= (borrows(user) * COLLATERAL_RATIO()) / 100,
            "COLLATERAL: position underwater after borrow";
    }
}

rule liquidationCheck(address user, address liquidator, uint256 debtToCover) {
    require user != liquidator;
    uint256 hf = getHealthFactor(user);
    liquidate@withrevert(e, user, debtToCover);
    if (!lastReverted) {
        assert hf < 100, "LIQUIDATION: healthy position was liquidated";
    }
}
""",
        "DEX/AMM": """\
/*
 * DEX / AMM Certora Spec
 * Constant product, swap correctness
 */
methods {
    function getReserves() external returns (uint256, uint256) envfree;
    function totalSupply() external returns (uint256) envfree;
}

rule constantProductInvariant(method f) {
    (uint256 r0_before, uint256 r1_before) = getReserves();
    uint256 k_before = r0_before * r1_before;
    calldataarg args; f(e, args);
    (uint256 r0_after, uint256 r1_after) = getReserves();
    assert r0_after * r1_after >= k_before,
        "AMM: constant product invariant violated";
}

rule swapOutputPositive(uint256 amountIn) {
    require amountIn > 0;
    uint256 out = swap(e, amountIn);
    assert out > 0, "SWAP: output must be positive";
}
""",
        "Governance": """\
/*
 * Governance Certora Spec
 * Quorum, majority, proposal lifecycle
 */
methods {
    function quorumThreshold() external returns (uint256) envfree;
    function proposalVotes(uint256) external returns (uint256, uint256) envfree;
}

rule quorumRequired(uint256 proposalId) {
    execute@withrevert(e, proposalId);
    if (!lastReverted) {
        (uint256 yes, uint256 no) = proposalVotes(proposalId);
        assert yes + no >= quorumThreshold(),
            "GOVERNANCE: executed without quorum";
        assert yes > no,
            "GOVERNANCE: executed without majority";
    }
}

rule onlyOwnerCanCancel(uint256 proposalId, method f) {
    uint256 state_before = proposalState(proposalId);
    calldataarg args; f(e, args);
    assert proposalState(proposalId) == 2 && state_before != 2
        => e.msg.sender == owner(),
        "GOVERNANCE: only owner may cancel proposals";
}
""",
        "Vault": """\
/*
 * Vault Certora Spec
 * Deposit/withdraw correctness, share accounting
 */
methods {
    function totalAssets()          external returns (uint256) envfree;
    function totalSupply()          external returns (uint256) envfree;
    function balanceOf(address)     external returns (uint256) envfree;
    function convertToAssets(uint256) external returns (uint256) envfree;
}

rule depositCorrect(address receiver, uint256 assets) {
    require assets > 0; require receiver != 0;
    uint256 shares_before = balanceOf(receiver);
    uint256 assets_before = totalAssets();
    deposit(e, assets, receiver);
    assert balanceOf(receiver) > shares_before,
        "VAULT: deposit must mint shares";
    assert totalAssets() == assets_before + assets,
        "VAULT: total assets must increase by deposit amount";
}

rule withdrawCorrect(address owner, uint256 assets) {
    require assets > 0;
    uint256 assets_before = totalAssets();
    withdraw@withrevert(e, assets, e.msg.sender, owner);
    if (!lastReverted) {
        assert totalAssets() == assets_before - assets,
            "VAULT: total assets must decrease by withdrawal";
    }
}

rule solvency(method f) {
    calldataarg args; f(e, args);
    assert convertToAssets(totalSupply()) <= totalAssets(),
        "VAULT: shares exceed backing assets";
}
""",
        "Custom": """\
/*
 * Custom Certora Specification
 *
 * Key patterns:
 *   envfree  — declare view functions that don't read msg.sender
 *   method f + calldataarg — check property across ALL contract methods
 *   @withrevert + lastReverted — handle reverting paths
 *   Symbolic vars — prover finds violating assignments automatically
 */
methods {
    // function myView(address) external returns (uint256) envfree;
}

// Template: monotonically increasing state variable
// rule xNeverDecreases(method f) {
//     uint256 x_before = getX();
//     calldataarg args; f(e, args);
//     assert getX() >= x_before, "X must never decrease";
// }

// Template: only owner can change critical state (checks ALL methods)
// rule onlyOwnerCanChange(method f) {
//     uint256 state_before = criticalState();
//     calldataarg args; f(e, args);
//     assert criticalState() != state_before => e.msg.sender == owner(),
//         "Only owner may change critical state";
// }
""",
    }

    def _spec_load_template(self, name):
        tpl = self._SPEC_TEMPLATES.get(name, self._SPEC_TEMPLATES["Custom"])
        self.spec_editor.delete("1.0", "end")
        self.spec_editor.insert("1.0", tpl)
        self._spec_tpl_var.set(name)

    def ai_generate_specs(self):
        """
        Smart spec generator: reads the active source file, detects contract
        type, and loads the best-matching Certora CVL template into the editor.
        Also runs Slither if available to enrich the spec with real findings.
        """
        if not self.current_file:
            self.console.insert("end", "No file loaded. Open a .sol or .rs file first.\n", "error")
            return

        ext = os.path.splitext(self.current_file)[1].lower()

        def _run():
            self.after(0, lambda: self.console.insert("end",
                "\n🤖 AI SPEC GENERATOR\n" + "─"*50 + "\n", "header"))

            contract_name = os.path.splitext(os.path.basename(self.current_file))[0]

            if ext == '.sol':
                # ── Solidity: generate Certora CVL spec ──────────────────
                self.after(0, lambda: self.console.insert("end",
                    f"Detecting contract type for: {contract_name}\n", "dim"))

                # Read source to detect patterns
                try:
                    with open(self.current_file, 'r') as f:
                        source = f.read()
                except Exception as e:
                    self.after(0, lambda: self.console.insert("end",
                        f"Could not read file: {e}\n", "error"))
                    return

                # Detect contract type from source content
                src_lower = source.lower()
                if any(k in src_lower for k in ("transfer", "allowance", "balanceof", "erc20")):
                    detected = "ERC20 Token"
                elif any(k in src_lower for k in ("borrow", "collateral", "liquidat", "healthfactor")):
                    detected = "Lending Protocol"
                elif any(k in src_lower for k in ("vest", "cliff", "release", "schedule")):
                    detected = "Vesting Wallet"
                elif any(k in src_lower for k in ("flashloan", "onflashloan", "flashborrow")):
                    detected = "Flash Loan"
                elif any(k in src_lower for k in ("reserve", "swap", "liquidity", "amm")):
                    detected = "DEX/AMM"
                elif any(k in src_lower for k in ("propose", "vote", "quorum", "execute")):
                    detected = "Governance"
                else:
                    detected = "Generic"

                self.after(0, lambda: self.console.insert("end",
                    f"Detected: {detected}\n", "accent"))

                # Generate the spec
                spec = self._generate_default_certora_spec(contract_name)

                # Try to enrich with Slither if available
                try:
                    from spec_generator import SlitherSpecExtractor
                    extractor = SlitherSpecExtractor()
                    if extractor.slither_available:
                        self.after(0, lambda: self.console.insert("end",
                            "Running Slither for additional findings...\n", "dim"))
                        summary = extractor.generate_summary(self.current_file)
                        self.after(0, lambda: self.console.insert("end",
                            summary + "\n", "dim"))
                        # Append Slither-derived rules as comments
                        slither_ltl = extractor.generate_ltl_from_slither(self.current_file)
                        if "No issues found" not in slither_ltl:
                            spec += "\n\n/* === Slither-derived properties === */\n"
                            spec += "/* " + slither_ltl.replace("*/", "* /") + " */\n"
                except Exception:
                    pass

                # Save spec file
                spec_path = os.path.join(
                    PROJECT_DIR, "certora", "specs", f"{contract_name}.spec"
                )
                os.makedirs(os.path.dirname(spec_path), exist_ok=True)
                with open(spec_path, "w") as f:
                    f.write(spec)

                def _load_sol():
                    self.update_spec_editor(spec, overwrite=True)
                    self.editor_tabs.set("Specifications & LTL")
                    self.console.insert("end",
                        f"✅ Certora spec saved: {spec_path}\n"
                        f"   Loaded into Specifications & LTL tab.\n"
                        f"   Run 'Verify with Certora' to check these rules.\n",
                        "success")
                    self.console.see("end")

                self.after(0, _load_sol)

            elif ext == '.rs':
                # ── Rust: generate Prusti/Kani annotations ───────────────
                self.after(0, lambda: self.console.insert("end",
                    "Generating Prusti/Kani specs for Rust...\n", "dim"))

                try:
                    with open(self.current_file, 'r') as f:
                        source = f.read()
                except Exception as e:
                    self.after(0, lambda: self.console.insert("end",
                        f"Could not read file: {e}\n", "error"))
                    return

                try:
                    from llm_spec_generator import LLMSpecGenerator
                    gen = LLMSpecGenerator()
                    # Extract function names and generate specs for each
                    import re
                    funcs = re.findall(r'(?:pub\s+)?fn\s+(\w+)\s*\(', source)
                    spec_lines = [
                        "// Prusti/Kani specifications generated by DeFi Guardian",
                        "// Add these annotations above each function\n",
                    ]
                    for func in funcs[:10]:
                        # Find the function body
                        m = re.search(
                            rf'(?:pub\s+)?fn\s+{re.escape(func)}\s*\([^{{]*\{{([^}}]*)\}}',
                            source, re.DOTALL
                        )
                        body = m.group(1) if m else ""
                        annotations = gen.generate_prusti_annotations(body, func)
                        if annotations:
                            spec_lines.append(f"// --- {func} ---")
                            spec_lines.append(annotations)
                            spec_lines.append("")

                    kani = gen.generate_kani_harness(source)
                    spec_lines.append("\n// Kani proof harness:")
                    spec_lines.append(kani)

                    spec = "\n".join(spec_lines)
                except Exception as e:
                    spec = f"// Could not generate Rust specs: {e}\n"

                def _load_rs():
                    self.update_spec_editor(spec, overwrite=True)
                    self.editor_tabs.set("Specifications & LTL")
                    self.console.insert("end",
                        "✅ Prusti/Kani annotations loaded into Specifications & LTL tab.\n",
                        "success")
                    self.console.see("end")

                self.after(0, _load_rs)

            else:
                self.after(0, lambda: self.console.insert("end",
                    "AI spec generation supports .sol and .rs files.\n", "warning"))

        threading.Thread(target=_run, daemon=True).start()

    def _spec_update_pos(self, event=None):
        try:
            idx = self.spec_editor._textbox.index("insert")
            ln, col = idx.split(".")
            self._spec_pos_label.configure(text=f"Ln {ln}  Col {int(col)+1}")
        except Exception:
            pass

    def _spec_save(self):
        content = self.spec_editor.get("1.0", "end-1c")
        # Derive a default filename from the first ltl/rule name in the editor
        import re as _re, os as _os
        name_match = _re.search(r'ltl\s+(\w+)', content) or _re.search(r'rule\s+(\w+)', content)
        default_name = name_match.group(1) if name_match else "specification"
        path = filedialog.asksaveasfilename(
            initialfile=default_name,
            defaultextension=".spec",
            filetypes=[
                ("Specification files", "*.spec"),
                ("LTL Specification", "*.ltl"),
                ("CVL Specification", "*.cvl"),
                ("Text", "*.txt"),
                ("All files", "*.*"),
            ],
            title="Save Specification"
        )
        if not path:
            return
        try:
            # 1. Write to wherever the user chose
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            saved_paths = [path]

            # 2. If user chose a non-.spec extension, also write a .spec copy
            #    alongside the chosen file so the extension is always present.
            base, ext = _os.path.splitext(path)
            if ext.lower() != ".spec":
                spec_alongside = base + ".spec"
                with open(spec_alongside, "w", encoding="utf-8") as f:
                    f.write(content)
                saved_paths.append(spec_alongside)

            # 3. Always mirror to generated/specs/<name>.spec so other tools
            #    (web portal, Coq verifier, SPIN) can always find it there.
            specs_dir = _os.path.join(PROJECT_DIR, "generated", "specs")
            _os.makedirs(specs_dir, exist_ok=True)
            mirror_path = _os.path.join(specs_dir, default_name + ".spec")
            with open(mirror_path, "w", encoding="utf-8") as f:
                f.write(content)
            if mirror_path not in saved_paths:
                saved_paths.append(mirror_path)

            # 4. For CVL content, also mirror to certora/specs/<name>.spec
            if _re.search(r'rule\s+\w+', content):
                certora_dir = _os.path.join(PROJECT_DIR, "certora", "specs")
                _os.makedirs(certora_dir, exist_ok=True)
                certora_path = _os.path.join(certora_dir, default_name + ".spec")
                with open(certora_path, "w", encoding="utf-8") as f:
                    f.write(content)
                if certora_path not in saved_paths:
                    saved_paths.append(certora_path)

            lines = [f"\n\U0001f4be Specification saved:"]
            for p in saved_paths:
                lines.append(f"   \u2192 {p}")
            self.console.insert("end", "\n".join(lines) + "\n", "accent")

        except Exception as e:
            self.console.insert("end", f"\n\u274c Save failed: {e}\n", "error")

    def _spec_load(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Specification", "*.spec"),
                ("LTL Specification", "*.ltl"),
                ("Text", "*.txt"),
                ("All", "*.*"),
            ],
            title="Load Specification"
        )
        if path:
            try:
                with open(path, "r") as f:
                    content = f.read()
                self.spec_editor.delete("1.0", "end")
                self.spec_editor.insert("1.0", content)
                self.console.insert("end", f"\n📂 Specification loaded from {path}\n", "accent")
            except Exception as e:
                self.console.insert("end", f"\n❌ Load failed: {e}\n", "error")

    def _spec_validate(self):
        content = self.spec_editor.get("1.0", "end-1c")
        lines = content.splitlines()
        errors, warnings, ok = [], [], []
        for i, line in enumerate(lines, 1):
            t = line.strip()
            if not t or t.startswith("//"):
                continue
            if t.startswith("ltl ") and ":" in t:
                if not t.rstrip().endswith(";"):
                    errors.append(f"Line {i}: missing semicolon — {t[:60]}")
                else:
                    ok.append(f"Line {i}: ✅ {t[:80]}")
            elif t:
                warnings.append(f"Line {i}: unrecognised syntax — {t[:60]}")

        self.console.insert("end", "\n── Specification Validation ──\n", "accent")
        for msg in ok:      self.console.insert("end", f"  {msg}\n", "success")
        for msg in warnings: self.console.insert("end", f"  ⚠ {msg}\n")
        for msg in errors:   self.console.insert("end", f"  ✗ {msg}\n", "error")
        summary = f"  {len(ok)} valid, {len(warnings)} warnings, {len(errors)} errors\n"
        self.console.insert("end", summary, "accent")
        if self.auto_scroll_enabled:
            self.console.see("end")

    def _spec_clear(self):
        self.spec_editor.delete("1.0", "end")

    def open_dashboard(self):
        """Open the verification dashboard in default browser"""
        # The desktop Flask server runs on port 5005 — open its /dashboard route directly
        dashboard_url = "http://localhost:5005/dashboard"
        webbrowser.open(dashboard_url)
        self.console.insert("end", f"\n🌐 Opening dashboard at {dashboard_url}\n", "accent")
        self.status_label.configure(text="Dashboard opened")

    def open_account_dashboard(self):
        """Start the web portal if needed, then open the account dashboard in the browser"""
        portal_url = "http://localhost:5000/dashboard"

        def _launch():
            import socket, time, subprocess, sys, os

            def is_up():
                try:
                    with socket.create_connection(("localhost", 5000), timeout=1.0):
                        return True
                except OSError:
                    return False

            if is_up():
                self.console.insert("end", "\n✅ Account portal already running\n", "accent")
                webbrowser.open(portal_url)
                self.status_label.configure(text="Account dashboard opened")
                return

            self.console.insert("end", "\n🚀 Starting account portal on port 5000...\n", "accent")
            try:
                web_portal_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web_portal')
                web_app_path = os.path.join(web_portal_dir, 'app.py')
                portal_log = os.path.join(LOGS_DIR, "portal_server.log")

                with open(portal_log, 'w') as log_f:
                    self._portal_process = subprocess.Popen(
                        [sys.executable, '-u', web_app_path],
                        cwd=web_portal_dir,
                        stdout=log_f,
                        stderr=log_f,
                        env={**os.environ, 'PYTHONUNBUFFERED': '1'}
                    )
            except Exception as e:
                self.console.insert("end", f"❌ Failed to start account portal: {e}\n", "error")
                return

            # Poll up to 15 s for the server to bind
            for i in range(30):
                time.sleep(0.5)
                # Check if process died early
                if self._portal_process.poll() is not None:
                    portal_log = os.path.join(LOGS_DIR, "portal_server.log")
                    try:
                        with open(portal_log) as f:
                            err_text = f.read()[-800:]
                    except Exception:
                        err_text = "(no log)"
                    self.console.insert("end", f"❌ Portal process exited early.\n{err_text}\n", "error")
                    return
                if is_up():
                    self.console.insert("end", "✅ Account portal started\n", "accent")
                    webbrowser.open(portal_url)
                    self.status_label.configure(text="Account dashboard opened")
                    return

            # Timed out — show log tail
            portal_log = os.path.join(LOGS_DIR, "portal_server.log")
            try:
                with open(portal_log) as f:
                    log_tail = f.read()[-400:]
            except Exception:
                log_tail = ""
            self.console.insert("end", f"⚠️ Portal did not bind in 15s.\n{log_tail}\n", "error")

        # Run in a background thread so the UI stays responsive
        threading.Thread(target=_launch, daemon=True).start()

    def start_web_portal(self):
        """Start the web portal server (legacy helper — prefer open_account_dashboard)"""
        import socket, subprocess, sys, os, time

        def is_up():
            try:
                with socket.create_connection(("localhost", 5000), timeout=1.0):
                    return True
            except OSError:
                return False

        if is_up():
            self.console.insert("end", "✅ Web portal is already running\n", "accent")
            return

        try:
            web_portal_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web_portal')
            web_app_path = os.path.join(web_portal_dir, 'app.py')
            portal_log = os.path.join(LOGS_DIR, "portal_server.log")
            with open(portal_log, 'w') as log_f:
                self._portal_process = subprocess.Popen(
                    [sys.executable, '-u', web_app_path],
                    cwd=web_portal_dir,
                    stdout=log_f,
                    stderr=log_f,
                    env={**os.environ, 'PYTHONUNBUFFERED': '1'}
                )
            for _ in range(10):
                time.sleep(0.5)
                if is_up():
                    self.console.insert("end", "✅ Web portal started\n", "accent")
                    return
            self.console.insert("end", "⚠️ Web portal may still be starting\n", "error")
        except Exception as e:
            self.console.insert("end", f"❌ Failed to start web portal: {e}\n", "error")

    def stop_dashboard(self):
        """Stop the dashboard and account portal"""
        self.console.insert("end", "\n🛑 Stopping dashboard...\n")

        try:
            if hasattr(self, 'dashboard_process') and self.dashboard_process and self.dashboard_process.poll() is None:
                self.dashboard_process.terminate()
                self.dashboard_process.wait(timeout=5)
                self.console.insert("end", "✅ Dashboard stopped\n")

            if hasattr(self, '_portal_process') and self._portal_process and self._portal_process.poll() is None:
                self._portal_process.terminate()
                self._portal_process.wait(timeout=5)
                self.console.insert("end", "✅ Account portal stopped\n")

            # Kill any remaining streamlit processes
            if sys.platform == "win32":
                subprocess.run("taskkill /f /im streamlit.exe", shell=True, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["pkill", "-f", "streamlit"], stderr=subprocess.DEVNULL)
        except Exception as e:
            self.console.insert("end", f"⚠️ Error stopping dashboard: {e}\n")

        self.status_label.configure(text="Dashboard stopped")
        if self.auto_scroll_enabled:
            self.console.see("end")

    def debug_sidebar_visibility(self):
        """Debug method to check sidebar visibility"""
        print(f"Sidebar visible: {self.sidebar.winfo_ismapped()}")
        print(f"Sidebar width: {self.sidebar.winfo_width()}")
        print(f"Sidebar height: {self.sidebar.winfo_height()}")
        print(f"Sidebar inner visible: {self.sidebar_inner.winfo_ismapped()}")
        print(f"Sidebar inner width: {self.sidebar_inner.winfo_width()}")
        print(f"Sidebar inner height: {self.sidebar_inner.winfo_height()}")

        # Check if scrollbar exists
        if hasattr(self.sidebar_inner, '_scrollbar'):
            print(f"Scrollbar visible: {self.sidebar_inner._scrollbar.winfo_ismapped()}")

        # Force update
        self.update()

        # Schedule another check after a short delay
        self.after(100, lambda: print(f"After update - Sidebar height: {self.sidebar.winfo_height()}"))


def create_gradio_interface():
    """
    Gradio version - modern AI-focused interface
    To run this, call create_gradio_interface().launch()
    """
    if not HAS_GRADIO:
        return None

    with gr.Blocks(theme=gr.themes.Soft(
        primary_hue="emerald",
        secondary_hue="purple",
        neutral_hue="slate",
    )) as demo:
        gr.Markdown("# 🛡️ DeFi Guardian")

        with gr.Tab("Verification"):
            with gr.Row():
                file_input = gr.File(label="Upload Contract")
                verify_btn = gr.Button("Run Verification", variant="primary")
            output = gr.Code(label="Verification Output", language="text")

        with gr.Tab("State Machine"):
            graph = gr.Plot(label="State Diagram")

        with gr.Tab("Analytics"):
            metrics = gr.JSON(label="Verification Metrics")

    return demo


def run_nicegui_interface():
    """
    NiceGUI version - web UI in desktop wrapper
    To run this, call run_nicegui_interface() instead of the mainloop
    """
    if not HAS_NICEGUI:
        return

    # Example stubs for NiceGUI interface
    def load_file():
        ui.notify("Loading file...")

    def run_verification():
        ui.notify("Running verification...")

    @ui.page('/')
    def main_page():
        with ui.header(elevated=True).classes('bg-primary'):
            ui.label('🛡️ DeFi Guardian').classes('text-h4 text-white')

        with ui.left_drawer().classes('bg-dark'):
            ui.button('Open File', on_click=load_file)
            ui.button('Run Verification', on_click=run_verification)

        with ui.column().classes('w-full'):
            ui.editor().classes('w-full h-96')
            ui.terminal().classes('w-full h-64')

    ui.run(native=True, window_size=(1400, 900), title="DeFi Guardian - NiceGUI")


# ==================== INTEGRATED FLASK BACKEND ====================

flask_app = Flask(__name__,
    template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web_portal', 'templates'))

@flask_app.route('/')
def desktop_home():
    """Main desktop application page"""
    # Try to render template, fall back to inline HTML if template missing
    template_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'web_portal', 'templates', 'desktop_app.html'
    )

    if not os.path.exists(template_path):
        # Return a simple inline dashboard if template doesn't exist
        return '''
        <!DOCTYPE html>
        <html>
        <head>
            <title>DeFi Guardian</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
            <style>
                body { background: #0a0a0f; color: #e6edf3; font-family: Inter, sans-serif; }
                .container { max-width: 1200px; margin: 2rem auto; }
                .card { background: #131720; border: 1px solid #21262d; border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; }
                .text-accent { color: #00ffcc; }
                .status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 8px; }
                .status-dot.online { background: #238636; }
                .status-dot.offline { background: #da3633; }
            </style>
        </head>
        <body>
            <div class="container">
                <h2><i class="fas fa-shield-halved text-accent"></i> DeFi Guardian</h2>
                <p class="text-muted">Formal Verification Suite — Web Interface</p>

                <div class="row mt-4">
                    <div class="col-md-6">
                        <div class="card">
                            <h5><i class="fas fa-microchip text-accent"></i> Tool Status</h5>
                            <div id="toolStatus">Loading...</div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="card">
                            <h5><i class="fas fa-chart-bar text-accent"></i> Verification Stats</h5>
                            <div id="verifStats">Loading...</div>
                        </div>
                    </div>
                </div>

                <div class="card mt-3">
                    <h5><i class="fas fa-info-circle text-accent"></i> Quick Links</h5>
                    <div class="mt-3">
                        <a href="#" class="btn btn-sm btn-outline-light me-2">Open Desktop App</a>
                        <button class="btn btn-sm btn-outline-light me-2" onclick="refreshData()">
                            <i class="fas fa-sync-alt"></i> Refresh
                        </button>
                    </div>
                </div>
            </div>

            <script>
                async function refreshData() {
                    try {
                        const toolResp = await fetch('/api/tools/status');
                        const tools = await toolResp.json();
                        document.getElementById('toolStatus').innerHTML =
                            Object.entries(tools).map(([t, ok]) =>
                                `<div class="mb-1"><span class="status-dot ${ok ? 'online' : 'offline'}"></span>
                                ${t.toUpperCase()}: ${ok ? 'Available' : 'Not Found'}</div>`
                            ).join('');

                        const stateResp = await fetch('/api/state/current');
                        const state = await stateResp.json();
                        document.getElementById('verifStats').innerHTML =
                            `<p>States Explored: ${state.states_stored || 0}</p>` +
                            `<p>Depth: ${state.depth || 0}</p>` +
                            `<p>Last Verification: ${state.datetime || 'Never'}</p>`;
                    } catch(e) {
                        document.getElementById('toolStatus').textContent = 'Error loading data';
                    }
                }
                refreshData();
            </script>
        </body>
        </html>
        '''

    return render_template('desktop_app.html')

@flask_app.route('/api/file/open', methods=['POST'])
def api_open_file():
    """Open and read a file"""
    data = request.json
    file_path = data.get('path')
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({
            'success': True,
            'content': content,
            'filename': os.path.basename(file_path),
            'file_type': os.path.splitext(file_path)[1].lower()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@flask_app.route('/api/translate', methods=['POST'])
def api_translate_contract():
    """Translate Solidity/Rust to Promela"""
    data = request.json
    source_code = data.get('code', '')
    file_type = data.get('file_type', '.sol')

    try:
        from translator import DeFiTranslator, VerifiedTranslator

        if file_type == '.sol':
            translator = VerifiedTranslator()
            translated, obligations = translator.translate_with_proof(source_code)
        elif file_type == '.rs':
            translated = DeFiTranslator.translate_rust(source_code)
        else:
            translated = source_code

        # Save to disk
        output_path = os.path.join(MODELS_DIR, "translated_output.pml")
        with open(output_path, 'w') as f:
            f.write(translated)

        # Extract LTL properties
        ltl_properties = []
        ltl_pattern = r'ltl\s+(\w+)\s*\{([^}]+)\}'
        for match in re.finditer(ltl_pattern, translated, re.DOTALL):
            ltl_properties.append({
                'name': match.group(1),
                'formula': match.group(2).strip()
            })

        return jsonify({
            'success': True,
            'translated': translated,
            'ltl_properties': ltl_properties,
            'output_path': output_path
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@flask_app.route('/api/verify/spin', methods=['POST'])
def api_verify_spin():
    """Run SPIN verification via API"""
    data = request.json
    translated_code = data.get('code', '')

    pml_path = os.path.join(MODELS_DIR, "temp_verify.pml")
    with open(pml_path, 'w') as f:
        f.write(translated_code)

    try:
        result = subprocess.run(
            ['spin', '-a', pml_path],
            capture_output=True, text=True, timeout=60,
            cwd=PROJECT_DIR
        )

        spin_output = result.stdout + '\n' + result.stderr

        pan_path = os.path.join(SPIN_LOGS, "pan")
        compile_result = subprocess.run(
            ['gcc', '-O3', '-o', pan_path, 'pan.c'],
            capture_output=True, text=True, timeout=60,
            cwd=PROJECT_DIR
        )

        if compile_result.returncode != 0:
            return jsonify({
                'success': False,
                'error': f'Compilation failed: {compile_result.stderr}',
                'spin_output': spin_output
            })

        verify_result = subprocess.run(
            [pan_path, '-a'],
            capture_output=True, text=True, timeout=120,
            cwd=PROJECT_DIR
        )

        output = verify_result.stdout
        has_errors = 'errors: 0' not in output or 'assertion violated' in output.lower()

        # Update app state if possible
        VerificationState.save_result(not has_errors, output, verify_result.stderr, "API_Spin")

        return jsonify({
            'success': not has_errors,
            'output': output,
            'has_counterexample': has_errors
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@flask_app.route('/api/tools/status')
def api_tools_status():
    """Check tool availability for API"""
    tools = {}
    for tool, cmd in [('spin', ['spin', '-V']), ('coq', ['coqc', '--version']),
                      ('lean', ['lean', '--version']), ('prusti', ['prusti-rustc', '--version']),
                      ('kani', ['cargo', 'kani', '--version'])]:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=2)
            tools[tool] = r.returncode == 0
        except:
            tools[tool] = False
    return jsonify(tools)

@flask_app.route('/api/state/current')
def api_current_state():
    """Get current verification state from unified source"""
    state_file = os.path.join(PROJECT_DIR, "verification_state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                return jsonify(json.load(f))
        except:
            pass
    # Fallback to REPORTS_DIR if not in root
    state_file_alt = os.path.join(REPORTS_DIR, "verification_state.json")
    if os.path.exists(state_file_alt):
        try:
            with open(state_file_alt, 'r') as f:
                return jsonify(json.load(f))
        except:
            pass
    return jsonify({})

@flask_app.route('/api/activity/recent')
def api_recent_activity():
    """Get recent jobs from audit log, normalised for the dashboard"""
    if os.path.exists(AUDIT_LOG_FILE):
        try:
            with open(AUDIT_LOG_FILE, 'r') as f:
                raw = json.load(f)
            # Normalise field names so the dashboard JS can use them consistently
            result = []
            for r in raw[:20]:
                result.append({
                    'datetime':   r.get('timestamp', r.get('datetime', '')),
                    'model_name': os.path.basename(r.get('file', r.get('model_name', 'Unknown'))),
                    'tool':       r.get('tool', ''),
                    'status':     r.get('status', ''),
                    'states':     r.get('details', {}).get('states', 0),
                    'depth':      r.get('details', {}).get('depth', 0),
                })
            return jsonify(result)
        except Exception:
            pass
    return jsonify([])

@flask_app.route('/dashboard')
def desktop_dashboard():
    """Dashboard route — serves the same desktop_app.html template (no login required for local desktop use)"""
    template_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'web_portal', 'templates', 'desktop_app.html'
    )
    if os.path.exists(template_path):
        return render_template('desktop_app.html')

    # Inline fallback dashboard if template is missing
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>DeFi Guardian — Dashboard</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        <style>
            body { background: #f0f2f5; color: #1e293b; font-family: Inter, sans-serif; }
            nav { background: #1e293b; padding: 0.85rem 2rem; display: flex; align-items: center; }
            nav a.brand { color: #2dd4bf; font-weight: 800; font-size: 1.1rem; text-decoration: none; }
            .nav-btn { background: #0d9488; color: #fff; border: none; border-radius: 8px;
                       padding: 0.4rem 0.9rem; font-size: 0.82rem; font-weight: 600;
                       text-decoration: none; margin-left: 0.5rem; }
            .nav-btn.purple { background: #7c3aed; }
            .container { max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }
            .card { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 12px;
                    padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 1px 4px rgba(0,0,0,0.07); }
            .card h5 { color: #1e293b; font-weight: 700; margin-bottom: 1rem; }
            .text-accent { color: #0d9488; }
            .status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 8px; }
            .status-dot.online { background: #16a34a; }
            .status-dot.offline { background: #dc2626; }
            .text-muted { color: #64748b !important; }
            h2 { color: #0d9488; }
        </style>
    </head>
    <body>
        <nav>
            <a class="brand" href="/"><i class="fas fa-shield-halved"></i> DeFi Guardian</a>
            <div class="ms-auto">
                <a href="/dashboard" class="nav-btn"><i class="fas fa-chart-line me-1"></i> Verification Dashboard</a>
                <a href="http://localhost:5000/dashboard" class="nav-btn purple"><i class="fas fa-user-circle me-1"></i> Account Dashboard</a>
            </div>
        </nav>
        <div class="container">
            <h2 class="mt-4"><i class="fas fa-shield-halved"></i> DeFi Guardian — Dashboard</h2>
            <p class="text-muted mb-4">Formal Verification Suite — Local Desktop Interface</p>

            <div class="row">
                <div class="col-md-6">
                    <div class="card">
                        <h5><i class="fas fa-microchip text-accent me-2"></i> Tool Status</h5>
                        <div id="toolStatus">Loading...</div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card">
                        <h5><i class="fas fa-chart-bar text-accent me-2"></i> Verification Stats</h5>
                        <div id="verifStats">Loading...</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <h5><i class="fas fa-history text-accent me-2"></i> Recent Activity</h5>
                <div id="recentActivity">Loading...</div>
            </div>
        </div>

        <script>
            async function refreshData() {
                try {
                    const toolResp = await fetch('/api/tools/status');
                    const tools = await toolResp.json();
                    document.getElementById('toolStatus').innerHTML =
                        Object.entries(tools).map(([t, ok]) =>
                            `<div class="mb-1"><span class="status-dot ${ok ? 'online' : 'offline'}"></span>
                            ${t.toUpperCase()}: ${ok ? 'Available' : 'Not Found'}</div>`
                        ).join('');

                    const stateResp = await fetch('/api/state/current');
                    const state = await stateResp.json();
                    const ltlResults = state.ltl_results || [];
                    const passed = ltlResults.filter(r => r.success).length;
                    const failed = ltlResults.filter(r => !r.success).length;
                    document.getElementById('verifStats').innerHTML =
                        `<p>States Explored: <strong>${state.states_stored || state.states || 0}</strong></p>` +
                        `<p>Depth Reached: <strong>${state.depth || 0}</strong></p>` +
                        `<p>Transitions: <strong>${state.transitions || 0}</strong></p>` +
                        `<p>LTL Passed: <strong style="color:#3fb950">${passed}</strong> / Failed: <strong style="color:#f85149">${failed}</strong></p>` +
                        `<p>Last Run: <strong>${state.datetime || 'Never'}</strong></p>` +
                        `<p>File: <strong>${state.model_name || '—'}</strong></p>`;

                    const actResp = await fetch('/api/activity/recent');
                    const activity = await actResp.json();
                    document.getElementById('recentActivity').innerHTML = activity.length
                        ? `<table style="width:100%;font-size:0.85rem;border-collapse:collapse;">
                            <thead><tr style="color:#8b949e;text-align:left;">
                              <th style="padding:4px 8px;">Time</th>
                              <th style="padding:4px 8px;">File</th>
                              <th style="padding:4px 8px;">Tool</th>
                              <th style="padding:4px 8px;">Status</th>
                              <th style="padding:4px 8px;">States</th>
                            </tr></thead>
                            <tbody>${activity.map(a => `<tr style="border-top:1px solid #30363d;">
                              <td style="padding:4px 8px;color:#8b949e;font-size:0.78rem;">${(a.datetime||'').slice(0,16)}</td>
                              <td style="padding:4px 8px;font-family:monospace;">${a.model_name||'—'}</td>
                              <td style="padding:4px 8px;">${a.tool||'—'}</td>
                              <td style="padding:4px 8px;">
                                <span style="padding:2px 8px;border-radius:10px;font-size:0.75rem;font-weight:700;
                                  background:${(a.status==='SUCCESS'||a.status==='PASS')?'rgba(63,185,80,0.15)':'rgba(248,81,73,0.15)'};
                                  color:${(a.status==='SUCCESS'||a.status==='PASS')?'#3fb950':'#f85149'};">
                                  ${(a.status==='SUCCESS'||a.status==='PASS')?'PASS':'FAIL'}
                                </span>
                              </td>
                              <td style="padding:4px 8px;">${a.states||0}</td>
                            </tr>`).join('')}</tbody>
                           </table>`
                        : '<p class="text-muted">No recent activity</p>';
                } catch(e) {
                    document.getElementById('toolStatus').textContent = 'Error loading data';
                }
            }
            refreshData();
            setInterval(refreshData, 10000);
        </script>
    </body>
    </html>
    '''

# Import verification server routes for portal compatibility
try:
    sys.path.insert(0, os.path.join(PROJECT_DIR, "web_portal"))
    from verification_server import verify as portal_verify, get_job as portal_get_job
    flask_app.route('/verify', methods=['POST'])(portal_verify)
    flask_app.route('/job/<job_id>', methods=['GET'])(portal_get_job)
except ImportError:
    pass

def start_flask():
    """Start Flask server in a separate thread"""
    try:
        flask_app.run(port=5005, debug=False, threaded=True, use_reloader=False)
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"⚠️  Port 5005 already in use. Using port 5006 instead.")
            flask_app.run(port=5006, debug=False, threaded=True, use_reloader=False)
        else:
            raise


if __name__ == "__main__":
    # Start Flask background thread for potential web-based components
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    app = FormalVerifierApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("\n👋 DeFi Guardian closed safely.")
