import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature, HVACMode, FAN_HIGH, FAN_MEDIUM, FAN_LOW, SWING_OFF, SWING_VERTICAL
)
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN, make_control_packet

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    async_add_entities([LGAirConditionerClimate(entry.entry_id, dev) for dev in devices.values()])
    return True

class LGAirConditionerClimate(ClimateEntity):
    def __init__(self, entry_id, device):
        self.entry_id = entry_id
        self.device = device
        
        self.entity_id = f"climate.lgac_{device.entity_idx.lower()}_cm"
        self._attr_unique_id = f"lgac_climate_{device.entity_idx.lower()}"
        self._attr_name = device.name
        self._attr_device_info = {"identifiers": {(DOMAIN, f"lgac_device_{device.real_id}")}, "name": device.name, "manufacturer": "LG"}
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_target_temperature_step = device.temp_step
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE | ClimateEntityFeature.SWING_MODE
        
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY]
        if device.has_heat: self._attr_hvac_modes.append(HVACMode.HEAT)
            
        # 🌟 esphome-lgap 요청 풍속 완벽 지원 (silent, turbo 추가)
        self._attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "auto", "silent", "turbo"]
        self._attr_swing_modes = [SWING_OFF, SWING_VERTICAL]

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

    async def async_set_hvac_mode(self, hvac_mode): 
        if not self.device.lock_mode and not self.device.power_only:
            await self._fire_tx(override_hvac=hvac_mode)
        elif self.device.power_only and hvac_mode in [HVACMode.OFF, HVACMode.COOL]: # 전원전용
            await self._fire_tx(override_hvac=hvac_mode)

    async def async_set_temperature(self, **kwargs):
        if "temperature" in kwargs and not self.device.lock_temp and not self.device.power_only: 
            await self._fire_tx(override_temp=kwargs["temperature"])

    async def async_set_fan_mode(self, fan_mode): 
        if not self.device.lock_fan and not self.device.power_only:
            await self._fire_tx(override_fan=fan_mode)

    async def async_set_swing_mode(self, swing_mode): 
        if not self.device.power_only:
            self.device.swing_state = (swing_mode == SWING_VERTICAL)
            await self._fire_tx()

    async def _fire_tx(self, override_hvac=None, override_temp=None, override_fan=None):
        hvac = override_hvac if override_hvac is not None else self.device.hvac_mode
        temp = override_temp if override_temp is not None else self.device.target_temp
        fan = override_fan if override_fan is not None else self.device.fan_mode

        turn_on = hvac != HVACMode.OFF
        mode_hex = 0 
        if hvac == HVACMode.DRY: mode_hex = 1
        elif hvac == HVACMode.FAN_ONLY: mode_hex = 2
        elif hvac == HVACMode.HEAT: mode_hex = 4

        fan_hex = 2 
        if fan == FAN_LOW: fan_hex = 1
        elif fan == FAN_HIGH: fan_hex = 3
        elif fan == "auto": fan_hex = 4
        elif fan == "silent": fan_hex = 5
        elif fan == "turbo": fan_hex = 6

        packet = make_control_packet(self.device.real_id, mode_hex, fan_hex, temp, turn_on, self.device.child_lock, self.device.plasma_ion)
        writer = self.hass.data[DOMAIN][self.entry_id]["writer"]
        if writer:
            try:
                writer.write(packet)
                await writer.drain()
            except Exception as e: _LOGGER.error(f"명령 전송 에러: {e}")