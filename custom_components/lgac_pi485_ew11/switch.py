import logging
from homeassistant.components.switch import SwitchEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    entities = []
    for device in devices.values():
        entities.append(LGACSwitch(entry.entry_id, device, "child_lock", "차일드 락", "mdi:lock"))
        entities.append(LGACSwitch(entry.entry_id, device, "lock_temp", "온도 조절 잠금", "mdi:lock-outline"))
        entities.append(LGACSwitch(entry.entry_id, device, "lock_fan", "풍량 조절 잠금", "mdi:lock-outline"))
        entities.append(LGACSwitch(entry.entry_id, device, "lock_mode", "모드 변경 잠금", "mdi:lock-outline"))
        entities.append(LGACSwitch(entry.entry_id, device, "power_only", "전원 제어만 허용", "mdi:power-plug-off"))
        if device.has_plasma:
            entities.append(LGACSwitch(entry.entry_id, device, "plasma_ion", "음이온", "mdi:snowflake-melt"))
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
        return getattr(self.device, self.switch_type, False)

    async def turn_on(self, **kwargs):
        await self._send_command(True)

    async def turn_off(self, **kwargs):
        await self._send_command(False)

    async def _send_command(self, state):
        # 🌟 낙관적 업데이트(setattr) 삭제 완료. 패킷만 전송합니다.
        
        # 소프트웨어 락(HA 내부에서만 동작하는 락)일 경우만 즉시 반영
        if self.switch_type in ["lock_temp", "lock_fan", "lock_mode", "power_only"]:
            setattr(self.device, self.switch_type, state)
            self.async_write_ha_state()
            return
            
        packet = None
        if self.switch_type == "child_lock":
            packet = self.device.make_tx_packet(override_lock=state)
        elif self.switch_type == "plasma_ion":
            packet = self.device.make_tx_packet(override_plasma=state)
            
        if packet:
            writer = self.hass.data[DOMAIN][self.entry_id]["writer"]
            if writer:
                try:
                    writer.write(packet)
                    await writer.drain()
                except Exception as e: _LOGGER.error(f"스위치 명령 실패: {e}")