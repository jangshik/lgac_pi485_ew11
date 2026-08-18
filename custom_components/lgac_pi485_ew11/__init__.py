import asyncio
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.climate.const import HVACMode, FAN_MEDIUM, FAN_LOW, FAN_HIGH
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["climate", "sensor"]

class LGDeviceState:
    """esphome-lgap의 모든 센서와 제어 상태 정보를 담는 허브 객체"""
    def __init__(self, entity_idx, real_id, name, temp_step, has_heat):
        self.entity_idx = entity_idx
        self.real_id = real_id
        self.name = name
        self.temp_step = temp_step
        self.has_heat = has_heat
        
        # 기본 제어 상태
        self.is_on = False
        self.hvac_mode = HVACMode.OFF
        self.fan_mode = FAN_MEDIUM
        self.current_temp = 24.0
        self.target_temp = 24.0
        
        # 🌟 esphome-lgap 고급 센서 변수
        self.error_code = 0          
        self.swing_state = False     
        self.pipe_in = 0.0           
        self.pipe_out = 0.0          
        self.zone_active_load = 0    
        
        # 🌟 [에러 수정 포인트] 변수명을 sensor.py가 찾는 이름과 완벽히 일치시킴
        self.zone_power_state_flag = 0 
        
        self.zone_design_load = 0    
        self.odu_total_load = 0      
        self.child_lock = False      
        self.plasma_ion = False      
        
        self._listeners = []

    def register_listener(self, listener):
        self._listeners.append(listener)

    def update_from_packet(self, packet: bytes):
        """16바이트 응답 패킷 파싱"""
        if len(packet) < 16 or packet[0] != 0x10: return
        try:
            self.is_on = bool(packet[1] & 0x01)
            self.child_lock = bool(packet[1] & 0x04)
            self.plasma_ion = bool(packet[1] & 0x10)
            
            self.error_code = packet[5]
            
            mode_raw = packet[6] & 0x07
            self.swing_state = bool(packet[6] & 0x08)
            fan_raw = (packet[6] >> 4) & 0x07
            
            self.target_temp = float((packet[7] & 0x0F) + 15)
            self.current_temp = float((192 - packet[8]) / 3.0)
            
            self.pipe_in = float((192 - packet[9]) / 3.0)
            self.pipe_out = float((192 - packet[10]) / 3.0)
            
            self.zone_active_load = packet[11]
            
            # 🌟 [에러 수정 포인트] 업데이트 시에도 올바른 변수명에 값 저장
            self.zone_power_state_flag = packet[12] 
            
            self.zone_design_load = packet[13]
            self.odu_total_load = packet[14]

            if not self.is_on:
                self.hvac_mode = HVACMode.OFF
            else:
                if mode_raw == 0: self.hvac_mode = HVACMode.COOL
                elif mode_raw == 1: self.hvac_mode = HVACMode.DRY
                elif mode_raw == 2: self.hvac_mode = HVACMode.FAN_ONLY
                elif mode_raw == 4: self.hvac_mode = HVACMode.HEAT
                else: self.hvac_mode = HVACMode.AUTO
                
                if fan_raw == 1: self.fan_mode = FAN_LOW
                elif fan_raw == 2: self.fan_mode = FAN_MEDIUM
                elif fan_raw == 3: self.fan_mode = FAN_HIGH
                else: self.fan_mode = "auto"

            for listener in self._listeners:
                listener()
        except Exception as e:
            _LOGGER.error(f"고급 패킷 분석 오류: {e}")

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    host = entry.data["host"]
    port = entry.data["port"]
    mapping_str = entry.data["mapping"]
    temp_step = entry.data.get("temp_step", 1.0)
    has_heat = entry.data.get("has_heat", True)

    devices = {}
    for item in mapping_str.split(","):
        if ":" in item:
            entity_val, rest = item.split(":")
            entity_val = entity_val.strip()
            real_id = int(rest.split("/")[0].strip(), 16)
            name = rest.split("/")[1].strip() if "/" in rest else f"에어컨 {entity_val}"
            
            devices[real_id] = LGDeviceState(entity_val, real_id, name, temp_step, has_heat)

    hass.data[DOMAIN][entry.entry_id] = {"devices": devices, "writer": None}
    hass.loop.create_task(ew11_socket_task(hass, entry, host, port))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def ew11_socket_task(hass: HomeAssistant, entry: ConfigEntry, host: str, port: int):
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            hass.data[DOMAIN][entry.entry_id]["writer"] = writer
            _LOGGER.info(f"Connected to EW11 Stream Handler ({host}:{port})")

            buffer = bytearray()
            while True:
                data = await reader.read(1024)
                if not data: break
                buffer.extend(data)

                while len(buffer) >= 8:
                    if buffer[0] == 0x80 or buffer[0] == 0x10:
                        room_idx = 3 if buffer[0] == 0x80 else 4
                        packet_len = 8 if buffer[0] == 0x80 else 16
                        
                        if len(buffer) >= packet_len:
                            if buffer[0] == 0x10:
                                real_id = buffer[room_idx]
                                devices = hass.data[DOMAIN][entry.entry_id]["devices"]
                                if real_id in devices:
                                    devices[real_id].update_from_packet(bytes(buffer[:16]))
                            del buffer[:packet_len]
                        else:
                            break
                    else:
                        del buffer[0:1]
        except Exception as e:
            _LOGGER.error(f"EW11 TCP 소켓 연결 재시도: {e}")
            await asyncio.sleep(10)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok