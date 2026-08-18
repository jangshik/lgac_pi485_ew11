DOMAIN = "lgac_pi485_ew11"

def calculate_checksum(packet_bytes: bytes) -> int:
    """LG 에어컨 프로토콜 체크섬 계산"""
    checksum = sum(packet_bytes) & 255
    csum_odd = checksum & 170
    csum_even = 85 ^ (checksum & 85)
    return (csum_odd + csum_even) & 255

def make_control_packet(room_hex: int, mode_hex: int, temp_hex: int) -> bytes:
    """실내기 제어용 바이트 배열 생성"""
    # 80 00 A3 [실내기번호] 03 [명령타입] [온도] [체크섬]
    base_packet = bytes([0x80, 0x00, 0xA3, room_hex, 0x03, mode_hex, temp_hex])
    csum = calculate_checksum(base_packet)
    return base_packet + bytes([csum])