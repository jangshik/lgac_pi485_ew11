import asyncio
import logging
import time
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.climate.const import HVACMode, FAN_MEDIUM, FAN_LOW, FAN_HIGH
from .const import DOMAIN, make_poll_packet, calculate_checksum

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["climate", "sensor", "switch", "number"]

class LGDeviceState:
    def __init__(self, entity_idx, real_id, name, temp_step, has_heat, has_plasma, system_type):
        self.entity_idx = entity_idx
        self.real_id = real_id
        self.name = name
        self.temp_step = 1.0
        self.has_heat = has_heat
        self.has_plasma = has_plasma
        self.system_type = system_type 
        
        self.is_online = False
        self.last_rx_time = 0
        
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
        
        self.child_lock = False      
        self.plasma_ion = False
        self.lock_temp = False
        self.lock_fan = False
        self.lock_mode = False
        self.power_only = False
        
        self.sleep_timer = 0
        self.timer_remaining = 0
        self.timer_end_time = None 
        
        self._listeners = []

    def register_listener(self, listener):
        self._listeners.append(listener)

    def set_sleep_timer(self, minutes):
        self.sleep_timer = minutes
        if minutes > 0:
            self.timer_end_time = time.time() + (minutes * 60)
            self.timer_remaining = minutes
        else:
            self.timer_end_time = None
            self.timer_remaining = 0
        for listener in self._listeners: listener()

    def make_tx_packet(self, override_hvac=None, override_temp=None, override_fan=None, override_lock=None, override_plasma=None, override_swing=None) -> bytes:
        hvac = override_hvac if override_hvac is not None else self.hvac_mode
        temp = override_temp if override_temp is not None else self.target_temp
        fan = override_fan if override_fan is not None else self.fan_mode
        lock = override_lock if override_lock is not None else self.child_lock
        plasma = override_plasma if override_plasma is not None else self.plasma_ion
        swing = override_swing if override_swing is not None else self.swing_state

        tx4 = 0x02
        if hvac != HVACMode.OFF: tx4 |= 0x01
        if lock: tx4 |= 0x04
        if plasma: tx4 |= 0x10

        mode_hex = 0
        if hvac == HVACMode.DRY: mode_hex = 1
        elif hvac == HVACMode.FAN_ONLY: mode_hex = 2
        elif hvac == HVACMode.HEAT: mode_hex = 4
        elif hvac == HVACMode.AUTO: mode_hex = 3 

        fan_hex = 2
        if fan == FAN_LOW: fan_hex = 1
        elif fan == FAN_HIGH: fan_hex = 3
        elif fan == "auto": fan_hex = 4
        elif fan == "silent": fan_hex = 5
        elif fan == "turbo": fan_hex = 6

        tx5 = (mode_hex & 0x07) | ((fan_hex & 0x07) << 4)
        if swing: tx5 |= 0x08 

        tx6 = int(round(temp)) - 15
        tx6 = max(1, min(15, tx6))

        base_packet = bytearray([0x00, 0x00, 0xA0, self.real_id, tx4, tx5, tx6])
        base_packet.append(calculate_checksum(base_packet))
        return bytes(base_packet)

    def update_from_packet(self, packet: bytes):
        if len(packet) < 16 or packet[0] != 0x10: return
        try:
            # 🌟 [스마트 필터 1] 이전 상태의 핵심 변수들을 튜플로 기록
            # 온도는 0.3도 단위 노이즈를 막기 위해 소수점 1자리에서 묶음
            prev_online = self.is_online
            old_state = (
                self.is_on, self.hvac_mode, self.fan_mode, self.target_temp,
                round(self.current_temp, 1), round(self.pipe_in, 1), round(self.pipe_out, 1),
                self.zone_active_load, self.odu_total_load, self.zone_power_state_flag,
                self.error_code, self.swing_state, self.child_lock, self.plasma_ion,
                self.timer_remaining
            )

            self.raw_packet = packet.hex().upper()
            self.last_rx_time = time.time()
            self.is_online = True
            
            # --- 16바이트 상태 업데이트 진행 ---
            self.is_on = bool(packet[1] & 0x01)
            self.child_lock = bool(packet[1] & 0x04)
            self.plasma_ion = bool(packet[1] & 0x10)
            self.error_code = packet[5]
            
            mode_raw = packet[6] & 0x07
            self.swing_state = bool(packet[6] & 0x08)
            fan_raw = (packet[6] >> 4) & 0x07
            
            if self.system_type == "M":
                self.target_temp = float((packet[7] & 0x0F) + 15)
            else:
                self.target_temp = float((packet[7] & 0x1F) + 15)
            
            self.current_temp = float((192 - packet[8]) / 3.0)
            self.pipe_in = float((192 - packet[9]) / 3.0)
            self.pipe_out = float((192 - packet[10]) / 3.0)
            
            self.zone_active_load = packet[11]
            self.zone_power_state_flag = packet[12] 
            self.zone_design_load = packet[13]
            self.odu_total_load = packet[14]

            if not self.is_on: 
                self.hvac_mode = HVACMode.OFF
                self.sleep_timer = 0
                self.timer_end_time = None
                self.timer_remaining = 0
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

            # 🌟 [스마트 필터 2] 방금 파싱된 값들로 새로운 스냅샷 생성
            new_state = (
                self.is_on, self.hvac_mode, self.fan_mode, self.target_temp,
                round(self.current_temp, 1), round(self.pipe_in, 1), round(self.pipe_out, 1),
                self.zone_active_load, self.odu_total_load, self.zone_power_state_flag,
                self.error_code, self.swing_state, self.child_lock, self.plasma_ion,
                self.timer_remaining
            )

            # 🌟 [스마트 필터 3] 통신이 뻗었다 돌아왔거나, 튜플 값 중 단 하나라도 변했을 때만 HA 갱신!
            # (raw_packet은 스냅샷에 없으므로, 체크섬만 바뀐 패킷은 여기서 컷오프 됩니다.)
            if not prev_online or old_state != new_state:
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
            sys_type = parts[4].strip() if len(parts) > 4 else "M"
            
            devices[real_id] = LGDeviceState(entity_val, real_id, name, temp_step, has_heat, has_plasma, sys_type)
        except Exception as e: continue

    hass.data[DOMAIN][entry.entry_id] = {"devices": devices, "writer": None}
    
    hass.data[DOMAIN][entry.entry_id]["socket_task"] = hass.loop.create_task(ew11_socket_task(hass, entry, host, port))
    hass.data[DOMAIN][entry.entry_id]["poll_task"] = hass.loop.create_task(ew11_poll_task(hass, entry, update_interval))
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def ew11_poll_task(hass, entry, interval):
    while True:
        await asyncio.sleep(interval)
        writer = hass.data[DOMAIN][entry.entry_id].get("writer")
        devices = hass.data[DOMAIN][entry.entry_id].get("devices", {})
        now = time.time()
        
        if writer:
            for real_id, dev in devices.items():
                if now - dev.last_rx_time > 60:
                    if dev.is_online:
                        dev.is_online = False
                        for listener in dev._listeners: listener()

                if dev.sleep_timer > 0 and dev.timer_end_time and dev.is_on:
                    remaining_secs = dev.timer_end_time - now
                    if remaining_secs <= 0:
                        dev.sleep_timer = 0
                        dev.timer_end_time = None
                        dev.timer_remaining = 0
                        
                        off_packet = dev.make_tx_packet(override_hvac=HVACMode.OFF)
                        try:
                            writer.write(off_packet)
                            await writer.drain()
                        except: pass
                        for listener in dev._listeners: listener()
                    else:
                        new_remaining = int(remaining_secs / 60) + 1
                        if new_remaining != dev.timer_remaining:
                            dev.timer_remaining = new_remaining
                            for listener in dev._listeners: listener()

                try:
                    writer.write(make_poll_packet(real_id))
                    await writer.drain()
                    await asyncio.sleep(0.2)
                except: pass

