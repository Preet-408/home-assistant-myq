from collections.abc import Mapping
from typing import cast

from .exceptions import MyQApiError
from .models import GarageDoor, MyQCamera, MyQLight


def parse_garage_door(
    account_id: str,
    item: Mapping[str, object],
    cameras: Mapping[str, MyQCamera],
) -> GarageDoor:
    """Decode an opener and associate its camera from the same account."""
    serial_number = item.get("serial_number")
    name = item.get("name")
    model = item.get("device_model")
    raw_state = item.get("state")
    if not isinstance(serial_number, str):
        raise MyQApiError("MyQ returned a garage door without a serial number")
    if raw_state is not None and not isinstance(raw_state, dict):
        raise MyQApiError("MyQ returned an invalid garage door state")
    state = cast(dict[str, object], raw_state or {})
    door_state = state.get("door_state")
    online = state.get("online")
    battery_backup_state = state.get("battery_backup_state")
    in_vacation_mode = state.get("in_vacation_mode")
    attached_worklight_on = state.get("attached_worklight_on")
    raw_fault_codes = state.get("active_fault_codes")
    absolute_cycle_count = state.get("absolute_cycle_count")
    service_cycle_count = state.get("service_cycle_count")
    last_device_activation_source = state.get("last_device_activation_source")
    camera_serial_number = state.get("attached_camera_serial_number")
    fault_codes = (
        tuple(code for code in raw_fault_codes if isinstance(code, str))
        if isinstance(raw_fault_codes, list)
        else ()
    )
    return GarageDoor(
        account_id=account_id,
        serial_number=serial_number,
        name=name if isinstance(name, str) else serial_number,
        device_model=model if isinstance(model, str) else None,
        door_state=door_state if isinstance(door_state, str) else None,
        online=online if isinstance(online, bool) else None,
        battery_backup_state=(
            battery_backup_state if isinstance(battery_backup_state, str) else None
        ),
        in_vacation_mode=(in_vacation_mode if isinstance(in_vacation_mode, bool) else None),
        attached_worklight_on=(
            attached_worklight_on if isinstance(attached_worklight_on, bool) else None
        ),
        active_fault_codes=fault_codes,
        absolute_cycle_count=(
            absolute_cycle_count
            if isinstance(absolute_cycle_count, int) and not isinstance(absolute_cycle_count, bool)
            else None
        ),
        service_cycle_count=(
            service_cycle_count
            if isinstance(service_cycle_count, int) and not isinstance(service_cycle_count, bool)
            else None
        ),
        last_device_activation_source=(
            last_device_activation_source
            if isinstance(last_device_activation_source, str)
            else None
        ),
        camera=(
            cameras.get(camera_serial_number, MyQCamera(camera_serial_number))
            if isinstance(camera_serial_number, str) and camera_serial_number
            else None
        ),
    )


def parse_light(account_id: str, item: Mapping[str, object]) -> MyQLight:
    """Decode a standalone light without inferring unsupported power states."""
    serial_number = item.get("serial_number")
    if not isinstance(serial_number, str) or not serial_number:
        raise MyQApiError("MyQ returned a light without a serial number")
    raw_state = item.get("state")
    if raw_state is not None and not isinstance(raw_state, dict):
        raise MyQApiError("MyQ returned an invalid light state")
    state = cast(dict[str, object], raw_state or {})
    lamp_state = state.get("lamp_state")
    online = state.get("online")
    name = item.get("name")
    model = item.get("device_model")
    return MyQLight(
        account_id=account_id,
        serial_number=serial_number,
        name=name if isinstance(name, str) and name else serial_number,
        device_model=model if isinstance(model, str) else None,
        lamp_state=lamp_state.lower() if isinstance(lamp_state, str) else None,
        online=online if isinstance(online, bool) else None,
    )
