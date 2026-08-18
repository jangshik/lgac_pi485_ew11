import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """esphome-lgap의 모든 하드웨어 모니터링 센서를 한 번에 생성"""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    devices = entry_data["devices"]

    entities = []
    for device in devices.values():
        # 1. 온/오프 상태 플래그 센서
        entities.append(LGACSensor(device, "pipe_in", "액관 온도 (Pipe In)", UnitOfTemperature.CELSIUS, "mdi:pipe"))
        entities.append(LGACSensor(device, "pipe_out", "가스관 온도 (Pipe Out)", UnitOfTemperature.CELSIUS, "mdi:pipe"))
        
        # 2. 시스템 에러 진단 코드 센서
        entities.append(LGACSensor(device, "error_code", "에러 코드 (Error)", None, "mdi:alert-circle"))
        
        # 3. LonWorks 연동 지표 - 컴프레서 및 기기 효율 부하 센서 전체 복원
        entities.append(LGACSensor(device, "zone_active_load", "실내기 가동 부하 지수", None, "mdi:chart-bell-curve"))
        entities.append(LGACSensor(device, "zone_power_state_flag", "컴프레서 유휴 상태 플래그", None, "mdi:power-setting"))
        entities.append(LGACSensor(device, "zone_design_load_index", "정격 설계 용량 가중치", None, "mdi:weight"))
        entities.append(LGACSensor(device, "odu_total_load", "실외기 총 열부하 지수 (ODU Total Load)", None, "mdi:speedometer"))
    
    async_add_entities(entities)
    return True

class LGACSensor(SensorEntity):
    def __init__(self, device, sensor_type, name_suffix, unit, icon):
        self.device = device
        self.sensor_type = sensor_type
        
        # 고정 엔티티 ID 규격 생성 (예: sensor.lgac_01_odu_total_load)
        self.entity_id = f"sensor.lgac_{device.entity_idx.lower()}_{sensor_type}"
        self._attr_unique_id = f"lgac_sensor_{device.entity_idx.lower()}_{sensor_type}"
        self._attr_name = f"{device.name} {name_suffix}"
        
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

    async def async_added_to_hass(self):
        self.device.register_listener(self.async_write_ha_state)

    @property
    def native_value(self):
        """중앙 데이터 상태 허브 객체에서 자신의 변수 추출"""
        if self.sensor_type == "pipe_in": return self.device.pipe_in
        if self.sensor_type == "pipe_out": return self.device.pipe_out
        if self.sensor_type == "error_code": return self.device.error_code
        if self.sensor_type == "zone_active_load": return self.device.zone_active_load
        if self.sensor_type == "zone_power_state_flag": return self.device.zone_power_state_flag
        if self.sensor_type == "zone_design_load_index": return self.device.zone_design_load
        if self.sensor_type == "odu_total_load": return self.device.odu_total_load
        return None