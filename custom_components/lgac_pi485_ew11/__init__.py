import asyncio
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.climate.const import HVACMode, FAN_MEDIUM, FAN_LOW, FAN_HIGH
from .const import DOMAIN, make_poll_packet

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["climate", "sensor", "switch", "number"]

class LGDeviceState:
    def __init__(self, entity_idx, real_id, name, temp_step, has_heat, has_plasma):
        self.entity_idx = entity_idx
        self.real_id = real_id
        self.name = name
        self.temp_step = temp_step
        self.has_heat = has_heat
        self.has_plasma = has_plasma
        
        self.is_on = False
        self.hvac_mode = HVACMode.OFF
        self.fan_mode = FAN_MEDIUM
        self.current_temp = 24.0
        self.target_temp = 24.0
        
        self.error_code = 0          
        self.swing_state = False     
        self.pipe_in = 0.0           
        self.pipe_out = 0.0          
        self.zone_active_load = 0    
        self.zone_power_state_flag = 0 
        self.zone_design_load = 0    
        self.odu_total_load = 0      
        self.raw_packet = "None"
        
        # 스위치 및 넘버 상태 저장 (esphome-lgap 구현)
        self.child_lock = False      
        self.plasma_ion = False
        self.lock_temp = False
        self.lock_fan = False
        self.lock_mode = False
        self.power_only = False
        self.sleep_timer = 0
        self.timer_remaining = 0
        
        self._listeners = []

    def register_listener(self, listener):
        self._listeners.append(listener)

    def update_from_packet(self, packet: bytes):
        if len(packet) < 16 or packet[0] != 0x10: return
        try:
            self.raw_packet = packet.hex().upper()
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
            self.zone_power_state_flag = packet[12] 
            self.zone_design_load = packet[13]
            self.odu_total_load = packet[14]

            if not self.is_on: self.hvac_mode = HVACMode.OFF
            else:
                if mode_raw == 0: self.hvac_mode = HVACMode.COOL
                elif mode_raw == 1: self.hvac_mode = HVACMode.DRY
                elif mode_raw == 2: self.hvac_mode = HVACMode.FAN_ONLY
                elif mode_raw == 4: self.hvac_mode = HVACMode.HEAT
                else: self.hvac_mode = HVACMode.AUTO
                
                if fan_raw == 1: self.fan_mode = FAN_LOW
                elif fan_raw == 2: self.fan_mode = FAN_MEDIUM
                elif fan_raw == 3: self.fan_mode = FAN_HIGH
                elif fan_raw == 4: self.fan_mode = "auto"
                elif fan_raw == 5: self.fan_mode = "silent"
                elif fan_raw == 6: self.fan_mode = "turbo"

            # 수면 타이머 카운트다운 로직
            if self.sleep_timer > 0 and self.is_on:
                self.timer_remaining = max(0, self.timer_remaining - 1)
                if self.timer_remaining == 0:
                    self.sleep_timer = 0
                    self.is_on = False
                    self.hvac_mode = HVACMode.OFF

            for listener in self._listeners: listener()
        except Exception as e: _LOGGER.error(f"패킷 분석 오류: {e}")

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    host = entry.data["host"]
    port = entry.data["port"]
    mapping_str = entry.data["mapping"]
    temp_step = entry.data.get("temp_step", 1.0)
    update_interval = entry.data.get("update_interval", 10)

    devices = {}
    for item in mapping_str.split(","):
        item = item.strip()
        if not item or ":" not in item: continue
        try:
            entity_val, rest = item.split(":", 1)
            parts = rest.split("/")
            real_id = int(parts[0].strip(), 16)
            name = parts[1].strip() if len(parts) > 1 else f"에어컨 {entity_val}"
            has_heat = parts[2].strip() == "1" if len(parts) > 2 else True
            has_plasma = parts[3].strip() == "1" if len(parts) > 3 else False
            
            devices[real_id] = LGDeviceState(entity_val, real_id, name, temp_step, has_heat, has_plasma)
        except Exception as e: continue

    hass.data[DOMAIN][entry.entry_id] = {"devices": devices, "writer": None}
    
    # 🌟 수신 태스크와 주기적 업데이트(Polling) 태스크 동시 가동
    hass.loop.create_task(ew11_socket_task(hass, entry, host, port))
    hass.loop.create_task(ew11_poll_task(hass, entry, update_interval))
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def ew11_poll_task(hass, entry, interval):
    """설정된 주기마다 모든 에어컨에 상태 갱신 요청 패킷(Polling) 전송"""
    while True:
        await asyncio.sleep(interval)
        writer = hass.data[DOMAIN][entry.entry_id].get("writer")
        devices = hass.data[DOMAIN][entry.entry_id].get("devices", {})
        if writer:
            for real_id in devices.keys():
                try:
                    writer.write(make_poll_packet(real_id))
                    await writer.drain()
                    await asyncio.sleep(0.2) # 버스 충돌 방지 지연
                except: pass

async def ew11_socket_task(hass, entry, host, port):
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            hass.data[DOMAIN][entry.entry_id]["writer"] = writer
            buffer = bytearray()
            while True:
                data = await reader.read(1024)
                if not data: break
                buffer.extend(data)
                while len(buffer) >= 8:
                    if buffer[0] in [0x80, 0x10]:
                        room_idx = 3 if buffer[0] == 0x80 else 4
                        packet_len = 8 if buffer[0] == 0x80 else 16
                        if len(buffer) >= packet_len:
                            if buffer[0] == 0x10:
                                real_id = buffer[room_idx]
                                devices = hass.data[DOMAIN][entry.entry_id]["devices"]
                                if real_id in devices: devices[real_id].update_from_packet(bytes(buffer[:16]))
                            del buffer[:packet_len]
                        else: break
                    else: del buffer[0:1]
        except Exception:
            await asyncio.sleep(5)

async def async_unload_entry(hass, entry):
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok: hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok