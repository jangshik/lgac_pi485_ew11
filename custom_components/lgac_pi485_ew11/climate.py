import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature, HVACMode, FAN_HIGH, FAN_MEDIUM, FAN_LOW
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from .const import DOMAIN, make_control_packet

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    entry_data = hass.data[DOMAIN][entry.entry_id]
    writer = entry_data["writer"]
    mapping_dict = entry_data["mapping"]
    piping_type = entry_data["piping_type"]

    entities = []
    for entity_suffix, real_room_id in mapping_dict.items():
        entity = LGAirConditionerEntity(writer, entity_suffix, real_room_id, piping_type)
        entities.append(entity)
        
        # 🌟 __init__.py의 패킷 리스너가 참조할 수 있도록 실제 ID-객체 매핑 등록
        entry_data["entities"][real_room_id] = entity
    
    async_add_entities(entities)
    return True


class LGAirConditionerEntity(ClimateEntity):
    def __init__(self, writer, entity_suffix: str, real_room_id: int, piping_type: str):
        self._writer = writer
        self._real_room_id = real_room_id
        self._piping_type = piping_type
        
        self.entity_id = f"climate.lgac_{entity_suffix.lower()}_cm"
        self._attr_unique_id = f"lgac_{entity_suffix.lower()}_cm"
        self._attr_name = f"LG AirCon {entity_suffix.upper()}"
        
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
        )
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.FAN_ONLY, HVACMode.DRY, HVACMode.HEAT, HVACMode.AUTO]
        self._attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        
        # 엔티티 기본 상태값
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = 24.0
        self._attr_current_temperature = 26.0
        self._attr_fan_mode = FAN_MEDIUM

    async def async_set_hvac_mode(self, hvac_mode):
        self._attr_hvac_mode = hvac_mode
        mode_hex = 0x48 if hvac_mode == HVACMode.COOL else 0x02
        await self._send_control(mode_hex, int(self._attr_target_temperature))
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        if (target_temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = target_temp
            mode_hex = 0x48 if self._attr_hvac_mode == HVACMode.COOL else 0x02
            await self._send_control(mode_hex, int(target_temp))
            self.async_write_ha_state()

    async def _send_control(self, mode_hex: int, temp: int):
        packet = make_control_packet(self._real_room_id, mode_hex, temp)
        if self._writer:
            try:
                self._writer.write(packet)
                await self._writer.drain()
            except Exception as e:
                _LOGGER.error(f"[{self.entity_id}] Send failed: {e}")

    # 🌟 실시간 수신 패킷 파싱 후 HA UI 상태값 업데이트 함수
    def update_status_from_packet(self, packet_bytes: bytes):
        """백그라운드 스니퍼가 유효한 패킷을 던져주면 실시간 갱신 호출"""
        try:
            # 원본 문서 데이터에 근거한 온도 및 가동 상태 추출 (바이트 인덱스는 기종별 조율 필요)
            # 예시: packet_bytes[5]가 실내 온도 데이터일 경우
            room_temp = packet_bytes[5] 
            target_temp = packet_bytes[6]
            
            # 단배관 / 다배관 유형에 따른 예외 처리 레이어 적용
            if self._piping_type == "multi":
                # 다배관 구조일 때 가스관/액관 개별 온도 추가 가공 처리 파트
                pass
            
            # 내부 속성 갱신
            self._attr_current_temperature = float(room_temp)
            self._attr_target_temperature = float(target_temp)
            
            # HA 코어에 상태 변경 사실을 실시간 브로드캐스트하여 대시보드 UI를 즉시 갱신
            self.schedule_update_ha_state()
            _LOGGER.debug(f"[{self.entity_id}] Real-time UI pushed. Temp: {room_temp}°C")
            
        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Packet parse error: {e}")