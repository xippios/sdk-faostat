"""Pydantic models mirroring upstream's payloads, one ``UpstreamModel`` per object.

Conventions §3 and ``/add-endpoint`` give the rules.

The names come from the OpenAPI document (``docs/upstream/openapi/faostat_openapi.yaml``)
where its schemas match the answers, and from the recorded answers where they do not
(FETCHED.md, "How this is captured": the answers' field names differ from the document's
schemas). ``Auth`` and ``AuthenticationResult`` are ``auth_login``'s answer, the
document's ``Auth`` schema; ``DataResponse`` with ``DataMetadata``, ``DsdColumn`` and
``DataRecord`` is ``get_data``'s, the document's ``DataResponse`` schema as the recorded
answers spell it (``docs/upstream/samples/data_QCL_231_2510_15_2015-2021.json``);
``GroupsAndDomainsResponse`` with ``Metadata`` and ``Domain`` is
``get_groupsanddomains``'s, the document's ``GroupsAndDomainsResponse`` and
``DomainMetadata`` schemas (``docs/upstream/samples/groupsanddomains.json``);
``CodeResponse`` with ``CodeItem`` is ``getCodeList``'s, the document's ``CodeResponse``
and ``CodeItem`` schemas (``docs/upstream/samples/codes_element_QCL.json``). Each field
is upstream's name snake_cased, the upstream spelling accepted with ``validation_alias``,
so every output surface stays snake_case.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import Field, SecretStr, model_validator
from xippios.core import UpstreamModel

__all__ = [
    "Auth",
    "AuthenticationResult",
    "CodeItem",
    "CodeResponse",
    "DataMetadata",
    "DataRecord",
    "DataResponse",
    "Domain",
    "DsdColumn",
    "GroupsAndDomainsResponse",
    "Metadata",
]


def _gather_columns(model: type[UpstreamModel], data: Any) -> Any:
    """``data`` with the keys no field of ``model`` names gathered into ``columns``.

    A row's columns under upstream's headers, as sent and in the row's order, for a
    model that keeps every column it does not name (ADR-0003: nothing dropped). A
    mapping that carries ``columns`` already (a record dumped by field name) is taken as
    it is.
    """
    if not isinstance(data, Mapping) or "columns" in data:
        return data
    named = set(model.model_fields)
    named |= {
        field.validation_alias
        for field in model.model_fields.values()
        if isinstance(field.validation_alias, str)
    }
    others = {header: value for header, value in data.items() if header not in named}
    return {**data, "columns": others}


class AuthenticationResult(UpstreamModel):
    """The tokens of a login: ``auth_login``'s ``AuthenticationResult``, issued by Cognito.

    The three tokens are ``SecretStr``, masked in every ``repr`` and dump; the package
    keeps the access token alone (``_client.LoginAuth``).

    Attributes:
        access_token: The token a request sends as ``Authorization: Bearer <token>``;
            upstream's ``AccessToken``.
        expires_in: Seconds the access token lives, e.g. ``3600``; upstream's ``ExpiresIn``.
        id_token: The identity token, which carries the account's e-mail; upstream's
            ``IdToken``. Never kept.
        refresh_token: Upstream's ``RefreshToken``; never kept.
        token_type: The kind of token, e.g. ``"Bearer"``; upstream's ``TokenType``.
    """

    access_token: SecretStr = Field(validation_alias="AccessToken")
    expires_in: int = Field(validation_alias="ExpiresIn")
    id_token: SecretStr = Field(validation_alias="IdToken")
    refresh_token: SecretStr = Field(validation_alias="RefreshToken")
    token_type: str = Field(validation_alias="TokenType")


class Auth(UpstreamModel):
    """``auth_login``'s answer: the document's ``Auth`` schema.

    Attributes:
        authentication_result: The tokens; upstream's ``AuthenticationResult``.
        challenge_parameters: Upstream's ``ChallengeParameters``, an object the document
            leaves untyped, empty in the recorded login.
    """

    authentication_result: AuthenticationResult = Field(validation_alias="AuthenticationResult")
    challenge_parameters: Mapping[str, Any] = Field(
        default_factory=dict, validation_alias="ChallengeParameters"
    )


class DsdColumn(UpstreamModel):
    """One column of a data answer's structure, ``metadata.dsd``.

    Attributes:
        label: The column's header, e.g. ``"Area Code"``.
        type: What the column holds, e.g. ``"code"``, ``"label"``, ``"unit"``,
            ``"value"``, ``"flag"`` or ``"flag_label"``.
        key: The record's key for the column, e.g. ``"Area Code"``.
        dimension_id: The dimension the column belongs to, e.g. ``"area"``; ``None`` for
            ``Domain Code``, ``Domain`` and ``Note``, which name none.
        data_type: The column's data type, e.g. ``"string"`` (every column of the
            recorded answers, ``Value`` included).
    """

    label: str
    type: str
    key: str
    dimension_id: str | None = None
    data_type: str


class Metadata(UpstreamModel):
    """An answer's ``metadata``: the document's ``Metadata`` schema.

    Attributes:
        processing_time: Milliseconds upstream took, e.g. ``89``; changes on every request.
        datasource: The database answered from, e.g. ``"PRODUCTION"``.
        output_type: The answer's form, e.g. ``"OBJECTS"``.
    """

    processing_time: int
    datasource: str
    output_type: str


class DataMetadata(Metadata):
    """A data answer's ``metadata``: ``Metadata`` and the answer's columns.

    Attributes:
        dsd: The answer's columns in order, e.g. ``Domain Code`` first and ``Note`` last.
    """

    dsd: list[DsdColumn] = Field(default_factory=list)


class DataRecord(UpstreamModel):
    """One row of a data answer: one value with its domain, area, element, item and year.

    The columns as the answers print them, each a field snake_cased: ``Domain Code``,
    ``Domain``, ``Area Code``, ``Area``, ``Element Code``, ``Element``, ``Item Code``,
    ``Item``, ``Year Code``, ``Year``, ``Unit``, ``Value``, ``Flag``, ``Flag Description``,
    ``Note`` (QCL, recorded 2026-10-29). A domain may print other columns: PP prints
    ``Months Code`` and ``Months`` and no ``Note`` (recorded 2026-10-29,
    ``tests/fixtures/get_data/PP_231_2020_page_size_2.json``), so ``months_code`` and
    ``months`` are ``None`` in a domain without them and ``note`` in one without it. Every
    column the row prints beyond the named ones is kept in ``columns`` under upstream's
    header, so nothing is dropped (ADR-0003); a named column is never there too. A query
    with ``area_cs`` or ``item_cs`` renames the code column: the recorded answer to
    ``area_cs=FAO`` and ``item_cs=FAO`` prints ``Area Code (FAO)`` and ``Item Code (FAO)``
    (``tests/fixtures/get_data/QCL_231_FAO_15_FAO_2510_2020.json``), and the one to
    ``area_cs=M49`` names ``Area Code (M49)`` in its ``metadata.dsd``
    (``tests/fixtures/get_data/QCL_840_M49_15_2510_2020.json``, no rows); such a row has
    ``area_code`` or ``item_code`` ``None`` and its coded column in ``columns``. The
    OpenAPI document's ``DataResponse`` spells the two columns ``Area Code (M49)`` and
    ``Item Code (CPC)``; a query without ``area_cs`` and ``item_cs`` prints ``Area Code``
    and ``Item Code`` (FETCHED.md). Every value is text as printed but ``value``.

    ``element_code`` is the code the answer prints, which is not the code a query filters
    by: a query with ``element=2510`` (Production Quantity in ``codes/element/QCL``)
    answers rows with ``element_code`` ``"5510"`` (Production), and nothing is translated
    (ADR-0003); ``list_elements`` lists the filter codes.

    Attributes:
        domain_code: The domain, e.g. ``"QCL"``; upstream's ``Domain Code``.
        domain: The domain's name, e.g. ``"Crops and livestock products"``.
        area_code: The area's FAO code, e.g. ``"231"``; upstream's ``Area Code``. ``None``
            where a query with ``area_cs`` prints the codes under another header
            (``Area Code (M49)``), which ``columns`` keeps.
        area: The area's name, e.g. ``"United States of America"``.
        element_code: The element's code as the answer prints it, e.g. ``"5510"``;
            upstream's ``Element Code``.
        element: The element's name, e.g. ``"Production"``.
        item_code: The item's FAO code, e.g. ``"15"``; upstream's ``Item Code``. ``None``
            where a query with ``item_cs`` prints the codes under another header
            (``Item Code (FAO)``), which ``columns`` keeps.
        item: The item's name, e.g. ``"Wheat"``.
        year_code: The year's code, e.g. ``"2020"``; upstream's ``Year Code``.
        year: The year, e.g. ``"2020"``.
        months_code: The period's code, e.g. ``"7021"``; upstream's ``Months Code``,
            printed by PP; ``None`` in a domain without the column.
        months: The period, e.g. ``"Annual value"``; upstream's ``Months``, printed by
            PP; ``None`` in a domain without the column.
        unit: The value's unit as printed, e.g. ``"t"``.
        value: The value, a number where its text is one, e.g. ``Decimal("49751180")``,
            else the text as printed; ``None`` for ``null``. Upstream's ``Value``.
        flag: The value's flag, e.g. ``"A"``.
        flag_description: The flag's meaning, e.g. ``"Official value"``; upstream's
            ``Flag Description``.
        note: The value's note as printed, ``""`` when it has none; ``None`` for ``null``
            and in a domain without the column (PP).
        columns: The row's other columns, under upstream's headers, as sent, in the
            row's order, e.g. ``{"Area Code (M49)": ...}`` for a query with
            ``area_cs=M49``; ``{}`` in the recorded QCL and PP rows, whose columns are all
            named.
    """

    domain_code: str = Field(validation_alias="Domain Code")
    domain: str = Field(validation_alias="Domain")
    area_code: str | None = Field(default=None, validation_alias="Area Code")
    area: str = Field(validation_alias="Area")
    element_code: str = Field(validation_alias="Element Code")
    element: str = Field(validation_alias="Element")
    item_code: str | None = Field(default=None, validation_alias="Item Code")
    item: str = Field(validation_alias="Item")
    year_code: str = Field(validation_alias="Year Code")
    year: str = Field(validation_alias="Year")
    months_code: str | None = Field(default=None, validation_alias="Months Code")
    months: str | None = Field(default=None, validation_alias="Months")
    unit: str = Field(validation_alias="Unit")
    value: Decimal | str | None = Field(validation_alias="Value", union_mode="left_to_right")
    flag: str = Field(validation_alias="Flag")
    flag_description: str = Field(validation_alias="Flag Description")
    note: str | None = Field(default=None, validation_alias="Note")
    columns: Mapping[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _other_columns(cls, data: Any) -> Any:
        """Gather the columns no field names into ``columns``, under upstream's headers."""
        return _gather_columns(cls, data)


