#!/usr/bin/env python3
"""Visual wizard window for the Raspberry Pi (or a Linux desktop), modelled on windows/kiosk-gui.ps1.

Runs as the desktop user and changes nothing itself: every button sends one
JSON request on stdout to the root process (gui_launcher.py), which answers on
stdin with `log` lines and a final `done`. Standard library only, and no
pi_kiosk imports, because the launcher runs a standalone copy of this file.

Preview the layout on any desktop with:  python3 gui.py --demo [--displays 2]
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

SETTINGS_VERSION = 1
FINAL_ACTIONS = ("launch", "reboot", "nothing")
VIDEO_TYPES = (
    ("Videos", "*.mp4 *.m4v *.mkv *.mov *.webm *.avi *.MP4 *.MOV"),
    ("All files", "*"),
)


def settings_path(home: str) -> Path:
    return Path(home) / ".config" / "pi-kiosk" / "gui-settings.json"


def load_defaults(home: str, state: dict | None) -> dict | None:
    """Last GUI answers, or the saved kiosk setup when the GUI was never used here."""
    try:
        settings = json.loads(settings_path(home).read_text(encoding="utf-8"))
        if settings.get("version") == SETTINGS_VERSION and isinstance(settings.get("displays"), list):
            return settings
    except (OSError, ValueError, AttributeError):
        pass  # A damaged settings file must not prevent the wizard from opening.
    if not state:
        return None
    return {
        "displays": state.get("displays", []),
        "audioDisplay": state.get("audioDisplay", ""),
        "audioDevice": state.get("audioDevice", ""),
        "touchOutput": state.get("touchOutput", ""),
        "skipRustDesk": bool(state.get("skipRustDesk", False)),
        "registerTotem": False,
        "totemName": "",
        "totemDescription": "",
        "totemLocation": "",
        "finalAction": "launch",
    }


def display_defaults(defaults: dict | None, output: str) -> dict:
    for entry in (defaults or {}).get("displays", []):
        if entry.get("output") == output:
            return entry
    return {}


def settings_to_save(form: dict) -> dict:
    """The form without passwords: those are never written to disk."""
    saved = {key: value for key, value in form.items() if "password" not in key.lower()}
    saved["version"] = SETTINGS_VERSION
    return saved


def save_settings(home: str, form: dict) -> None:
    path = settings_path(home)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings_to_save(form), indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


class PipeChannel:
    """Talks to the root process over stdin/stdout."""

    def __init__(self) -> None:
        self.events: queue.Queue = queue.Queue()

    def hello(self) -> dict:
        line = sys.stdin.readline()
        if not line:
            raise SystemExit("The setup process did not send the display list.")
        threading.Thread(target=self._read, daemon=True).start()
        return json.loads(line)

    def _read(self) -> None:
        for line in sys.stdin:
            try:
                self.events.put(json.loads(line))
            except ValueError:
                continue
        self.events.put({"type": "eof"})

    def send(self, request: dict) -> None:
        try:
            sys.stdout.write(json.dumps(request) + "\n")
            sys.stdout.flush()
        except (BrokenPipeError, ValueError):
            self.events.put({"type": "eof"})


class DemoChannel:
    """Fake backend so the window can be previewed without a Pi."""

    def __init__(self, displays: int) -> None:
        self.events: queue.Queue = queue.Queue()
        self.count = displays

    def hello(self) -> dict:
        names = ["HDMI-A-1", "HDMI-A-2", "HDMI-A-3"][: self.count]
        return {
            "type": "hello",
            "platform": "raspberry-pi",
            "user": "pi",
            "home": str(Path.home()),
            "displays": [
                {"name": name, "label": f"Display {number} ({name} Demo monitor) - 1920x1080"}
                for number, name in enumerate(names, start=1)
            ],
            "audioOutputs": [
                {"id": "pulse/hdmi-0", "name": "Built-in Audio Digital Stereo (HDMI) - vc4-hdmi-0"},
                {"id": "pulse/hdmi-1", "name": "Built-in Audio Digital Stereo (HDMI) - vc4-hdmi-1"},
            ],
            "defaultAudioLabel": "Default output - whatever is available when it plays",
            "touchscreen": True,
            "rotations": [
                {"id": "none", "label": "No rotation"},
                {"id": "clockwise", "label": "Rotate clockwise (90 deg)"},
                {"id": "counterclockwise", "label": "Rotate counterclockwise (90 deg)"},
                {"id": "upside-down", "label": "Rotate 180 deg (upside down)"},
            ],
            "projects": [{"id": "webapp", "label": "Webapp"}, {"id": "video", "label": "Video"}],
            "webappExample": "screen_1_de/screen_1_de-dist.zip",
            "state": None,
        }

    def send(self, request: dict) -> None:
        if request.get("type") == "quit":
            return

        def work() -> None:
            for text in ("[....] Demo mode: nothing is changed.", json.dumps(request, indent=1)):
                time.sleep(0.4)
                self.events.put({"type": "log", "text": text})
            self.events.put({"type": "done", "request": request["type"], "ok": True, "message": "Demo finished."})

        threading.Thread(target=work, daemon=True).start()


def run_window(channel) -> int:
    import tkinter as tk
    from tkinter import filedialog, font, messagebox, ttk

    hello = channel.hello()
    displays = hello["displays"]
    if not displays:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("Kiosk setup", "No active displays were detected. Nothing was changed.")
        channel.send({"type": "quit"})
        return 0
    multiple = len(displays) > 1
    defaults = load_defaults(hello["home"], hello.get("state"))
    rotations = hello["rotations"]
    projects = hello["projects"]
    audio_outputs = hello["audioOutputs"]

    root = tk.Tk()
    root.title("Kiosk setup")
    root.geometry("760x780")
    root.minsize(600, 480)

    # Scrollable page: the Pi may have a small or rotated screen.
    outer = ttk.Frame(root)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, highlightthickness=0)
    scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    page = ttk.Frame(canvas, padding=20)
    page_id = canvas.create_window((0, 0), window=page, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    page.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(page_id, width=e.width))
    root.bind_all("<Button-4>", lambda _e: canvas.yview_scroll(-3, "units"))
    root.bind_all("<Button-5>", lambda _e: canvas.yview_scroll(3, "units"))
    root.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
    page.columnconfigure(0, weight=1)
    row = [0]

    def add(widget, pady=(0, 14)) -> None:
        widget.grid(row=row[0], column=0, sticky="ew", pady=pady)
        row[0] += 1

    def group(parent, title: str):
        frame = ttk.LabelFrame(parent, text=title, padding=12)
        frame.columnconfigure(1, weight=1)
        return frame

    def field(frame, label, widget) -> None:
        line = frame.grid_size()[1]
        text = ttk.Label(frame, text=label) if isinstance(label, str) else ttk.Label(frame, textvariable=label)
        text.grid(row=line, column=0, sticky="w", padx=(0, 12), pady=4)
        widget.grid(row=line, column=1, sticky="ew", pady=4)

    def combo(frame, labels: list[str], index: int = 0) -> ttk.Combobox:
        box = ttk.Combobox(frame, values=labels, state="readonly")
        box.current(max(0, min(index, len(labels) - 1)))
        return box

    def index_of(items: list[dict], value: str, key: str = "id") -> int:
        return next((i for i, item in enumerate(items) if item[key] == value), 0)

    def source_field(frame, show_browse: bool = True):
        holder = ttk.Frame(frame)
        holder.columnconfigure(0, weight=1)
        entry = ttk.Entry(holder)
        entry.grid(row=0, column=0, sticky="ew")

        def browse() -> None:
            media = Path("/media") / hello["user"]
            start = media if media.is_dir() else Path(hello["home"])
            chosen = filedialog.askopenfilename(parent=root, initialdir=str(start), filetypes=VIDEO_TYPES)
            if chosen:
                entry.delete(0, "end")
                entry.insert(0, chosen)

        button = ttk.Button(holder, text="Browse...", command=browse)
        if show_browse:
            button.grid(row=0, column=1, padx=(8, 0))
        return holder, entry, button

    title_font = font.nametofont("TkDefaultFont").copy()
    title_font.configure(size=16, weight="bold")
    machine = "Raspberry Pi" if hello.get("platform") == "raspberry-pi" else "Linux"
    title = ttk.Label(page, text=f"Configure this {machine} kiosk", font=title_font)
    add(title, pady=(0, 6))
    intro = (
        f"{len(displays)} displays detected. Each one plays its own looping video and starts on its "
        "own screen. Review the settings, then select Configure kiosk."
        if multiple
        else "Review the settings, then select Configure kiosk."
    )
    add(ttk.Label(page, text=intro, wraplength=680, justify="left"), pady=(0, 18))

    sections: list[dict[str, Any]] = []
    rotation_labels = [item["label"] for item in rotations]
    type_box = None
    source_label = tk.StringVar(value="S3 ZIP path:")
    if multiple:
        tabs = ttk.Notebook(page)
        for number, display in enumerate(displays, start=1):
            saved = display_defaults(defaults, display["name"])
            tab = ttk.Frame(tabs, padding=12)
            tab.columnconfigure(0, weight=1)
            box = group(tab, display["label"])
            box.grid(row=0, column=0, sticky="ew")
            rotation = combo(box, rotation_labels, index_of(rotations, saved.get("rotation", "none")))
            field(box, "Rotation:", rotation)
            holder, entry, _ = source_field(box)
            entry.insert(0, saved.get("source", "") if saved.get("type", "video") == "video" else "")
            field(box, "Dropbox link or local file:", holder)
            tabs.add(tab, text=f"Display {number}")
            sections.append({"display": display, "rotation": rotation, "source": entry})
        add(tabs)
    else:
        display = displays[0]
        saved = display_defaults(defaults, display["name"])
        box = group(page, "Display")
        field(box, "Active display:", ttk.Label(box, text=display["label"]))
        rotation = combo(box, rotation_labels, index_of(rotations, saved.get("rotation", "none")))
        field(box, "Rotation:", rotation)
        add(box)
        content = group(page, "Kiosk content")
        type_box = combo(content, [item["label"] for item in projects], index_of(projects, saved.get("type", "webapp")))
        field(content, "Type:", type_box)
        holder, entry, browse_button = source_field(content)
        entry.insert(0, saved.get("source", ""))
        field(content, source_label, holder)
        add(content)
        hint = ttk.Label(content, foreground="#555", text=f"Example: {hello['webappExample']}")
        hint.grid(row=content.grid_size()[1], column=1, sticky="w")
        sections.append({"display": display, "rotation": rotation, "source": entry})

    audio = group(page, "Audio")
    if multiple:
        audio_from = combo(
            audio,
            [display["label"] for display in displays],
            index_of(displays, (defaults or {}).get("audioDisplay", ""), key="name"),
        )
    else:
        audio_from = combo(audio, ["Display 1 - the only screen"])
        audio_from.state(["disabled"])
    field(audio, "Audio from:", audio_from)
    output_items = [{"id": "", "name": hello["defaultAudioLabel"]}] + (audio_outputs if multiple else [])
    audio_output = combo(
        audio,
        [item["name"] for item in output_items],
        index_of(output_items, (defaults or {}).get("audioDevice", "")),
    )
    if not multiple:
        audio_output.state(["disabled"])
    field(audio, "Output:", audio_output)
    audio_note = ttk.Label(audio, wraplength=560, justify="left")
    audio_note.grid(row=audio.grid_size()[1], column=0, columnspan=2, sticky="w", pady=(8, 0))
    add(audio)

    touch_box = None
    if multiple and hello.get("touchscreen"):
        touch = group(page, "Touchscreen")
        touch_box = combo(
            touch,
            [display["label"] for display in displays],
            index_of(displays, (defaults or {}).get("touchOutput", ""), key="name"),
        )
        field(touch, "Touchscreen on:", touch_box)
        add(touch)

    access = group(page, "Access")
    skip_rustdesk = tk.BooleanVar(value=bool((defaults or {}).get("skipRustDesk", False)))
    password = ttk.Entry(access, show="•")
    confirmation = ttk.Entry(access, show="•")

    def toggle_rustdesk() -> None:
        state = ["disabled"] if skip_rustdesk.get() else ["!disabled"]
        for widget in (password, confirmation):
            if skip_rustdesk.get():
                widget.delete(0, "end")
            widget.state(state)

    ttk.Checkbutton(
        access, text="Skip RustDesk (no remote access)", variable=skip_rustdesk, command=toggle_rustdesk
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
    field(access, "RustDesk password:", password)
    field(access, "Confirm RustDesk password:", confirmation)
    toggle_rustdesk()
    add(access)

    registration = group(page, "Registration")
    register = tk.BooleanVar(value=bool((defaults or {}).get("registerTotem", True)))
    ttk.Checkbutton(registration, text="Register this totem", variable=register).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
    )
    totem_fields = {}
    for key, label in (("totemName", "Name:"), ("totemDescription", "Description:"), ("totemLocation", "Location:")):
        entry = ttk.Entry(registration)
        entry.insert(0, str((defaults or {}).get(key, "")))
        field(registration, label, entry)
        totem_fields[key] = entry
    add(registration)

    finish = group(page, "After setup")
    final_box = combo(finish, ["Launch now", "Reboot", "Do nothing"])
    final_box.current(FINAL_ACTIONS.index((defaults or {}).get("finalAction", "launch")) if (defaults or {}).get("finalAction") in FINAL_ACTIONS else 0)
    field(finish, "Next action:", final_box)
    add(finish)

    status_frame = ttk.Frame(page)
    status_frame.columnconfigure(0, weight=1)
    status = tk.Text(status_frame, height=9, wrap="word", state="disabled", relief="solid", borderwidth=1)
    status_scroll = ttk.Scrollbar(status_frame, orient="vertical", command=status.yview)
    status.configure(yscrollcommand=status_scroll.set)
    status.grid(row=0, column=0, sticky="ew")
    status_scroll.grid(row=0, column=1, sticky="ns")
    add(status_frame, pady=(0, 12))

    def show(text: str, replace: bool = False) -> None:
        status.configure(state="normal")
        if replace:
            status.delete("1.0", "end")
        status.insert("end", text.rstrip() + "\n")
        status.see("end")
        status.configure(state="disabled")

    buttons = ttk.Frame(page)
    add(buttons, pady=(0, 24))

    def project_type() -> str:
        if type_box is None:
            return "video"
        return projects[type_box.current()]["id"]

    def on_type_change(_event=None) -> None:
        webapp = project_type() == "webapp"
        if not multiple:
            source_label.set("S3 ZIP path:" if webapp else "Dropbox link or local file:")
            if webapp:
                browse_button.grid_remove()
                hint.grid()
            else:
                browse_button.grid()
                hint.grid_remove()
        audio_note.configure(
            text=(
                "Only one screen plays sound; the others are muted. Choose the output when the "
                "screens have their own speakers."
                if multiple
                else "The webapp plays its own sound through the output available when it plays."
                if webapp
                else "The only video plays its own sound through the output available when it plays."
            )
        )
        labels = list(final_box.cget("values"))
        labels[2] = "Keep the app server running" if webapp and not multiple else "Do nothing"
        selected = final_box.current()
        final_box.configure(values=labels)
        final_box.current(selected)

    if type_box is not None:
        type_box.bind("<<ComboboxSelected>>", on_type_change)
    on_type_change()

    def collect_form() -> dict:
        kind = project_type()
        return {
            "displays": [
                {
                    "output": section["display"]["name"],
                    "rotation": rotations[section["rotation"].current()]["id"],
                    "type": kind,
                    "source": section["source"].get().strip(),
                }
                for section in sections
            ],
            "audioDisplay": displays[audio_from.current()]["name"] if multiple else "",
            "audioDevice": output_items[audio_output.current()]["id"] if multiple else "",
            "touchOutput": displays[touch_box.current()]["name"] if touch_box is not None else "",
            "skipRustDesk": bool(skip_rustdesk.get()),
            "rustdeskPassword": password.get(),
            "rustdeskPasswordConfirm": confirmation.get(),
            "registerTotem": bool(register.get()),
            "totemType": kind,
            **{key: entry.get().strip() for key, entry in totem_fields.items()},
            "finalAction": FINAL_ACTIONS[final_box.current()],
        }

    action_buttons: list = []
    pending: dict[str, Any] = {}

    def start(request: dict, message: str) -> None:
        for button in action_buttons:
            button.state(["disabled"])
        pending["form"] = request.get("form")
        show(message, replace=True)
        channel.send(request)

    def configure() -> None:
        start({"type": "configure", "form": collect_form()}, "Starting setup...")

    def remove() -> None:
        warning = (
            "This stops the kiosk, removes its startup, status reporting and autologin, deletes "
            "the files owned by pi-kiosk and restores normal rotation.\n\n"
            "RustDesk, mpv and the remote registration record are left unchanged.\n\nContinue?"
        )
        if messagebox.askyesno("Remove kiosk setup", warning, icon="warning", default="no", parent=root):
            start({"type": "cleanup"}, "Removing the kiosk configuration...")

    def register_only() -> None:
        start({"type": "register", "form": collect_form()}, "Registering the totem...")

    for text, command in (
        ("Configure kiosk", configure),
        ("Remove kiosk setup", remove),
        ("Register totem", register_only),
    ):
        button = ttk.Button(buttons, text=text, command=command)
        button.pack(side="right", padx=(8, 0), ipadx=8, ipady=4)
        action_buttons.append(button)
    root.bind("<Return>", lambda _e: configure() if "disabled" not in action_buttons[0].state() else None)

    show(
        "Previous settings loaded. Re-enter the passwords before configuring."
        if defaults
        else "Ready."
    )

    def poll() -> None:
        try:
            while True:
                event = channel.events.get_nowait()
                kind = event.get("type")
                if kind == "log":
                    show(event["text"])
                elif kind == "done":
                    show(("Done: " if event["ok"] else "ERROR: ") + event["message"])
                    if event["ok"] and event.get("request") in ("configure", "register") and pending.get("form"):
                        save_settings(hello["home"], pending["form"])
                    for button in action_buttons:
                        button.state(["!disabled"])
                elif kind == "eof":
                    show("ERROR: the setup process stopped. Close this window and run the setup again.")
                    for button in action_buttons:
                        button.state(["disabled"])
                    return
        except queue.Empty:
            pass
        root.after(100, poll)

    def close() -> None:
        channel.send({"type": "quit"})
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.after(100, poll)
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--demo" in argv:
        count = int(argv[argv.index("--displays") + 1]) if "--displays" in argv else 1
        return run_window(DemoChannel(count))
    return run_window(PipeChannel())


if __name__ == "__main__":
    raise SystemExit(main())
