from hypothesis import given
from hypothesis import strategies as st

from pons_analysis.results import Table


@given(
    st.lists(
        st.tuples(st.integers(), st.text(max_size=20)),
        max_size=50,
    )
)
def test_table_roundtrip(rows) -> None:
    table = Table.from_rows([{"number": number, "text": text} for number, text in rows])
    assert len(table) == len(rows)
    for original, decoded in zip(rows, table.to_dicts(), strict=True):
        assert decoded == {"number": original[0], "text": original[1]}
