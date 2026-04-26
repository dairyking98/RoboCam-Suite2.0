            QMessageBox.critical(self, "Save Error", str(e))

    def _load_calibration(self, path: Optional[Path] = None):
        if path is None:
            cal_dir = self._get_cal_dir()
            selected_path, _ = QFileDialog.getOpenFileName(
                self, "Load Calibration",
                str(cal_dir),
                "JSON Files (*.json)"
            )
            if not selected_path:
                # User cancelled, do not load anything and do not save a 'False' path
                session_manager.update_session("calibration", {"last_calibration_path": None})
                return False
            path = Path(selected_path)
        else:
            # Ensure path is a Path object if it came from session_manager as str
            path = Path(path)

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Load Error", str(e))
            return

        corners = data.get("corners", {})
        for name in CORNER_NAMES:
            pos = corners.get(name)
            if pos is not None:
                self.corners[name]["position"] = pos
                self.corners[name]["label"].setText(
                    f"X:{pos[0]:.2f}  Y:{pos[1]:.2f}  Z:{pos[2]:.2f}"
                )
                self.corners[name]["label"].setStyleSheet("color: green;")

        if "cols" in data:
            self.cols_spin.setValue(int(data["cols"]))
        if "rows" in data:
            self.rows_spin.setValue(int(data["rows"]))

        self._persist_corners()
        self._cal_status_label.setText(f"Loaded: {Path(path).name}")
        self._cal_status_label.setStyleSheet("font-size: 10px; color: #888;")
        logger.info(f"[Calibration] Loaded from {path}")
        session_manager.update_session("calibration", {"last_calibration_path": str(path)})
        self._generate_well_map()
        self.corners_changed.emit()

    # ------------------------------------------------------------------
    # Public accessors used by ExperimentPanel
    # ------------------------------------------------------------------

    def get_corners(self) -> dict:
        return {k: v["position"] for k, v in self.corners.items()}

    def get_well_dimensions(self) -> tuple[int, int]:
        """Return (cols, rows)."""
        return self.cols_spin.value(), self.rows_spin.value()

    def get_well_positions(self) -> Optional[list]:
        return self._compute_well_positions()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _on_step_btn_clicked(self, btn):
        """Preset radio clicked — keep custom input visible."""
        if btn is not self._custom_rb:
            # Preset selected - DONT change the input box so the user can still see their custom value
            self._session.update_session("calibration", {"step_size": btn.text()})
        else:
            # Re-selected "Custom"
            self._session.update_session("calibration", {"step_size": self.step_size_input.text()})

    def _on_custom_step_edited(self, text: str):
        """User typed in the custom field — auto-select the Custom radio button."""
        self._last_custom_step = text
        self._custom_rb.setChecked(True)
        self._session.update_session("calibration", {
            "step_size": text,
            "custom_step_size": text
        })

    def _update_position_display(self):
        try:
            mc = self.hw_manager.get_motion_controller()
            pos = mc.get_current_position()
            self.x_pos_label.setText(f"{pos[0]:.2f}")
            self.y_pos_label.setText(f"{pos[1]:.2f}")
            self.z_pos_label.setText(f"{pos[2]:.2f}")

            # Update homing status
            if mc.is_homed():
                self._is_homed = True
                self._cal_status_label.setText("Ready.")
                self._cal_status_label.setStyleSheet("font-size: 10px; color: #888;")
                self._set_movement_controls_enabled(True)
                self._set_camera_controls_enabled(True)
            else:
                self._is_homed = False
                self._cal_status_label.setText("<b style=\"color: red;\">Printer Not Homed.</b>")
                self._cal_status_label.setStyleSheet("font-size: 10px; color: red;")
                self._set_movement_controls_enabled(False)
                self._set_camera_controls_enabled(False)

        except Exception as e:
            logger.error(f"[Calibration] Error updating position display: {e}")
            self.x_pos_label.setText("ERR")
            self.y_pos_label.setText("ERR")
            self.z_pos_label.setText("ERR")
            self._cal_status_label.setText("<b style=\"color: red;\">Printer Disconnected.</b>")
            self._cal_status_label.setStyleSheet("font-size: 10px; color: red;")
            self._set_movement_controls_enabled(False)
            self._set_camera_controls_enabled(False)

    def _set_movement_controls_enabled(self, enabled: bool):
        self.y_plus_btn.setEnabled(enabled)
        self.x_minus_btn.setEnabled(enabled)
        self.x_plus_btn.setEnabled(enabled)
        self.y_minus_btn.setEnabled(enabled)
        self.z_plus_btn.setEnabled(enabled)
        self.z_minus_btn.setEnabled(enabled)
        self.home_btn.setEnabled(True) # Always allow homing
        self.go_to_xyz_btn.setEnabled(enabled)
        self.set_corner_btn.setEnabled(enabled)
        self.clear_corners_btn.setEnabled(enabled)
        self.load_cal_btn.setEnabled(enabled)
        self.save_cal_btn.setEnabled(enabled)
        self.well_map_widget.setEnabled(enabled)

    def _set_camera_controls_enabled(self, enabled: bool):
        self.auto_exp_check.setEnabled(enabled)
        self.exp_spin.setEnabled(enabled)
        self.gain_spin.setEnabled(enabled)
        self.brightness_spin.setEnabled(enabled)
        self.usb_bandwidth_spin.setEnabled(enabled)
        self.hw_binning_combo.setEnabled(enabled)
        self.reset_camera_btn.setEnabled(enabled)

    def _get_cal_dir(self) -> Path:
        cal_dir = _default_cal_dir()
        cal_dir.mkdir(parents=True, exist_ok=True)
        return cal_dir

    def _on_home_clicked(self):
        logger.info("[Calibration] Homing printer...")
        self.hw_manager.get_motion_controller().home()
        self._is_homed = True
        self._update_position_display()

    def _on_set_corner_clicked(self, corner_name: str):
        pos = self.hw_manager.get_motion_controller().get_current_position()
        self.corners[corner_name]["position"] = pos
        self.corners[corner_name]["label"].setText(
            f"X:{pos[0]:.2f}  Y:{pos[1]:.2f}  Z:{pos[2]:.2f}"
        )
        self.corners[corner_name]["label"].setStyleSheet("color: green;")
        self._persist_corners()
        self.corners_changed.emit()

    def _on_clear_corners_clicked(self):
        for name in CORNER_NAMES:
            self.corners[name]["position"] = None
            self.corners[name]["label"].setText("Not Set")
            self.corners[name]["label"].setStyleSheet("color: #888;")
        self._persist_corners()
        self.corners_changed.emit()
        self.well_map_widget.clear()

    def _on_go_to_xyz_clicked(self):
        x = float(self.x_go_to_input.text())
        y = float(self.y_go_to_input.text())
        z = float(self.z_go_to_input.text())
        self.hw_manager.get_motion_controller().move_to(x, y, z)
        self._update_position_display()

    def _on_well_map_clicked(self, x: float, y: float, z: float):
        self.hw_manager.get_motion_controller().move_to(x, y, z)
        self._update_position_display()

    def _on_load_cal_clicked(self):
        self._load_calibration()

    def _on_save_cal_clicked(self):
        self._save_calibration()

    def _on_reset_camera_clicked(self):
        logger.info("[Calibration] Resetting camera controls to defaults...")
        self.hw_manager.get_camera().reset_to_defaults()
        self._load_camera_settings_from_hw()
        self._on_camera_params_changed() # Trigger session save

    def _load_camera_settings_from_hw(self):
        camera = self.hw_manager.get_camera()
        if camera and camera.is_connected:
            self.auto_exp_check.blockSignals(True)
            self.exp_spin.blockSignals(True)
            self.gain_spin.blockSignals(True)
            self.brightness_spin.blockSignals(True)
            self.usb_bandwidth_spin.blockSignals(True)
            self.hw_binning_combo.blockSignals(True)

            self.auto_exp_check.setChecked(camera.get_auto_exposure())
            self.exp_spin.setValue(camera.get_exposure())
            self.gain_spin.setValue(camera.get_gain())
            self.brightness_spin.setValue(camera.get_target_brightness())
            self.usb_bandwidth_spin.setValue(camera.get_usb_bandwidth())
            self.hw_binning_combo.setCurrentText(str(camera.get_hw_binning()))

            self.auto_exp_check.blockSignals(False)
            self.exp_spin.blockSignals(False)
            self.gain_spin.blockSignals(False)
            self.brightness_spin.blockSignals(False)
            self.usb_bandwidth_spin.blockSignals(False)
            self.hw_binning_combo.blockSignals(False)

    def _on_camera_params_changed(self):
        camera = self.hw_manager.get_camera()
        if camera and camera.is_connected:
            camera.set_auto_exposure(self.auto_exp_check.isChecked())
            camera.set_exposure(self.exp_spin.value())
            camera.set_gain(self.gain_spin.value())
            camera.set_target_brightness(self.brightness_spin.value())
            camera.set_usb_bandwidth(self.usb_bandwidth_spin.value())
            camera.set_hw_binning(int(self.hw_binning_combo.currentText()))

            # Save all camera settings to session
            camera_settings = {
                "auto_exposure": self.auto_exp_check.isChecked(),
                "exposure": self.exp_spin.value(),
                "gain": self.gain_spin.value(),
                "target_brightness": self.brightness_spin.value(),
                "usb_bandwidth": self.usb_bandwidth_spin.value(),
                "hw_binning": int(self.hw_binning_combo.currentText()),
            }
            session_manager.update_session("calibration", {"camera_settings": camera_settings})

    def _load_from_session(self):
        # Load step size from session
        s = session_manager.get_session("calibration")
        step_size = s.get("step_size", "1.0")
        custom_step = s.get("custom_step_size", "1.0")

        if step_size in STEP_PRESETS:
            for rb in self.step_size_group.buttons():
                if rb.text() == step_size:
                    rb.setChecked(True)
                    break
        else:
            self._custom_rb.setChecked(True)
            self.step_size_input.setText(step_size)

        self._last_custom_step = custom_step

        # Load camera settings from session
        self.exp_spin.blockSignals(True)
        self.gain_spin.blockSignals(True)

        # Load last used calibration file
        last_cal_path = session_manager.get_session("calibration").get("last_calibration_path")
        if last_cal_path and last_cal_path != "None": # Check for both None and the string "None"
            logger.info(f"[Calibration] Auto-loading calibration from {last_cal_path}")
            self._load_calibration(Path(last_cal_path))

        # Initial check for homing status
        self._update_position_display()

        # Check initial printer position and enforce homing if at (0,0,0)
        initial_pos = self.hw_manager.get_motion_controller().get_current_position()
        if initial_pos == (0.0, 0.0, 0.0):
            self._set_movement_controls_enabled(False)
            self._set_camera_controls_enabled(False)
            self._cal_status_label.setText("<b style=\"color: red;\">Homing Required: Printer at (0,0,0). Please Home.</b>")
        else:
            self._set_movement_controls_enabled(True)
            self._set_camera_controls_enabled(True)
            self._cal_status_label.setText("Ready.")

        # Load camera settings from session and apply to UI
        camera_settings = session_manager.get_session("calibration").get("camera_settings", {})
        if camera_settings:
            self.auto_exp_check.setChecked(camera_settings.get("auto_exposure", False))
            self.exp_spin.setValue(camera_settings.get("exposure", 20000))
            self.gain_spin.setValue(camera_settings.get("gain", 100))
            self.brightness_spin.setValue(camera_settings.get("target_brightness", 100))
            self.usb_bandwidth_spin.setValue(camera_settings.get("usb_bandwidth", 50))
            self.hw_binning_combo.setCurrentText(str(camera_settings.get("hw_binning", 1)))

        self.exp_spin.blockSignals(False)
        self.gain_spin.blockSignals(False)

    def _persist_corners(self):
        corners_data = {
            name: self.corners[name]["position"]
            for name in CORNER_NAMES
            if self.corners[name]["position"] is not None
        }
        session_manager.update_session("calibration", {"corners": corners_data}))
