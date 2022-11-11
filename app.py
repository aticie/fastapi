import hashlib
import os
import uuid
from typing import List

import aiohttp
from fastapi import Depends, FastAPI, HTTPException, Cookie
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from dbsql import crud, models, schemas
from dbsql.database import SessionLocal, engine
from dbsql.schemas import OsuUserCreate, DiscordUser

ONE_MONTH = 2592000

models.Base.metadata.create_all(bind=engine)

frontend_homepage = os.getenv("FRONTEND_HOMEPAGE")
app = FastAPI()

if os.getenv("DEV"):
    origins = [
        "*"
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_with_secret(string_to_be_hashed: str) -> str:
    hash_secret = os.getenv("SECRET")
    return hashlib.md5(f"{string_to_be_hashed}+{hash_secret}".encode()).hexdigest()


def hash_with_random(string_to_be_hashed: str) -> str:
    hash_secret = uuid.uuid4()
    return hashlib.md5(f"{string_to_be_hashed}+{hash_secret}".encode()).hexdigest()


async def oauth2_authorization(code: str,
                               client_id: str,
                               client_secret: str,
                               redirect_uri: str,
                               token_endpoint: str,
                               me_endpoint: str):
    token_body = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri
    }
    async with aiohttp.ClientSession() as sess:
        async with sess.post(token_endpoint, data=token_body) as resp:
            contents = await resp.json()

        access_token = contents.get("access_token")
        if not access_token:
            raise HTTPException(500,
                                "Something went wrong with the authentication, didn't get access token...")

        headers = {"Authorization": f"Bearer {access_token}"}
        async with sess.get(me_endpoint, headers=headers) as resp:
            me_result = await resp.json()

    return me_result


@app.get("/osu-identify", response_class=RedirectResponse)
async def osu_identify(code: str, db: Session = Depends(get_db)) -> RedirectResponse:
    me_result = await oauth2_authorization(code=code,
                                           client_id=os.getenv("OSU_CLIENT_ID"),
                                           client_secret=os.getenv("OSU_CLIENT_SECRET"),
                                           redirect_uri=os.getenv("REDIRECT_URI") + "/osu-identify",
                                           token_endpoint=r"https://osu.ppy.sh/oauth/token",
                                           me_endpoint=r"https://osu.ppy.sh/api/v2/me/osu")
    osu_id = me_result["id"]
    user_hash = hash_with_secret(osu_id)
    redirect = RedirectResponse(frontend_homepage)
    redirect.set_cookie(key="user_hash", value=user_hash, max_age=ONE_MONTH)

    global_rank = me_result["statistics"]["global_rank"]
    badges = me_result["badges"]
    num_badges = len(badges)
    bws_rank = round(global_rank if global_rank else 0 ** (0.9937 ** (num_badges ** 2)))

    db_user = crud.get_user(db=db, user_hash=user_hash)
    if db_user:
        return redirect

    user = OsuUserCreate(osu_id=osu_id,
                         osu_username=me_result["username"],
                         osu_avatar_url=me_result["avatar_url"],
                         osu_global_rank=me_result["statistics"]["global_rank"],
                         user_hash=user_hash,
                         bws_rank=bws_rank,
                         badges=num_badges)

    crud.create_osu_user(db=db, user=user)

    return redirect


@app.get("/discord-identify", response_class=RedirectResponse)
async def discord_identify(code: str, db: Session = Depends(get_db),
                           user_hash: str | None = Cookie(default=None)):
    me_result = await oauth2_authorization(code=code,
                                           client_id=os.getenv("DISCORD_CLIENT_ID"),
                                           client_secret=os.getenv("DISCORD_CLIENT_SECRET"),
                                           redirect_uri=os.getenv("REDIRECT_URI") + "/discord-identify",
                                           token_endpoint=r"https://discord.com/api/oauth2/token",
                                           me_endpoint=r"https://discord.com/api/v10/users/@me")

    id = me_result["id"]
    username = me_result["username"]
    discriminator = me_result["discriminator"]
    avatar_hash = me_result["avatar"]
    avatar_url = f"https://cdn.discordapp.com/avatars/{id}/{avatar_hash}.png"
    user = DiscordUser(discord_id=id,
                       discord_avatar_url=avatar_url,
                       discord_tag=f"{username}#{discriminator}",
                       )
    crud.upgrade_to_discord_user(db=db, user_hash=user_hash, user=user)

    redirect = RedirectResponse(frontend_homepage)
    redirect.set_cookie(key="user", value=user_hash, max_age=ONE_MONTH)
    return redirect


@app.get("/users/me", response_model=schemas.User)
async def read_me(db: Session = Depends(get_db),
                  user_hash: str = Cookie(default=None)):
    user = crud.get_user(db, user_hash)
    return user


@app.get("/users/me/invites", response_model=List[schemas.Invite])
async def read_user_invites(db: Session = Depends(get_db),
                            user_hash: str = Cookie(default=None)):
    invites = crud.get_user_invites(db, user_hash)
    return invites


@app.get("/team/invites", response_model=List[schemas.Invite])
async def read_team_invites(team_hash: str, db: Session = Depends(get_db)):
    return crud.get_team_invites(db, team_hash)


@app.get("/users", response_model=List[schemas.User])
async def read_users(db: Session = Depends(get_db), skip: int = 0, limit: int = 100):
    user = crud.get_users(db=db, skip=skip, limit=limit)
    return user


@app.get("/teams", response_model=List[schemas.Team])
async def read_teams(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    teams = crud.get_teams(db, skip=skip, limit=limit)
    return teams


@app.post("/team/create", response_model=schemas.Team)
async def create_team(team: schemas.TeamCreate, db: Session = Depends(get_db),
                      user_hash: str | None = Cookie(default=None)):
    team_hash = hash_with_random(user_hash)
    team = crud.create_team(db=db, team=team, user_hash=user_hash, team_hash=team_hash)

    return team


@app.post("/team/join", response_model=schemas.User)
def join_team(team_hash: str, db: Session = Depends(get_db),
              user_hash: str | None = Cookie(default=None)):
    db_user = crud.add_to_team(db=db, team_hash=team_hash, user_hash=user_hash)

    return db_user


@app.post("/team/leave", response_model=schemas.User)
def leave_team(db: Session = Depends(get_db),
              user_hash: str | None = Cookie(default=None)):
    db_user = crud.leave_team(db=db, user_hash=user_hash)

    return db_user


@app.post("/team/invite", response_model=schemas.Invite)
def create_invite(other_user_osu_id: int,
                  db: Session = Depends(get_db),
                  user_hash: str | None = Cookie(default=None)):
    return crud.create_invite(db=db, team_owner_hash=user_hash, invited_user_osu_id=other_user_osu_id)
