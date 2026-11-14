"""EVM decoding helpers built on eth-utils and eth-abi.

Quantities stay integer until a presentation boundary. Address normalization is
centralized here so checksummed user input and ABI words decode consistently.
"""

from functools import lru_cache
from typing import Any

from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak

ADDRESS_HEX = 40
WORD_HEX = 64


@lru_cache(maxsize=1024)
def sig(signature: str) -> str:
    return "0x" + keccak(text=signature).hex()


def selector(signature: str) -> str:
    return sig(signature)[:10]


def encode_word(types: list[str], values: list[Any]) -> str:
    return "0x" + abi_encode(types, values).hex()


def decode_abi(types: list[str], data: str) -> tuple[Any, ...]:
    payload = data[2:] if data.startswith("0x") else data
    if len(payload) % 2:
        raise ValueError("ABI data must have even-length hex")
    if not payload:
        raise ValueError("ABI data is empty")
    return tuple(abi_decode(types, bytes.fromhex(payload)))


def addr(value: str | int) -> str:
    if isinstance(value, int):
        if not 0 <= value < 2**160:
            raise ValueError("Address integer must fit 160 bits")
        return "0x" + format(value, "040x")
    if not isinstance(value, str):
        raise ValueError("Expected an EVM address")
    value = value.lower().removeprefix("0x")
    if len(value) not in (ADDRESS_HEX, WORD_HEX) or any(
        c not in "0123456789abcdef" for c in value
    ):
        raise ValueError("Expected an EVM address or a 32-byte ABI word")
    return "0x" + value[-ADDRESS_HEX:]


def words(data: str | dict[str, Any] | Any) -> list[int]:
    if isinstance(data, str):
        payload = data
    elif isinstance(data, dict):
        payload = data["data"]
    else:
        payload = data.data
    if not payload.startswith("0x") or (len(payload) - 2) % WORD_HEX:
        raise ValueError("ABI data must contain complete 32-byte words")
    count = (len(payload) - 2) // WORD_HEX
    return list(abi_decode(["uint256"] * count, bytes.fromhex(payload[2:])))


def signed(value: int, bits: int = 256) -> int:
    if bits < 1 or not 0 <= value < 2**bits:
        raise ValueError("Unsigned value does not fit the requested width")
    return value - 2**bits if value >= 2 ** (bits - 1) else value


def position(log: Any) -> tuple[int, int, int]:
    if hasattr(log, "position"):
        return log.position()
    if isinstance(log, dict):
        block, tx_index, log_index = (
            int(log[key], 16) if isinstance(log[key], str) else int(log[key])
            for key in ("blockNumber", "transactionIndex", "logIndex")
        )
        return (block, tx_index, log_index)
    raise TypeError("Expected a log model or mapping")


def address_word(value: str | int) -> str:
    return encode_word(["address"], [addr(value)])[2:]


def array_words(values: list[int], index: int) -> tuple[list[int], int]:
    offset = values[index]
    if offset % 32 or offset // 32 >= len(values):
        raise ValueError("Array offset does not point inside the ABI payload")
    start = offset // 32
    length = values[start]
    end = start + 1 + length
    if end > len(values):
        raise ValueError("Array length exceeds the ABI payload")
    return values[start + 1 : end], end


def addr_array(values: list[int], index: int) -> tuple[list[str], int]:
    items, end = array_words(values, index)
    return [addr(item) for item in items], end


def account_kind(code: str | None) -> tuple[str, str | int | None]:
    data = (code or "0x").removeprefix("0x").lower()
    if not data or int(data, 16) == 0:
        return ("eoa", None)
    if data.startswith("ef0100") and len(data) == 46:
        return ("delegated", "0x" + data[6:])
    return ("contract", len(data) // 2)


def delegation_target(code: str | None) -> str | None:
    kind, value = account_kind(code)
    return str(value) if kind == "delegated" and isinstance(value, str) else None


def uint(value: str | int) -> int:
    return int(value, 16) if isinstance(value, str) else int(value)


def from_wei(value: int, decimals: int = 18) -> float:
    return value / 10**decimals
