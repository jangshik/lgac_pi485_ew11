import logging
from homeassistant.components.switch import SwitchEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    entry_data = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for device in entry_data["devices"].values():
        # 🌟 차일드 락 제어 스위치 엔티티 추가 [protocol.md 기반]
        entities.append(LGACSwitch(entry.entry_id, device, "child_lock", "차일드 락", "mdi:lock"))
        # 🌟 플라즈마 음이온 제어 스위치 엔티티 추가 [protocol.md 기반]
        entities.append(LGACSwitch(entry.entry_id, device, "plasma_ion", "음이온 공기청정", "mdi:snowflake-melt"))
        
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
        
        # 동일 기기 카드로 귀속 분리
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"lgac_device_{device.real_id}")},
        }
        self._attr_icon = icon

    async def async_added_to_hass(self):
        self.device.register_listener(self.async_write_ha_state)

    @property
    def is_on(self):
        if self.switch_type == "child_lock": return self.device.child_lock
        if self.switch_type == "plasma_ion": return self.device.plasma_ion
        return False

    async def turn_on(self, **kwargs):
        await self._toggle_hardware(True)

    async def turn_off(self, **kwargs):
        await self._toggle_hardware(False)

    async def _toggle_hardware(self, enable: bool):
        """스위치 조작에 따른 비트 연산 제어 패킷 방출"""
        if self.switch_type == "child_lock":
            packet = self.device.make_tx_packet(override_lock=enable)
        else:
            packet = self.device.make_tx_packet(override_plasma=enable)
            
        writer = self.hass.data[DOMAIN][self.entry_id]["writer"]
        if writer:
            try:
                writer.write(packet)
                await writer.drain()
            except Exception as e: _LOGGER.error(f"스위치 명령 실패: {e}")