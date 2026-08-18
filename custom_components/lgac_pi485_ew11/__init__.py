import asyncio
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    host = entry.data["host"]
    port = entry.data["port"]
    mapping_str = entry.data["mapping"]
    temp_step = entry.data.get("temp_step", 1.0) # 🌟 선택된 단위를 가져옴

    mapping_dict = {}
    for item in mapping_str.split(","):
        if ":" in item:
            part1, part2 = item.split(":")
            entity_idx = part1.strip()
            real_id = int(part2.split("/")[0].strip(), 16)
            name = part2.split("/")[1].strip() if "/" in part2 else f"LG AC {entity_idx}"
            mapping_dict[entity_idx] = {"real_id": real_id, "name": name}

    hass.data[DOMAIN][entry.entry_id] = {
        "writer": None,
        "mapping": mapping_dict,
        "temp_step": temp_step,
        "entities": {}
    }

    hass.loop.create_task(ew11_socket_task(hass, entry, host, port))
    await hass.config_entries.async_forward_entry_setups(entry, ["climate"])
    return True

async def ew11_socket_task(hass: HomeAssistant, entry: ConfigEntry, host: str, port: int):
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            hass.data[DOMAIN][entry.entry_id]["writer"] = writer
            _LOGGER.info(f"Connected to EW11 TCP Socket ({host}:{port})")

            buffer = bytearray()
            while True:
                data = await reader.read(1024)
                if not data: break
                buffer.extend(data)

                while len(buffer) >= 8:
                    # esphome-lgap 프로토콜 동기화 헤더 매칭 (0x10, 0x80 등)
                    if buffer[0] in [0x10, 0x80, 0x00]:
                        real_room_id = buffer[3]
                        entities = hass.data[DOMAIN][entry.entry_id]["entities"]
                        
                        if real_room_id in entities:
                            if len(buffer) >= 16:
                                packet = bytes(buffer[:16])
                                entities[real_room_id].update_from_packet(packet)
                                del buffer[:16]
                            else:
                                break
                        else:
                            del buffer[0:1]
                    else:
                        del buffer[0:1]
        except Exception as e:
            _LOGGER.error(f"EW11 Socket Connection Error: {e}")
            await asyncio.sleep(5)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["climate"])
    if unload_ok: hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok