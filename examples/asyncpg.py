import json
import random
from datetime import datetime

import asyncpg
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, validator

from crud_api.asyncpg import AsyncpgBulkCrud, AsyncpgCrud
from crud_api.contrib.fastapi import BulkCRUDRouter, CRUDRouter

app = FastAPI()

DATABASE_URL = "postgresql://postgres:postgres@postgres:5432/postgres"

TABLE = "example" + str(random.randint(0, 999))


@app.on_event("startup")
async def startup():
    pool = await asyncpg.create_pool(DATABASE_URL, max_inactive_connection_lifetime=3)
    async with pool.acquire() as pg:
        await pg.execute(f"drop table if exists {TABLE}")
        await pg.execute(
            f"""
            create table {TABLE} (
                id serial primary key,
                user_id varchar(100),
                created_dt timestamp with time zone default current_timestamp,
                updated_dt timestamp with time zone default current_timestamp,
                data jsonb
            );
        """
        )
        await pg.execute(
            """
            create or replace function update_dt()
              returns trigger
              language plpgsql as
            $$
            begin
               new.updated_dt := current_timestamp;
               return new;
            end
            $$;
            """
        )
        await pg.execute(
            f"""
            create trigger up before insert or update on {TABLE}
            for each row execute function update_dt();
        """
        )

    app.pool = pool


@app.on_event("shutdown")
async def shutdown():
    pool = app.pool
    async with pool.acquire() as pg:
        await pg.execute(f"drop table {TABLE}")
    await pool.close()


class TestSchema(BaseModel):
    id: int
    user_id: str
    created_dt: datetime
    updated_dt: datetime
    data: dict | str

    @validator("data", pre=True)
    def change_data(cls, v):
        if isinstance(v, dict):
            v = json.dumps(v)
        return v


class ExampleCrud(AsyncpgCrud):
    table = TABLE
    schema = TestSchema


class ExampleBulkCrud(AsyncpgBulkCrud):
    table = TABLE
    schema = TestSchema


def crud_dep():
    return ExampleCrud(pool=app.pool)


def bulk_crud_dep():
    return ExampleBulkCrud(pool=app.pool)


main_router = APIRouter()
router_1 = CRUDRouter(crud_model=ExampleCrud, crud_model_dependence=crud_dep, prefix="/example", tags=["single"])
router_2 = BulkCRUDRouter(
    crud_model=ExampleBulkCrud,
    crud_model_dependence=bulk_crud_dep,
    prefix="/bulk-example",
    tags=["bulk"],
    only_errors=False,
    # available_filters={
    #     'id_in': list[int],
    #     'id_eq': int,
    #     'user_id_eq': int,
    #     'user_id_in': list[int],
    # }
)


main_router.include_router(router_1)
main_router.include_router(router_2)
app.include_router(main_router)