async def ew11_socket_task(hass, entry, host, port):
    while True:
        writer = None
        try:
            reader, writer = await asyncio.open_connection(host, port)
            hass.data[DOMAIN][entry.entry_id]["writer"] = writer
            buffer = bytearray()
            while True:
                data = await asyncio.wait_for(reader.read(1024), timeout=60.0)
                if not data: break
                buffer.extend(data)
                
                while len(buffer) >= 8:
                    if buffer[0] in [0x00, 0x80, 0x10]:
                        packet_len = 16 if buffer[0] == 0x10 else 8
                        if len(buffer) >= packet_len:
                            csum = calculate_checksum(buffer[:packet_len-1])
                            
                            if buffer[packet_len-1] == csum:
                                if buffer[0] == 0x10:
                                    real_id = buffer[4]
                                    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
                                    if real_id in devices: 
                                        devices[real_id].update_from_packet(bytes(buffer[:16]))
                                del buffer[:packet_len]
                            else:
                                del buffer[0:1]
                        else: break 
                    else: 
                        del buffer[0:1] 
        except Exception as e:
            _LOGGER.error(f"통신 끊김, 재연결 중... : {e}")
        finally:
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except: pass
        await asyncio.sleep(5)

async def async_unload_entry(hass, entry):
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
        if "socket_task" in entry_data:
            entry_data["socket_task"].cancel()
        if "poll_task" in entry_data:
            entry_data["poll_task"].cancel()
            
        hass.data[DOMAIN].pop(entry.entry_id)
        
    return unload_ok