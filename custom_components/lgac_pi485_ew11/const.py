DOMAIN = "lgac_pi485_ew11"

def calculate_checksum(packet: bytes) -> int:
    return (sum(packet) & 0xFF) ^ 0x55

def make_control_packet(room_id: int, mode_hex: int, fan_hex: int, target_temp: float, turn_on: bool, lock: bool, plasma: bool) -> bytes:
    tx4 = 0x02 
    if turn_on: tx4 |= 0x01
    if lock: tx4 |= 0x04
    if plasma: tx4 |= 0x10
    
    tx5 = (mode_hex & 0x07) | ((fan_hex & 0x07) << 4)
    tx6 = int(target_temp) - 15
    tx6 = max(1, min(15, tx6))
    
    # 🌟 [수정] 제어 명령은 0x10이 아니라 반드시 0x00으로 시작해야 합니다!
    base_packet = bytearray([0x00, 0x00, 0xA0, room_id, tx4, tx5, tx6])
    base_packet.append(calculate_checksum(base_packet))
    return bytes(base_packet)

def make_poll_packet(room_id: int) -> bytes:
    # 🌟 [수정] 폴링 명령 역시 0x00으로 시작해야 실내기가 응답합니다.
    base_packet = bytearray([0x00, 0x00, 0xA0, room_id, 0x00, 0x00, 0x00])
    base_packet.append(calculate_checksum(base_packet))
    return bytes(base_packet)