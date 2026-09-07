"""Midea Smart Home Extra Logic Handler."""

import logging
import time
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

_DISHWASHER_COMPOSITE_KEYS = {
    "mode",
    "wash_region",
    "additional",
    "more_dry",
    "door_auto_open",
    "work_status",
}

_DISHWASHER_PENDING_KEYS = (
    "mode",
    "wash_region",
    "additional",
    "more_dry",
    "door_auto_open",
)

# 02db/03db/04db frames only contribute these keys to the merged state.
_DB_METERING_PASS_KEYS = (
    "water_consumption",
    "power_consumption",
    "clean_notification",
    "version",
    "data_type",
)


class DeviceLogicHandler:
    def __init__(self, device_type: int, device_name: str):
        self.device_type = device_type
        self.device_name = device_name
        self._last_standby_status: Any = None
        self._last_high_float_type: Any = None
        self._last_valid_humidity: Any = None
        self._last_valid_input_temp: Any = None
        self._last_valid_env_temp: Any = None

    def adjust_control_status(self, data: dict, running_status: str, prefix: str) -> None:
        control_status = "start" if running_status == "start" else "pause"
        control_status_key = f"{prefix}_control_status" if prefix else "control_status"
        data[control_status_key] = control_status

    def adjust_work_switch(self, data: dict) -> None:
        if "work_status" in data:
            work_status = data["work_status"]
            if work_status == "cancel":
                data["work_switch"] = 0
            elif work_status in ("cooking", "keep_warm"):
                data["work_switch"] = 2

    def _adjust_invalid_order_time(self, data: dict) -> None:
        """Treat invalid order_time values as None."""
        if "order_time_hour" in data:
            try:
                if int(data["order_time_hour"]) > 24:
                    data["order_time_hour"] = None
            except (ValueError, TypeError):
                pass
        if "order_time_min" in data:
            try:
                if int(data["order_time_min"]) > 59:
                    data["order_time_min"] = None
            except (ValueError, TypeError):
                pass

    def adjust_ac_mode(self, data: dict) -> None:
        if "mode" in data:
            power = data.get("power")
            if power == "off" or power == 0:
                data["mode"] = "idle"

    def adjust_ac_humidity(self, data: dict, status: dict) -> None:
        """For AC devices, only accept valid indoor_humidity values.

        Filters out invalid humidity readings (0 or None) from non-0x45 messages,
        preserving the last valid humidity value.
        """
        if "indoor_humidity" not in status:
            return

        humidity_value = status["indoor_humidity"]
        # Only update if the new value is valid (not None and not 0)
        if humidity_value is not None and humidity_value != 0:
            data["indoor_humidity"] = humidity_value
            self._last_valid_humidity = humidity_value
        elif self._last_valid_humidity is not None:
            # Keep the last valid humidity value if new value is invalid
            data["indoor_humidity"] = self._last_valid_humidity

    def filter_status(self, status: dict) -> dict:
        """Filter a raw decoded status before it merges into device state."""
        if self.device_type == 0xDB and str(status.get("data_type", "")).lower() in ("02db", "03db", "04db"):
            # 02db/03db/04db responses reuse field names from the 0404 program
            # frame but with incompatible shapes (numeric vs enum strings, hex
            # vs decimal error codes, bitmask vs "on"/"off"). Only let the
            # water/power metrics and metadata through so a full merge cannot
            # corrupt the program status used for control round-trips.
            return {k: v for k, v in status.items() if k in _DB_METERING_PASS_KEYS}
        return status

    def adjust_ac_compressor_current(self, data: dict, status: dict) -> None:
        """For AC devices, derive compressor_current when it reports 0.

        compressor_current and compressor_voltage come from group 1 (0x41)
        while compressor_power comes from group 7 (0x47), so they may arrive
        in different messages. Read power/voltage from the accumulated `data`
        to use the latest known values.
        """
        if "compressor_current" not in status:
            return

        current = status.get("compressor_current")
        if current is None:
            return

        try:
            current = float(current)
        except (ValueError, TypeError):
            return

        if current > 0:
            data["compressor_current"] = current
            return

        # current == 0: derive I = P / U from accumulated values
        power = data.get("compressor_power")
        voltage = data.get("compressor_voltage")
        if power is None or voltage is None:
            data["compressor_current"] = current
            return

        try:
            power = float(power)
            voltage = float(voltage)
        except (ValueError, TypeError):
            data["compressor_current"] = current
            return

        if voltage == 0:
            data["compressor_current"] = current
            return

        data["compressor_current"] = power / voltage

    def apply_special_handling(
        self,
        data: dict,
        recent_controls: dict,
        control_timeout: float,
        is_control: bool = False,
        control_attrs: dict = None,
        status: dict = None
    ) -> None:
        if self.device_type == 0xD9:
            # All drums in push path use the same generic handling.
            for prefix in ("da", "db", "dc"):
                running_key = f"{prefix}_running_status"
                if running_key not in data:
                    continue
                self._d9_push_device_running_status_for_power_off(data, prefix)
                self.adjust_control_status(data, data[running_key], prefix=prefix)
                # dc drum (dryer) reports progress via dc_dry_status
                progress_key = "dc_dry_status" if prefix == "dc" else f"{prefix}_progress"
                self.process_progress(data, running_key, progress_key)
                self._d9_push_device_remain_time(data, prefix)

        elif self.device_type == 0xE1:
            self._apply_dishwasher_pending_state(data, recent_controls, control_timeout)

        elif self.device_type in [0xDA, 0xDB, 0xDC]:
            if "running_status" in data:
                self.adjust_control_status(data, data["running_status"], prefix="")
            self.process_progress(data, "running_status", "progress")
            self._adjust_remain_time(data)

        elif self.device_type == 0xEA:
            self.adjust_work_switch(data)
            self._adjust_invalid_order_time(data)

        elif self.device_type == 0xAC:
            self.adjust_ac_mode(data)
            if status:
                self.adjust_ac_humidity(data, status)
                self.adjust_ac_compressor_current(data, status)

        elif self.device_type == 0x9C:
            self.adjust_b3_function_control(data)

        elif self.device_type == 0xED:
            self.adjust_standby_status_for_wash(data)
            self.adjust_high_float_type_when_filter_on(data)
            if status:
                self.adjust_ed_temperature(data, status)

        elif self.device_type == 0x26:
            self.adjust_bath_heater_direction(data)

    def apply_special_handling_for_poll(self, data: dict, suffix: str, raw_status: dict = None) -> bool:
        """Apply special handling for poll data with suffix (_l or _r).

        Only process the specific bucket's data (left or right),
        do not affect the other bucket's data.

        Returns:
            True if data should be processed, False if data should be skipped.
        """
        if self.device_type != 0xD9:
            return True

        status_key = f"db_running_status{suffix}"
        progress_key = f"db_progress{suffix}"
        remain_time_key = f"db_remain_time{suffix}"

        if status_key not in data:
            return True

        running_status = data[status_key]

        if running_status == "end" and not self._validate_end_status(raw_status):
            return False

        # Handle common (non-suffixed) fields from the first poll response
        if raw_status and raw_status.get('db_position') == 1:
            self._d9_polling_device_running_status_for_power_off(data)
            if "db_running_status" in data:
                self.adjust_control_status(data, data["db_running_status"], prefix="db")
            self.process_progress(data, "db_running_status", "db_progress")
            self._d9_polling_device_remain_time(data)

        # Handle suffixed progress for the specific bucket
        if progress_key in data:
            if running_status != "start":
                data[progress_key] = "idle"
            else:
                self.process_progress(data, status_key, progress_key)

        # Handle suffixed remain time for the specific bucket
        if remain_time_key in data:
            self._adjust_remain_time_by_status(data, remain_time_key, running_status)

        # Calculate db_remain_time_long as max of left and right remain times
        self._calculate_db_remain_time_long(data)

        return True

    def _validate_end_status(self, raw_status: dict) -> bool:
        """Validate that an 'end' running status is legitimate.

        Checks that progress is 0 and remain_time <= 1 to filter out
        false 'end' signals from the device.

        Returns:
            True if the end status is valid, False otherwise.
        """
        if not raw_status:
            return False
        raw_progress = raw_status.get("db_progress")
        raw_remain_time = raw_status.get("db_remain_time")
        if raw_progress is None or raw_remain_time is None:
            return False
        try:
            if isinstance(raw_progress, str):
                raw_progress = int(raw_progress, 16) if raw_progress.startswith("0x") else int(raw_progress)
            if raw_progress != 0:
                return False
        except (ValueError, TypeError):
            return False
        try:
            if isinstance(raw_remain_time, str):
                raw_remain_time = int(raw_remain_time, 16) if raw_remain_time.startswith("0x") else int(raw_remain_time)
            if raw_remain_time > 1:
                return False
        except (ValueError, TypeError):
            return False
        return True

    @staticmethod
    def _adjust_remain_time_by_status(data: dict, remain_time_key: str, running_status: str) -> None:
        """Adjust remain time based on running status for any key prefix."""
        if running_status == "start":
            return
        elif running_status == "end":
            data[remain_time_key] = 0
        else:
            data[remain_time_key] = None

    @staticmethod
    def _calculate_db_remain_time_long(data: dict) -> None:
        """Calculate db_remain_time_long as max of left and right remain times.

        Rules:
        - If both are unknown (None), result is unknown
        - If one is unknown and other has value, result is the value
        - If both have values, result is the maximum
        """
        remain_l = data.get("db_remain_time_l")
        remain_r = data.get("db_remain_time_r")

        if remain_l is None and remain_r is None:
            data["db_remain_time_long"] = None
        elif remain_l is None:
            data["db_remain_time_long"] = remain_r
        elif remain_r is None:
            data["db_remain_time_long"] = remain_l
        else:
            data["db_remain_time_long"] = max(remain_l, remain_r)

    def _d9_polling_device_running_status_for_power_off(self, data: dict) -> None:
        db_power = data.get("db_power")
        if db_power == "off" or db_power == 0:
            if "db_running_status" in data:
                data["db_running_status"] = "standby"

    def _adjust_remain_time(self, data: dict) -> None:
        if "remain_time" in data and "running_status" in data:
            self._adjust_remain_time_by_status(data, "remain_time", data["running_status"])

    def _d9_polling_device_remain_time(self, data: dict) -> None:
        if "db_remain_time" in data and "db_running_status" in data:
            self._adjust_remain_time_by_status(data, "db_remain_time", data["db_running_status"])

    def _d9_push_device_running_status_for_power_off(self, data: dict, prefix: str) -> None:
        """Generic power-off status adjustment for da/db/dc drum prefix."""
        power = data.get(f"{prefix}_power")
        if power == "off" or power == 0:
            running_key = f"{prefix}_running_status"
            if running_key in data:
                data[running_key] = "standby"
            # dc drum (dryer) also resets dry_status to idle on power off
            if prefix == "dc" and "dc_dry_status" in data:
                data["dc_dry_status"] = "idle"

    def _d9_push_device_remain_time(self, data: dict, prefix: str) -> None:
        """Generic remain time adjustment for da/db/dc drum prefix."""
        remain_key = f"{prefix}_remain_time"
        running_key = f"{prefix}_running_status"
        if remain_key in data and running_key in data:
            self._adjust_remain_time_by_status(data, remain_key, data[running_key])

    def process_progress(self, data: dict, status_key: str, progress_key: str) -> None:
        """Process progress sensor special logic"""
        if progress_key not in data:
            return

        running_status = data.get(status_key)
        if running_status != "start":
            data[progress_key] = "idle"
            return

        value = data[progress_key]
        try:
            if isinstance(value, str):
                value = int(value, 16) if value.startswith("0x") else int(value)

            calculated_value = 0
            if value > 0:
                calculated_value = (value & -value).bit_length()
        except (ValueError, TypeError):
            if isinstance(value, str):
                return
            calculated_value = -1

        # For T0xD9 combo devices, map each drum by its prefix (da/db/dc)
        effective_type = self.device_type
        if self.device_type == 0xD9:
            if progress_key.startswith("da_"):
                effective_type = 0xDA
            elif progress_key.startswith("db_"):
                effective_type = 0xDB
            elif progress_key.startswith("dc_"):
                effective_type = 0xDC

        if effective_type == 0xDA:
            progress_map = {
                0: "idle",
                1: "spin",
                2: "rinse",
                3: "wash",
                4: "weight",
                5: "unknown",
                6: "dry",
                7: "soak",
            }
        elif effective_type == 0xDB:
            progress_map = {
                0: "idle",
                1: "spin",
                2: "rinse",
                3: "wash",
                4: "pre-wash",
                5: "dry",
                6: "weight",
                7: "spin_high",
                8: "unknown",
            }
        elif effective_type == 0xDC:
            progress_map = {
                0: "idle",
                1: "dry",
                2: "anti-wrinkle",
                3: "cold_air",
            }
        else:
            return
        data[progress_key] = progress_map.get(calculated_value, "unknown")

    def prepare_control_data(self, control: dict, current_data: dict = None) -> dict:
        """Prepare control data with device-specific requirements."""
        if self.device_type == 0xD9:
            # Determine drum prefix from location field
            if "da_location" in control:
                control["bucket"] = "da"
            elif "dc_location" in control:
                control["bucket"] = "dc"
            else:
                control["bucket"] = "db"
                if "db_location" not in control and current_data and "db_location" in current_data:
                    control["db_location"] = current_data["db_location"]
        elif self.device_type == 0xE1:
            control = self._prepare_dishwasher_control(control, current_data)
        return control

    def _prepare_dishwasher_control(
        self,
        control: dict,
        current_data: dict | None = None,
    ) -> dict:
        if not any(key in control for key in _DISHWASHER_COMPOSITE_KEYS):
            return control

        current_data = current_data or {}
        prepared = control.copy()

        if "mode" in prepared:
            prepared.setdefault("wash_region", 3)
            prepared.setdefault("additional", 0)

        if "mode" not in prepared:
            prepared["mode"] = self._normalize_dishwasher_mode(current_data.get("mode"))

        if "work_status" not in prepared:
            prepared["work_status"] = self._normalize_dishwasher_work_status(
                current_data.get("work_status")
            )

        if "wash_region" not in prepared:
            prepared["wash_region"] = self._normalize_dishwasher_int(
                current_data.get("wash_region"), 3
            )

        if "additional" not in prepared:
            prepared["additional"] = self._normalize_dishwasher_int(
                current_data.get("additional"), 0
            )

        if "more_dry" not in prepared:
            prepared["more_dry"] = self._normalize_dishwasher_int(
                current_data.get("more_dry"), 0
            )

        if "door_auto_open" not in prepared:
            prepared["door_auto_open"] = self._normalize_dishwasher_int(
                current_data.get("door_auto_open"), 0
            )

        return prepared

    def _normalize_dishwasher_work_status(self, value: Any) -> str:
        return value if value in {"cancel", "work", "order"} else "cancel"

    def _normalize_dishwasher_mode(self, value: Any) -> str:
        if isinstance(value, str) and value:
            return value
        return "neutral_gear"

    def _normalize_dishwasher_int(self, value: Any, default: int) -> int:
        if isinstance(value, bool):
            return int(value)
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _apply_dishwasher_pending_state(
        self,
        data: dict,
        recent_controls: dict,
        control_timeout: float,
    ) -> None:
        work_status = data.get("work_status")
        mode = data.get("mode")

        # The local protocol reports pre-start selections as cancel + neutral_gear.
        # Keep recent user selections visible in HA until the device reports a real running state.
        if work_status not in {"cancel", "power_off"} or mode != "neutral_gear":
            return

        for key in _DISHWASHER_PENDING_KEYS:
            recent = recent_controls.get(key)
            if not recent:
                continue

            value, timestamp = recent
            if timestamp is None:
                continue

            # Device.py cleans expired controls after this hook, so re-check here.
            if time.time() - timestamp >= control_timeout:
                continue

            if key == "mode" and value == "neutral_gear":
                continue

            data[key] = value

    def adjust_b3_function_control(self, data: dict) -> None:
        """For T0x9C devices, map b3_upstair_status to b3_function_control."""
        if "b3_upstair_status" not in data:
            return

        status_map = {
            "power_off": 1,
            "uperization": 2,
            "drying": 4,
        }
        mapped = status_map.get(data["b3_upstair_status"])
        if mapped is not None:
            data["b3_function_control"] = mapped

    def adjust_standby_status_for_wash(self, data: dict) -> None:
        """For T0xED devices, prevent standby_status update when wash is on."""
        if self.device_type != 0xED:
            return

        if "standby_status" not in data or "wash" not in data:
            return

        wash_status = data.get("wash")
        if wash_status == "on" or wash_status == 1:
            if self._last_standby_status is not None:
                data["standby_status"] = self._last_standby_status
        else:
            self._last_standby_status = data.get("standby_status")

    def adjust_high_float_type_when_filter_on(self, data: dict) -> None:
        """For T0xED devices, adjust high_float_type when filter is on.

        When the device reports both high_float_type and filter attributes,
        and filter is 'on', keep the previous high_float_type value instead
        of updating it with the new (possibly invalid) device value.
        Other attributes are not affected.
        """
        if self.device_type != 0xED:
            return

        if "high_float_type" not in data or "filter" not in data:
            return

        filter_value = data.get("filter")
        if filter_value == "on" or filter_value == 1:
            if self._last_high_float_type is not None:
                data["high_float_type"] = self._last_high_float_type
        else:
            self._last_high_float_type = data.get("high_float_type")

    def adjust_ed_temperature(self, data: dict, status: dict) -> None:
        """For T0xED devices, filter out invalid temperature readings (0).

        Preserves the last valid temperature value for input_temperature_Sensing
        and env_temperature sensors.
        """
        if self.device_type != 0xED:
            return

        for key, last_valid_key in [
            ("input_temperature_Sensing", "_last_valid_input_temp"),
            ("env_temperature", "_last_valid_env_temp")
        ]:
            if key not in status:
                continue

            value = status[key]
            if value is not None and value != 0:
                data[key] = value
                setattr(self, last_valid_key, value)
            elif getattr(self, last_valid_key) is not None:
                data[key] = getattr(self, last_valid_key)

    def adjust_bath_heater_direction(self, data: dict) -> None:
        """For T0x26 devices, map direction values to nearest multiple of 10.

        Bath heater direction values should be multiples of 10 between 60-120,
        or 253 for swing mode. This method maps arbitrary integer values to
        the nearest configured value (60, 70, 80, 90, 100, 110, 120).
        """
        direction_keys = [
            "heating_direction",
            "bath_direction",
            "blowing_direction",
            "drying_direction",
            "soft_wind_direction"
        ]

        for key in direction_keys:
            if key not in data:
                continue

            value = data[key]
            # Keep swing mode (253) unchanged
            try:
                value_num = int(value) if isinstance(value, str) else value
                if value_num == 253:
                    continue

                # Map to nearest multiple of 10 within valid range
                mapped = round(value_num / 10) * 10
                result = str(max(60, min(120, mapped)))
                data[key] = result
            except (ValueError, TypeError):
                # If conversion fails, keep original value
                pass
