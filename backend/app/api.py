from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.agent_repository import PostgresAgentStore
from app.booking import BookingApplication, BookingService
from app.booking_lifecycle import (
    ArriveInput,
    BookingLifecycle,
    CancelInput,
    ProposeInput,
    RespondInput,
)
from app.booking_models import CodeInput, ConfirmInput, DraftInput, VerificationInput
from app.catalog import CatalogService
from app.config import Settings
from app.consultation_agent import ConsultationAgent
from app.consultation_cases import CaseCreate, CaseDecision, CaseRevision, ConsultationCases
from app.db import PostgresRepository, transaction
from app.demo_materials import DemoMaterials
from app.domain import Actor, DomainError
from app.followups import FollowupCreate, FollowupResponse, Followups, FollowupStaffAction
from app.graph_adapter import Neo4jKnowledgeGraph
from app.knowledge_types import KnowledgeDetails
from app.model_gateway import QwenEmbeddingGateway
from app.retrieval import PostgresEvidenceReader, RetrievalService
from app.sandbox_runtime import DockerRuntime, SandboxedConsultationAgent
from app.services import ConversationService, IdentityService, KnowledgeService
from app.staff_booking import DecisionInput, StaffBookingService
from app.vector_adapter import MilvusVectorStore, VectorError


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MessageInput(Input):
    message_id: UUID
    question: str = Field(min_length=1, max_length=2000)


class VisitorInput(Input):
    store_code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")


class LoginInput(Input):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class KnowledgeInput(Input):
    knowledge_key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")
    category: Literal["operational", "communication", "medical"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=12000)
    source: str = Field(min_length=1, max_length=1000)
    simulated: bool
    valid_until: AwareDatetime
    details: KnowledgeDetails | None = None


class ReviewInput(Input):
    approved: bool
    reason: str = Field(min_length=1, max_length=1000)