class DataResponse(UpstreamModel):
    """``get_data``'s answer: its metadata and its rows.

    Attributes:
        metadata: Processing time, datasource, output type and the columns.
        data: The rows, ``[]`` when no row matches the query (an unknown code too).
    """

    metadata: DataMetadata
    data: list[DataRecord]


class Domain(UpstreamModel):
    """One row of ``groupsanddomains``: a domain (a dataset) or a subgroup, with its group.

    The fields as the answer prints them, in its order; the dates are text as printed,
    since ``release_current`` and ``release_next`` hold more than a date
    (``"2026-01-09 / 2026-10-09"``, ``"2026-12"``, ``""``). A subgroup's row
    (``subgroup_flag`` ``"1"``, ``domain_level`` 1, ``"RN"`` Land) has no dates, no
    release fields and no focal point: those are ``None`` there.

    Attributes:
        group_code: The group, e.g. ``"Q"``.
        group_name: The group's name, e.g. ``"Production"``.
        subgroup_code: The subgroup of a domain at level 3, e.g. ``"RN"``; ``None`` elsewhere.
        subgroup_name: The subgroup's name, e.g. ``"Land"``; ``None`` elsewhere.
        domain_code: The domain, e.g. ``"QCL"``: ``get_data``'s ``domain``.
        domain_name: The domain's name, e.g. ``"Crops and livestock products"``.
        date_update: The domain's last update as printed, e.g. ``"2025-12-31"``.
        note_update: A note on the update, e.g. ``"minor revision"``, or ``""``.
        release_current: The current release as printed, e.g. ``"2025-12-31"`` or
            ``"2026-01-09 / 2026-10-09"``.
        state_current: The current release's state, e.g. ``"final"``.
        year_current: The latest year of the current release, e.g. ``"2024"``.
        release_next: The next release as printed, e.g. ``"2026-12"``, or ``""``.
        state_next: The next release's state, e.g. ``"final"``.
        year_next: The latest year of the next release, e.g. ``"2025"``.
        release_note: E.g. ``"update"`` or ``"revision"``.
        release_note_expiry: As printed, e.g. ``"2026-02-28"``, or ``""``.
        subgroup_flag: ``"1"`` for a subgroup's row, else ``"0"``.
        subdomain_flag: As printed, e.g. ``"0"``.
        domain_level: The row's level in the tree: 1 a subgroup, 2 or 3 a domain.
        sdg_flag: ``"1"`` where the domain serves a Sustainable Development Goal, else ``"0"``.
        sdg_text: As printed, e.g. ``""``.
        focal_point: The domain's contact address, e.g. ``"FAOSTAT@fao.org"``;
            upstream's ``FocalPoint``.
    """

    group_code: str
    group_name: str
    subgroup_code: str | None = None
    subgroup_name: str | None = None
    domain_code: str
    domain_name: str
    date_update: str | None = None
    note_update: str | None = None
    release_current: str | None = None
    state_current: str | None = None
    year_current: str | None = None
    release_next: str | None = None
    state_next: str | None = None
    year_next: str | None = None
    release_note: str | None = None
    release_note_expiry: str | None = None
    subgroup_flag: str | None = None
    subdomain_flag: str | None = None
    domain_level: int
    sdg_flag: str | None = None
    sdg_text: str | None = None
    focal_point: str | None = Field(default=None, validation_alias="FocalPoint")


