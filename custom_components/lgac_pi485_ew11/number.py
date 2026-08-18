import logging
from homeassistant.components.number import NumberEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    async_add_entities([LGACSleepTimer(entry.entry_id, dev) for dev in devices.values()])
    return True

class LGACSleepTimer(NumberEntity):
    def __init__(self, entry_id, device):
        self.entry_id = entry_id
        self.device = device
        self.entity_id = f"number.lgac_{device.entity_idx.lower()}_sleep_timer"
        self._attr_unique_id = f"lgac_number_{device.entity_idx.lower()}_sleep_timer"
        self._attr_name = f"{device.name} 수면 타이머 설정"
        self._attr_device_info = {"identifiers": {(DOMAIN, f"lgac_device_{device.real_id}")}}
        self._attr_icon = "mdi:timer-cog"
        
        # esphome-lgap 규격 0~420분
        self._attr_native_min_value = 0
        self._attr_native_max_value = 420
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "min"

    async def async_added_to_hass(self):
        self.device.register_listener(self.async_write_ha_state)

    @property
    def native_value(self):
        return self.device.sleep_timer

    async def async_set_native_value(self, value: float):
        """타이머 값 설정 및 카운트다운 시작"""
        val = int(value)
        self.device.sleep_timer = val
        self.device.timer_remaining = val
        self.async_write_ha_state()