class SearchInput(Input):
    question: str = Field(min_length=1, max_length=2000)


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        if settings.agent_runtime == "docker":
            runtime = DockerRuntime(settings)
            app.state.sandbox_runtime = runtime
            app.state.agent_factory = lambda store: SandboxedConsultationAgent(
                store, runtime=runtime
            )
        with transaction(settings.database_url) as repository:
            if not repository.one(
                "SELECT name FROM schema_revision WHERE name='012_followups.sql'"
            ):
                raise RuntimeError("Run migrations before starting API")
        yield

    app = FastAPI(title="Beauty consultation foundation", lifespan=lifespan)
    app.state.agent_factory = ConsultationAgent
    app.state.sandbox_runtime = None
    app.state.booking_sms_gateway = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    )

    @app.middleware("http")
    async def request_scope(request: Request, call_next: Any) -> Response:
        request.state.request_id = str(uuid4())
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            if origin not in settings.allowed_origins:
                return JSONResponse(
                    {
                        "code": "origin_denied",
                        "safe_message": "请求来源未授权",
                        "retryable": False,
                        "request_id": request.state.request_id,
                    },
                    status_code=403,
                )
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    def safe_error(
        request: Request, code: str, status: int, retryable: bool = False
    ) -> JSONResponse:
        return JSONResponse(
            {
                "code": code,
                "safe_message": "请求未完成，请检查权限或操作状态",
                "retryable": retryable,
                "request_id": request.state.request_id,
            },
            status_code=status,
        )

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return safe_error(request, exc.code, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Default validation output can echo a password or future contact field.
        return safe_error(request, "invalid_input", 422)

    @app.exception_handler(psycopg.Error)
    async def database_error(request: Request, exc: psycopg.Error) -> JSONResponse:
        if isinstance(exc, psycopg.errors.UniqueViolation):
            return safe_error(request, "state_conflict", 409)
        return safe_error(request, "database_unavailable", 503, True)

    @app.exception_handler(VectorError)
    async def vector_error(request: Request, exc: VectorError) -> JSONResponse:
        return safe_error(request, exc.code, 503, True)

    def repository() -> Iterator[PostgresRepository]:
        with transaction(settings.database_url) as repo:
            yield repo

    # Commit before a successful response or cookie can leave the server.
    Repo = Annotated[PostgresRepository, Depends(repository, scope="function")]

    def visitor(request: Request, repo: Repo) -> Actor:
        credential = request.cookies.get("ma_visitor", "")
        csrf = None
        if request.method not in ("GET", "HEAD"):
            csrf = request.headers.get("x-csrf-token", "")
        return IdentityService(repo, settings).authenticate(credential, "visitor", csrf)

    def staff(request: Request, repo: Repo) -> Actor:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise DomainError("unauthenticated", 401)
        return IdentityService(repo, settings).authenticate(authorization[7:], "staff")

    Visitor = Annotated[Actor, Depends(visitor)]
    Staff = Annotated[Actor, Depends(staff)]

    def agent_visitor(request: Request) -> Actor:
        # Close authentication transaction before model/graph/network calls.
        with transaction(settings.database_url) as repo:
            csrf = request.headers.get("x-csrf-token", "") if request.method == "POST" else None
            return IdentityService(repo, settings).authenticate(
                request.cookies.get("ma_visitor", ""), "visitor", csrf
            )

    AgentVisitor = Annotated[Actor, Depends(agent_visitor)]

    @app.get("/api/stores/{store_id}/demo-materials")
    def read_demo_materials(
        store_id: UUID, actor: Staff, repo: Repo, request: Request
    ) -> dict[str, Any]:
        return DemoMaterials(repo, settings, actor, str(store_id)).read(request.state.request_id)

    @app.get("/api/stores/{store_id}/followups")
    def followup_inbox(
        store_id: UUID,
        actor: Staff,
        repo: Repo,
        request: Request,
        state: Literal["awaiting_confirmation", "scheduled", "completed", "declined", "cancelled"]
        | None = None,
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10000),
    ) -> dict[str, Any]:
        return Followups(repo, settings, actor, str(store_id)).inbox(
            state, limit, offset, request.state.request_id
        )

    @app.get("/api/stores/{store_id}/followup-cases")
    def followup_cases(
        store_id: UUID,
        actor: Staff,
        repo: Repo,
        request: Request,
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10000),
    ) -> dict[str, Any]:
        return Followups(repo, settings, actor, str(store_id)).candidates(
            limit, offset, request.state.request_id
        )

    @app.post("/api/stores/{store_id}/followups")
    def propose_followup(
        store_id: UUID, data: FollowupCreate, actor: Staff, repo: Repo, request: Request
    ) -> dict[str, Any]:
        return Followups(repo, settings, actor, str(store_id)).create(
            data, request.state.request_id
        )

    @app.get("/api/stores/{store_id}/followups/{task_id}")
    def read_followup(
        store_id: UUID, task_id: UUID, actor: Staff, repo: Repo, request: Request
    ) -> dict[str, Any]:
        return Followups(repo, settings, actor, str(store_id)).detail(
            str(task_id), request.state.request_id
        )

    @app.post("/api/stores/{store_id}/followups/{task_id}/actions")
    def record_followup(
        store_id: UUID,
        task_id: UUID,
        data: FollowupStaffAction,
        actor: Staff,
        repo: Repo,
        request: Request,
    ) -> dict[str, Any]:
        return Followups(repo, settings, actor, str(store_id)).staff_action(
            str(task_id), data, request.state.request_id
        )

    @app.get("/api/threads/{thread_id}/appointments/{appointment_id}/followups")
    def customer_followups(
        thread_id: UUID, appointment_id: UUID, actor: AgentVisitor, repo: Repo, request: Request
    ) -> dict[str, Any]:
        return Followups(
            repo, settings, actor, str(actor.store_id), str(thread_id), str(appointment_id)
        ).customer(request.state.request_id)

    @app.post("/api/threads/{thread_id}/appointments/{appointment_id}/followups/{task_id}/response")
    def respond_followup(
        thread_id: UUID,
        appointment_id: UUID,
        task_id: UUID,
        data: FollowupResponse,
        actor: AgentVisitor,
        repo: Repo,
        request: Request,
    ) -> dict[str, Any]:
        return Followups(
            repo, settings, actor, str(actor.store_id), str(thread_id), str(appointment_id)
        ).respond(str(task_id), data, request.state.request_id)

    @app.get("/api/stores/{store_id}/consultations")
    def consultation_inbox(
        store_id: UUID,
        actor: Staff,
        repo: Repo,
        request: Request,
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10000),
    ) -> dict[str, Any]:
        return ConsultationCases(repo, settings, actor, str(store_id)).inbox(
            limit, offset, request.state.request_id
        )

    @app.post("/api/stores/{store_id}/consultations")
    def create_consultation(
        store_id: UUID,
        data: CaseCreate,
        actor: Staff,
        repo: Repo,
        request: Request,
    ) -> dict[str, Any]:
        return ConsultationCases(repo, settings, actor, str(store_id)).create(
            data, request.state.request_id
        )

    @app.get("/api/stores/{store_id}/consultation-options")
    def consultation_options(
        store_id: UUID, actor: Staff, repo: Repo, request: Request
    ) -> dict[str, Any]:
        return ConsultationCases(repo, settings, actor, str(store_id)).options(
            request.state.request_id
        )

    @app.get("/api/stores/{store_id}/consultations/{case_id}")
    def consultation_detail(
        store_id: UUID, case_id: UUID, actor: Staff, repo: Repo, request: Request
    ) -> dict[str, Any]:
        return ConsultationCases(repo, settings, actor, str(store_id)).detail(
            str(case_id), request.state.request_id
        )

    @app.post("/api/stores/{store_id}/consultations/{case_id}/revisions")
    def revise_consultation(
        store_id: UUID,
        case_id: UUID,
        data: CaseRevision,
        actor: Staff,
        repo: Repo,
        request: Request,
    ) -> dict[str, Any]:
        return ConsultationCases(repo, settings, actor, str(store_id)).update(
            str(case_id), data, request.state.request_id
        )

    @app.get("/api/threads/{thread_id}/appointments/{appointment_id}/consultation")
    def customer_consultation(
        thread_id: UUID,
        appointment_id: UUID,
        actor: AgentVisitor,
        repo: Repo,
        request: Request,
    ) -> dict[str, Any] | None:
        return ConsultationCases(
            repo, settings, actor, str(actor.store_id), str(thread_id)
        ).customer(str(appointment_id), request.state.request_id)

    @app.post("/api/threads/{thread_id}/appointments/{appointment_id}/consultation/decision")
    def decide_consultation(
        thread_id: UUID,
        appointment_id: UUID,
        data: CaseDecision,
        actor: AgentVisitor,
        repo: Repo,
        request: Request,
    ) -> dict[str, Any]:
        return ConsultationCases(repo, settings, actor, str(actor.store_id), str(thread_id)).decide(
            str(appointment_id), data, request.state.request_id
        )

    @app.get("/api/stores/{store_id}/appointments")
    def appointment_inbox(
        store_id: UUID,
        actor: Staff,
        repo: Repo,
        request: Request,
        state: Literal[
            "pending_store_confirmation",
            "confirmed",
            "declined",
            "arrived",
            "cancelled",
            "completed",
            "no_show",
        ]
        | None = None,
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10000),
    ) -> dict[str, Any]:
        return StaffBookingService(repo, settings, actor, str(store_id)).inbox(
            state, limit, offset, request.state.request_id
        )

    @app.get("/api/stores/{store_id}/appointments/{appointment_id}")
    def appointment_detail(
        store_id: UUID, appointment_id: UUID, actor: Staff, repo: Repo, request: Request
    ) -> dict[str, Any]:
        return StaffBookingService(repo, settings, actor, str(store_id)).detail(
            str(appointment_id), request.state.request_id
        )

    @app.post("/api/stores/{store_id}/appointments/{appointment_id}/contact")
    def appointment_contact(
        store_id: UUID, appointment_id: UUID, actor: Staff, repo: Repo, request: Request
    ) -> dict[str, str]:
        return StaffBookingService(repo, settings, actor, str(store_id)).contact(
            str(appointment_id), request.state.request_id
        )

    @app.post("/api/stores/{store_id}/appointments/{appointment_id}/decision")
    def appointment_decision(
        store_id: UUID,
        appointment_id: UUID,
        data: DecisionInput,
        actor: Staff,
        repo: Repo,
        request: Request,
    ) -> dict[str, Any]:
        return StaffBookingService(repo, settings, actor, str(store_id)).decide(
            str(appointment_id), data, request.state.request_id
        )

    @app.get("/api/threads/{thread_id}/booking")
    def booking_state(thread_id: UUID, actor: AgentVisitor, repo: Repo) -> dict[str, Any]:
        return BookingService(repo, settings, actor, str(thread_id)).state()

    @app.post("/api/stores/{store_id}/appointments/{appointment_id}/change-proposals")
    def propose_booking_change(
        store_id: UUID,
        appointment_id: UUID,
        data: ProposeInput,
        actor: Staff,
        repo: Repo,
        request: Request,
    ) -> dict[str, Any]:
        return BookingLifecycle(repo, settings, actor, str(store_id)).propose(
            str(appointment_id), data, request.state.request_id
        )

    @app.post("/api/stores/{store_id}/appointments/{appointment_id}/arrive")
    def register_arrival(
        store_id: UUID,
        appointment_id: UUID,
        data: ArriveInput,
        actor: Staff,
        repo: Repo,
        request: Request,
    ) -> dict[str, Any]:
        return BookingLifecycle(repo, settings, actor, str(store_id)).arrive(
            str(appointment_id), data, request.state.request_id
        )

    @app.post("/api/threads/{thread_id}/appointments/{appointment_id}/change-response")
    def respond_booking_change(
        thread_id: UUID,
        appointment_id: UUID,
        data: RespondInput,
        actor: AgentVisitor,
        repo: Repo,
        request: Request,
    ) -> dict[str, Any]:
        return BookingLifecycle(repo, settings, actor, str(actor.store_id), str(thread_id)).respond(
            str(appointment_id), data, request.state.request_id
        )

    @app.post("/api/threads/{thread_id}/appointments/{appointment_id}/cancel")
    def cancel_booking(
        thread_id: UUID,
        appointment_id: UUID,
        data: CancelInput,
        actor: AgentVisitor,
        repo: Repo,
        request: Request,
    ) -> dict[str, Any]:
        return BookingLifecycle(repo, settings, actor, str(actor.store_id), str(thread_id)).cancel(
            str(appointment_id), data, request.state.request_id
        )

    @app.post("/api/threads/{thread_id}/appointment-drafts", status_code=201)
    def create_booking_draft(
        thread_id: UUID, data: DraftInput, actor: AgentVisitor, repo: Repo, request: Request
    ) -> dict[str, Any]:
        return BookingService(repo, settings, actor, str(thread_id)).create(
            data, request.state.request_id
        )

    @app.post("/api/threads/{thread_id}/appointment-drafts/{draft_id}/verification")
    def send_booking_code(
        thread_id: UUID,
        draft_id: UUID,
        data: VerificationInput,
        actor: AgentVisitor,
        request: Request,
    ) -> dict[str, Any]:
        return BookingApplication(settings, app.state.booking_sms_gateway).send_code(
            actor,
            str(thread_id),
            str(draft_id),
            str(data.request_key),
            data.sms_consent,
            request.state.request_id,
        )

    @app.post("/api/threads/{thread_id}/contact-verifications/{verification_id}/verify")
    def verify_booking_code(
        thread_id: UUID,
        verification_id: UUID,
        data: CodeInput,
        actor: AgentVisitor,
        request: Request,
    ) -> dict[str, Any]:
        # Commit denied attempts before returning an error to avoid resetting the counter.
        with transaction(settings.database_url) as repo:
            result = BookingService(repo, settings, actor, str(thread_id)).verify(
                str(verification_id), data.code, request.state.request_id
            )
        if result.get("error"):
            raise DomainError(result["error"], 422)
        return result

    @app.post("/api/threads/{thread_id}/appointment-drafts/{draft_id}/confirm")
    def confirm_booking(
        thread_id: UUID,
        draft_id: UUID,
        data: ConfirmInput,
        actor: AgentVisitor,
        repo: Repo,
        request: Request,
    ) -> dict[str, Any]:
        return BookingService(repo, settings, actor, str(thread_id)).confirm(
            str(draft_id), data, request.state.request_id
        )

    @app.post("/api/threads/{thread_id}/appointment-drafts/{draft_id}/discard")
    def discard_booking_draft(
        thread_id: UUID, draft_id: UUID, actor: AgentVisitor, repo: Repo, request: Request
    ) -> dict[str, bool]:
        return BookingService(repo, settings, actor, str(thread_id)).discard(
            str(draft_id), request.state.request_id
        )

    @app.post("/api/threads/{thread_id}/messages")
    def send_message(thread_id: UUID, data: MessageInput, actor: AgentVisitor) -> dict[str, Any]:
        store = PostgresAgentStore(settings, actor, str(thread_id))
        agent: ConsultationAgent = app.state.agent_factory(store)
        return agent.send(str(data.message_id), data.question)

    @app.get("/api/threads/{thread_id}/messages")
    def read_messages(
        thread_id: UUID,
        actor: AgentVisitor,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10000),
        recent: bool = False,
    ) -> dict[str, Any]:
        agent = ConsultationAgent(PostgresAgentStore(settings, actor, str(thread_id)))
        return {"items": agent.history(limit, offset, recent)}

    @app.get("/api/threads/{thread_id}/runs/{run_id}")
    def read_run(thread_id: UUID, run_id: UUID, actor: AgentVisitor) -> dict[str, Any]:
        agent = ConsultationAgent(PostgresAgentStore(settings, actor, str(thread_id)))
        return agent.get_run(str(run_id))

    @app.get("/health/ready")
    def ready(repo: Repo) -> dict[str, str]:
        repo.one("SELECT 1")
        if app.state.sandbox_runtime:
            app.state.sandbox_runtime.check_available()
        return {
            "status": "ready",
            "milestone": "M2-knowledge",
            "scope": "api-database",
            "agent_runtime": settings.agent_runtime,
        }

    @app.post("/api/visitor-sessions", status_code=201)
    def create_visitor(
        data: VisitorInput, response: Response, request: Request, repo: Repo
    ) -> dict[str, Any]:
        identity = IdentityService(repo, settings)
        old = request.cookies.get("ma_visitor")
        if old:
            # Session replacement requires the existing CSRF credential; no forced logout.
            try:
                identity.authenticate(old, "visitor")
            except DomainError as error:
                if error.status != 401:
                    raise
            else:
                actor = identity.authenticate(
                    old, "visitor", request.headers.get("x-csrf-token", "")
                )
                identity.revoke(actor)
        result = identity.visitor_session(data.store_code)
        actor = result["actor"]
        repo.audit(actor, "visitor.session_create", actor.session_id, request.state.request_id)
        response.set_cookie(
            "ma_visitor",
            result["credential"],
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=settings.session_hours * 3600,
            path="/",
        )
        response.set_cookie(
            "ma_visitor_csrf",
            result["csrf_token"],
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=settings.session_hours * 3600,
            path="/",
        )
        return {
            "visitor_id": actor.id,
            "store_id": actor.store_id,
            "csrf_token": result["csrf_token"],
            "simulated": result["simulated"],
        }

    @app.get("/api/public/stores")
    def public_stores(repo: Repo) -> dict[str, Any]:
        return {
            "items": repo.all(
                "SELECT s.public_code AS code,s.name,s.simulated FROM store s "
                "JOIN tenant t ON t.id=s.tenant_id WHERE s.active "
                "AND (%s OR NOT(s.simulated OR t.simulated)) "
                "ORDER BY EXISTS(SELECT 1 FROM knowledge_version k JOIN publication p "
                "ON p.version_id=k.id WHERE k.store_id=s.id AND k.tenant_id=s.tenant_id "
                "AND k.status='published' AND p.state='ready' AND k.valid_until>now()) DESC,"
                "s.public_code LIMIT 100",
                (settings.allow_simulated_data,),
            )
        }

    @app.get("/api/visitor-sessions/current")
    def current_visitor(
        response: Response, request: Request, actor: Visitor, repo: Repo
    ) -> dict[str, Any]:
        result = IdentityService(repo, settings).current_visitor(
            actor, request.cookies.get("ma_visitor_csrf", "")
        )
        response.set_cookie(
            "ma_visitor_csrf",
            result["csrf_token"],
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=settings.session_hours * 3600,
            path="/",
        )
        return result

    @app.get("/api/catalog/projects")
    def public_projects(actor: AgentVisitor) -> dict[str, Any]:
        return {"items": CatalogService(PostgresEvidenceReader(settings)).projects(actor)}

    @app.get("/api/catalog/projects/{project_id}")
    def project_detail(project_id: UUID, actor: AgentVisitor) -> dict[str, Any]:
        return CatalogService(PostgresEvidenceReader(settings)).get(actor, str(project_id))

    @app.get("/api/threads")
    def visitor_threads(actor: Visitor, repo: Repo) -> dict[str, Any]:
        return {
            "items": repo.all(
                "SELECT id AS thread_id,created_at FROM conversation WHERE tenant_id=%s "
                "AND store_id=%s AND visitor_id=%s ORDER BY created_at DESC LIMIT 20",
                (actor.tenant_id, actor.store_id, actor.id),
            )
        }

    @app.post("/api/visitor-sessions/logout")
    def logout(response: Response, request: Request, actor: Visitor, repo: Repo) -> dict[str, str]:
        IdentityService(repo, settings).revoke(actor)
        repo.audit(actor, "visitor.logout", actor.session_id, request.state.request_id)
        response.delete_cookie("ma_visitor", secure=settings.cookie_secure, samesite="strict")
        response.delete_cookie("ma_visitor_csrf", secure=settings.cookie_secure, samesite="strict")
        return {"status": "revoked"}

    @app.post("/api/staff-sessions")
    def login(data: LoginInput, request: Request) -> dict[str, str]:
        with transaction(settings.database_url) as repo:
            result = IdentityService(repo, settings).login(
                data.username,
                data.password,
                request.client.host if request.client else "unknown",
                request.state.request_id,
            )
        if "error" in result:
            raise DomainError(result["error"], 429 if result["error"] == "login_throttled" else 401)
        return result

    @app.post("/api/staff-sessions/logout")
    def staff_logout(actor: Staff, request: Request, repo: Repo) -> dict[str, str]:
        IdentityService(repo, settings).revoke(actor)
        repo.audit(actor, "staff.logout", actor.session_id, request.state.request_id)
        return {"status": "revoked"}

    @app.get("/api/staff/me")
    def staff_profile(actor: Staff, repo: Repo) -> dict[str, Any]:
        return IdentityService(repo, settings).profile(actor)

    @app.get("/api/stores/{store_id}/knowledge")
    def list_knowledge(
        store_id: UUID,
        actor: Staff,
        repo: Repo,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    ) -> dict[str, Any]:
        return KnowledgeService(repo, settings).list_versions(actor, str(store_id), limit, offset)

    @app.post("/api/threads", status_code=201)
    def create_thread(actor: Visitor, request: Request, repo: Repo) -> dict[str, Any]:
        return ConversationService(repo).create(actor, request.state.request_id)

    @app.get("/api/threads/{thread_id}")
    def get_thread(thread_id: UUID, actor: Visitor, repo: Repo) -> dict[str, Any]:
        return ConversationService(repo).get(actor, str(thread_id))

    @app.get("/api/knowledge/evidence")
    def evidence(actor: Visitor, repo: Repo) -> dict[str, Any]:
        return {
            "items": KnowledgeService(repo, settings).evidence(actor),
            "simulation_allowed": settings.allow_simulated_data,
        }

    @app.post("/api/stores/{store_id}/knowledge", status_code=201)
    def create_knowledge(
        store_id: UUID, data: KnowledgeInput, actor: Staff, request: Request, repo: Repo
    ) -> dict[str, Any]:
        return KnowledgeService(repo, settings).create(
            actor, str(store_id), data.model_dump(), request.state.request_id
        )

    @app.post("/api/knowledge/search")
    def search_knowledge(data: SearchInput, request: Request) -> dict[str, Any]:
        with transaction(settings.database_url) as repo:
            actor = IdentityService(repo, settings).authenticate(
                request.cookies.get("ma_visitor", ""),
                "visitor",
                request.headers.get("x-csrf-token", ""),
            )
        reader = PostgresEvidenceReader(settings)
        # Avoid constructing an external client when no approved evidence is available.
        if not reader.evidence(actor):
            return {"items": [], "method": "none", "graph_status": "not_queried"}
        graph = Neo4jKnowledgeGraph(settings)
        gateway = QwenEmbeddingGateway(settings)
        vectors = MilvusVectorStore(settings)
        try:
            return RetrievalService(
                reader, graph, gateway, vectors, settings.allow_simulated_data
            ).search(actor, data.question)
        finally:
            graph.close()
            gateway.close()
            vectors.close()

    @app.post("/api/stores/{store_id}/knowledge/{version_id}/review")
    def review(
        store_id: UUID,
        version_id: UUID,
        data: ReviewInput,
        actor: Staff,
        request: Request,
        repo: Repo,
    ) -> dict[str, str]:
        return KnowledgeService(repo, settings).review(
            actor,
            str(store_id),
            str(version_id),
            data.approved,
            data.reason,
            request.state.request_id,
        )

    @app.post("/api/stores/{store_id}/knowledge/{version_id}/publish")
    def publish(
        store_id: UUID, version_id: UUID, actor: Staff, request: Request, repo: Repo
    ) -> dict[str, str]:
        return KnowledgeService(repo, settings).publish(
            actor, str(store_id), str(version_id), request.state.request_id
        )

    @app.post("/api/stores/{store_id}/knowledge/{version_id}/withdraw")
    def withdraw(
        store_id: UUID, version_id: UUID, actor: Staff, request: Request, repo: Repo
    ) -> dict[str, str]:
        return KnowledgeService(repo, settings).withdraw(
            actor, str(store_id), str(version_id), request.state.request_id
        )

    return app
