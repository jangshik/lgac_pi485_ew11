import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature, HVACMode, HVACAction,
    FAN_HIGH, FAN_MEDIUM, FAN_LOW, SWING_OFF, SWING_VERTICAL
)
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN

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
        self._attr_target_temperature_step = 1.0 
        
        # 🌟 [버그 수정] 명시적 TURN_ON, TURN_OFF 기능 추가
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | 
            ClimateEntityFeature.FAN_MODE | 
            ClimateEntityFeature.SWING_MODE |
            ClimateEntityFeature.TURN_ON | 
            ClimateEntityFeature.TURN_OFF
        )
        
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY, HVACMode.AUTO]
        if device.has_heat: self._attr_hvac_modes.append(HVACMode.HEAT)
            
        self._attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH, "auto", "silent", "turbo"]
        self._attr_swing_modes = [SWING_OFF, SWING_VERTICAL]

    async def async_added_to_hass(self):
        self.device.register_listener(self.async_write_ha_state)

    @property
    def available(self):
        return self.device.is_online

    @property
    def min_temp(self):
        return 18.0

    @property
    def max_temp(self):
        return 30.0

    @property
    def hvac_mode(self): return self.device.hvac_mode

    @property
    def hvac_action(self):
        if not self.device.is_on: return HVACAction.OFF
        if self.device.hvac_mode == HVACMode.COOL: return HVACAction.COOLING
        elif self.device.hvac_mode == HVACMode.HEAT: return HVACAction.HEATING
        elif self.device.hvac_mode == HVACMode.DRY: return HVACAction.DRYING
        elif self.device.hvac_mode == HVACMode.FAN_ONLY: return HVACAction.FAN
        elif self.device.hvac_mode == HVACMode.AUTO:
            return HVACAction.COOLING if self.device.current_temp > self.device.target_temp else HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def current_temperature(self): return self.device.current_temp
    @property
    def target_temperature(self): return self.device.target_temp
    @property
    def fan_mode(self): return self.device.fan_mode
    @property
    def swing_mode(self): return SWING_VERTICAL if self.device.swing_state else SWING_OFF

    # 🌟 [버그 수정] 자동화에서 호출하는 climate.turn_on 서비스 대응
    async def async_turn_on(self):
        """Turn the entity on."""
        # 에어컨이 꺼져있을 때 켜면, 이전에 쓰던 모드를 기억해서 켜거나 기본값(냉방)으로 켭니다.
        target_mode = self.device.hvac_mode if self.device.hvac_mode != HVACMode.OFF else HVACMode.COOL
        await self.async_set_hvac_mode(target_mode)

    # 🌟 [버그 수정] 자동화에서 호출하는 climate.turn_off 서비스 대응
    async def async_turn_off(self):
        """Turn the entity off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_hvac_mode(self, hvac_mode): 
        if not self.device.lock_mode and not self.device.power_only:
            await self._fire_tx(override_hvac=hvac_mode)
        elif self.device.power_only and hvac_mode in [HVACMode.OFF, HVACMode.COOL]: 
            await self._fire_tx(override_hvac=hvac_mode)

    async def async_set_temperature(self, **kwargs):
        if "temperature" in kwargs and not self.device.lock_temp and not self.device.power_only: 
            temp_val = round(kwargs["temperature"])
            await self._fire_tx(override_temp=temp_val)

    async def async_set_fan_mode(self, fan_mode): 
        if not self.device.lock_fan and not self.device.power_only:
            await self._fire_tx(override_fan=fan_mode)

    async def async_set_swing_mode(self, swing_mode): 
        if not self.device.power_only:
            is_swing = (swing_mode == SWING_VERTICAL)
            await self._fire_tx(override_swing=is_swing)

    async def _fire_tx(self, **kwargs):
        packet = self.device.make_tx_packet(**kwargs)
        writer = self.hass.data[DOMAIN][self.entry_id]["writer"]
        if writer:
            try:
                writer.write(packet)
                await writer.drain()
            except Exception as e: _LOGGER.error(f"명령 전송 에러: {e}")