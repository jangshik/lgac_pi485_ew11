import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACMode,
    FAN_HIGH,
    FAN_MEDIUM,
    FAN_LOW,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from .const import DOMAIN, make_control_packet

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """치환 맵 구조를 순회하며 요청된 고정 ID 포맷대로 엔티티 일괄 등록"""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    writer = entry_data["writer"]
    mapping_dict = entry_data["mapping"]
    piping_type = entry_data["piping_type"]

    entities = []
    # entity_suffix: 생성할 주소 이름 ("00", "01" 등)
    # real_room_id: 실제 통신 버스 라인에서의 주소값 (1, 2 등)
    for entity_suffix, real_room_id in mapping_dict.items():
        entities.append(LGAirConditionerEntity(writer, entity_suffix, real_room_id, piping_type))
    
    async_add_entities(entities)
    return True


class LGAirConditionerEntity(ClimateEntity):
    """치환 매핑 및 단/다배관 설정이 통합된 실내기 엔티티"""
    
    def __init__(self, writer, entity_suffix: str, real_room_id: int, piping_type: str):
        self._writer = writer
        self._real_room_id = real_room_id
        self._piping_type = piping_type
        
        # 🌟 사용자가 요구한 대시보드 호환용 고정 엔티티 ID 강제 부여 ("00", "01" 등)
        self.entity_id = f"climate.lgac_{entity_suffix.lower()}_cm"
        self._attr_unique_id = f"lgac_{entity_suffix.lower()}_cm"
        self._attr_name = f"LG AirCon {entity_suffix.upper()}"
        
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
        )
        self._attr_hvac_modes = [
            HVACMode.OFF, HVACMode.COOL, HVACMode.FAN_ONLY, 
            HVACMode.DRY, HVACMode.HEAT, HVACMode.AUTO
        ]
        self._attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        
        # 상태값 기본값 설정
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
        # 🌟 제어 패킷 생성 시 '기존 명칭'이 아닌 '치환된 실제 하드웨어 주소'(_real_room_id) 사용
        packet = make_control_packet(self._real_room_id, mode_hex, temp)
        
        if self._writer:
            try:
                self._writer.write(packet)
                await self._writer.drain()
                _LOGGER.debug(f"[{self.entity_id}] Sent to real ID {self._real_room_id:02X}: {packet.hex()}")
            except Exception as e:
                _LOGGER.error(f"[{self.entity_id}] Communication failure: {e}")

    def update_status_from_packet(self, packet_bytes: bytes):
        """(향후 확장용) 외부 수신 리스너로부터 전달받은 버스 패킷 동기화 로직"""
        # 단배관/다배관 유형별 수신 인덱스 차이 예외 처리 구문 뼈대
        if self._piping_type == "multi":
            # 다배관 파싱 로직: pipe1, pipe2 인덱스를 모두 조회하여 온도 추출 
            pass
        else:
            # 단배관 파싱 로직: pipe2 인덱스 생략 및 예외 바이패스 [cite: 178, 233]
            pass