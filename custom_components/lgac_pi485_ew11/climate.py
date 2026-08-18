import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature, HVACMode, FAN_HIGH, FAN_MEDIUM, FAN_LOW
)
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN, make_control_packet

_LOGGER = logging.getLogger(__name__)
FAN_AUTO = "auto"

async def async_setup_entry(hass, entry, async_add_entities):
    entry_data = hass.data[DOMAIN][entry.entry_id]
    devices = entry_data["devices"]
    entities = [LGAirConditionerClimate(entry.entry_id, device) for device in devices.values()]
    async_add_entities(entities)
    return True

class LGAirConditionerClimate(ClimateEntity):
    def __init__(self, entry_id, device):
        self.entry_id = entry_id
        self.device = device
        
        self.entity_id = f"climate.lgac_{device.entity_idx.lower()}_cm"
        self._attr_unique_id = f"lgac_climate_{device.entity_idx.lower()}"
        self._attr_name = device.name
        
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_target_temperature_step = device.temp_step
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
        
        # 🌟 난방 유무(has_heat)에 따라 지원 모드 동적 조합
        if device.has_heat:
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.DRY, HVACMode.HEAT, HVACMode.FAN_ONLY]
        else:
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY] # Heat 제거
            
        self._attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_AUTO]

    async def async_added_to_hass(self):
        self.device.register_listener(self.async_write_ha_state)

    @property
    def hvac_mode(self): return self.device.hvac_mode
    @property
    def current_temperature(self): return self.device.current_temp
    @property
    def target_temperature(self): return self.device.target_temp
    @property
    def fan_mode(self): return self.device.fan_mode

    # 🌟 extra_state_attributes 내부에 기기 전용 플래그 상태(차일드락, 음이온) 복원
    @property
    def extra_state_attributes(self):
        return {
            "child_lock_status": "on" if self.device.child_lock else "off",
            "plasma_ion_status": "on" if self.device.plasma_ion else "off",
            "auto_swing_status": "on" if self.device.swing_state else "off"
        }

    async def async_set_hvac_mode(self, hvac_mode): await self._send_packet(override_hvac=hvac_mode)
    async def async_set_temperature(self, **kwargs):
        if "temperature" in kwargs: await self._send_packet(override_temp=kwargs["temperature"])
    async def async_set_fan_mode(self, fan_mode): await self._send_packet(override_fan=fan_mode)

    async def _send_packet(self, override_hvac=None, override_temp=None, override_fan=None):
        hvac = override_hvac or self.device.hvac_mode
        temp = override_temp or self.device.target_temp
        fan = override_fan or self.device.fan_mode

        turn_on = hvac != HVACMode.OFF
        mode_hex = 0 
        if hvac == HVACMode.DRY: mode_hex = 1
        elif hvac == HVACMode.FAN_ONLY: mode_hex = 2
        elif hvac == HVACMode.HEAT: mode_hex = 4

        fan_hex = 2 
        if fan == FAN_LOW: fan_hex = 1
        elif fan == FAN_HIGH: fan_hex = 3
        elif fan == FAN_AUTO: fan_hex = 4

        packet = make_control_packet(self.device.real_id, mode_hex, fan_hex, temp, turn_on)
        writer = self.hass.data[DOMAIN][self.entry_id]["writer"]
        if writer:
            try:
                writer.write(packet)
                await writer.drain()
            except Exception as e: _LOGGER.error(f"명령 전송 실패: {e}")