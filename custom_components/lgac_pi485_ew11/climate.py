import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature, HVACMode, FAN_HIGH, FAN_MEDIUM, FAN_LOW, SWING_OFF, SWING_VERTICAL
)
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
FAN_AUTO = "auto"

async def async_setup_entry(hass, entry, async_add_entities):
    entry_data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LGAirConditionerClimate(entry.entry_id, dev) for dev in entry_data["devices"].values()])
    return True

class LGAirConditionerClimate(ClimateEntity):
    def __init__(self, entry_id, device):
        self.entry_id = entry_id
        self.device = device
        
        self.entity_id = f"climate.lgac_{device.entity_idx.lower()}_cm"
        self._attr_unique_id = f"lgac_climate_{device.entity_idx.lower()}"
        self._attr_name = device.name
        
        # 🌟 [기기 분리 핵심] 이 속성을 선언하면 모든 엔티티가 에어컨 기기별 카드로 묶입니다.
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"lgac_device_{device.real_id}")},
            "name": device.name,
            "manufacturer": "LG",
            "model": f"PI485 AC (HW ID: 0x{device.real_id:02X})",
        }
        
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_target_temperature_step = device.temp_step
        
        # 🌟 스윙 모드(SWING_MODE) 피처 플래그 결합
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | 
            ClimateEntityFeature.FAN_MODE | 
            ClimateEntityFeature.SWING_MODE
        )
        
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY]
        if device.has_heat: self._attr_hvac_modes.append(HVACMode.HEAT)
            
        self._attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_AUTO]
        self._attr_swing_modes = [SWING_OFF, SWING_VERTICAL] # Off / On(Vertical) 매핑

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
    @property
    def swing_mode(self): return SWING_VERTICAL if self.device.swing_state else SWING_OFF

    async def async_set_hvac_mode(self, hvac_mode): await self._fire_tx(override_hvac=hvac_mode)
    async def async_set_temperature(self, **kwargs):
        if "temperature" in kwargs: await self._fire_tx(override_temp=kwargs["temperature"])
    async def async_set_fan_mode(self, fan_mode): await self._fire_tx(override_fan=fan_mode)
    async def async_set_swing_mode(self, swing_mode): 
        await self._fire_tx(override_swing=(swing_mode == SWING_VERTICAL))

    async def _fire_tx(self, **kwargs):
        packet = self.device.make_tx_packet(**kwargs)
        writer = self.hass.data[DOMAIN][self.entry_id]["writer"]
        if writer:
            try:
                writer.write(packet)
                await writer.drain()
            except Exception as e: _LOGGER.error(f"명령 전송 에러: {e}")