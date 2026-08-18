import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    entities = []
    for device in devices.values():
        entities.append(LGACSensor(device, "pipe_in", "배관 입구 온도", UnitOfTemperature.CELSIUS, "mdi:pipe"))
        entities.append(LGACSensor(device, "pipe_out", "배관 출구 온도", UnitOfTemperature.CELSIUS, "mdi:pipe"))
        entities.append(LGACSensor(device, "error_code", "에러 코드", None, "mdi:alert-circle"))
        entities.append(LGACSensor(device, "zone_active_load", "실내기 가동 부하", None, "mdi:chart-bell-curve"))
        entities.append(LGACSensor(device, "zone_power_state_flag", "컴프레서 플래그", None, "mdi:power-setting"))
        entities.append(LGACSensor(device, "zone_design_load_index", "정격 용량 가중치", None, "mdi:weight"))
        entities.append(LGACSensor(device, "odu_total_load", "실외기 총 열부하", None, "mdi:speedometer"))
        entities.append(LGACSensor(device, "timer_remaining", "남은 수면 타이머", "min", "mdi:timer-sand"))
        entities.append(LGACSensor(device, "raw_packet", "수신 패킷", None, "mdi:network-packet"))
    async_add_entities(entities)
    return True

class LGACSensor(SensorEntity):
    def __init__(self, device, sensor_type, name_suffix, unit, icon):
        self.device = device
        self.sensor_type = sensor_type
        self.entity_id = f"sensor.lgac_{device.entity_idx.lower()}_{sensor_type}"
        self._attr_unique_id = f"lgac_sensor_{device.entity_idx.lower()}_{sensor_type}"
        self._attr_name = f"{device.name} {name_suffix}"
        self._attr_device_info = {"identifiers": {(DOMAIN, f"lgac_device_{device.real_id}")}}
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

    async def async_added_to_hass(self):
        self.device.register_listener(self.async_write_ha_state)

    @property
    def native_value(self):
        if self.sensor_type == "pipe_in": return round(self.device.pipe_in, 2)
        if self.sensor_type == "pipe_out": return round(self.device.pipe_out, 2)
        if self.sensor_type == "error_code": return self.device.error_code
        if self.sensor_type == "zone_active_load": return self.device.zone_active_load
        if self.sensor_type == "zone_power_state_flag": return self.device.zone_power_state_flag
        if self.sensor_type == "zone_design_load_index": return self.device.zone_design_load
        if self.sensor_type == "odu_total_load": return self.device.odu_total_load
        if self.sensor_type == "timer_remaining": return self.device.timer_remaining
        if self.sensor_type == "raw_packet": return self.device.raw_packet
        return None