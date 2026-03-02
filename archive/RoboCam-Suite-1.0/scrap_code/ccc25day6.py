import tkinter as tk
from picamera2 import Picamera2
import cv2
from robocam.robocam_ccc import RoboCam
from experiment import ExperimentWindow

preview_resolution = (640, 512)

class CameraApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Camera & Control")

        # Preview camera
        self.picam2 = Picamera2()
        prev_cfg = self.picam2.create_preview_configuration(main={"size": preview_resolution})
        self.picam2.configure(prev_cfg)
        self.picam2.start()

        # Printer/experiment robot
        self.robocam = RoboCam(baudrate=115200)

        # Experiment window helper
        self.experiment = ExperimentWindow(self.root, self.picam2, self.robocam)

        # Printer control state
        self.printer_window = None

        # Build UI
        self.create_widgets()
        self.update_preview()

    def create_widgets(self):
        # Camera preview
        self.preview_label = tk.Label(self.root)
        self.preview_label.grid(row=0, column=0, columnspan=2, padx=10, pady=10)

        # Printer Control button
        tk.Button(self.root, text="Printer Control",
                  command=self.open_printer_control_window) \
          .grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        # Experiment button
        tk.Button(self.root, text="Experiment",
                  command=self.experiment.open) \
          .grid(row=1, column=1, sticky="ew", padx=5, pady=5)

    def open_printer_control_window(self):
        if self.printer_window and self.printer_window.winfo_exists():
            self.printer_window.lift()
            return

        w = tk.Toplevel(self.root)
        w.title("Printer Control")
        self.printer_window = w

        def on_close():
            w.destroy()
            self.printer_window = None
        w.protocol("WM_DELETE_WINDOW", on_close)

        # Step size
        self.step_size = tk.DoubleVar(value=1.0)
        tk.Label(w, text="Step Size:").grid(row=0, column=0, columnspan=4, pady=(10,0))
        for i, v in enumerate((0.1, 1.0, 10.0)):
            tk.Radiobutton(w, text=f"{v} mm", variable=self.step_size, value=v)\
              .grid(row=1, column=i, padx=5, pady=5)

        # Speed entry
        tk.Label(w, text="Move Speed (mm/min):").grid(row=2, column=0, sticky="e")
        self.move_speed_ent = tk.Entry(w)
        self.move_speed_ent.insert(0, "1500")  # default speed
        self.move_speed_ent.grid(row=2, column=1, padx=5, pady=5)

        # Movement buttons
        moves = [
            ("Y+", (3,1, lambda: self.robocam.move_relative(Y=self.step_size.get(), speed=float(self.move_speed_ent.get())))),
            ("X−", (4,0, lambda: self.robocam.move_relative(X=-self.step_size.get(), speed=float(self.move_speed_ent.get())))),
            ("X+", (4,2, lambda: self.robocam.move_relative(X=self.step_size.get(), speed=float(self.move_speed_ent.get())))),
            ("Y−", (5,1, lambda: self.robocam.move_relative(Y=-self.step_size.get(), speed=float(self.move_speed_ent.get())))),
            ("Z−", (3,3, lambda: self.robocam.move_relative(Z=-self.step_size.get(), speed=float(self.move_speed_ent.get())))),
            ("Z+", (5,3, lambda: self.robocam.move_relative(Z=self.step_size.get(), speed=float(self.move_speed_ent.get()))))
        ]
        for text, (r, c, cmd) in moves:
            tk.Button(w, text=text, command=cmd).grid(row=r, column=c, padx=5, pady=5)

        # Home button
        tk.Button(w, text="Home", command=self.robocam.home)\
          .grid(row=6, column=0, columnspan=2, pady=(10,5))

        # Position display
        tk.Label(w, text="Position:").grid(row=7, column=0, sticky="e", pady=(5,10))
        self.position_label = tk.Label(w, text="0, 0, 0")
        self.position_label.grid(row=7, column=1, columnspan=3, sticky="w", pady=(5,10))

        # Goto coordinates entries
        tk.Label(w, text="Goto X:").grid(row=8, column=0, sticky="e")
        self.goto_x_ent = tk.Entry(w)
        self.goto_x_ent.grid(row=8, column=1, padx=5, pady=5)
        tk.Label(w, text="Goto Y:").grid(row=9, column=0, sticky="e")
        self.goto_y_ent = tk.Entry(w)
        self.goto_y_ent.grid(row=9, column=1, padx=5, pady=5)
        tk.Label(w, text="Goto Z:").grid(row=10, column=0, sticky="e")
        self.goto_z_ent = tk.Entry(w)
        self.goto_z_ent.grid(row=10, column=1, padx=5, pady=5)
        tk.Button(
            w, text="Go",
            command=lambda: self.robocam.move_absolute(
                X=float(self.goto_x_ent.get()),
                Y=float(self.goto_y_ent.get()),
                Z=float(self.goto_z_ent.get()),
                speed=float(self.move_speed_ent.get())
            )
        ).grid(row=11, column=0, columnspan=2, pady=5)

        w.transient(self.root)
        w.grab_set()

    def update_preview(self):
        if self.experiment.running:
            self.preview_label.config(text="Recording…", image="")
        else:
            frame = self.picam2.capture_array("main")
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.resize(frame, preview_resolution)
            data = cv2.imencode('.ppm', frame)[1].tobytes()
            photo = tk.PhotoImage(data=data)
            self.preview_label.config(image=photo, text="")
            self.preview_label.image = photo

        if self.printer_window and self.printer_window.winfo_exists():
            pos = f"{self.robocam.X}, {self.robocam.Y}, {self.robocam.Z}"
            self.position_label.config(text=pos)

        self.root.after(30, self.update_preview)

    def on_close(self):
        self.picam2.stop()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = CameraApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
