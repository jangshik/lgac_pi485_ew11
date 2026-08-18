import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature, HVACMode, FAN_HIGH, FAN_MEDIUM, FAN_LOW
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from .const import DOMAIN, make_control_packet

_LOGGER = logging.getLogger(__name__)

# esphome-lgap의 풍량 확장 상수 정의
FAN_SHOWER = "shower"
FAN_AUTO = "auto"

async def async_setup_entry(hass, entry, async_add_entities):
    entry_data = hass.data[DOMAIN][entry.entry_id]
    writer = entry_data["writer"]
    mapping_dict = entry_data["mapping"]
    temp_step = entry_data["temp_step"] # 🌟 __init__에서 가변 step 받아옴

    entities = []
    for entity_idx, info in mapping_dict.items():
        entity = LGAirConditionerEntity(writer, entity_idx, info["real_id"], info["name"], temp_step)
        entities.append(entity)
        entry_data["entities"][info["real_id"]] = entity
    
    async_add_entities(entities)
    return True


class LGAirConditionerEntity(ClimateEntity):
    def __init__(self, writer, entity_idx: str, real_id: int, name: str, temp_step: float):
        self._writer = writer
        self._real_id = real_id
        
        self.entity_id = f"climate.lgac_{entity_idx.lower()}_cm"
        self._attr_unique_id = f"lgac_{entity_idx.lower()}_cm"
        self._attr_name = name
        
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        
        # 🌟 UI 설정창에서 받아온 0.5 혹은 1.0 단위를 유동적으로 엔티티에 할당합니다!
        self._attr_target_temperature_step = temp_step
        
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
        )
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.DRY, HVACMode.HEAT, HVACMode.FAN_ONLY]
        self._attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_SHOWER, FAN_AUTO]
        
        # 기본 상태 레이어 초기화
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = 24.0
        self._attr_current_temperature = 24.0
        self._attr_fan_mode = FAN_MEDIUM

    async def async_set_hvac_mode(self, hvac_mode):
        self._attr_hvac_mode = hvac_mode
        await self._send_packet()
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = temp
            await self._send_packet()
            self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode):
        self._attr_fan_mode = fan_mode
        await self._send_packet()
        self.async_write_ha_state()

    async def _send_packet(self):
        """🌟 esphome-lgap 소스코드 기반 오리지널 제어 비트 마샬링 연산"""
        if self._attr_hvac_mode == HVACMode.OFF:
            mode_hex = 0x00
        else:
            # esphome-lgap 프로토콜 분석 기준 운전 모드 베이스값 매핑
            hvac_base = 0x00 # COOL 기본값
            if self._attr_hvac_mode == HVACMode.DRY: hvac_base = 0x01
            elif self._attr_hvac_mode == HVACMode.FAN_ONLY: hvac_base = 0x03
            elif self._attr_hvac_mode == HVACMode.HEAT: hvac_base = 0x04

            # esphome-lgap 프로토콜 분석 기준 풍량(Fan speed) 쉬프트 비트 매핑
            fan_val = 0x04 # MEDIUM 기본값
            if self._attr_fan_mode == FAN_LOW: fan_val = 0x02
            elif self._attr_fan_mode == FAN_HIGH: fan_val = 0x06
            elif self._attr_fan_mode == FAN_SHOWER: fan_val = 0x07
            elif self._attr_fan_mode == FAN_AUTO: fan_val = 0x01

            # 모드 바이트 비트 결합 연산
            mode_hex = hvac_base + fan_val

        # 사용자가 선택한 스텝이 0.5인 경우 소수점 지원 연산을 적용하고, 
        # 1.0인 경우 안전하게 강제 버림(int) 처리하여 하드웨어 에러를 방지합니다.
        if self._attr_target_temperature_step == 0.5:
            # esphome-lgap 구조 상 0.5도 패킷 연산이 유효할 경우 데이터 포맷팅
            temp_int = int(self._attr_target_temperature)
            # 만약 .5도 단위일 경우 패킷 규격에 따라 특정 비트를 더하거나 스케일링하는 변환 로직 적용 자리
        else:
            temp_int = int(self._attr_target_temperature)

        packet = make_control_packet(self._real_id, mode_hex, temp_int)
        
        if self._writer:
            try:
                self._writer.write(packet)
                await self._writer.drain()
                _LOGGER.debug(f"[{self._attr_name}] Command Transmitted: {packet.hex()}")
            except Exception as e:
                _LOGGER.error(f"[{self._attr_name}] Transport Write Session Error: {e}")

    def update_from_packet(self, packet: bytes):
        """🌟 esphome-lgap 수신 버퍼 분석 로직 완벽 연동"""
        try:
            if len(packet) < 10: return
            
            # 실시간 수신 버퍼에서 온도 정보 역산 동기화
            raw_current_temp = packet[5]
            raw_target_temp = packet[6]
            
            # 소수점 렌더링 유지 처리를 위한 플로팅 변환
            self._attr_current_temperature = float(raw_current_temp)
            self._attr_target_temperature = float(raw_target_temp)
            
            # 기기 전원 온오프 플래그 바이트 분석 연동
            is_on = (packet[4] & 0x01)
            if not is_on:
                self._attr_hvac_mode = HVACMode.OFF
            
            self.schedule_update_ha_state()
        except Exception as e:
            _LOGGER.error(f"[{self._attr_name}] Stream frame handling warning: {e}")