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
    """플랫폼 초기화 시 콜백 함수 바인딩 (자동 감지 리스너가 호출할 함수)"""
    hass.data[DOMAIN][entry.entry_id]["async_add_entities_fn"] = async_add_entities
    return True


class LGAirConditionerEntity(ClimateEntity):
    """LG 에어컨 개별 실내기 엔티티"""
    
    def __init__(self, writer, room_id: int):
        self._writer = writer
        self._room_id = room_id
        
        # 16진수 2자리 소문자 포맷팅 (0 -> 00, 1 -> 01, 10 -> 0a ...)
        room_hex_str = f"{room_id:02x}"
        
        # 🌟 사용자가 요청한 엔티티 ID 포맷 (climate.lgac_xx_cm) 고정
        self.entity_id = f"climate.lgac_{room_hex_str}_cm"
        
        # 기기 고유 ID 및 UI 표시 이름 설정
        self._attr_unique_id = f"lgac_{room_hex_str}_cm"
        self._attr_name = f"LG AirCon {room_hex_str.upper()}"
        
        # 기능 및 지원 모드 설정
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
        )
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.COOL,
            HVACMode.FAN_ONLY,
            HVACMode.DRY,
            HVACMode.HEAT,
            HVACMode.AUTO,
        ]
        self._attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        
        # 기본 상태값 초기화 (향후 수신 패킷 파싱 시 이 값들을 업데이트해야 함)
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = 24.0
        self._attr_current_temperature = 26.0
        self._attr_fan_mode = FAN_MEDIUM


    async def async_set_hvac_mode(self, hvac_mode):
        """HVAC(냉난방) 모드 변경 시 호출"""
        self._attr_hvac_mode = hvac_mode
        
        # TODO: 엑셀 시트 규칙에 맞게 모드 헥사값 정밀 매핑 필요
        # (임시 예시: COOL은 0x48, 나머지는 0x02)
        mode_hex = 0x48 if hvac_mode == HVACMode.COOL else 0x02
        
        await self._send_control(mode_hex, int(self._attr_target_temperature))
        self.async_write_ha_state()


    async def async_set_temperature(self, **kwargs):
        """설정 온도 변경 시 호출"""
        if (target_temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = target_temp
            
            mode_hex = 0x48 if self._attr_hvac_mode == HVACMode.COOL else 0x02
            await self._send_control(mode_hex, int(target_temp))
            self.async_write_ha_state()


    async def async_set_fan_mode(self, fan_mode):
        """풍속 변경 시 호출"""
        self._attr_fan_mode = fan_mode
        
        # TODO: 풍속(fan_mode)에 따른 제어 패킷 생성 로직 추가 필요
        # mode_hex = ... 
        # await self._send_control(mode_hex, int(self._attr_target_temperature))
        
        self.async_write_ha_state()


    async def _send_control(self, mode_hex: int, temp: int):
        """EW11 소켓으로 최종 조합된 패킷 전송"""
        packet = make_control_packet(self._room_id, mode_hex, temp)
        
        if self._writer:
            try:
                self._writer.write(packet)
                await self._writer.drain()
                _LOGGER.debug(f"[Room {self._room_id:02x}] Sent packet: {packet.hex()}")
            except Exception as e:
                _LOGGER.error(f"[Room {self._room_id:02x}] Packet send failed: {e}")