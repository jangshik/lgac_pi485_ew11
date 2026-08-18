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
    mapping_str = entry.data.get("room_mapping", "00:01")
    piping_type = entry.data.get("piping_type", "multi")

    # "00:01, 01:02" -> {"00": 1, "01": 2} 형태로 치환 맵 빌드
    mapping_dict = {}
    for item in mapping_str.split(","):
        if ":" in item:
            entity_part, real_part = item.split(":")
            try:
                mapping_dict[entity_part.strip()] = int(real_part.strip(), 16) # 16진수 대응
            except ValueError:
                continue

    try:
        reader, writer = await asyncio.open_connection(host, port)
        _LOGGER.info(f"Connected to EW11 Gateway ({host}:{port})")
    except Exception as e:
        _LOGGER.error(f"EW11 socket connection failure: {e}")
        writer = None

    hass.data[DOMAIN][entry.entry_id] = {
        "writer": writer,
        "mapping": mapping_dict,
        "piping_type": piping_type
    }

    await hass.config_entries.async_forward_entry_setups(entry, ["climate"])
    return True