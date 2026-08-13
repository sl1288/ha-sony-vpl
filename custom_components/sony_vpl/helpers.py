"""Shared helpers for the Sony VPL projector integration."""

from dataclasses import dataclass

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api import ERR_INVALID_DATA, SdcpClient, SdcpError, SdcpItemError
from .const import DOMAIN
from .items import (
    ITEM_FPGA_VERSION,
    ITEM_MAC_ADDRESS,
    ITEM_MODEL_NAME,
    ITEM_SERIAL_NUMBER,
    ITEM_SW_VERSION,
    decode_mac_address,
    decode_serial_number,
    decode_text,
    decode_version,
)


@dataclass(frozen=True, kw_only=True, slots=True)
class SonyVplIdentity:
    """Identity of a projector, read once per config entry setup."""

    model: str | None = None
    serial_number: str | None = None
    mac_address: str | None = None
    sw_version: str | None = None
    fpga_version: str | None = None

    @property
    def unique_id(self) -> str | None:
        """Return the most stable identifier the projector gave us.

        The serial number is preferred because it survives a network card swap;
        the MAC address is the fallback. Both come from SDCP items that are
        documented for the projector category but unconfirmed on every model, so
        callers must cope with this being None.

        No further normalisation is applied: ``decode_mac_address`` already
        produces the lower case colon separated form that ``format_mac`` would,
        and a serial number must be left exactly as the projector reported it.
        """
        return self.serial_number or self.mac_address


async def async_get_identity(client: SdcpClient) -> SonyVplIdentity:
    """Read the identity items, tolerating any the projector does not implement.

    The equipment and network information items are documented in the protocol
    manual but pysdcp never used them, so support on any given model is
    unconfirmed. None of them may fail the setup.
    """
    async with client.connection():
        model = await client.async_try_get_raw(ITEM_MODEL_NAME)
        serial = await client.async_try_get_raw(ITEM_SERIAL_NUMBER)
        mac = await client.async_try_get_raw(ITEM_MAC_ADDRESS)
        sw_version = await client.async_try_get(ITEM_SW_VERSION)
        fpga_version = await client.async_try_get(ITEM_FPGA_VERSION)

    return SonyVplIdentity(
        model=decode_text(model) if model else None,
        serial_number=decode_serial_number(serial) if serial else None,
        mac_address=decode_mac_address(mac) if mac else None,
        sw_version=decode_version(sw_version) if sw_version is not None else None,
        fpga_version=decode_version(fpga_version) if fpga_version is not None else None,
    )


def write_error(err: SdcpError, name: str) -> HomeAssistantError:
    """Translate a failed write into a user facing exception.

    "Invalid data" means the projector understood the item but refused the value,
    which on this hardware nearly always means the current input or signal does
    not allow it. That is the user's choice being wrong rather than a fault, so it
    becomes a ServiceValidationError.
    """
    if isinstance(err, SdcpItemError):
        key = (
            "value_rejected"
            if err.code == ERR_INVALID_DATA
            else "setting_not_applicable"
        )
        return ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders={"name": name},
        )
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="write_failed",
        translation_placeholders={"name": name},
    )
