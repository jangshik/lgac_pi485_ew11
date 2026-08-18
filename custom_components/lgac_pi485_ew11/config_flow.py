import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN

class LGACConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id(user_input["host"])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title="LG 에어컨 제어기", 
                data=user_input
            )

        data_schema = vol.Schema({
            vol.Required("host", default="192.168.0."): str,
            vol.Required("port", default=8899): int,
            # 🌟 [생성할엔티티번호:실제RS485주소] 형태로 치환 정의
            vol.Required("room_mapping", default="00:01, 01:02"): str,
            # 🌟 단배관/다배관 등 하드웨어 유형에 따른 파싱 예외 처리용 선택박스
            vol.Required("piping_type", default="multi"): vol.In({
                "multi": "다배관 (일반 가정용 멀티)",
                "single": "단배관 (중앙 분지관 방식)"
            })
        })

        return self.async_show_form(step_id="user", data_schema=data_schema)