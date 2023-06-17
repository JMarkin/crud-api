from collections.abc import AsyncIterator, Iterable, Sized
from functools import cache
from typing import Any

from asyncpg import Pool
from pydantic import BaseModel

from .base import BaseBulkCrud, BaseCrud, ByEnum, ErrorModel, cached_property


class AsyncpgCrud(BaseCrud):
    table: str
    pool: Pool

    def __init__(self, pool: Pool):
        self.pool = pool

    @cached_property
    def columns(cls) -> tuple[str, ...]:
        return tuple(cls.schema.__fields__)

    @cached_property
    def creatable_columns(cls) -> tuple[str, ...]:
        return tuple(k for k in cls.schema.__fields__ if k != cls.id_name)

    @cached_property
    def columns_str(cls) -> str:
        return ",".join(cls.columns)

    @cached_property
    def create_sql(cls):
        return """
            insert into {}({}) values ({}) returning *
        """.format(
            cls.table,
            ",".join(cls.creatable_columns),
            ",".join(f"${i+1}" for i in range(len(cls.creatable_columns))),
        )

    async def create(self, **fields) -> BaseModel:
        async with self.pool.acquire() as conn:
            data = await conn.fetchrow(self.create_sql, *(fields[k] for k in self.creatable_columns))
        return self.schema(**data)

    @cached_property
    def read_sql(cls):
        return """
            select * from {} where {} = $1
        """.format(
            cls.table,
            cls.id_name,
        )

    async def read(self, pk: Any) -> BaseModel | None:
        async with self.pool.acquire() as conn:
            data = await conn.fetchrow(self.read_sql, pk)
        if not data:
            return None
        return self.schema(**data)

    @cached_property
    def update_sql(cls):
        return """
            update {} set {{}} where {} = $1 returning *
        """.format(
            cls.table,
            cls.id_name,
        )

    async def update(self, pk: Any, **fields) -> BaseModel | None:
        keys = [k for k in fields if k in self.creatable_columns]
        if len(keys) == 0:
            raise ValueError("No fields for update")
        set_sql = ",".join(f"{keys[i]} = ${i+2}" for i in range(len(keys)))
        sql = self.update_sql.format(set_sql)
        async with self.pool.acquire() as conn:
            data = await conn.fetchrow(sql, pk, *(fields[keys[i]] for i in range(len(keys))))
        if not data:
            return None
        return self.schema(**data)

    @cached_property
    def delete_sql(cls):
        return """
            delete from {} where {} = $1 returning *
        """.format(
            cls.table,
            cls.id_name,
        )

    async def delete(self, pk: Any) -> BaseModel | None:
        async with self.pool.acquire() as conn:
            data = await conn.fetchrow(self.delete_sql, pk)
        if not data:
            return None
        return self.schema(**data)


class AsyncpgBulkCrud(AsyncpgCrud, BaseBulkCrud):
    async def bulk_create(
        self, data: Iterable[dict], only_errors: bool = True
    ) -> AsyncIterator[BaseModel | ErrorModel]:
        for obj in data:
            try:
                _obj = await self.create(**obj)
                if not only_errors:
                    yield _obj
            except Exception as e:
                yield ErrorModel(obj=obj, error=str(e))

    filter_operator = {
        "eq": "=",
        "in": "in",
        "lte": "<=",
        "lt": "<",
        "gt": ">",
        "gte": ">=",
    }

    def _configure_filters_sql(
        self,
        filters: dict[str, Any],
    ):
        arguments = []
        filters_sql = []

        if filters is not None:
            for f in filters:
                field, _filter = f.split("_")
                operator = self.filter_operator[_filter]
                arguments.append(filters[f])
                filters_sql.append(f"{field} {operator} ${len(arguments)}")

        return filters_sql, arguments

    async def _read_many(
        self,
        limit: int | None = None,
        offset: int | None = None,
        order_by: dict[str, ByEnum] | None = None,
        **filters,
    ) -> AsyncIterator[BaseModel]:
        sql = f"select * from {self.table}"

        filters_sql, arguments = self._configure_filters_sql(filters)

        if len(filters_sql) > 0:
            sql = f"{sql} where {' and '.join(filters_sql)}"

        if limit is not None:
            arguments.append(limit)
            sql = f"{sql} limit ${len(arguments)}"

        if offset is not None:
            arguments.append(offset)
            sql = f"{sql} offset ${len(arguments)}"

        if order_by is not None:
            order_by_str = ",".join(
                f"{k} {sort}"
                for k, sort in map(
                    lambda k, v: (k, v.value),  # type: ignore
                    order_by.items(),
                )
            )
            sql = f"{sql} order by {order_by_str}"

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if len(arguments) > 0:
                    cursor = conn.cursor(sql, *arguments)
                else:
                    cursor = conn.cursor(sql)
                async for record in cursor:
                    yield self.schema(**record)

    async def bulk_update(
        self, data: Iterable[dict], only_errors: bool = True
    ) -> AsyncIterator[BaseModel | ErrorModel]:
        for obj in data:
            try:
                if self.id_name not in obj:
                    raise ValueError(f"{self.id_name} not in object")
                _obj = await self.update(obj[self.id_name], **obj)
                if not only_errors and _obj:
                    yield _obj
            except Exception as e:
                yield ErrorModel(obj=obj, error=str(e))

    async def bulk_delete(
        self,
        pks: Iterable[Any],
        only_errors: bool = True,
    ) -> AsyncIterator[BaseModel | ErrorModel]:
        for pk in pks:
            try:
                obj = await self.delete(pk)
                if not only_errors and obj:
                    yield obj
            except Exception as e:
                yield ErrorModel(obj={"pk": pk}, error=str(e))
