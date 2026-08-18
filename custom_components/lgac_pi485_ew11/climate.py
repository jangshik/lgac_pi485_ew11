import Voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature, HVACMode, FAN_HIGH, FAN_MEDIUM, FAN_LOW
)
from homeassistant.const import CONF_HOST, CONF_PORT, ATTR_TEMPERATURE, UnitOfTemperature
from .__init__ import LGACSocketManager
from .const import make_control_packet

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_PORT): cv.port,
    vol.Required("room_id"): cv.positive_int, # 16진수 번호 (예: 0, 1, 2...)
})

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    ip = config.get(CONF_HOST)
    port = config.get(CONF_PORT)
    room_id = config.get("room_id")
    
    socket_mgr = LGACSocketManager(ip, port)
    await socket_mgr.connect()
    
    async_add_entities([LGAirConditionerEntity(socket_mgr, room_id)])

class LGAirConditionerEntity(ClimateEntity):
    """LG 에어컨 최신 표준 엔티티 구체화"""
    def __init__(self, socket_mgr, room_id):
        self._socket = socket_mgr
        self._room_id = room_id
        self._attr_name = f"LG AirCon {room_id:02X}"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
        )
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.FAN_ONLY, HVACMode.DRY]
        self._attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        
        # 현재 상태 초기 기본값 설정
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = 24.0
        self._attr_fan_mode = FAN_MEDIUM

    async def async_set_hvac_mode(self, hvac_mode):
        """HVAC 모드 변경시 EW11로 소켓 패킷 전송"""
        self._attr_hvac_mode = hvac_mode
        # 문서 속성 맵핑 기초 데이터 기반 헥사 조합 (예시값)
        mode_hex = 0x48 if hvac_mode == HVACMode.COOL else 0x02 
        await self._send_current_state(mode_hex, int(self._attr_target_temperature))
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        """목표 온도 설정 변경시 패킷 전송"""
        if (target_temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = target_temp
            mode_hex = 0x48 if self._attr_hvac_mode == HVACMode.COOL else 0x02
            await self._send_current_state(mode_hex, int(target_temp))
            self.async_write_ha_state()

    async def _send_current_state(self, mode_hex, temp):
        # 엑셀 시트 규칙에 맞게 온도 인덱스 매핑 필요 (여기서는 예시로 일반 int 처리)
        packet = make_control_packet(self._room_id, mode_hex, temp)
        await self._socket.send_packet(packet)