"""Adpress HTTP API (PRD: API)."""

from __future__ import annotations

import difflib
import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import compliance, db as dbmod, exporter, generation, kit_markdown
from .auth import ROLES, current_user, editor, hash_password, issue_token, owner, revoke_token, verify_password
from .config import settings
from .db import get_db, init_db
from .fetcher import Fetcher, FetchError, normalize_url
from .formats import all_formats, get_format
from .kit import Industry, Kit
from .kit_builder import build_kit
from .llm import LLMError, Usage, get_llm
from .models import Ad, AuditLog, Brand, Event, GenRequest, Job, KitVersion, Source, User, Workspace, utcnow

log = logging.getLogger("adpress")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    # Jobs run in-process; any left running by a previous process will never finish.
    with dbmod.SessionLocal() as session:
        session.query(Job).filter(Job.status.in_(("queued", "running"))).update(
            {"status": "failed", "error": "Interrupted by a server restart. Try again.", "finished_at": utcnow()},
            synchronize_session=False,
        )
        session.commit()
    yield


app = FastAPI(title="Adpress", version="1.0.0", lifespan=lifespan)


@app.exception_handler(LLMError)
def _llm_error(_: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


# ---------- helpers ----------

def log_event(db: Session, name: str, user: User | None, workspace_id: str, brand_id: str | None = None,
              **props: Any) -> None:
    db.add(Event(name=name, workspace_id=workspace_id, user_id=user.id if user else None, brand_id=brand_id,
                 props=props))


def audit(db: Session, user: User, action: str, target: str, reason: str | None = None) -> None:
    db.add(AuditLog(workspace_id=user.workspace_id, actor=user.id, action=action, target=target, reason=reason))


def get_brand(db: Session, user: User, brand_id: str) -> Brand:
    brand = db.get(Brand, brand_id)
    if brand is None or brand.workspace_id != user.workspace_id:
        raise HTTPException(404, "Brand not found.")
    return brand


def get_ad(db: Session, user: User, ad_id: str) -> tuple[Ad, Brand]:
    ad = db.get(Ad, ad_id)
    if ad is None:
        raise HTTPException(404, "Ad not found.")
    return ad, get_brand(db, user, ad.brand_id)


def load_kit(db: Session, brand: Brand, version: int | None = None) -> Kit | None:
    v = version if version is not None else brand.current_kit_version
    if not v:
        return None
    row = db.scalar(select(KitVersion).where(KitVersion.brand_id == brand.id, KitVersion.version == v))
    return Kit.model_validate(row.kit_json) if row else None


def save_kit(db: Session, brand: Brand, kit: Kit, user_id: str | None) -> int:
    version = (db.scalar(select(func.max(KitVersion.version)).where(KitVersion.brand_id == brand.id)) or 0) + 1
    db.add(KitVersion(brand_id=brand.id, version=version, kit_json=kit.model_dump(mode="json"), created_by=user_id))
    brand.current_kit_version = version
    return version


def third_party_texts(db: Session, brand_id: str) -> list[str]:
    return [s.text for s in db.scalars(select(Source).where(Source.brand_id == brand_id, Source.owned.is_(False)))]


def ad_out(ad: Ad) -> dict[str, Any]:
    return {
        "id": ad.id, "request_id": ad.request_id, "brand_id": ad.brand_id, "platform": ad.platform,
        "format": ad.format, "audience": ad.audience, "location": ad.location, "offer": ad.offer, "angle": ad.angle,
        "content": ad.fields_json, "generated": ad.generated_json, "status": ad.status, "flags": ad.flags_json,
        "blocking": len(compliance.blocking_open(ad.flags_json)), "edited": ad.edited,
        "parent_ad_id": ad.parent_ad_id, "created_at": ad.created_at.isoformat(),
    }


def brand_out(db: Session, brand: Brand) -> dict[str, Any]:
    kit = load_kit(db, brand)
    return {
        "id": brand.id, "name": brand.name, "website_url": brand.website_url, "industry": brand.industry,
        "current_kit_version": brand.current_kit_version,
        "kit_ready": bool(kit and not kit.guessed),
        "guessed_count": len(kit.guessed) if kit else 0,
        "source_count": db.scalar(select(func.count()).select_from(Source).where(Source.brand_id == brand.id)) or 0,
        "ad_count": db.scalar(select(func.count()).select_from(Ad).where(Ad.brand_id == brand.id,
                                                                      Ad.status != "superseded")) or 0,
        "created_at": brand.created_at.isoformat(),
    }


def job_out(job: Job) -> dict[str, Any]:
    return {"id": job.id, "kind": job.kind, "status": job.status, "progress": job.progress, "result": job.result,
            "error": job.error, "brand_id": job.brand_id}


def start_job(db: Session, background: BackgroundTasks, user: User, kind: str, brand_id: str | None,
              fn: Callable[[Session, Job], dict[str, Any]]) -> Job:
    job = Job(workspace_id=user.workspace_id, brand_id=brand_id, kind=kind)
    db.add(job)
    db.commit()
    background.add_task(_run_job, job.id, fn)
    return job


def _run_job(job_id: str, fn: Callable[[Session, Job], dict[str, Any]]) -> None:
    session = dbmod.SessionLocal()
    try:
        job = session.get(Job, job_id)
        job.status = "running"
        session.commit()
        try:
            job.result = fn(session, job)
            job.status = "done"
        except (LLMError, FetchError, ValueError) as e:
            session.rollback()
            job = session.get(Job, job_id)
            job.status, job.error = "failed", str(e)
        except Exception:  # noqa: BLE001
            log.exception("job %s failed", job_id)
            session.rollback()
            job = session.get(Job, job_id)
            job.status, job.error = "failed", "Something went wrong. Try again, and contact support if it keeps happening."
        job.finished_at = utcnow()
        session.commit()
    finally:
        session.close()


def _progress(session: Session, job: Job) -> Callable[[str], None]:
    def update(msg: str) -> None:
        job.progress = msg
        session.commit()
    return update


# ---------- auth ----------

class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    workspace_name: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


def user_out(user: User) -> dict[str, Any]:
    return {"id": user.id, "email": user.email, "role": user.role, "workspace_id": user.workspace_id,
            "workspace_name": user.workspace.name if user.workspace else None}


@app.post("/api/auth/signup")
def signup(body: SignupIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with that email already exists. Sign in instead.")
    ws = Workspace(name=body.workspace_name)
    db.add(ws)
    db.flush()
    user = User(workspace_id=ws.id, email=email, password_hash=hash_password(body.password), role="Owner")
    db.add(user)
    db.commit()
    return {"token": issue_token(db, user), "user": user_out(user)}


@app.post("/api/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect.")
    return {"token": issue_token(db, user), "user": user_out(user)}


@app.post("/api/auth/logout")
def logout(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    revoke_token(db, request.headers["authorization"][7:].strip())
    return {"ok": True}


@app.get("/api/me")
def me(db: Session = Depends(get_db), user: User = Depends(current_user)):
    last = db.scalar(select(func.max(Event.at)).where(Event.user_id == user.id))
    if last is not None:
        last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
    if last is None or datetime.now(timezone.utc) - last > timedelta(minutes=30):
        log_event(db, "session_started", user, user.workspace_id)
        db.commit()
    return user_out(user)


class InviteIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    role: Literal["Owner", "Editor", "Viewer"] = "Editor"


@app.get("/api/workspace/users")
def list_users(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(User).where(User.workspace_id == user.workspace_id).order_by(User.created_at))
    return [user_out(u) for u in rows]


@app.post("/api/workspace/users")
def add_user(body: InviteIn, db: Session = Depends(get_db), user: User = Depends(owner)):
    if body.role not in ROLES:
        raise HTTPException(422, "Unknown role.")
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "That email already has an account.")
    new = User(workspace_id=user.workspace_id, email=body.email.lower(), password_hash=hash_password(body.password),
               role=body.role)
    db.add(new)
    audit(db, user, "user_added", new.email)
    db.commit()
    return user_out(new)


# ---------- formats ----------

@app.get("/api/formats")
def formats():
    return [f.model_dump() for f in all_formats().values()]


# ---------- brands and sources ----------

class BrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    website_url: str | None = None
    industry: Industry = "general"


def _import_website(brand_id: str, url: str) -> Callable[[Session, Job], dict[str, Any]]:
    def run(session: Session, job: Job) -> dict[str, Any]:
        _progress(session, job)("Reading your website")
        site = Fetcher().fetch_site(url)
        session.query(Source).filter(Source.brand_id == brand_id, Source.type == "website").delete()
        for i, page in enumerate(site.pages):
            meta = {"title": page.title}
            if i == 0:
                meta.update({"colors": site.colors, "fonts": site.fonts})
            session.add(Source(brand_id=brand_id, type="website", kind="page", url=page.url, text=page.text,
                               owned=True, meta=meta))
        return {"pages": len(site.pages), "colors": site.colors, "fonts": site.fonts, "warnings": site.errors}
    return run


@app.get("/api/brands")
def list_brands(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Brand).where(Brand.workspace_id == user.workspace_id).order_by(Brand.created_at.desc()))
    return [brand_out(db, b) for b in rows]


@app.post("/api/brands")
def create_brand(body: BrandIn, background: BackgroundTasks, db: Session = Depends(get_db),
                 user: User = Depends(editor)):
    url = None
    if body.website_url and body.website_url.strip():
        try:
            url = normalize_url(body.website_url)
        except FetchError as e:
            raise HTTPException(422, str(e)) from e
    brand = Brand(workspace_id=user.workspace_id, name=body.name.strip(), website_url=url, industry=body.industry)
    db.add(brand)
    db.flush()
    log_event(db, "kit_setup_started", user, user.workspace_id, brand.id)
    db.commit()
    job = start_job(db, background, user, "import", brand.id, _import_website(brand.id, url)) if url else None
    return {"brand": brand_out(db, brand), "job": job_out(job) if job else None}


@app.get("/api/brands/{brand_id}")
def read_brand(brand_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return brand_out(db, get_brand(db, user, brand_id))


class BrandPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    website_url: str | None = None
    industry: Industry | None = None


@app.patch("/api/brands/{brand_id}")
def update_brand(brand_id: str, body: BrandPatch, db: Session = Depends(get_db), user: User = Depends(editor)):
    brand = get_brand(db, user, brand_id)
    if body.name is not None:
        brand.name = body.name.strip()
    if body.website_url is not None:
        brand.website_url = normalize_url(body.website_url) if body.website_url.strip() else None
    if body.industry is not None:
        brand.industry = body.industry
    db.commit()
    return brand_out(db, brand)


@app.delete("/api/brands/{brand_id}")
def delete_brand(brand_id: str, db: Session = Depends(get_db), user: User = Depends(owner)):
    """Delete a brand and all its data (PRD: privacy)."""
    brand = get_brand(db, user, brand_id)
    for model in (Ad, GenRequest, KitVersion, Source):
        db.query(model).filter(model.brand_id == brand.id).delete(synchronize_session=False)
    db.query(Event).filter(Event.brand_id == brand.id).delete(synchronize_session=False)
    audit(db, user, "brand_deleted", brand.id, brand.name)
    db.delete(brand)
    db.commit()
    return {"ok": True}


@app.post("/api/brands/{brand_id}/import")
def reimport(brand_id: str, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(editor)):
    brand = get_brand(db, user, brand_id)
    if not brand.website_url:
        raise HTTPException(422, "Add a website address first.")
    job = start_job(db, background, user, "import", brand.id, _import_website(brand.id, brand.website_url))
    return job_out(job)


class SourceIn(BaseModel):
    platform: Literal["facebook", "instagram", "linkedin", "google", "x"]
    kind: Literal["bio", "post"] = "post"
    text: str = Field(min_length=1, max_length=20000)
    owned: bool = True


def source_out(s: Source) -> dict[str, Any]:
    return {"id": s.id, "type": s.type, "platform": s.platform, "kind": s.kind, "url": s.url, "text": s.text,
            "owned": s.owned, "meta": s.meta, "fetched_at": s.fetched_at.isoformat()}


@app.get("/api/brands/{brand_id}/sources")
def list_sources(brand_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    brand = get_brand(db, user, brand_id)
    return [source_out(s) for s in db.scalars(select(Source).where(Source.brand_id == brand.id)
                                                .order_by(Source.fetched_at))]


@app.post("/api/brands/{brand_id}/sources")
def add_source(brand_id: str, body: SourceIn, db: Session = Depends(get_db), user: User = Depends(editor)):
    brand = get_brand(db, user, brand_id)
    count = db.scalar(select(func.count()).select_from(Source).where(
        Source.brand_id == brand.id, Source.platform == body.platform, Source.kind == "post")) or 0
    if body.kind == "post" and count >= 10:
        raise HTTPException(422, "You can add up to 10 posts per platform.")
    src = Source(brand_id=brand.id, type="paste", platform=body.platform, kind=body.kind, text=body.text.strip(),
                 owned=body.owned)
    db.add(src)
    db.commit()
    return source_out(src)


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str, db: Session = Depends(get_db), user: User = Depends(editor)):
    src = db.get(Source, source_id)
    if src is None:
        raise HTTPException(404, "Source not found.")
    get_brand(db, user, src.brand_id)
    db.delete(src)
    db.commit()
    return {"ok": True}


# ---------- kit ----------

@app.post("/api/brands/{brand_id}/kit/build")
def kit_build(brand_id: str, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(editor)):
    brand = get_brand(db, user, brand_id)
    sources = list(db.scalars(select(Source).where(Source.brand_id == brand.id)))
    if not sources:
        raise HTTPException(422, "Add your website or paste some posts first.")
    brand_id_, user_id = brand.id, user.id

    def run(session: Session, job: Job) -> dict[str, Any]:
        _progress(session, job)("Building your brand kit")
        b = session.get(Brand, brand_id_)
        srcs = list(session.scalars(select(Source).where(Source.brand_id == brand_id_).order_by(Source.fetched_at)))
        website = [{"url": s.url, "text": s.text} for s in srcs if s.type == "website"]
        pasted = [{"platform": s.platform, "kind": s.kind, "text": s.text} for s in srcs if s.type == "paste" and s.owned]
        first = next((s for s in srcs if s.type == "website" and s.meta.get("colors") is not None), None)
        kit, usage = build_kit(get_llm(), name=b.name, industry=b.industry, website=website, pasted=pasted,
                               colors=first.meta.get("colors", []) if first else [],
                               fonts=first.meta.get("fonts", []) if first else [], previous=load_kit(session, b))
        version = save_kit(session, b, kit, user_id)
        return {"version": version, "guessed": len(kit.guessed), "cost_usd": round(usage.cost_usd, 4)}

    return job_out(start_job(db, background, user, "kit_build", brand.id, run))


@app.get("/api/brands/{brand_id}/kit")
def read_kit(brand_id: str, version: int | None = Query(default=None), db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    brand = get_brand(db, user, brand_id)
    kit = load_kit(db, brand, version)
    if kit is None:
        raise HTTPException(404, "This brand has no kit yet.")
    return {"version": version or brand.current_kit_version, "kit": kit.model_dump(mode="json")}


@app.get("/api/brands/{brand_id}/kit/versions")
def kit_versions(brand_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    brand = get_brand(db, user, brand_id)
    rows = db.scalars(select(KitVersion).where(KitVersion.brand_id == brand.id).order_by(KitVersion.version.desc()))
    return [{"version": r.version, "created_at": r.created_at.isoformat(), "created_by": r.created_by} for r in rows]


class KitIn(BaseModel):
    kit: dict[str, Any]
    base_version: int | None = None


@app.put("/api/brands/{brand_id}/kit")
def save_kit_route(brand_id: str, body: KitIn, db: Session = Depends(get_db), user: User = Depends(editor)):
    brand = get_brand(db, user, brand_id)
    if body.base_version is not None and body.base_version != brand.current_kit_version:
        raise HTTPException(409, "Someone else saved this kit since you opened it. Reload to see their changes.")
    try:
        kit = Kit.model_validate(body.kit)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False)) from e
    was_ready = bool((old := load_kit(db, brand)) and not old.guessed)
    version = save_kit(db, brand, kit, user.id)
    if not kit.guessed and not was_ready:
        log_event(db, "kit_saved", user, user.workspace_id, brand.id, version=version)
    db.commit()
    return {"version": version, "kit": kit.model_dump(mode="json")}


@app.get("/api/brands/{brand_id}/kit/export.md")
def export_kit(brand_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    brand = get_brand(db, user, brand_id)
    kit = load_kit(db, brand)
    if kit is None:
        raise HTTPException(404, "This brand has no kit yet.")
    filename = exporter._slug(brand.name) + "-brand-kit.md"
    return PlainTextResponse(kit_markdown.to_markdown(kit), media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


class KitImportIn(BaseModel):
    markdown: str = Field(max_length=2_000_000)


@app.post("/api/brands/{brand_id}/kit/import")
def import_kit(brand_id: str, body: KitImportIn, db: Session = Depends(get_db), user: User = Depends(editor)):
    brand = get_brand(db, user, brand_id)
    try:
        kit = kit_markdown.from_markdown(body.markdown)
    except (ValueError, ValidationError) as e:
        raise HTTPException(422, str(e)) from e
    version = save_kit(db, brand, kit, user.id)
    db.commit()
    return {"version": version, "kit": kit.model_dump(mode="json")}


# ---------- generation ----------

class GenerateIn(BaseModel):
    formats: list[str] = Field(min_length=1)
    audiences: list[str] = []
    locations: list[str] = []
    offer: str | None = None
    angle: str | None = Field(default=None, max_length=300)
    count: int = Field(default=5, ge=1, le=20)


def _require_ready_kit(db: Session, brand: Brand) -> Kit:
    kit = load_kit(db, brand)
    if kit is None:
        raise HTTPException(422, "Build the brand kit first.")
    if kit.guessed:
        raise HTTPException(422, f"Review the {len(kit.guessed)} guessed field(s) in the kit before generating ads.")
    return kit


@app.post("/api/brands/{brand_id}/requests")
def create_request(brand_id: str, body: GenerateIn, background: BackgroundTasks, db: Session = Depends(get_db),
                   user: User = Depends(editor)):
    brand = get_brand(db, user, brand_id)
    kit = _require_ready_kit(db, brand)
    for f in body.formats:
        try:
            get_format(f)
        except KeyError as e:
            raise HTTPException(422, str(e)) from e
    for a in body.audiences:
        if not kit.audience(a):
            raise HTTPException(422, f"Unknown audience: {a}")
    for loc in body.locations:
        if not kit.location(loc):
            raise HTTPException(422, f"Unknown location: {loc}")
    if body.offer and not kit.offer(body.offer):
        raise HTTPException(422, f"Unknown offer: {body.offer}")
    params = generation.GenParams(formats=list(dict.fromkeys(body.formats)),
                                  audiences=list(dict.fromkeys(body.audiences)) or [None],
                                  locations=list(dict.fromkeys(body.locations)) or [None],
                                  offer=body.offer, angle=body.angle, count=body.count)
    combos = params.combos()
    if len(combos) > settings.max_generation_pairs:
        raise HTTPException(422, f"That's {len(combos)} combinations; the limit is {settings.max_generation_pairs} per run.")
    if len(combos) * body.count > settings.max_ads_per_request:
        raise HTTPException(422, f"That's {len(combos) * body.count} ads; the limit is {settings.max_ads_per_request} per run.")

    brand_id_, user_id, ws_id, kit_version = brand.id, user.id, user.workspace_id, brand.current_kit_version
    third_party = third_party_texts(db, brand.id)

    def run(session: Session, job: Job) -> dict[str, Any]:
        progress = _progress(session, job)
        progress(f"Writing {len(combos) * body.count} ads")
        outcome = generation.generate(get_llm(), kit, params, third_party, review=settings.llm_review,
                                      on_progress=progress)
        if not outcome.ads:
            raise LLMError(outcome.errors[0] if outcome.errors else "No ads were generated.")
        req = GenRequest(brand_id=brand_id_, kit_version=kit_version, params_json=body.model_dump(),
                         model=outcome.usage.model or settings.write_model, tokens_in=outcome.usage.tokens_in,
                         tokens_out=outcome.usage.tokens_out, cost_usd=outcome.usage.cost_usd, created_by=user_id)
        session.add(req)
        session.flush()
        for g in outcome.ads:
            fmt = get_format(g.combo.format_key)
            session.add(Ad(request_id=req.id, brand_id=brand_id_, platform=fmt.platform, format=fmt.key,
                           audience=g.combo.audience, location=g.combo.location, offer=params.offer,
                           angle=g.content.get("angle") or params.angle, generated_json=g.content,
                           fields_json=g.content, flags_json=g.flags))
        per_ad = outcome.usage.cost_usd / len(outcome.ads)
        if per_ad > settings.daily_cost_alert_usd_per_ad:
            log.warning("cost alert: request %s averaged $%.4f per ad", req.id, per_ad)
        user_ = session.get(User, user_id)
        flags_raised = sum(len(g.flags) for g in outcome.ads)
        log_event(session, "ads_generated", user_, ws_id, brand_id_, count=len(outcome.ads), request_id=req.id,
                  cost_usd=round(outcome.usage.cost_usd, 4))
        for g in outcome.ads:
            for f in g.flags:
                log_event(session, "compliance_flag_raised", user_, ws_id, brand_id_, rule=f["rule"],
                          severity=f["severity"])
        return {"request_id": req.id, "ads": len(outcome.ads), "flags": flags_raised, "errors": outcome.errors,
                "cost_usd": round(outcome.usage.cost_usd, 4)}

    return job_out(start_job(db, background, user, "generate", brand.id, run))


@app.get("/api/brands/{brand_id}/requests")
def list_requests(brand_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    brand = get_brand(db, user, brand_id)
    rows = db.scalars(select(GenRequest).where(GenRequest.brand_id == brand.id).order_by(GenRequest.created_at.desc()))
    return [{"id": r.id, "params": r.params_json, "kit_version": r.kit_version, "model": r.model,
             "cost_usd": round(r.cost_usd, 4), "created_at": r.created_at.isoformat()} for r in rows]


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if job is None or job.workspace_id != user.workspace_id:
        raise HTTPException(404, "Job not found.")
    return job_out(job)


# ---------- ads ----------

@app.get("/api/brands/{brand_id}/ads")
def list_ads(brand_id: str, status: str | None = None, platform: str | None = None, request_id: str | None = None,
             db: Session = Depends(get_db), user: User = Depends(current_user)):
    brand = get_brand(db, user, brand_id)
    q = select(Ad).where(Ad.brand_id == brand.id).order_by(Ad.created_at.desc())
    q = q.where(Ad.status == status) if status else q.where(Ad.status != "superseded")
    if platform:
        q = q.where(Ad.platform == platform)
    if request_id:
        q = q.where(Ad.request_id == request_id)
    return [ad_out(a) for a in db.scalars(q)]


class RefineIn(BaseModel):
    instruction: str = Field(min_length=1, max_length=500)


@app.post("/api/ads/{ad_id}/refine")
def refine_ad(ad_id: str, body: RefineIn, db: Session = Depends(get_db), user: User = Depends(editor)):
    ad, brand = get_ad(db, user, ad_id)
    if ad.status == "superseded":
        raise HTTPException(409, "This ad was already replaced by a newer version.")
    kit = _require_ready_kit(db, brand)
    combo = generation.Combo(ad.format, ad.audience, ad.location)
    new, usage = generation.refine(get_llm(), kit, combo, ad.offer, ad.angle, ad.fields_json, body.instruction,
                                   third_party_texts(db, brand.id), review=settings.llm_review)
    req = db.get(GenRequest, ad.request_id)
    req.tokens_in += usage.tokens_in
    req.tokens_out += usage.tokens_out
    req.cost_usd += usage.cost_usd
    child = Ad(request_id=ad.request_id, brand_id=brand.id, platform=ad.platform, format=ad.format,
               audience=ad.audience, location=ad.location, offer=ad.offer, angle=new.content.get("angle") or ad.angle,
               generated_json=new.content, fields_json=new.content, flags_json=new.flags, parent_ad_id=ad.id)
    ad.status = "superseded"
    db.add(child)
    log_event(db, "ads_generated", user, user.workspace_id, brand.id, count=1, refine=body.instruction)
    db.commit()
    return ad_out(child)


class OverrideIn(BaseModel):
    index: int
    reason: str = Field(min_length=3, max_length=1000)


class AdPatch(BaseModel):
    content: dict[str, Any] | None = None
    status: Literal["draft", "approved"] | None = None
    override: OverrideIn | None = None


def _edit_distance_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, a, b).ratio()


@app.patch("/api/ads/{ad_id}")
def update_ad(ad_id: str, body: AdPatch, db: Session = Depends(get_db), user: User = Depends(editor)):
    ad, brand = get_ad(db, user, ad_id)
    if ad.status == "superseded":
        raise HTTPException(409, "This ad was replaced by a newer version.")
    kit = load_kit(db, brand)
    if body.content is not None:
        if kit is None:
            raise HTTPException(422, "This brand has no kit.")
        fmt = get_format(ad.format)
        content = {**ad.fields_json, **{k: v for k, v in body.content.items()
                                          if k in ("fields", "cta", "hashtags", "image_direction")}}
        allowed = {f.key for f in fmt.fields}
        content["fields"] = {k: v for k, v in (content.get("fields") or {}).items() if k in allowed}
        code = compliance.code_checks(content, kit, fmt, third_party_texts(db, brand.id))
        # Keep review flags whose words are still in the ad; code checks are re-run in full.
        text = compliance.full_text(content).lower()
        kept_review = [f for f in ad.flags_json if f.get("source") == "review" and f["words"].lower() in text]
        ad.flags_json = compliance.merge_flags(code, kept_review, previous=ad.flags_json)
        ad.fields_json = content
        ad.edited = compliance.full_text(content) != compliance.full_text(ad.generated_json)
        if ad.status == "exported":
            ad.status = "approved"
        log_event(db, "ad_edited", user, user.workspace_id, brand.id, ad_id=ad.id,
                  edit_distance=round(_edit_distance_ratio(compliance.full_text(ad.generated_json),
                                                           compliance.full_text(content)), 3))
    if body.override is not None:
        if user.role != "Owner":
            raise HTTPException(403, "Only workspace owners can override a blocking flag.")
        flags = [dict(f) for f in ad.flags_json]
        if not 0 <= body.override.index < len(flags):
            raise HTTPException(422, "Unknown flag.")
        flags[body.override.index]["overridden"] = True
        flags[body.override.index]["override_reason"] = body.override.reason
        ad.flags_json = flags
        audit(db, user, "flag_override", ad.id, f"{flags[body.override.index]['rule']}: {body.override.reason}")
    if body.status is not None:
        if body.status == "approved":
            open_flags = compliance.blocking_open(ad.flags_json)
            if open_flags:
                raise HTTPException(422, f"Fix or override {len(open_flags)} blocking flag(s) before approving.")
            log_event(db, "ad_approved", user, user.workspace_id, brand.id, ad_id=ad.id, edited=ad.edited,
                      edit_distance=round(_edit_distance_ratio(compliance.full_text(ad.generated_json),
                                                               compliance.full_text(ad.fields_json)), 3))
        audit(db, user, f"status_{body.status}", ad.id)
        ad.status = body.status
    db.commit()
    return ad_out(ad)


# ---------- export ----------

class ExportIn(BaseModel):
    platform: Literal["facebook", "instagram", "linkedin", "google", "x"]
    ad_ids: list[str] | None = None


@app.post("/api/brands/{brand_id}/exports")
def export_csv(brand_id: str, body: ExportIn, db: Session = Depends(get_db), user: User = Depends(editor)):
    brand = get_brand(db, user, brand_id)
    kit = load_kit(db, brand)
    q = select(Ad).where(Ad.brand_id == brand.id, Ad.platform == body.platform, Ad.status != "superseded")
    if body.ad_ids:
        q = q.where(Ad.id.in_(body.ad_ids))
    else:
        q = q.where(Ad.status.in_(("approved", "exported")))
    ads = list(db.scalars(q.order_by(Ad.created_at)))
    if not ads:
        raise HTTPException(422, "No ads to export. Approve or select some ads for this platform first.")
    blocked = [a for a in ads if compliance.blocking_open(a.flags_json)]
    if blocked:
        raise HTTPException(422, f"{len(blocked)} ad(s) still have blocking flags. Fix or override them first.")
    category = exporter.special_ad_category(brand.industry, bool(kit and kit.compliance.special_ad_category))
    csv_text = exporter.to_csv(body.platform, brand.name, brand.website_url or "", category, [ad_out(a) for a in ads])
    for a in ads:
        a.status = "exported"
        log_event(db, "ad_exported", user, user.workspace_id, brand.id, ad_id=a.id, edited=a.edited,
                  edit_distance=round(_edit_distance_ratio(compliance.full_text(a.generated_json),
                                                           compliance.full_text(a.fields_json)), 3))
    db.commit()
    filename = f"{exporter._slug(brand.name)}-{body.platform}-ads.csv"
    return Response(csv_text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---------- metrics ----------

@app.get("/api/brands/{brand_id}/metrics")
def brand_metrics(brand_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """PRD success metrics for one brand, computed from events."""
    brand = get_brand(db, user, brand_id)
    kept = list(db.scalars(select(Event).where(Event.brand_id == brand.id,
                                               Event.name.in_(("ad_approved", "ad_exported")))))
    by_ad: dict[str, float] = {}
    for e in kept:
        by_ad[e.props.get("ad_id")] = e.props.get("edit_distance", 0.0)
    total = len(by_ad)
    generated = sum(e.props.get("count", 0) for e in db.scalars(
        select(Event).where(Event.brand_id == brand.id, Event.name == "ads_generated")))
    flags = db.scalar(select(func.count()).select_from(Event).where(
        Event.brand_id == brand.id, Event.name == "compliance_flag_raised")) or 0
    cost = db.scalar(select(func.sum(GenRequest.cost_usd)).where(GenRequest.brand_id == brand.id)) or 0.0
    return {
        "ads_generated": generated,
        "ads_kept": total,
        "kept_without_edits_pct": round(100 * sum(1 for d in by_ad.values() if d == 0) / total, 1) if total else None,
        "kept_after_light_edits_pct": round(100 * sum(1 for d in by_ad.values() if d <= 0.2) / total, 1) if total else None,
        "flags_per_100_ads": round(100 * flags / generated, 1) if generated else None,
        "llm_cost_usd": round(cost, 4),
        "cost_per_ad_usd": round(cost / generated, 4) if generated else None,
    }


# ---------- health and frontend ----------

@app.get("/api/health")
def health():
    return {"ok": True}


_dist = os.path.abspath(settings.frontend_dist)
if os.path.isdir(_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        candidate = os.path.join(_dist, path)
        if path and os.path.isfile(candidate) and os.path.abspath(candidate).startswith(_dist):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_dist, "index.html"))