class GroupsAndDomainsResponse(UpstreamModel):
    """``get_groupsanddomains``'s answer: its metadata and one row per domain or subgroup.

    Attributes:
        metadata: Processing time, datasource and output type.
        data: The rows, group by group, e.g. 78 on 2026-10-29.
    """

    metadata: Metadata
    data: list[Domain]


class CodeItem(UpstreamModel):
    """One code of a domain's dimension, as ``getCodeList`` lists it: the document's ``CodeItem``.

    The codes a data query filters by: ``codes/area/QCL`` lists the areas QCL's
    ``area`` takes (``"231"`` United States of America), ``codes/element/QCL`` its
    elements (``"2510"`` Production Quantity), ``codes/item/QCL`` its items (``"15"``
    Wheat). An element code here is a filter code, which the data rows do not print: a
    query with ``element=2510`` answers rows whose ``element_code`` is ``"5510"``
    (Production), and nothing is translated between the two (ADR-0003). The document's
    schema names ``code``, ``label`` and ``aggregate_type``; QCL's and TCL's item lists,
    RL's on 51 of its 57 records, and TCL's and RL's element lists carry ``parent`` as
    well (2026-10-29), which this model names, and every other field a list carries is
    kept in ``columns`` under upstream's name, so nothing is dropped. A list may name a
    code twice (QCL's item list its five top groups, ``QC>`` among them), as upstream
    sends it.

    Attributes:
        code: The code, as a data query sends it, e.g. ``"231"``, ``"2510"``, ``"15"``,
            or ``"5000>"`` (World > (List)).
        label: The code's name as printed, e.g. ``"United States of America"``,
            ``"Production Quantity"``, ``"Wheat"`` or ``"World + (Total)"``.
        parent: The code above it in the list's tree as printed, e.g. ``"QC>"`` (Crops,
            primary > (List)) or ``"#"`` at the top; ``None`` for a record without the
            field (every area list, the element lists of QCL, FBS and PP, the item lists
            of FBS and PP, and six records of RL's, on 2026-10-29).
        aggregate_type: As printed: ``"0"`` in the recorded lists for a single code,
            ``"+"`` for a code whose label ends ``+ (Total)`` and ``">"`` for one whose
            code and label end ``>`` and ``> (List)``; ``None`` where the field is absent.
        columns: The code's other fields, under upstream's names, as sent; ``{}`` in the
            recorded lists, whose fields are all named.
    """

    code: str
    label: str
    parent: str | None = None
    aggregate_type: str | None = None
    columns: Mapping[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _other_columns(cls, data: Any) -> Any:
        """Gather the fields no field names into ``columns``, under upstream's names."""
        return _gather_columns(cls, data)

    def dump_upstream(self) -> dict[str, Any]:
        """This code as upstream sent it, for a packaged table (conventions §3).

        The named fields the list carried, under upstream's names, which are the
        fields' own, then ``columns`` as sent: a named field the list lacked
        (``parent`` in an area list) is left out, so a packaged record is upstream's.

        Returns:
            E.g. ``{"code": "231", "label": "United States of America",
            "aggregate_type": "0"}``.
        """
        dumped = super().dump_upstream()
        sent = {
            name: dumped[name]
            for name in type(self).model_fields
            if name != "columns" and name in self.model_fields_set
        }
        return {**sent, **self.columns}


class CodeResponse(UpstreamModel):
    """``getCodeList``'s answer: the document's ``CodeResponse``, its metadata and its codes.

    Attributes:
        metadata: Processing time, datasource and output type.
        data: The codes in upstream's order, e.g. 5 for ``codes/element/QCL`` on
            2026-10-29.
    """

    metadata: Metadata
    data: list[CodeItem]
