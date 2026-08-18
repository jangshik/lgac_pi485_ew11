import logging
from homeassistant.components.switch import SwitchEntity
from .const import DOMAIN, make_control_packet

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    entities = []
    for device in devices.values():
        entities.append(LGACSwitch(entry.entry_id, device, "child_lock", "차일드 락", "mdi:lock"))
        entities.append(LGACSwitch(entry.entry_id, device, "lock_temp", "온도 조절 잠금", "mdi:lock-outline"))
        entities.append(LGACSwitch(entry.entry_id, device, "lock_fan", "풍량 조절 잠금", "mdi:lock-outline"))
        entities.append(LGACSwitch(entry.entry_id, device, "lock_mode", "모드 변경 잠금", "mdi:lock-outline"))
        entities.append(LGACSwitch(entry.entry_id, device, "power_only", "전원만 허용 모드", "mdi:power-plug-off"))
        
        if device.has_plasma: # 🌟 설정에서 플라즈마 체크 시에만 생성
            entities.append(LGACSwitch(entry.entry_id, device, "plasma_ion", "플라즈마 음이온", "mdi:snowflake-melt"))
            
    async_add_entities(entities)
    return True

class LGACSwitch(SwitchEntity):
    def __init__(self, entry_id, device, switch_type, name_suffix, icon):
        self.entry_id = entry_id
        self.device = device
        self.switch_type = switch_type
        self.entity_id = f"switch.lgac_{device.entity_idx.lower()}_{switch_type}"
        self._attr_unique_id = f"lgac_switch_{device.entity_idx.lower()}_{switch_type}"
        self._attr_name = f"{device.name} {name_suffix}"
        self._attr_device_info = {"identifiers": {(DOMAIN, f"lgac_device_{device.real_id}")}}
        self._attr_icon = icon

    async def async_added_to_hass(self):
        self.device.register_listener(self.async_write_ha_state)

    @property
    def is_on(self):
        if self.switch_type == "child_lock": return self.device.child_lock
        if self.switch_type == "plasma_ion": return self.device.plasma_ion
        if self.switch_type == "lock_temp": return self.device.lock_temp
        if self.switch_type == "lock_fan": return self.device.lock_fan
        if self.switch_type == "lock_mode": return self.device.lock_mode
        if self.switch_type == "power_only": return self.device.power_only
        return False

    async def turn_on(self, **kwargs):
        setattr(self.device, self.switch_type, True)
        self.async_write_ha_state()
        if self.switch_type in ["child_lock", "plasma_ion"]:
            await self._fire_tx()

    async def turn_off(self, **kwargs):
        setattr(self.device, self.switch_type, False)
        self.async_write_ha_state()
        if self.switch_type in ["child_lock", "plasma_ion"]:
            await self._fire_tx()

    async def _fire_tx(self):
        # 켜짐 여부 등 기존 상태 복구
        turn_on = self.device.hvac_mode != "off"
        packet = make_control_packet(self.device.real_id, 0, 2, self.device.target_temp, turn_on, self.device.child_lock, self.device.plasma_ion)
        writer = self.hass.data[DOMAIN][self.entry_id]["writer"]
        if writer:
            try:
                writer.write(packet)
                await writer.drain()
            except Exception as e: _LOGGER.error(f"스위치 명령 실패: {e}")