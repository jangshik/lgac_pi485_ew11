DOMAIN = "lgac_pi485_ew11"

# esphome-lgap 방식의 정밀 체크섬 연산
def calculate_checksum(packet: bytes) -> int:
    checksum = sum(packet) & 0xFF
    csum_odd = checksum & 0xAA  # 170
    csum_even = 0x55 ^ (checksum & 0x55) # 85
    return (csum_odd + csum_even) & 0xFF

# 제어 패킷 생성 (esphome-lgap 로직 기반)
def make_control_packet(room_id: int, mode_hex: int, temp_int: int) -> bytes:
    # 0x80(Write) 0x00 0xA3 [Room] [Command: 0x03(On) / 0x02(Off)] [Mode+Fan] [Temp]
    # 모드가 OFF(0x00)에 가까우면 Command를 0x02로 설정
    cmd = 0x03 if mode_hex > 0 else 0x02 
    
    base_packet = bytearray([0x80, 0x00, 0xA3, room_id, cmd, mode_hex, temp_int])
    csum = calculate_checksum(base_packet)
    base_packet.append(csum)
    
    return bytes(base_packet)