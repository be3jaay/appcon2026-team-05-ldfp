from dataclasses import dataclass
from typing import Any


class OpenStatParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class TableVariable:
    code: str
    text: str
    values: list[str]
    value_texts: list[str]
    is_time: bool

    def code_for(self, label: str) -> str | None:
        wanted = label.strip().casefold()
        for code, text in zip(self.values, self.value_texts):
            if text.strip().casefold() == wanted:
                return code
        return None

    def label_for(self, code: str) -> str:
        return self.value_texts[self.values.index(code)]


@dataclass(frozen=True)
class TableMetadata:
    title: str
    variables: list[TableVariable]

    def variable(self, code: str) -> TableVariable:
        for var in self.variables:
            if var.code.casefold() == code.casefold():
                return var
        raise OpenStatParseError(f"OpenSTAT table has no '{code}' dimension.")


@dataclass(frozen=True)
class DataRow:
    key: dict[str, str]
    value: float | None


def parse_metadata(raw: dict[str, Any]) -> TableMetadata:
    try:
        variables = [
            TableVariable(
                code=v["code"],
                text=v.get("text", v["code"]),
                values=list(v["values"]),
                value_texts=list(v["valueTexts"]),
                is_time=bool(v.get("time", False)),
            )
            for v in raw["variables"]
        ]
    except (KeyError, TypeError) as exc:
        raise OpenStatParseError("OpenSTAT metadata is missing expected fields.") from exc
    return TableMetadata(title=raw.get("title", ""), variables=variables)


def parse_data(raw: dict[str, Any]) -> list[DataRow]:
    try:
        # Dimension columns come first, in the same order as each row's "key".
        dim_codes = [c["code"] for c in raw["columns"] if c.get("type") in ("t", "d")]
        rows = []
        for item in raw["data"]:
            key = dict(zip(dim_codes, item["key"], strict=True))
            rows.append(DataRow(key=key, value=_to_float(item["values"][0])))
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise OpenStatParseError("OpenSTAT data response is missing expected fields.") from exc
    return rows


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None
