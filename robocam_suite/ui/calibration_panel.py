    def _load_from_session(self):
        s = self._session.get_session("calibration")
        step = s.get("step_size", "1.0")
        
        matched = False
        for btn in self._step_btn_group.buttons():
            if btn is not self._custom_rb and btn.text() == step:
                btn.setChecked(True)
                matched = True
                break
        
        if not matched:
            self._custom_rb.setChecked(True)
            self.step_size_input.setText(step)
            self._last_custom_step = step
        else:
            # If session loaded a preset, we still want to load the last custom step
            # into the input box so it's visible.
            custom_step = s.get("custom_step_size", "1.0")
            self.step_size_input.setText(custom_step)
            self._last_custom_step = custom_step
            
        # Update the active display
        self._active_step_label.setText(f"{step} mm")

        # Load camera settings from session
        self.exp_spin.blockSignals(True)
        self.gain_spin.blockSignals(True)
        self.auto_exp_check.blockSignals(True)
        self.auto_gain_check.blockSignals(True)
        self.brightness_spin.blockSignals(True)
        self.bandwidth_spin.blockSignals(True)
        self.binning_check.blockSignals(True)

        self.exp_spin.setValue(int(s.get("exposure_ms", 20)))
        self.gain_spin.setValue(int(s.get("gain", 100)))
        self.auto_exp_check.setChecked(bool(s.get("auto_exposure", False)))
        self.auto_gain_check.setChecked(bool(s.get("auto_gain", False)))
        self.brightness_spin.setValue(int(s.get("target_brightness", 100)))
        self.bandwidth_spin.setValue(int(s.get("usb_bandwidth", 80)))
        self.binning_check.setChecked(bool(s.get("hardware_bin", False)))
        
        self.exp_spin.setEnabled(not self.auto_exp_check.isChecked())
        self.gain_spin.setEnabled(not self.auto_gain_check.isChecked())

        self.exp_spin.blockSignals(False)
        self.gain_spin.blockSignals(False)
        self.auto_exp_check.blockSignals(False)
        self.auto_gain_check.blockSignals(False)
        self.brightness_spin.blockSignals(False)
        self.bandwidth_spin.blockSignals(False)
        self.binning_check.blockSignals(False)

        # Attempt to auto-load the most recently saved calibration file;
        # only fall back to bare session values if no file is found.
        if not self._auto_load_latest_calibration():
            self.cols_spin.setValue(int(s.get("cols", 0)))
            self.rows_spin.setValue(int(s.get("rows", 0)))
            saved_corners = s.get("corners", {})
            for name, pos in saved_corners.items():
                if pos is not None and name in self.corners:
                    self.corners[name]["position"] = pos
                    self.corners[name]["label"].setText(f"X:{pos[0]:.2f} Y:{pos[1]:.2f} Z:{pos[2]:.2f}")
            
            self._generate_well_map()
            # Explicitly emit that corners are loaded from session
            self.corners_changed.emit()
        
        # Finally, refresh camera settings if a camera is connected
