import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN

class LGACConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            # 호스트당 하나의 설정 엔트리만 허용
            await self.async_set_unique_id(user_input["host"])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"LG AC Gateway ({user_input['host']})", 
                data=user_input
            )

        data_schema = vol.Schema({
            vol.Required("host", default="192.168.0."): str,
            vol.Required("port", default=8899): int,
        })

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)