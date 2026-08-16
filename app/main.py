from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import applications

# The app deliberately does not create or alter schema. `alembic upgrade head`
# is the single mechanism, run before the service starts — see README §7.
#
# This used to call Base.metadata.create_all. Leaving it alongside migrations
# would mean two things defining the schema: create_all adds a table no
# revision knows about, and the next autogenerate then proposes dropping it.
# Starting against a database that has not been migrated should fail loudly on
# the first query rather than be silently papered over here.

app = FastAPI(title="Job Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(applications.router)


@app.get("/health")
def health():
    return {"status": "ok"}
