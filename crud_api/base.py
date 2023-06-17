import abc
import datetime
import enum
from abc import abstractmethod
from collections.abc import AsyncIterator, Iterable, Sized
from decimal import Decimal
from functools import cache
from typing import Any

from pydantic import BaseModel, validator
from pydantic.fields import ModelField


def cached_property(f):
    return classmethod(property(cache(f)))


class ByEnum(enum.Enum):
    asc = "asc"
    desc = "desc"


class BaseCrud(abc.ABC):
    schema: type[BaseModel]
    id_name: str = "id"

    @abstractmethod
    async def create(self, **fields) -> BaseModel:
        ...

    @abstractmethod
    async def read(self, pk: Any) -> BaseModel | None:
        ...

    @abstractmethod
    async def update(self, pk: Any, **fields) -> BaseModel | None:
        ...

    @abstractmethod
    async def delete(self, pk: Any) -> BaseModel | None:
        ...


class ErrorModel(BaseModel):
    obj: dict
    error: str


class BaseBulkCrud(abc.ABC):
    schema: type[BaseModel]
    id_name: str = "id"

    @abstractmethod
    async def bulk_create(
        self, data: Iterable[dict], only_errors: bool = True
    ) -> AsyncIterator[BaseModel | ErrorModel]:
        yield ErrorModel(obj={}, error="unimplement")

    all_fields_filters = ("eq", "in")
    _other_filters = ("lte", "lt", "gt", "gte")
    specific_type_mapping = {}
    for _t in (int, float, datetime.date, datetime.datetime, datetime.timedelta, datetime.time, Decimal):
        specific_type_mapping[_t] = _other_filters

    @cached_property
    def available_filters(cls) -> dict[str, type]:
        _filters = {}
        val: ModelField
        for val in cls.schema.__fields__.values():
            field_filters = cls.all_fields_filters
            spec = False
            for _type in cls.specific_type_mapping:
                if isinstance(val.type_, _type) or val.type_ is _type:
                    field_filters += cls.specific_type_mapping[_type]
                    spec = True
                    break
            for f in field_filters:
                _t = str
                if spec:
                    _t = val.type_
                if f == "in":
                    _t = tuple[_t]
                _filters[f"{val.name}_{f}"] = _t

        return _filters

    @abstractmethod
    async def _read_many(
        self,
        limit: int | None = None,
        offset: int | None = None,
        order_by: dict[str, ByEnum] | None = None,
        **filters,
    ) -> AsyncIterator[BaseModel]:
        # mypy fix
        yield BaseModel()

    async def read_many(
        self,
        limit: int | None = None,
        offset: int | None = None,
        order_by: dict[str, int] | None = None,
        **filters,
    ) -> AsyncIterator[BaseModel]:
        if len(filters) > 0:
            filters = {k: v for k, v in filters.items() if k in self.available_filters}
        if order_by is not None:
            order_by = {k: v for k, v in order_by.items() if k in self.schema.__fields__}
        async for obj in self._read_many(limit=limit, offset=offset, order_by=order_by, **filters):
            yield obj

    @abstractmethod
    async def bulk_update(
        self, data: Iterable[dict], only_errors: bool = True
    ) -> AsyncIterator[BaseModel | ErrorModel]:
        yield ErrorModel(obj={}, error="unimplement")

    @abstractmethod
    async def bulk_delete(
        self,
        pks: Iterable[Any],
        only_errors: bool = True,
    ) -> AsyncIterator[BaseModel | ErrorModel]:
        yield ErrorModel(obj={}, error="unimplement")
