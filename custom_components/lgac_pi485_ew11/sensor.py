import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    entry_data = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for device in entry_data["devices"].values():
        entities.append(LGACSensor(device, "pipe_in", "액관 온도", UnitOfTemperature.CELSIUS, "mdi:pipe"))
        entities.append(LGACSensor(device, "pipe_out", "가스관 온도", UnitOfTemperature.CELSIUS, "mdi:pipe"))
        entities.append(LGACSensor(device, "error_code", "에러 코드", None, "mdi:alert-circle"))
        entities.append(LGACSensor(device, "odu_total_load", "실외기 총 부하", None, "mdi:speedometer"))
        # 🌟 요청하신 실시간 무선 패킷 모니터링 센서 추가
        entities.append(LGACSensor(device, "raw_packet", "현재 에어컨 패킷", None, "mdi:network-packet"))
    
    async_add_entities(entities)
    return True

class LGACSensor(SensorEntity):
    def __init__(self, device, sensor_type, name_suffix, unit, icon):
        self.device = device
        self.sensor_type = sensor_type
        
        self.entity_id = f"sensor.lgac_{device.entity_idx.lower()}_{sensor_type}"
        self._attr_unique_id = f"lgac_sensor_{device.entity_idx.lower()}_{sensor_type}"
        self._attr_name = f"{device.name} {name_suffix}"
        
        # 🌟 기기 분리를 위해 climate와 동일한 디바이스 인포 바인딩
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"lgac_device_{device.real_id}")},
        }
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

    async def async_added_to_hass(self):
        self.device.register_listener(self.async_write_ha_state)

    @property
    def native_value(self):
        if self.sensor_type == "pipe_in": return self.device.pipe_in
        if self.sensor_type == "pipe_out": return self.device.pipe_out
        if self.sensor_type == "error_code": return self.device.error_code
        if self.sensor_type == "odu_total_load": return self.device.odu_total_load
        if self.sensor_type == "raw_packet": return self.device.raw_packet # 🌟 헥사 데이터 출력
        return None