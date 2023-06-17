import enum
from collections.abc import Callable
from inspect import Parameter, signature

from fastapi import APIRouter, Body, Depends, HTTPException, params
from fastapi.exceptions import RequestErrorModel
from fastapi.params import Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, create_model

from crud_api.base import BaseBulkCrud, BaseCrud, ByEnum, ErrorModel

RESPONSES = {
    404: {"detail": "Not Found"},
}


class BaseCRUDRouter(APIRouter):
    crud_model: type[BaseCrud]
    crud_model_dependence: Callable[..., BaseCrud]
    crud_schema_name: str

    def __init__(
        self,
        crud_model: type[BaseCrud],
        crud_model_dependence: Callable[..., BaseCrud],
        methods: tuple,
        *args,
        crud_schema_name: str = "",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.crud_model = crud_model
        self.crud_model_dependence = crud_model_dependence
        self.crud_schema_name = crud_model.schema.__name__
        if crud_schema_name:
            self.crud_schema_name = crud_schema_name

        for method in methods:
            func = getattr(self, f"_{method}", None)
            if func is None:
                continue
            func()

    @property
    def schema(self):
        return self.crud_model.schema

    @property
    def id_name_type(self) -> type:
        return self.schema.__fields__[self.crud_model.id_name].type_


class CRUDRouter(BaseCRUDRouter):
    def __init__(
        self,
        crud_model: type[BaseCrud],
        crud_model_dependence: Callable[..., BaseCrud],
        *args,
        methods: tuple = ("create", "read", "update_patch", "update_put", "delete"),
        crud_schema_name: str = "",
        **kwargs,
    ):
        super().__init__(
            crud_model,
            crud_model_dependence,
            *args,
            methods,
            crud_schema_name=crud_schema_name,
            **kwargs,
        )

    def _create(self):
        create_schema = create_model(f"Create{self.crud_schema_name}", __base__=self.schema)
        del create_schema.__fields__[self.crud_model.id_name]

        async def _create(data: create_schema, crud: BaseCrud = Depends(self.crud_model_dependence)):
            return await crud.create(**data.dict())

        self.post("", response_model=self.schema, status_code=201)(_create)

    def _read(self):
        async def _read(pk: self.id_name_type, crud: BaseCrud = Depends(self.crud_model_dependence)):
            resp = await crud.read(pk)
            if not resp:
                raise HTTPException(404)
            return resp

        self.get("/{pk}", response_model=self.schema, responses=RESPONSES)(_read)

    def _update_patch(self):
        patch_schema = create_model(f"PartUpdate{self.crud_schema_name}", __base__=self.schema)
        del patch_schema.__fields__[self.crud_model.id_name]
        for k in patch_schema.__fields__:
            patch_schema.__fields__[k].required = False

        async def _patch(
            pk: self.id_name_type, data: patch_schema, crud: BaseCrud = Depends(self.crud_model_dependence)
        ):
            resp = await crud.update(pk, **data.dict())
            if not resp:
                raise HTTPException(404)
            return resp

        self.patch("/{pk}", response_model=self.schema, responses=RESPONSES)(_patch)

    def _update_put(self):
        put_schema = create_model(f"FullUpdate{self.crud_schema_name}", __base__=self.schema)
        del put_schema.__fields__[self.crud_model.id_name]

        async def _put(pk: self.id_name_type, data: put_schema, crud: BaseCrud = Depends(self.crud_model_dependence)):
            resp = await crud.update(pk, **data.dict())
            if not resp:
                raise HTTPException(404)
            return resp

        self.put("/{pk}", response_model=self.schema, responses=RESPONSES)(_put)

    def _delete(self):
        async def _delete(pk: self.id_name_type, crud: BaseCrud = Depends(self.crud_model_dependence)):
            return await crud.delete(pk)

        self.delete("/{pk}", response_model=self.schema | None)(_delete)


class BulkCRUDRouter(BaseCRUDRouter):
    def __init__(
        self,
        crud_model: type[BaseBulkCrud],
        crud_model_dependence: Callable[..., BaseBulkCrud],
        *args,
        methods: tuple = (
            "bulk_create",
            "read_many",
            "bulk_update",
            "bulk_delete",
        ),
        crud_schema_name: str = "",
        only_errors: bool = True,
        available_filters: dict[str, type] | None = None,
        **kwargs,
    ):
        self.only_errors = only_errors
        self.available_filters = crud_model.available_filters
        if available_filters is not None:
            self.available_filters = available_filters

        super().__init__(
            crud_model,
            crud_model_dependence,
            *args,
            methods,
            crud_schema_name=crud_schema_name,
            **kwargs,
        )

    def _bulk_create(self):
        create_schema = create_model(f"BulkCreate{self.crud_schema_name}", __base__=self.schema)
        del create_schema.__fields__[self.crud_model.id_name]

        async def _create(data: tuple[create_schema, ...], crud: BaseBulkCrud = Depends(self.crud_model_dependence)):
            return [
                resp_obj
                async for resp_obj in crud.bulk_create([obj.dict() for obj in data], only_errors=self.only_errors)
            ]

        if self.only_errors:
            response_model = list[ErrorModel]
        else:
            response_model = list[self.schema | ErrorModel]
        self.post("", response_model=response_model, status_code=201)(_create)

    def _bulk_update(self):
        patch_schema = create_model(f"BulkPartUpdate{self.crud_schema_name}", __base__=self.schema)
        for k in patch_schema.__fields__:
            patch_schema.__fields__[k].required = False

        async def _patch(data: tuple[patch_schema, ...], crud: BaseBulkCrud = Depends(self.crud_model_dependence)):
            return [
                resp_obj
                async for resp_obj in crud.bulk_update(
                    [obj.dict(exclude_unset=True) for obj in data], only_errors=self.only_errors
                )
            ]

        if self.only_errors:
            response_model = list[ErrorModel]
        else:
            response_model = list[self.schema | ErrorModel]

        self.patch("", response_model=response_model)(_patch)

    def _bulk_delete(self):
        _schema = create_model(
            f"BulkDelete{self.crud_schema_name}", **{self.crud_model.id_name: (self.id_name_type, ...)}
        )

        async def _delete(pks: list[_schema], crud: BaseBulkCrud = Depends(self.crud_model_dependence)):
            return [
                resp_obj
                async for resp_obj in crud.bulk_delete(
                    [getattr(obj, self.crud_model.id_name) for obj in pks], only_errors=self.only_errors
                )
            ]

        if self.only_errors:
            response_model = list[ErrorModel]
        else:
            response_model = list[self.schema | ErrorModel]

        self.delete("", response_model=response_model)(_delete)

    def _read_many(self):
        response_model = list[self.schema]

        OrderByEnum = enum.Enum(
            "OrderByEnum",
            {
                f"{field.name}_{by}": f"{field.name}_{by}"
                for field in self.schema.__fields__.values()
                for by in ByEnum._member_names_
            },
        )

        async def _get(
            limit: int | None = None,
            offset: int | None = None,
            order_by: list[OrderByEnum] | None = Query(None),
            **filters,
        ):
            print(limit, offset, order_by, filters)
            return []

        _filter_params = [
            Parameter(_f, Parameter.KEYWORD_ONLY, default=Query(None), annotation=_t)
            for _f, _t in self.available_filters.items()
        ]
        sig = signature(_get)
        params = sig.parameters
        new_sig = sig.replace(
            parameters=[param for param in params.values() if param.name != "filters"] + _filter_params
        )
        _get.__signature__ = new_sig

        self.get("", response_model=response_model)(_get)
